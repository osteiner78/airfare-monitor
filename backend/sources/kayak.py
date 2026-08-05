import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field

from backend.kayak_samples import _DEFAULT_SAMPLES_DIR, _SAMPLES_DIR_ENV, capture_sample
from backend.sources.base import FlightResult

logger = logging.getLogger(__name__)

_API_KEY_ENV = "DEEPSEEK_API_KEY"
# The key behind DEEPSEEK_API_KEY is an opencode.ai key (not a native DeepSeek
# API key), so base_url/model point at opencode's OpenAI-compatible endpoint
# rather than api.deepseek.com directly. Points at opencode Zen (not the Go
# proxy) using the free-tier model id -- the Go proxy's "deepseek-v4-flash"
# hit a regional access gate and then a monthly usage cap during Phase 6 live
# verification; Zen's "deepseek-v4-flash-free" worked with the same key and
# has no such cap (confirmed 2026-08-04 with a real request).
_LLM_BASE_URL = "https://opencode.ai/zen/v1"
_LLM_MODEL = "deepseek-v4-flash-free"

_RENDER_TIMEOUT_S = 45.0
_LLM_TIMEOUT_S = 30.0
# Worst case: page.goto's own timeout (_RENDER_TIMEOUT_S) plus
# _wait_for_results_stable's separate cap (also _RENDER_TIMEOUT_S) can both
# elapse before the LLM call even starts, so the overall budget must cover
# both render timeouts in full plus the LLM call, with slack.
_OVERALL_TIMEOUT_S = 2 * _RENDER_TIMEOUT_S + _LLM_TIMEOUT_S + 30.0

# The first six were written from guesses before any block had been seen and
# matched NONE of the interstitial Kayak actually served (Phase 6, 2026-08-04)
# -- a real block was logged as "no flights found", making the block-rate
# sample uninterpretable. The rest are taken from captured page text: the
# "thinks you are a"/"not a bot"/"only useful for humans" group is Kayak's own
# wording, verbatim; "pardon our interruption"/"press and hold" is PerimeterX's
# standard challenge copy. Keep markers specific to interstitial phrasing --
# a false positive returns [] without ever extracting, silently dropping real
# prices, which is as damaging as a miss.
_BLOCKED_MARKERS = (
    "verify you are human",
    "unusual traffic",
    "are you a robot",
    "captcha",
    "access denied",
    "automated queries",
    "thinks you are a",
    "i am not a bot",
    "only useful for humans",
    "pardon our interruption",
    "press and hold",
)

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract flight search results from the plain-text body of a Kayak "
    "flight results page. Respond with a JSON object of the form "
    '{"flights": [...]}. Each item must have: airline (string), '
    "flight_number (string, use '+' to join multi-leg flight numbers), "
    "departure_time (ISO 8601), arrival_time (ISO 8601), duration_min "
    "(integer minutes or null), stops (integer or null), price (number, no "
    "currency symbol or thousands separators). Only include flights that are "
    "genuinely present in the text -- never invent a row."
)

# The per-row action button _wait_for_results_stable polls for, and the
# structural block signal (plan 018 task 2.5) keys off the same token. The
# bundle pins the English kayak.com site (task 1.8), but Kayak may
# force-redirect by IP geography and the deployment itself moves country --
# a locale-driven lookup would be wrong in exactly those cases, so this is a
# set matched with any(), not a lookup keyed by config.locale.
_RESULT_MARKERS = {"Select", "Selecionar", "Auswählen"}
_RESULT_MARKERS_LOWER = {marker.lower() for marker in _RESULT_MARKERS}

# A real results page is long and carries one action button per itinerary; the
# interstitial is a couple of short paragraphs with none. Complements
# _BLOCKED_MARKERS (plan 018 task 2.5): markers catch the interstitial we have
# already seen, this catches its next rewrite. Deliberately requires BOTH
# conditions -- a long page with no recognised button is a redesign or an
# unexpected locale, not evidence of a block, and calling it blocked would
# silently discard real prices.
_MIN_RESULTS_PAGE_CHARS = 2000


@dataclass
class KayakRenderConfig:
    """The C1-C4 evasion bundle (plan 018) as a parameter object.

    Defaults are the deployable stack: headful under Xvfb (C2), a persistent
    profile + warm-up navigation (C3), and CDP-leak patching (C4, applied by
    the patchright swap in Phase 2 -- `stealth` just records intent here).
    C5 (attaching to a manually-launched Chrome) has no unattended form and
    is deliberately unreachable through this config.
    """

    headless: bool = False
    user_data_dir: str | None = "data/kayak-profile"
    # Pinned to English regardless of egress geography (task 1.8): language
    # preference and physical location are independent facts about a real
    # person, and re-tuning the parser on every relocation buys nothing.
    locale: str = "en-US"
    # Must track egress geography and be updated on relocation -- unlike
    # locale, timezone is OS-derived and trivially cross-checked against IP
    # geolocation, so it cannot be left to a default the way locale can.
    timezone_id: str = "America/Sao_Paulo"
    viewport: dict = field(default_factory=lambda: {"width": 1920, "height": 1080})
    warmup_url: str | None = "https://www.kayak.com/"
    warmup_dwell_s: tuple[float, float] = (2.0, 5.0)
    stealth: bool = True
    # Names the arm a captured sample belongs to, so past samples stay
    # re-classifiable once the bundle changes (plan 018 task 2.4).
    config_id: str = "c1-c4"
    samples_dir: str | None = field(
        default_factory=lambda: os.environ.get(_SAMPLES_DIR_ENV, _DEFAULT_SAMPLES_DIR)
    )


def _launch_args(config: KayakRenderConfig) -> list[str]:
    # Without the ANGLE/SwiftShader pair this container exposes NO WebGL
    # context at all (verified 2026-08-05, plan 018 Phase 3 Step 1) -- every
    # real Chrome has one, falling back to SwiftShader on GPU-less hosts, so
    # zero context is a harder tell than the software-renderer string itself.
    return [
        "--disable-blink-features=AutomationControlled",
        "--use-gl=angle",
        "--use-angle=swiftshader",
    ]


def _looks_blocked_structurally(body_text: str) -> bool:
    if not body_text:
        return False
    if len(body_text) >= _MIN_RESULTS_PAGE_CHARS:
        return False
    lowered = body_text.lower()
    return not any(marker.lower() in lowered for marker in _RESULT_MARKERS)


def _results_section(body_text: str, max_results: int) -> str:
    """The slice of the rendered body carrying the first `max_results`
    itineraries.

    The page is fetched with sort=price_a, so the cheapest itineraries come
    first and the LLM never needs the rest. Sending the whole ~20k-char body
    measured 103s against the extraction endpoint (2026-08-05) -- more than
    triple _LLM_TIMEOUT_S -- while the top-5 slice is ~9% of it.

    Each itinerary block ends with a _RESULT_MARKERS line, so block *ends* are
    exact; only the first block's start has to be estimated, and the widest of
    the leading blocks is a safe over-estimate. Keyed on the marker set rather
    than a layout string, so it survives a force-redirect the same way
    _wait_for_results_stable does. Returns the body unchanged when there is
    nothing to key on -- trimming is an optimisation, and dropping the page
    would cost a real request.
    """
    if max_results <= 0:
        return body_text

    lines = body_text.split("\n")
    marker_lines = [
        i for i, line in enumerate(lines) if line.strip().lower() in _RESULT_MARKERS_LOWER
    ]
    if not marker_lines:
        return body_text

    end = marker_lines[min(max_results, len(marker_lines)) - 1]
    spans = [b - a for a, b in zip(marker_lines, marker_lines[1:])]
    lookback = max(spans[:max_results], default=end)
    return "\n".join(lines[max(0, marker_lines[0] - lookback) : end + 1])


def _derive_user_agent(default_ua: str) -> str:
    return default_ua.replace("HeadlessChrome", "Chrome")


def _context_options(config: KayakRenderConfig, default_ua: str) -> dict:
    return {
        "locale": config.locale,
        "timezone_id": config.timezone_id,
        "viewport": dict(config.viewport),
        "user_agent": _derive_user_agent(default_ua),
    }


def _fingerprint_is_consistent(options: dict) -> bool:
    """Catches a self-inconsistent bundle, not attribution (plan 018 Decision
    3). Deliberately does NOT require locale/timezone region agreement --
    the shipped config pins English locale against a local timezone (task
    1.8), and that rule would reject its own defaults."""
    user_agent = options.get("user_agent") or ""
    if "headless" in user_agent.lower() or "playwright" in user_agent.lower():
        return False

    if not options.get("timezone_id"):
        return False

    viewport = options.get("viewport") or {}
    if viewport.get("width", 0) < 800 or viewport.get("height", 0) < 600:
        return False

    return True


def _warmup_sequence(config: KayakRenderConfig) -> list[tuple[str, float]]:
    if not config.warmup_url:
        return []
    dwell = random.uniform(*config.warmup_dwell_s)
    return [(config.warmup_url, dwell)]


# The default UA cannot change until the image is rebuilt, and reading it
# costs a whole throwaway Chromium launch. Memoized because the driver-crash
# ("Connection closed while reading from the driver") has fired twice, and
# two launches per render doubles the exposure to whatever causes it (plan
# 018 task 2.7).
_default_user_agent_cache: str | None = None


async def _probe_default_user_agent(playwright) -> str:
    global _default_user_agent_cache
    if _default_user_agent_cache is None:
        probe = await playwright.chromium.launch(headless=True)
        try:
            probe_page = await probe.new_page()
            _default_user_agent_cache = await probe_page.evaluate("navigator.userAgent")
        finally:
            await probe.close()
    return _default_user_agent_cache


async def _simulate_interaction(page) -> None:
    """PerimeterX scores mouse/scroll telemetry; a bare goto -> read emits
    none of it (plan 018 task 1.7)."""
    await page.mouse.move(200, 300)
    await page.mouse.wheel(0, 400)


class KayakSource:
    def __init__(self, config: KayakRenderConfig | None = None) -> None:
        self.config = config or KayakRenderConfig()
        self.last_error: str | None = None
        self.last_error_level: str = "ERROR"
        # Merged into every captured sample record; the experiment runner
        # fills in what only it knows (attempt number, egress IP).
        self.sample_context: dict = {}
        self.last_sample_path = None

    async def search(
        self,
        origin: str,
        dest: str,
        depart_date: str,
        return_date: str | None,
        currency: str,
        top_n: int,
    ) -> list[FlightResult]:
        self.last_error = None
        self.last_error_level = "ERROR"

        if top_n <= 0:
            return []

        url = self._build_url(origin, dest, depart_date, currency)

        try:
            return await asyncio.wait_for(
                self._search_inner(url, top_n, currency, depart_date),
                timeout=_OVERALL_TIMEOUT_S,
            )
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            api_key = os.environ.get(_API_KEY_ENV)
            if api_key:
                message = message.replace(api_key, "[REDACTED]")
            self.last_error = message
            self.last_error_level = "ERROR"
            return []

    async def _search_inner(
        self, url: str, top_n: int, currency: str, depart_date: str
    ) -> list[FlightResult]:
        started = time.monotonic()
        body_text = await self._render(url)

        record = {
            **self.sample_context,
            "config_id": self.config.config_id,
            "blocked_by_markers": self._looks_blocked(body_text),
            "blocked_by_structure": _looks_blocked_structurally(body_text),
            "extracted_rows": 0,
            "validated_rows": 0,
            "outcome": "error",
        }

        try:
            if record["blocked_by_markers"] or record["blocked_by_structure"]:
                record["outcome"] = "blocked"
                signal = "markers" if record["blocked_by_markers"] else "page structure"
                self.last_error = f"Kayak render appears blocked by bot detection ({signal})"
                self.last_error_level = "WARNING"
                return []

            rows = await self._extract(body_text, top_n, depart_date)
            record["extracted_rows"] = len(rows)
            if not rows:
                record["outcome"] = "no_flights"
                self.last_error = (
                    "Kayak extraction found no flights (route may genuinely have none)"
                )
                self.last_error_level = "WARNING"
                return []

            validated = self._validate(rows, body_text)
            record["validated_rows"] = len(validated)
            dropped = len(rows) - len(validated)

            if not validated:
                record["outcome"] = "all_dropped"
                self.last_error = (
                    f"Kayak validation dropped all {dropped} extracted row(s) "
                    "(grounding/price checks failed)"
                )
                self.last_error_level = "WARNING"
                return []

            if dropped:
                record["outcome"] = "partly_dropped"
                self.last_error = (
                    f"Kayak validation dropped {dropped} of {len(rows)} extracted row(s)"
                )
                self.last_error_level = "WARNING"
            else:
                record["outcome"] = "extracted"

            return [self._map_result(row, currency, url) for row in validated]
        finally:
            record["elapsed_s"] = round(time.monotonic() - started, 2)
            if self.config.samples_dir:
                self.last_sample_path = capture_sample(
                    body_text, record, self.config.samples_dir
                )

    @staticmethod
    def _build_url(origin: str, dest: str, depart_date: str, currency: str) -> str:
        return (
            f"https://www.kayak.com/flights/{origin}-{dest}/{depart_date}"
            f"?sort=price_a&currency={currency or 'USD'}"
        )

    @staticmethod
    def _looks_blocked(body_text: str) -> bool:
        if not body_text:
            return False
        lowered = body_text.lower()
        return any(marker in lowered for marker in _BLOCKED_MARKERS)

    async def _render(self, url: str) -> str:
        from patchright.async_api import async_playwright

        config = self.config
        launch_args = _launch_args(config)

        async with async_playwright() as p:
            # The real default UA comes from the browser itself (Decision 4:
            # derived from the launched build's own version, never
            # hardcoded). Context creation options can't be changed after the
            # fact, so this has to resolve before the real context.
            default_ua = await _probe_default_user_agent(p)

            options = _context_options(config, default_ua)
            browser_to_close = None

            if config.user_data_dir:
                context = await p.chromium.launch_persistent_context(
                    config.user_data_dir,
                    headless=config.headless,
                    args=launch_args,
                    locale=options["locale"],
                    timezone_id=options["timezone_id"],
                    viewport=options["viewport"],
                    user_agent=options["user_agent"],
                )
            else:
                browser = await p.chromium.launch(headless=config.headless, args=launch_args)
                context = await browser.new_context(
                    locale=options["locale"],
                    timezone_id=options["timezone_id"],
                    viewport=options["viewport"],
                    user_agent=options["user_agent"],
                )
                browser_to_close = browser

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                for warmup_url, dwell in _warmup_sequence(config):
                    await page.goto(warmup_url, timeout=_RENDER_TIMEOUT_S * 1000)
                    await asyncio.sleep(dwell)

                await page.goto(url, timeout=_RENDER_TIMEOUT_S * 1000)
                await self._wait_for_results_stable(page)
                await _simulate_interaction(page)
                return await page.inner_text("body")
            finally:
                await context.close()
                if browser_to_close is not None:
                    await browser_to_close.close()

    @staticmethod
    async def _wait_for_results_stable(page, cap_seconds: float = _RENDER_TIMEOUT_S) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + cap_seconds
        previous_count = -1
        stable_polls = 0
        while loop.time() < deadline:
            count = 0
            for marker in _RESULT_MARKERS:
                count += await page.get_by_text(marker, exact=True).count()
            if count > 0 and count == previous_count:
                stable_polls += 1
                if stable_polls >= 2:
                    return
            else:
                stable_polls = 0
            previous_count = count
            await asyncio.sleep(1)

    async def _extract(self, body_text: str, top_n: int, depart_date: str) -> list[dict]:
        from openai import AsyncOpenAI

        api_key = os.environ[_API_KEY_ENV]
        client = AsyncOpenAI(api_key=api_key, base_url=_LLM_BASE_URL)

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=_LLM_MODEL,
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        # The trimmed slice carries clock times but not the
                        # search date, so the date is stated rather than left
                        # to be inferred -- without it the model dates every
                        # row to the epoch.
                        "content": f"These flights depart on {depart_date}. Use that "
                        "date for departure_time, and for arrival_time unless the "
                        "itinerary arrives after midnight, which the page marks "
                        '"+1".\n\n'
                        f"Extract up to {top_n} flights from this Kayak "
                        f"results page text:\n\n{_results_section(body_text, top_n)}",
                    },
                ],
                response_format={"type": "json_object"},
            ),
            timeout=_LLM_TIMEOUT_S,
        )

        content = response.choices[0].message.content
        parsed = json.loads(content)
        flights = parsed["flights"]
        if not isinstance(flights, list):
            raise ValueError("Kayak extraction response 'flights' was not a list")
        return flights[:top_n]

    @staticmethod
    def _price_grounded(price: float, body_text: str) -> bool:
        # Accepts en-US comma-thousands ("4,312") and pt-BR/de-CH dot-thousands
        # with comma decimals ("4.312" / "4.312,00") unconditionally rather
        # than branching on locale (task 1.9) -- the fallback costs nothing
        # and survives a force-redirect even with the English site pinned.
        n = int(price) if price == int(price) else price
        comma_thousands = f"{n:,}"
        dot_thousands = comma_thousands.replace(",", ".")
        representations = {
            str(n),
            comma_thousands,
            dot_thousands,
            f"{dot_thousands},00",
        }
        return any(rep in body_text for rep in representations)

    @staticmethod
    def _validate(rows: list[dict], body_text: str) -> list[dict]:
        grounded = []
        for row in rows:
            price = row.get("price")
            if price is None or price <= 0:
                logger.warning("Dropping Kayak row with non-positive/missing price: %r", row)
                continue
            if not KayakSource._price_grounded(price, body_text):
                logger.warning("Dropping Kayak row whose price is absent from rendered text: %r", row)
                continue
            grounded.append(row)

        if not grounded:
            return grounded

        prices = sorted(r["price"] for r in grounded)
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

        kept = []
        for row in grounded:
            if median > 0 and row["price"] > 10 * median:
                logger.warning("Dropping Kayak row priced wildly outside the band of other rows: %r", row)
                continue
            kept.append(row)
        return kept

    @staticmethod
    def _map_result(row: dict, currency: str, url: str) -> FlightResult:
        return FlightResult(
            source="kayak",
            price=float(row["price"]),
            currency=currency,
            duration_min=row.get("duration_min"),
            stops=row.get("stops") or 0,
            airline=row.get("airline", ""),
            flight_number=row.get("flight_number", ""),
            departure_time=row.get("departure_time", ""),
            arrival_time=row.get("arrival_time", ""),
            legs_json="[]",
            booking_url=url,
        )

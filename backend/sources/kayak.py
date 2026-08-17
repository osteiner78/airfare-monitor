import asyncio
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from backend.fingerprint import canonical_timestamp
from backend.kayak_samples import _DEFAULT_SAMPLES_DIR, _SAMPLES_DIR_ENV, capture_sample
from backend.sources.base import FlightResult

logger = logging.getLogger(__name__)

_API_KEY_ENV = "DEEPSEEK_API_KEY"
# The key behind DEEPSEEK_API_KEY is an opencode.ai key (not a native DeepSeek
# API key), so base_url/model point at opencode's OpenAI-compatible endpoint
# rather than api.deepseek.com directly. Was opencode Zen's free tier
# (https://opencode.ai/zen/v1); switched to the paid Go subscription
# (2026-08-15) after Zen's free quota started 429ing on ~22-23 of every 24
# hourly cycles across the 4 kayak_enabled trackers (system_logs
# "kayak_search_error", FreeUsageLimitError, since 2026-08-12) -- 1 tracker's
# worth of traffic fit the free cap, 4 didn't. Go's base URL is
# opencode.ai/zen/go/v1. The docs' "opencode-go/<id>" model-id prefix is for
# opencode's own CLI config, not this endpoint -- a real call and this
# endpoint's own /v1/models both 401'd on the prefixed form and confirmed the
# plain id (verified 2026-08-15: `scripts/kayak_model_benchmark.py verify`).
# The Go proxy's plain "deepseek-v4-flash" is a separate, older finding: it
# hit a regional access gate and then a monthly usage cap during Phase 6 live
# verification -- unrelated to this quota, but a reason not to fall back to
# deepseek if mimo ever needs replacing.
_LLM_BASE_URL = "https://opencode.ai/zen/go/v1"
# Chosen by the plan 019 Phase 3b benchmark (200 replays of 5 captured bodies
# across 4 candidates, .agent/reports/019-phase-3b.md), not by preference.
# deepseek-v4-flash-free's problem was never accuracy, it was that Zen honours
# "thinking: disabled" only ~3 times in 10 and a thinking run blows the LLM
# budget. mimo-v2.5-free emitted 509 or 523 completion tokens on all 50 runs --
# two values, no reasoning burst ever -- so the flag cannot be ignored, because
# there is no reasoning mode to ignore it with. Same correctness (49/50), and
# 48/50 runs under 23s against deepseek's 6 runs over 30s. "mimo-v2.5" is the
# same model under the paid Go catalog (no "-free" suffix) -- carries the same
# benchmark result forward rather than reopening it.
_LLM_MODEL = "mimo-v2.5"

_RENDER_TIMEOUT_S = 45.0
# Raised from 30.0 by Phase 3b task 3b.4 ("prefer the tightest tail and raise
# the cap to fit it"): mimo's 50 measured runs span 4.3-58.7s, so 30s would
# discard 3 of 50 otherwise-correct extractions. The tail here is network, not
# reasoning -- the two slowest runs returned the same 523 tokens as the fastest.
# The margin over the observed max is thin (~2%); anything past the cap is a
# lost data point by design (3b.5: a hard cap stays regardless of model).
_LLM_TIMEOUT_S = 60.0
_RENDER_WORKER_MODULE = "backend.sources.kayak_render"

# The worker's cap is an explicit SUM of the waits the child actually performs,
# not a factor over _RENDER_TIMEOUT_S. Plan 021 wrote that factor (2.5) from a
# two-wait premise -- page.goto plus _wait_for_results_stable -- but the child
# runs FOUR waits in sequence: the warmup goto, the warmup dwell, the main goto
# and the stable-wait. At 2.5 that was 112.5s of budget against 140s of waiting
# the worker's own code permits, so a slow-but-healthy render could be killed
# mid-page. A factor hides that arithmetic; a sum states it, and
# `tests/test_kayak_timeout_budget.py` reads the waits out of kayak_render.py
# so a fifth one cannot be added without failing the suite.
#
# The warmup goto gets its own, tighter cap: it loads the homepage, not a
# results page, so it has no reason to need the full render budget.
_WARMUP_TIMEOUT_S = 20.0
_MAX_WARMUP_DWELL_S = 5.0
_WORKER_STARTUP_ALLOWANCE_S = 15.0
_WORKER_TIMEOUT_S = (
    _WARMUP_TIMEOUT_S
    + _MAX_WARMUP_DWELL_S
    + 2 * _RENDER_TIMEOUT_S
    + _WORKER_STARTUP_ALLOWANCE_S
)

# Extra itineraries requested so that duplicates removed by _dedupe_rows do not
# shrink the stored result set. 2 covers the observed case (one repeated fare
# brand); the slice is still a small fraction of the ~20k-char body, so the
# LLM-latency reason for trimming at all is unaffected.
_OVERFETCH_ROWS = 2

# Product decision (2026-08-13, user-confirmed), not a parsing accident: a
# flight departing after midnight but before this hour on depart_date+1 is
# still "the night of depart_date" for anyone booking that evening, so
# _rebase_departure_date buckets it under depart_date. Anything at or past
# this hour is left as extracted -- a genuinely different day's flight, not
# a late one. 3 sits at the upper end of "up to around 2-3am" as the user
# put it; narrow it to 2 if 2:00-2:59 departures should NOT roll over.
_NIGHT_ROLLOVER_CUTOFF_HOUR = 3

# Derived from the WORKER's cap, not from 2 * _RENDER_TIMEOUT_S. Plan 021
# Phase 2 moved the render into a subprocess with a 2.5x budget while this
# line still assumed the old in-process 2x bound, leaving 7.5s of slack
# instead of 30 -- and that cost a real, fully-rendered page: the 02:37 run on
# 2026-08-11 read a 19,085-char body in 124s and then lost it to this cap
# mid-extraction (`outcome: error`, `extracted_rows: 0`). Successful runs take
# 62-67s, so only the slow tail hits it, which is why it survived Phase 3's
# verification. Keep this derived: it must always exceed the worst case the
# sub-timeouts can actually produce, and `test_kayak_timeout_budget.py`
# fails if the slack ever narrows again.
_OVERALL_TIMEOUT_S = _WORKER_TIMEOUT_S + _LLM_TIMEOUT_S + 30.0

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
    "flight_number (always null -- Kayak's collapsed list view does not print "
    "flight numbers on any row; never invent a flight number, and never use a "
    'placeholder such as "N/A" or "unknown"), departure_time (ISO 8601), '
    "arrival_time (ISO 8601), duration_min (integer minutes or null), stops "
    "(integer or null), price (number, no currency symbol or thousands "
    "separators). Only include flights that are genuinely present in the text "
    "-- never invent a row."
)

# The model filled flight_number with "", "N/A", "unknown" and "AT" for one
# physical flight across runs (plan 018 Phase 3). flight_number is no longer
# part of the identity key, but a stored placeholder still renders in the
# results table's Flight column as though it were a real flight number.
_PLACEHOLDER_FLIGHT_NUMBERS = {"", "-", "n/a", "na", "none", "null", "unknown"}

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

# Kayak's header nav renders the *active* currency as an adjacent
# symbol/name pair on its own two lines (e.g. "$\nUnited States dollar" --
# verified across all 9 captured bodies in data/kayak-samples/). A currency
# PICKER component elsewhere on the page (CurrencyPickerStateProviderAction,
# confirmed live 2026-08-05) lists every currency Kayak supports as
# candidates, including "Euro" and "British pound" -- a bare substring
# search for a currency name would false-positive on that picker rather
# than reading what was actually served, which is exactly the trap the
# tests guard against. Only USD (evidenced from real captured samples) and
# EUR (this project's only tracker currency, and this plan's own test
# contract) are mapped -- GBP/CHF haven't been seen in Kayak's real header
# text, so an unrecognised marker returns None (refuse) rather than
# guessing their spelling.
# Which clock convention the rendered page is written in decides which form
# _time_grounded has to find. The 12-hour probe runs first and wins: on a page
# printing "12:30 am", a bare "12:30" lookup would match that very line and
# wave through the pm misread this check exists to catch.
_TWELVE_HOUR_TIME_RE = re.compile(r"\d{1,2}:\d{2}\s?[ap]m")
_ANY_CLOCK_TIME_RE = re.compile(r"\d{1,2}:\d{2}")

_CURRENCY_MARKERS: dict[str, tuple[str, str]] = {
    "USD": ("$", "united states dollar"),
    "EUR": ("€", "euro"),
}


def _page_currency(body_text: str) -> str | None:
    """The currency Kayak actually served, read from the header chrome --
    not from the request we sent (plan 019 Decision 1: forcing via
    ?currency= is unverified and was falsified live; a live investigation
    during this phase found no reliable alternative forcing mechanism --
    no dedicated currency cookie, and the CurrencyPicker XHR returns the
    full candidate list rather than the active selection)."""
    lines = body_text.split("\n")
    for i in range(len(lines) - 1):
        symbol = lines[i].strip()
        name = lines[i + 1].strip().lower()
        for code, (marker_symbol, marker_name) in _CURRENCY_MARKERS.items():
            if symbol == marker_symbol and name == marker_name:
                return code
    return None


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
    warmup_dwell_s: tuple[float, float] = (2.0, _MAX_WARMUP_DWELL_S)
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


_PLACEMENT_START_MARKER = "This is a paid placement from"
_PLACEMENT_END_MARKER = "View Deal"

# Precautionary, NOT observed live. Every real placement seen so far (19 blocks
# across two 2026-08-11 captures) carries the disclosure sentence above, and
# "Ad" only ever appears as its own line *inside* such a block. These two forms
# are named in plan 019's write-up as shapes Kayak might also use, so they are
# handled -- but only as a whole line, never as a substring, because "Sponsored"
# or "Ad" appearing mid-sentence in real copy would otherwise swallow every
# price up to the next "View Deal".
_PLACEMENT_ALT_START_LINES = ("sponsored", "| ad", "ad |")

# A placement block is a handful of lines. Without a bound, one false-positive
# start marker on a page with no later "View Deal" would strip the entire
# remainder of the results -- silently, and looking exactly like "no flights".
_PLACEMENT_MAX_BLOCK_LINES = 40

# Kayak offers a cheaper fare from a DIFFERENT airport ("Depart from nearby VCP
# and save EUR78"), and _results_section's slice starts at the top of the
# results, so this block and its price land in the extraction input. That price
# is not for the route being tracked. Same class of defect as the paid
# placement -- a real price, printed on the page, belonging to something else --
# so grounding cannot catch it either. Observed live 2026-08-11 on GRU-ZRH.
# BOTH directions exist: "Depart from nearby VCP and save EUR78" (origin,
# GRU-ZRH) and "Arrive at nearby ORY and save EUR160" (destination, GRU-CDG,
# found 2026-08-11 only after the origin form was already fixed). Matching one
# and assuming the other did not exist is exactly how the EUR160 ORY fare was
# still reaching a CDG tracker's extraction input.
_NEARBY_AIRPORT_START_MARKERS = ("Depart from nearby", "Arrive at nearby")
_NEARBY_AIRPORT_END_MARKER = "Show all"
_NEARBY_AIRPORT_MAX_BLOCK_LINES = 12


# Kayak labels some itineraries "Self-transfer hack": two SEPARATELY TICKETED
# flights it has stitched together. They are real and genuinely printed, so
# every guard passes -- but they are a different product from the one this
# tracker follows. A missed connection is not protected, the legs are booked
# apart, and because they are usually the cheapest thing on the page they
# dominate best_price and (permanently, since it is never recomputed)
# historical_best_price. Observed 2026-08-11: Arajet+Air Europa, 3 stops via
# PUJ, EUR702 while the cheapest normal fare was EUR784 -- and absent from the
# user's own kayak.com session entirely. Excluded by decision, not by defect;
# TODO.md carries surfacing them as an opt-in feature.
_SELF_TRANSFER_MARKER = "Self-transfer hack"
# Each itinerary block ends with a result marker ("Select"), so that bounds the
# span exactly. The cap only guards a page whose structure changed.
_SELF_TRANSFER_MAX_BLOCK_LINES = 60


def _strip_self_transfer_rows(body_text: str) -> str:
    """Remove whole "Self-transfer hack" itinerary blocks.

    Runs BEFORE _results_section slices, so a removed block does not consume
    one of the top-N slots the model is asked to read.
    """
    if _SELF_TRANSFER_MARKER not in body_text:
        return body_text

    lines = body_text.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if _SELF_TRANSFER_MARKER in lines[i]:
            end = i + 1
            limit = min(len(lines), i + 1 + _SELF_TRANSFER_MAX_BLOCK_LINES)
            while end < limit and lines[end].strip().lower() not in _RESULT_MARKERS_LOWER:
                end += 1
            if end < limit:
                i = end + 1
                continue
            # No result marker within range: drop only the label line rather
            # than guessing, exactly as the placement strips do.
            i += 1
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept)


def _is_placement_start(line: str) -> bool:
    if _PLACEMENT_START_MARKER in line:
        return True
    return line.strip().casefold() in _PLACEMENT_ALT_START_LINES


def _strip_nearby_airport_promos(body_text: str) -> str:
    """Remove "Depart from nearby XXX and save EUR N ... Show all" blocks.

    The fare inside belongs to a different origin airport, so attributing it to
    this tracker's route would store a price the user cannot actually book for
    the searched itinerary.
    """
    if not any(m in body_text for m in _NEARBY_AIRPORT_START_MARKERS):
        return body_text

    lines = body_text.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        if any(m in lines[i] for m in _NEARBY_AIRPORT_START_MARKERS):
            end = i + 1
            limit = min(len(lines), i + 1 + _NEARBY_AIRPORT_MAX_BLOCK_LINES)
            while end < limit and _NEARBY_AIRPORT_END_MARKER not in lines[end]:
                end += 1
            if end < limit:
                i = end + 1
                continue
            # No terminator within the expected span: drop only the promo line
            # itself rather than guessing where the block ends.
            i += 1
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept)


def _strip_placements(body_text: str) -> str:
    """Remove paid-placement blocks before the model ever sees them (plan 020
    Decision 1) -- a prompt instruction is a request, removing the text is a
    guarantee. A block starts at the line carrying the disclosure sentence
    and ends at the next 'View Deal' line, inclusive.

    The end search deliberately starts on the line AFTER the disclosure
    line, not on it: the disclosure line itself always ends with its own
    'View Deal' (its price sits inline), so anchoring there would strip only
    that one line and leave the block's other standalone price repeats
    behind -- exactly the €806 defect this exists to fix.
    """
    lines = body_text.split("\n")
    if not any(_is_placement_start(line) for line in lines):
        return body_text

    kept = []
    i = 0
    while i < len(lines):
        if _is_placement_start(lines[i]):
            end = i + 1
            limit = min(len(lines), i + 1 + _PLACEMENT_MAX_BLOCK_LINES)
            while end < limit and _PLACEMENT_END_MARKER not in lines[end]:
                end += 1
            i = end + 1 if end < limit else i + 1
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept)


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

    body_text = _strip_self_transfer_rows(
        _strip_nearby_airport_promos(_strip_placements(body_text))
    )
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


def _build_extraction_user_message(body_text: str, top_n: int, depart_date: str) -> str:
    """The user message sent to the extraction model.

    Module-level and pure so scripts/kayak_model_benchmark.py can import it
    rather than keep a byte-copy -- a benchmark that measured a different
    prompt than production would measure the wrong thing (plan 027 #4).
    """
    return (
        f"These flights depart on {depart_date}. Use that "
        "date for departure_time, and for arrival_time unless the "
        "itinerary arrives after midnight, which the page marks "
        '"+1".\n\n'
        f"Extract up to {top_n} flights from this Kayak "
        f"results page text:\n\n{_results_section(body_text, top_n)}"
    )


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


class _WorkerProcess:
    """Gives `subprocess.Popen` the slice of the `asyncio.subprocess.Process`
    surface `_render` needs, running the blocking calls off the event loop."""

    def __init__(self, popen: subprocess.Popen) -> None:
        self._popen = popen

    @property
    def returncode(self) -> int | None:
        return self._popen.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return await asyncio.to_thread(self._popen.communicate)

    def kill(self) -> None:
        self._popen.kill()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._popen.wait)


async def _spawn_render_worker(*argv: str) -> _WorkerProcess:
    """Spawn the render worker WITHOUT forking.

    Not `asyncio.create_subprocess_exec`: under uvloop that is libuv's
    fork-based `uv_spawn`, and this process cannot survive a fork -- the child
    segfaults finalising an inherited curl_cffi handle (plan 021 root cause,
    `.agent/reports/021-phase-1-rootcause.md`). `subprocess.Popen` does not go
    through the event loop at all, and with an absolute executable, no `cwd`
    and `close_fds=False` it routes to `os.posix_spawn`, which shares the
    address space instead of copying it so no finaliser ever runs in a child.

    `close_fds=False` is safe here because Python marks its own descriptors
    close-on-exec (PEP 446); only explicitly-inheritable ones would pass down.
    """
    popen = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=False,
    )
    return _WorkerProcess(popen)


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
        # Built before _render (plan 019 task 1.4): a render that hangs to
        # _OVERALL_TIMEOUT_S used to leave the `finally` below unreached, so
        # the hardest failures left no sample at all (018 attempt 7).
        body_text = ""
        record = {
            **self.sample_context,
            "config_id": self.config.config_id,
            "blocked_by_markers": False,
            "blocked_by_structure": False,
            "extracted_rows": 0,
            "validated_rows": 0,
            "outcome": "error",
        }

        try:
            body_text = await self._render(url)
            record["blocked_by_markers"] = self._looks_blocked(body_text)
            record["blocked_by_structure"] = _looks_blocked_structurally(body_text)

            if record["blocked_by_markers"] or record["blocked_by_structure"]:
                record["outcome"] = "blocked"
                signal = "markers" if record["blocked_by_markers"] else "page structure"
                self.last_error = f"Kayak render appears blocked by bot detection ({signal})"
                self.last_error_level = "WARNING"
                return []

            # Same cost-ordering rule as the block check (plan 019 task 1.2):
            # never spend an LLM call on a page we are going to refuse
            # anyway. An unreadable currency is refused too -- an
            # unverifiable currency is not a usable one.
            served_currency = _page_currency(body_text)
            if served_currency != currency:
                record["outcome"] = "currency_mismatch"
                if served_currency is None:
                    self.last_error = (
                        f"Kayak page currency could not be verified (requested {currency})"
                    )
                else:
                    self.last_error = (
                        f"Kayak served {served_currency}, requested {currency} -- refusing"
                    )
                self.last_error_level = "WARNING"
                return []

            # Stripped at the call site, not only inside _results_section:
            # _extract is the seam a caller could mock or reimplement, and
            # the guarantee (Decision 1) has to hold regardless of what runs
            # inside it. Grounding below still uses the unstripped body_text
            # (task 1.4).
            # Over-fetch, then dedupe back down to top_n. Kayak lists the same
            # itinerary more than once when it sells it under several fare
            # brands -- observed 2026-08-11 on GRU-GVA, where two rows shared
            # 7:20 pm - 10:25 pm+1 at EUR641 and differed only by carrier list
            # ("LATAM Airlines, Iberia" vs "LATAM Airlines") and brand
            # ("Light + Economy Cabin" vs "Light"). _first_carrier collapses
            # the first difference and flight_key carries no brand, so both
            # arrive here identical. Slicing exactly top_n blocks meant that
            # duplicate consumed a slot ON THE PAGE, before extraction, so
            # deduping afterwards alone would return top_n-1 rows.
            rows = await self._extract(
                _strip_self_transfer_rows(
                    _strip_nearby_airport_promos(_strip_placements(body_text))
                ),
                top_n + _OVERFETCH_ROWS,
                depart_date,
            )
            record["extracted_rows"] = len(rows)
            if not rows:
                record["outcome"] = "no_flights"
                self.last_error = (
                    "Kayak extraction found no flights (route may genuinely have none)"
                )
                self.last_error_level = "WARNING"
                return []

            validated, rebased_count = self._validate(rows, body_text, depart_date)
            record["validated_rows"] = len(validated)
            record["rebased_rows"] = rebased_count
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
            elif rebased_count:
                # No other message set (dropped == 0): surface the rebase on
                # /monitor, the only channel that has caught this class of
                # problem before (see _rebase_departure_date).
                record["outcome"] = "extracted"
                self.last_error = (
                    f"Kayak validation rebased {rebased_count} row(s) onto depart_date "
                    "(night rollover)"
                )
                self.last_error_level = "WARNING"
            else:
                record["outcome"] = "extracted"

            deduped = self._dedupe_rows(validated)[:top_n]
            record["stored_rows"] = len(deduped)
            return [self._map_result(row, currency, url) for row in deduped]
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
        fd, out_path = tempfile.mkstemp(prefix="kayak-render-", suffix=".txt")
        os.close(fd)

        argv = (
            sys.executable,
            "-m",
            _RENDER_WORKER_MODULE,
            url,
            json.dumps(asdict(self.config)),
            out_path,
        )
        timeout = _WORKER_TIMEOUT_S

        try:
            proc = await _spawn_render_worker(*argv)
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except (asyncio.TimeoutError, TimeoutError):
                # Kill AND reap: plan 020 Phase 3 found 171 orphaned Chromium
                # processes, which is what killing without waiting produces.
                proc.kill()
                await proc.wait()
                raise RuntimeError(
                    f"kayak render worker exceeded {timeout:.0f}s and was killed"
                ) from None

            if proc.returncode != 0:
                detail = (stderr or b"").decode("utf-8", "replace").strip()
                raise RuntimeError(
                    f"kayak render worker exited {proc.returncode}: {detail}"
                )

            with open(out_path, encoding="utf-8") as handle:
                return handle.read()
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

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
                        "content": _build_extraction_user_message(body_text, top_n, depart_date),
                    },
                ],
                response_format={"type": "json_object"},
                # DeepSeek thinks by default at "high" effort, which cost
                # 2677-4311 reasoning tokens to emit ~300 tokens of JSON --
                # 23.7-49.4s against a 30s budget. Disabled it measures
                # 3.5-4.7s on 439-453 tokens with byte-identical output:
                # reading fields out of already-structured text is not a
                # reasoning task. Passed through opencode's Zen proxy
                # (verified 2026-08-05).
                extra_body={"thinking": {"type": "disabled"}},
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
    def _time_grounded(value, body_text: str) -> bool:
        """Is this extracted clock time actually printed on the page?

        Ported from scripts/kayak_model_benchmark.py, where it decided the
        Phase 3b benchmark (plan 019 task 4.0). Kayak renders the cheapest
        GRU-LIS itinerary as "12:30 am - 5:40 pm" and a model reading that
        departure as 12:30 pm produces a value that parses, survives
        _canonical_timestamp and grounds its price -- yet both times are two
        thirds of the identity key, so it is a second flight_key for one
        physical flight. That is the defect Phase 2 exists to remove, arriving
        through the one field nothing checked. The winning model still misreads
        ~2% of runs, which at a 3h cadence is a phantom identity every day or
        two.

        Two deliberate abstentions, both of the same kind as
        _looks_blocked_structurally's "a long page with no recognised button is
        not a block": an unparseable value is KEPT (matching
        _canonical_timestamp, which stores such a row rather than dropping it
        -- this check is aimed at the misread, not at making parsing
        mandatory), and a body printing no recognisable clock time at all
        grounds nothing, since there is nothing to check against.
        """
        try:
            parsed = datetime.fromisoformat(str(value or "").strip())
        except ValueError:
            return True

        lowered = body_text.lower()
        if _TWELVE_HOUR_TIME_RE.search(lowered):
            hour12 = parsed.hour % 12 or 12
            meridiem = "am" if parsed.hour < 12 else "pm"
            return f"{hour12}:{parsed.minute:02d} {meridiem}" in lowered
        if _ANY_CLOCK_TIME_RE.search(lowered):
            # Only reached when the page prints no am/pm anywhere, i.e. a
            # force-redirect to a 24-hour locale (pt-BR/de-CH), where
            # demanding the 12-hour form would drop every row of a perfectly
            # good page -- the same silent data loss _price_grounded's
            # dot-thousands fallback exists to prevent.
            return any(
                form in lowered
                for form in (
                    f"{parsed.hour:02d}:{parsed.minute:02d}",
                    f"{parsed.hour}:{parsed.minute:02d}",
                )
            )
        return True

    # Kayak's own row label for a multi-carrier self-transfer itinerary
    # (plan 020 Decision 3 -- verified against the real captured body, 8
    # occurrences, not a model invention). Treated as unconditionally
    # trusted rather than substring-matched: unlike a named carrier, this
    # exact label is Kayak's own generated text for the row, not something
    # the model could have copied from elsewhere on the page and mis-bound.
    _TRUSTED_AIRLINE_LABELS = {"multiple airlines"}

    @staticmethod
    def _airline_grounded(airline, body_text: str) -> bool:
        """Is this extracted carrier actually printed on the page?

        Closes the last ungrounded third of flight_key
        (airline|departure_time|arrival_time) -- price and both clock times
        are already checked, so a fabricated airline could still fork a
        flight the same way a misread time does. Normalised the same way
        make_flight_key normalises (casefold, collapse whitespace), so a
        pure case difference is never treated as a fabrication.
        """
        normalized = " ".join(str(airline or "").split()).casefold()
        if normalized in KayakSource._TRUSTED_AIRLINE_LABELS:
            return True
        return normalized in body_text.casefold()

    @staticmethod
    def _rebase_departure_date(row: dict, depart_date: str) -> dict:
        """Bucket an after-midnight departure landing on depart_date+1 under depart_date.

        Not a misread to correct -- a deliberate window (2026-08-13,
        user-confirmed: "a flight at 00:45 on 22/08 counts as night of
        21/08 even if not formally correct"). Observed live on tracker 20
        GRU-ZRH: TAP AIR PORTUGAL / Azul rows printed on Kayak's own
        2026-08-21-dated results page as a bare "12:45 am" departure, but
        extracted with a 2026-08-22 date on 6 of several occasions across
        4 snapshots (2026-08-11 through 2026-08-13) -- the same real,
        printed itinerary (price, layover, duration all match the captured
        body, 20260813T005700.382768.txt lines 150/168) landing on either
        side of midnight depending on the run. _extract's prompt tells the
        model to use depart_date for departure_time and +1 only for an
        overnight arrival, so depart_date is the one field known with
        certainty regardless of which way a given run reads it -- rebase
        departure_time onto it and shift arrival_time by the identical
        delta, preserving the elapsed gap the model computed.

        Bounded to _NIGHT_ROLLOVER_CUTOFF_HOUR and exactly one day so this
        stays "the same evening's late flight", not silent tolerance for an
        arbitrarily wrong date: a departure two-plus days off, or one that
        lands after the cutoff, is left untouched -- almost certainly a
        different, unrelated flight rather than a night rolling over.
        An unparseable departure_time is also left untouched, matching
        _canonical_timestamp's "unparseable passes through" rule.
        """
        try:
            expected = date.fromisoformat(depart_date)
            dep_dt = datetime.fromisoformat(str(row.get("departure_time") or "").strip())
        except ValueError:
            return row

        if (dep_dt.date() - expected).days != 1 or dep_dt.hour >= _NIGHT_ROLLOVER_CUTOFF_HOUR:
            return row

        delta = timedelta(days=1)
        corrected = dict(row)
        corrected["departure_time"] = (dep_dt - delta).isoformat()
        try:
            arr_dt = datetime.fromisoformat(str(row.get("arrival_time") or "").strip())
            corrected["arrival_time"] = (arr_dt - delta).isoformat()
        except ValueError:
            pass
        return corrected

    @staticmethod
    def _validate(
        rows: list[dict], body_text: str, depart_date: str | None = None
    ) -> tuple[list[dict], int]:
        grounded = []
        rebased_count = 0
        for row in rows:
            if depart_date is not None:
                rebased = KayakSource._rebase_departure_date(row, depart_date)
                if rebased is not row:
                    rebased_count += 1
                row = rebased
            price = row.get("price")
            if price is None or price <= 0:
                logger.warning("Dropping Kayak row with non-positive/missing price: %r", row)
                continue
            if not KayakSource._price_grounded(price, body_text):
                logger.warning("Dropping Kayak row whose price is absent from rendered text: %r", row)
                continue
            if not KayakSource._time_grounded(
                row.get("departure_time"), body_text
            ) or not KayakSource._time_grounded(row.get("arrival_time"), body_text):
                logger.warning(
                    "Dropping Kayak row whose clock time is absent from rendered text: %r", row
                )
                continue
            if not KayakSource._airline_grounded(row.get("airline"), body_text):
                logger.warning(
                    "Dropping Kayak row whose airline is absent from rendered text: %r", row
                )
                continue
            grounded.append(row)

        if not grounded:
            return grounded, rebased_count

        prices = sorted(r["price"] for r in grounded)
        n = len(prices)
        median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

        kept = []
        for row in grounded:
            if median > 0 and row["price"] > 10 * median:
                logger.warning("Dropping Kayak row priced wildly outside the band of other rows: %r", row)
                continue
            kept.append(row)
        return kept, rebased_count

    @staticmethod
    def _dedupe_rows(rows: list[dict]) -> list[dict]:
        """Collapse rows we cannot tell apart.

        Two rows identical in carrier, both clock times and price are the same
        offer as far as anything downstream can see: they share a flight_key,
        so they occupy one chart line and one colour slot, and the second adds
        no information to the results table. They are NOT necessarily the same
        product -- Kayak sells one itinerary under several fare brands -- but
        the distinguishing field (brand) is not captured, so storing the row
        twice states a difference that nothing can read. Capturing fare brand
        is on the roadmap; until then, first occurrence wins (rows arrive
        cheapest-first).

        Identity is read off _map_result's output, not off the raw extracted
        row, because every normalisation that MAKES two rows identical runs in
        _map_result: _first_carrier folds "LATAM Airlines, Iberia" into "LATAM
        Airlines" and _canonical_timestamp folds "...T19:20" into
        "...T19:20:00". Comparing raw fields let the exact pair this function
        exists for through -- tracker 21 stored the duplicate on all 23 runs of
        2026-08-11 and lost a genuine fifth itinerary to the top_n slice each
        time. Mapping first means a normalisation added later cannot silently
        reopen that gap.
        """
        seen: set[tuple] = set()
        kept: list[dict] = []
        for row in rows:
            mapped = KayakSource._map_result(row, "", "")
            identity = (
                " ".join(mapped.airline.split()).casefold(),
                mapped.departure_time,
                mapped.arrival_time,
                mapped.price,
            )
            if identity in seen:
                continue
            seen.add(identity)
            kept.append(row)
        return kept

    # _canonical_timestamp used to live here. It is now
    # fingerprint.canonical_timestamp, because a normalisation the identity
    # layer depends on but cannot see is exactly the shape plan 025 exists to
    # remove: it stops applying the moment another source appears.
    _canonical_timestamp = staticmethod(canonical_timestamp)

    @staticmethod
    def _first_carrier(value) -> str:
        # Kayak names a connecting itinerary by every operator
        # ("Azul, easyJet") while the Google sources use only the first
        # (fast_flights.py, `r.airlines[0]`). This stays source-local because
        # it shapes the DISPLAYED airline, which is the source's business;
        # normalize_airline splits the same list for identity purposes, so a
        # source that skips this step still gets the right key.
        text = " ".join(str(value or "").split())
        return text.split(",")[0].strip()

    @staticmethod
    def _clean_flight_number(value) -> str:
        text = " ".join(str(value or "").split())
        return "" if text.lower() in _PLACEHOLDER_FLIGHT_NUMBERS else text

    @staticmethod
    def _map_result(row: dict, currency: str, url: str) -> FlightResult:
        return FlightResult(
            source="kayak",
            price=float(row["price"]),
            currency=currency,
            duration_min=row.get("duration_min"),
            stops=row.get("stops") or 0,
            airline=KayakSource._first_carrier(row.get("airline")),
            flight_number=KayakSource._clean_flight_number(row.get("flight_number")),
            departure_time=KayakSource._canonical_timestamp(row.get("departure_time")),
            arrival_time=KayakSource._canonical_timestamp(row.get("arrival_time")),
            legs_json="[]",
            booking_url=url,
        )

import asyncio
import json
import logging
import os

from backend.sources.base import FlightResult

logger = logging.getLogger(__name__)

_API_KEY_ENV = "DEEPSEEK_API_KEY"
_LLM_BASE_URL = "https://api.deepseek.com"
# TODO(plan 017 decision 6): unverified against DeepSeek's live model list --
# confirm model id, context window and pricing before enabling this in prod.
_LLM_MODEL = "deepseek-chat"

_RENDER_TIMEOUT_S = 45.0
_LLM_TIMEOUT_S = 30.0
_OVERALL_TIMEOUT_S = 90.0

_BLOCKED_MARKERS = (
    "verify you are human",
    "unusual traffic",
    "are you a robot",
    "captcha",
    "access denied",
    "automated queries",
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


class KayakSource:
    def __init__(self) -> None:
        self.last_error: str | None = None
        self.last_error_level: str = "ERROR"

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
                self._search_inner(url, top_n, currency),
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

    async def _search_inner(self, url: str, top_n: int, currency: str) -> list[FlightResult]:
        body_text = await self._render(url)

        if self._looks_blocked(body_text):
            self.last_error = "Kayak render appears blocked by bot detection"
            self.last_error_level = "WARNING"
            return []

        rows = await self._extract(body_text, top_n)
        if not rows:
            self.last_error = "Kayak extraction found no flights (route may genuinely have none)"
            self.last_error_level = "WARNING"
            return []

        validated = self._validate(rows, body_text)
        return [self._map_result(row, currency, url) for row in validated]

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
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=_RENDER_TIMEOUT_S * 1000)
                await self._wait_for_results_stable(page)
                return await page.inner_text("body")
            finally:
                await browser.close()

    @staticmethod
    async def _wait_for_results_stable(page, cap_seconds: float = _RENDER_TIMEOUT_S) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + cap_seconds
        previous_count = -1
        stable_polls = 0
        while loop.time() < deadline:
            count = await page.get_by_text("Select", exact=True).count()
            if count > 0 and count == previous_count:
                stable_polls += 1
                if stable_polls >= 2:
                    return
            else:
                stable_polls = 0
            previous_count = count
            await asyncio.sleep(1)

    async def _extract(self, body_text: str, top_n: int) -> list[dict]:
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
                        "content": f"Extract up to {top_n} flights from this Kayak "
                        f"results page text:\n\n{body_text}",
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
        n = int(price) if price == int(price) else price
        representations = {str(n), f"{n:,}"}
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
            stops=row.get("stops"),
            airline=row.get("airline", ""),
            flight_number=row.get("flight_number", ""),
            departure_time=row.get("departure_time", ""),
            arrival_time=row.get("arrival_time", ""),
            legs_json="[]",
            booking_url=url,
        )

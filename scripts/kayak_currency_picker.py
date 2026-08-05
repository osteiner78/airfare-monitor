"""Plan 019 Part B: can Kayak's currency be forced by driving the picker UI?

Phase 1 falsified every cheaper mechanism (the ?currency= URL param, a fresh
cookie-less profile, imitating a currency cookie, the CurrencyPicker XHR).
The one untried path is the UI itself: the bundle runs headful with a
persistent profile at data/kayak-profile, so a preference the picker stores
should survive into later renders.

Two modes, run as separate processes so the "does it persist" question is
answered by a genuinely separate browser session:

    set     open Kayak, drive the picker to EUR, dump what changed
    verify  fresh session, same profile, read back what is actually served

Every live page load is real traffic against the residential IP -- each mode
is deliberately one navigation (plus the bundle's own warm-up on `set`).
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sources.kayak import (  # noqa: E402
    KayakRenderConfig,
    _context_options,
    _launch_args,
    _page_currency,
    _probe_default_user_agent,
    _simulate_interaction,
)

TARGET = "EUR"
SEARCH_URL = "https://www.kayak.com/flights/GRU-LIS/2026-10-04?sort=price_a"
OUT_DIR = os.environ.get("KAYAK_EXP_DIR", "data/kayak-currency-experiment")


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _open(p, config: KayakRenderConfig):
    default_ua = await _probe_default_user_agent(p)
    options = _context_options(config, default_ua)
    context = await p.chromium.launch_persistent_context(
        config.user_data_dir,
        headless=config.headless,
        args=_launch_args(config),
        locale=options["locale"],
        timezone_id=options["timezone_id"],
        viewport=options["viewport"],
        user_agent=options["user_agent"],
    )
    return context


async def _dump(page, tag: str) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    body = await page.inner_text("body")
    with open(os.path.join(OUT_DIR, f"{tag}.txt"), "w") as fh:
        fh.write(body)
    try:
        await page.screenshot(path=os.path.join(OUT_DIR, f"{tag}.png"), full_page=False)
    except Exception as e:
        _log(f"  (screenshot failed: {type(e).__name__}: {e})")
    return body


async def _storage_snapshot(page) -> dict:
    return await page.evaluate(
        """() => {
            const ls = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                ls[k] = (localStorage.getItem(k) || '').slice(0, 200);
            }
            return ls;
        }"""
    )


async def mode_set() -> None:
    from patchright.async_api import async_playwright

    config = KayakRenderConfig()
    _log(f"profile: {config.user_data_dir}  headless={config.headless}")

    async with async_playwright() as p:
        context = await _open(p, config)
        try:
            page = context.pages[0] if context.pages else await context.new_page()

            _log("navigating to kayak.com ...")
            await page.goto("https://www.kayak.com/", timeout=45000)
            await asyncio.sleep(4)
            await _simulate_interaction(page)

            body = await _dump(page, "01-before")
            _log(f"  url={page.url}")
            _log(f"  body_len={len(body)}  page_currency={_page_currency(body)}")

            # Egress geography force-redirects the homepage to a local site
            # (kayak.com.br from Brazil). Preferences are stored per-origin,
            # and searches run against www.kayak.com -- so a currency set on
            # the .br origin would not apply to the page we actually render.
            if "kayak.com.br" in page.url or "kayak.com/" not in page.url + "/":
                _log("  redirected off www.kayak.com; taking the 'Go to kayak.com' escape")
                for label in ("Go to kayak.com instead.", "Go to kayak.com instead"):
                    loc = page.get_by_text(label, exact=True)
                    if await loc.count():
                        await loc.first.click(timeout=8000)
                        await asyncio.sleep(5)
                        _log(f"  now at {page.url}")
                        break
                body = await _dump(page, "01b-after-escape")
                _log(f"  body_len={len(body)}  page_currency={_page_currency(body)}")

            before_ls = await _storage_snapshot(page)

            # The footer carries a language/currency control rendered as
            # symbol + ISO code (observed: "Português / R$ / BRL"); the
            # results-page header uses symbol + full name ("$ / United
            # States dollar"). Try both vocabularies, and prefer the LAST
            # match -- the footer control sits at the end of the document,
            # while a bare "$" can appear in fare text higher up.
            _log("looking for the currency control ...")
            opened = False
            for label in ("BRL", "USD", "United States dollar", "R$", "$", "€"):
                loc = page.get_by_text(label, exact=True)
                try:
                    n = await loc.count()
                except Exception:
                    n = 0
                _log(f"  candidate {label!r}: {n} match(es)")
                if n:
                    try:
                        await loc.last.click(timeout=8000)
                        opened = True
                        _log(f"  clicked {label!r} (last match)")
                        break
                    except Exception as e:
                        _log(f"  click failed: {type(e).__name__}: {e}")

            if not opened:
                _log("could not open the picker; dumping and stopping")
                await _dump(page, "02-no-picker")
                return

            await asyncio.sleep(3)
            modal = await _dump(page, "02-picker-open")
            _log(f"  after click body_len={len(modal)}")
            # Show what the opened control actually offers, so a failed
            # selection can be diagnosed without spending another page load.
            hits = [ln.strip() for ln in modal.split("\n")
                    if ln.strip() and ("EUR" in ln or "Euro" in ln or "€" in ln)]
            _log(f"  euro-ish lines now on page: {hits[:10]}")

            _log(f"selecting {TARGET} ...")
            chosen = False
            for label in ("Euro", "EUR", "€ Euro", "€"):
                loc = page.get_by_text(label, exact=True)
                try:
                    n = await loc.count()
                except Exception:
                    n = 0
                _log(f"  option {label!r}: {n} match(es)")
                if n:
                    try:
                        await loc.first.click(timeout=8000)
                        chosen = True
                        _log(f"  clicked {label!r}")
                        break
                    except Exception as e:
                        _log(f"  click failed: {type(e).__name__}: {e}")

            if not chosen:
                _log("picker opened but no EUR option was clickable; dumping and stopping")
                await _dump(page, "03-no-eur")
                return

            await asyncio.sleep(4)

            # Selecting the currency only applies it to the current visit.
            # Kayak then asks "Save currency for future? ... Save for future /
            # One time only" -- closing the browser without answering is what
            # made the first attempt fail to persist (2026-08-05).
            _log("answering the 'save for future?' prompt ...")
            saved = False
            for label in ("Save for future", "Save for future visits", "Save"):
                loc = page.get_by_text(label, exact=True)
                try:
                    n = await loc.count()
                except Exception:
                    n = 0
                _log(f"  save option {label!r}: {n} match(es)")
                if n:
                    try:
                        await loc.first.click(timeout=8000)
                        saved = True
                        _log(f"  clicked {label!r}")
                        break
                    except Exception as e:
                        _log(f"  click failed: {type(e).__name__}: {e}")
            if not saved:
                _log("  WARNING: no save-for-future control found; preference may be one-time only")

            await asyncio.sleep(5)
            body = await _dump(page, "04-after")
            _log(f"  body_len={len(body)}  page_currency={_page_currency(body)}")
            _log(f"  footer tail: {[l for l in body.split(chr(10))[-6:] if l.strip()]}")

            after_ls = await _storage_snapshot(page)
            changed = {
                k: v for k, v in after_ls.items()
                if before_ls.get(k) != v
            }
            _log(f"localStorage keys changed by the picker: {list(changed)}")
            with open(os.path.join(OUT_DIR, "localstorage-delta.json"), "w") as fh:
                json.dump(changed, fh, indent=2)

            cookies = await context.cookies()
            with open(os.path.join(OUT_DIR, "cookies-after.json"), "w") as fh:
                json.dump(cookies, fh, indent=2)
            _log(f"cookies after: {len(cookies)} -> {sorted({c['name'] for c in cookies})}")
        finally:
            await context.close()
            _log("context closed (profile flushed to disk)")


async def mode_verify() -> None:
    from patchright.async_api import async_playwright

    config = KayakRenderConfig()
    async with async_playwright() as p:
        context = await _open(p, config)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            _log(f"navigating to {SEARCH_URL} (no currency param) ...")
            await page.goto(SEARCH_URL, timeout=45000)
            await asyncio.sleep(12)
            await _simulate_interaction(page)

            body = await _dump(page, "05-verify")
            served = _page_currency(body)
            _log(f"  body_len={len(body)}")
            _log(f"  _page_currency() -> {served!r}   (want {TARGET!r})")

            euro_prices = body.count("€")
            dollar_prices = body.count("$")
            _log(f"  '€' occurrences: {euro_prices}   '$' occurrences: {dollar_prices}")
            _log(f"RESULT: {'PASS' if served == TARGET else 'FAIL'}")
        finally:
            await context.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "set"
    asyncio.run(mode_set() if mode == "set" else mode_verify())

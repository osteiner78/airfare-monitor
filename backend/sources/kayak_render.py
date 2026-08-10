"""Out-of-process Chromium render worker (plan 021).

The ASGI worker cannot `fork()`: uvloop's `create_subprocess_exec` is libuv's
fork-based `uv_spawn`, and a forked child segfaults finalising an inherited
`curl_cffi` handle left behind by the fli Google Flights source (see the
"fork() is unsafe in the ASGI worker" note in CLAUDE.md). Patchright launches
its Node driver that way, which is why Kayak never once rendered in
production.

This module runs in a freshly exec'd process that never imports fli or
curl_cffi, so patchright's own internal spawn is safe here.

The render logic below is moved unchanged from `KayakSource._render` (plan
018 measured it at 0 blocks in 10 live attempts); the pure configuration
helpers stay in `kayak.py`, which owns them and their tests.

Invoked as: python -m backend.sources.kayak_render <url> <config-json> <out-path>
The body is written to <out-path> rather than stdout, because Chromium and
the Node driver both write to stdout and would corrupt it.
"""

import asyncio
import json
import sys

from backend.sources.kayak import (
    _RENDER_TIMEOUT_S,
    _RESULT_MARKERS,
    KayakRenderConfig,
    _context_options,
    _launch_args,
    _probe_default_user_agent,
    _simulate_interaction,
    _warmup_sequence,
)


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


async def render(url: str, config: KayakRenderConfig) -> str:
    from patchright.async_api import async_playwright

    launch_args = _launch_args(config)

    async with async_playwright() as p:
        # The real default UA comes from the browser itself (Decision 4:
        # derived from the launched build's own version, never hardcoded).
        # Context creation options can't be changed after the fact, so this
        # has to resolve before the real context.
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
            await _wait_for_results_stable(page)
            await _simulate_interaction(page)
            return await page.inner_text("body")
        finally:
            await context.close()
            if browser_to_close is not None:
                await browser_to_close.close()


def main(argv: list[str]) -> None:
    url, config_json, out_path = argv[0], argv[1], argv[2]
    config = KayakRenderConfig(**json.loads(config_json))
    body = asyncio.run(render(url, config))
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(body)


if __name__ == "__main__":
    main(sys.argv[1:])

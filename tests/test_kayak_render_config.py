"""Tests for plan 018 Phase 1 — the C1-C4 evasion bundle as a config seam.

All offline: no browser is launched anywhere in this file. Every helper under
test is pure, or takes an injected value (a default user-agent string, a mock
page) in place of a live browser -- that is the point of the seam. If a test
here needs Playwright to run, the seam is in the wrong place.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.

Everything here is NEW-BEHAVIOR: before Phase 1 these fail with ImportError
(`KayakRenderConfig`, `_launch_args`, `_context_options`,
`_fingerprint_is_consistent`, `_warmup_sequence`, `_simulate_interaction`,
`_result_marker`).

API contract these tests pin (the plan leaves some of it open, so the
implementer should follow what is asserted here):
  - `_context_options(config, default_ua)` takes the browser's *default user
    agent string*, not a Browser object -- keeping it pure is what makes it
    testable without launching anything.
  - `_warmup_sequence(config)` returns only the PRE-search navigation steps,
    as `[(url, dwell_seconds), ...]`; the search URL itself is not a member,
    so the sequence is empty when warm-up is disabled.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

_SEARCH_URL = "https://www.kayak.com.br/flights/GRU-LIS/2026-10-04?sort=price_a"

# Verbatim shape of what headless Chromium reports for navigator.userAgent.
_HEADLESS_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "HeadlessChrome/141.0.0.0 Safari/537.36"
)


# --- launch args (C1) ---

async def test_launch_args_disable_automation_controlled_blink_feature():
    from backend.sources.kayak import KayakRenderConfig, _launch_args
    args = _launch_args(KayakRenderConfig())
    assert any("disable-blink-features=AutomationControlled" in a for a in args)


async def test_launch_args_do_not_enable_automation():
    """--enable-automation sets navigator.webdriver and advertises the session
    as automated -- the single cheapest signal to hand a detector."""
    from backend.sources.kayak import KayakRenderConfig, _launch_args
    args = _launch_args(KayakRenderConfig())
    assert not any("enable-automation" in a for a in args)


# --- user agent derivation (Decision 4: derive, never hardcode) ---

async def test_context_options_derive_user_agent_from_browser_version():
    """A hardcoded UA silently rots on the next image rebuild and becomes a
    signal rather than a disguise, so the UA must track whatever Chromium the
    image actually ships. Two different browser builds must yield two
    different UAs."""
    from backend.sources.kayak import KayakRenderConfig, _context_options

    config = KayakRenderConfig()
    older = _context_options(config, _HEADLESS_UA)["user_agent"]
    newer = _context_options(
        config, _HEADLESS_UA.replace("141.0.0.0", "999.0.0.0")
    )["user_agent"]

    assert "141" in older
    assert "999" in newer
    assert older != newer


async def test_derived_user_agent_strips_headless_token():
    from backend.sources.kayak import KayakRenderConfig, _context_options
    ua = _context_options(KayakRenderConfig(), _HEADLESS_UA)["user_agent"]
    assert "headless" not in ua.lower()
    assert "Chrome/141.0.0.0" in ua


# --- fingerprint self-consistency (Decision 3) ---

async def test_fingerprint_consistent_for_default_config():
    from backend.sources.kayak import KayakRenderConfig, _context_options, _fingerprint_is_consistent
    options = _context_options(KayakRenderConfig(), _HEADLESS_UA)
    assert _fingerprint_is_consistent(options) is True


async def test_fingerprint_inconsistent_when_user_agent_says_headless():
    from backend.sources.kayak import KayakRenderConfig, _context_options, _fingerprint_is_consistent
    options = _context_options(KayakRenderConfig(), _HEADLESS_UA)
    options["user_agent"] = _HEADLESS_UA
    assert _fingerprint_is_consistent(options) is False


async def test_fingerprint_inconsistent_when_locale_and_timezone_disagree():
    """A pt-BR browser reporting a Swiss timezone is more suspicious than no
    override at all -- this is the self-own the smoke test exists to catch
    before any live attempt is spent on it."""
    from backend.sources.kayak import KayakRenderConfig, _context_options, _fingerprint_is_consistent
    options = _context_options(
        KayakRenderConfig(locale="pt-BR", timezone_id="Europe/Zurich"), _HEADLESS_UA
    )
    assert _fingerprint_is_consistent(options) is False


async def test_fingerprint_inconsistent_for_headless_default_viewport():
    from backend.sources.kayak import KayakRenderConfig, _context_options, _fingerprint_is_consistent
    options = _context_options(
        KayakRenderConfig(viewport={"width": 0, "height": 0}), _HEADLESS_UA
    )
    assert _fingerprint_is_consistent(options) is False


# --- warm-up navigation (C3) ---

async def test_warmup_sequence_visits_homepage_before_search_url():
    """Cold-landing on a deep search URL with no referrer and no cookies is a
    classic scraper signature. These steps run before the search navigation."""
    from backend.sources.kayak import KayakRenderConfig, _warmup_sequence

    config = KayakRenderConfig(warmup_url="https://www.kayak.com.br/", warmup_dwell_s=(2.0, 5.0))
    steps = _warmup_sequence(config)

    assert len(steps) == 1
    url, dwell = steps[0]
    assert url == "https://www.kayak.com.br/"
    assert 2.0 <= dwell <= 5.0
    assert _SEARCH_URL not in [u for u, _ in steps]


async def test_warmup_sequence_empty_when_warmup_url_not_set():
    from backend.sources.kayak import KayakRenderConfig, _warmup_sequence
    assert _warmup_sequence(KayakRenderConfig(warmup_url=None)) == []


async def test_warmup_dwell_is_not_always_the_same_value():
    """A fixed dwell is itself a pattern; the range must actually be sampled."""
    from backend.sources.kayak import KayakRenderConfig, _warmup_sequence
    config = KayakRenderConfig(warmup_url="https://www.kayak.com.br/", warmup_dwell_s=(2.0, 5.0))
    dwells = {_warmup_sequence(config)[0][1] for _ in range(30)}
    assert len(dwells) > 1


# --- behavioural noise (task 1.7) ---

async def test_simulate_interaction_emits_mouse_and_scroll_events():
    """PerimeterX scores interaction telemetry; goto -> read emits none."""
    from backend.sources.kayak import _simulate_interaction

    page = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.evaluate = AsyncMock()

    await _simulate_interaction(page)

    assert page.mouse.move.await_count >= 1
    assert page.mouse.wheel.await_count >= 1 or page.evaluate.await_count >= 1


# --- locale-aware result marker (task 1.9) ---
# _wait_for_results_stable polls the count of the per-row action button text,
# and the structural block signal keys off the same token. Switching the
# bundle to kayak.com.br makes that button "Selecionar", not "Select" -- so a
# hardcoded "Select" would poll zero forever (burning the full render cap on
# every attempt) AND make the structural signal call every real results page
# blocked. The marker has to follow the locale.

async def test_result_marker_is_portuguese_for_pt_br_locale():
    from backend.sources.kayak import KayakRenderConfig, _result_marker
    assert _result_marker(KayakRenderConfig(locale="pt-BR")) == "Selecionar"


async def test_result_marker_is_english_for_en_locale():
    from backend.sources.kayak import KayakRenderConfig, _result_marker
    assert _result_marker(KayakRenderConfig(locale="en-US")) == "Select"


# --- the bundle as shipped ---

async def test_config_defaults_to_the_c1_c4_bundle():
    """Defaults are the deployable stack (C1-C4). C5 is deliberately absent:
    it attaches to a manually-launched Chrome and has no unattended form, so
    it must never be reachable through config (plan 018 Decision 2)."""
    from backend.sources.kayak import KayakRenderConfig

    config = KayakRenderConfig()
    assert config.headless is False              # C2
    assert config.user_data_dir                  # C3
    assert config.warmup_url                     # C3
    assert config.stealth is True                # C4
    assert config.locale and config.timezone_id  # C1
    assert config.viewport["width"] > 0 and config.viewport["height"] > 0


async def test_kayak_source_accepts_a_render_config():
    from backend.sources.kayak import KayakRenderConfig, KayakSource
    config = KayakRenderConfig(headless=True, user_data_dir=None, warmup_url=None)
    assert KayakSource(config=config).config is config


async def test_kayak_source_defaults_to_the_bundle_config():
    from backend.sources.kayak import KayakRenderConfig, KayakSource
    assert KayakSource().config == KayakRenderConfig()

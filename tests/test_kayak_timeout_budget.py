"""The overall Kayak budget must always cover its own sub-timeouts.

Plan 021 Phase 2 moved the render into a subprocess with a
`_WORKER_TIMEOUT_FACTOR * _RENDER_TIMEOUT_S` budget (112.5s), while
`_OVERALL_TIMEOUT_S` still assumed the old in-process bound of
`2 * _RENDER_TIMEOUT_S` (90s). Slack fell from 30s to 7.5s, and it cost real
data: the 02:37 run on 2026-08-11 rendered a full 19,085-char page in 124s and
then lost it to the overall cap mid-extraction -- `outcome: error`,
`extracted_rows: 0`, nothing wrong with the page at all.

It survived Phase 3's live verification because successful runs take 62-67s;
only the slow tail crosses 172.5s. That is exactly the kind of regression a
constant-vs-constant assertion catches and a live smoke test does not.

CLAUDE.md already warned "if changing either render/LLM timeout, re-check the
arithmetic still leaves slack". This file is that check, executable.

Plan 024 Phase 3 found the same rot one level down: the 2.5x worker factor was
itself written from a two-wait premise while the child performs three capped
waits plus the warmup dwell (140s of legitimate waiting against a 112.5s kill
cap). The factor is gone; the budget is now an explicit sum, and
`test_the_worker_cap_covers_every_wait_the_child_performs` reads the waits out
of the worker's own source so a fourth one cannot be added unnoticed.
"""

import re
from pathlib import Path

from backend.sources import kayak, kayak_render


def _worst_case() -> float:
    """Everything `_search_inner` can spend before the overall cap fires:
    the worker's own cap, then the LLM call."""
    return kayak._WORKER_TIMEOUT_S + kayak._LLM_TIMEOUT_S


def test_overall_timeout_exceeds_worst_case_render_plus_llm():
    assert kayak._OVERALL_TIMEOUT_S > _worst_case(), (
        f"_OVERALL_TIMEOUT_S ({kayak._OVERALL_TIMEOUT_S}s) cannot fire before "
        f"a render+extract that the sub-timeouts still permit "
        f"({_worst_case()}s) -- a fully rendered page would be discarded"
    )


def test_the_slack_is_a_real_margin_not_a_rounding_error():
    """7.5s was technically 'greater than' and still lost a good page. The
    margin has to absorb process spawn, sample capture and DB writes."""
    slack = kayak._OVERALL_TIMEOUT_S - _worst_case()
    assert slack >= 25.0, (
        f"only {slack}s of slack above the worst case -- this is how the "
        "2026-08-11 timeout happened"
    )


def test_the_budget_is_derived_not_hardcoded():
    """Pin the relationship, not the number: a future change to
    _RENDER_TIMEOUT_S must move _OVERALL_TIMEOUT_S with it."""
    original = kayak._RENDER_TIMEOUT_S
    try:
        kayak._RENDER_TIMEOUT_S = original * 2
        recomputed = (
            kayak._WARMUP_TIMEOUT_S
            + kayak._MAX_WARMUP_DWELL_S
            + 2 * kayak._RENDER_TIMEOUT_S
            + kayak._WORKER_STARTUP_ALLOWANCE_S
            + kayak._LLM_TIMEOUT_S
            + 30.0
        )
        assert recomputed > kayak._OVERALL_TIMEOUT_S, (
            "doubling the render timeout did not raise the derived budget -- "
            "_OVERALL_TIMEOUT_S has been hardcoded"
        )
    finally:
        kayak._RENDER_TIMEOUT_S = original


def _worker_wait_caps() -> list[str]:
    """Every bounded wait `kayak_render.render` performs, named by the constant
    that caps it, read out of the worker's own source.

    Read from source rather than listed by hand on purpose: a hand-written list
    is a second premise that can rot exactly the way the 2.5x factor did. A
    `page.goto(..., timeout=X * 1000)` and a `cap_seconds: float = X` default
    are the only two shapes the worker uses to bound a wait; the warmup dwell is
    an unbounded `asyncio.sleep` and is accounted for separately by
    `_MAX_WARMUP_DWELL_S`.
    """
    source = Path(kayak_render.__file__).read_text(encoding="utf-8")
    names = re.findall(r"timeout=([A-Za-z_][A-Za-z_0-9]*) \* 1000", source)
    names += re.findall(r"cap_seconds: float = ([A-Za-z_][A-Za-z_0-9]*)", source)
    return names


def test_the_worker_cap_covers_every_wait_the_child_performs():
    """The child runs the warmup goto, the warmup dwell, the main goto and
    _wait_for_results_stable in sequence, so its own budget must clear all four
    plus interpreter and browser startup.

    The 2.5x factor it replaced was written for two of those four and cleared
    112.5s against 140s of waits the code itself still permitted.
    """
    names = _worker_wait_caps()
    assert len(names) == 3, (
        f"the render worker performs {len(names)} capped waits {names}, not the "
        "3 this budget was sized for -- re-derive _WORKER_TIMEOUT_S before "
        "updating this count"
    )

    total = sum(getattr(kayak, name) for name in names) + kayak._MAX_WARMUP_DWELL_S
    assert kayak._WORKER_TIMEOUT_S >= total, (
        f"_WORKER_TIMEOUT_S ({kayak._WORKER_TIMEOUT_S}s) kills the worker while "
        f"it is still inside waits the worker's own code permits ({total}s from "
        f"{names} plus the {kayak._MAX_WARMUP_DWELL_S}s warmup dwell)"
    )


def test_the_warmup_dwell_bound_matches_the_config_it_claims_to_bound():
    """_MAX_WARMUP_DWELL_S is only an honest budget line while it really is the
    upper bound of the dwell _warmup_sequence draws."""
    assert kayak.KayakRenderConfig().warmup_dwell_s[1] == kayak._MAX_WARMUP_DWELL_S

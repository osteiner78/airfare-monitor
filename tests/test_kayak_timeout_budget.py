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
"""

from backend.sources import kayak


def _worst_case() -> float:
    """Everything `_search_inner` can spend before the overall cap fires:
    the worker's own cap, then the LLM call."""
    return kayak._WORKER_TIMEOUT_FACTOR * kayak._RENDER_TIMEOUT_S + kayak._LLM_TIMEOUT_S


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
            kayak._WORKER_TIMEOUT_FACTOR * kayak._RENDER_TIMEOUT_S
            + kayak._LLM_TIMEOUT_S
            + 30.0
        )
        assert recomputed > kayak._OVERALL_TIMEOUT_S, (
            "doubling the render timeout did not raise the derived budget -- "
            "_OVERALL_TIMEOUT_S has been hardcoded"
        )
    finally:
        kayak._RENDER_TIMEOUT_S = original


def test_the_worker_cap_covers_both_render_waits():
    """The child runs page.goto's cap and _wait_for_results_stable's cap in
    sequence, so its own budget must clear both plus browser startup."""
    worker_budget = kayak._WORKER_TIMEOUT_FACTOR * kayak._RENDER_TIMEOUT_S
    assert worker_budget > 2 * kayak._RENDER_TIMEOUT_S, (
        "the render worker can be killed while still inside its own two "
        "legitimate waits"
    )

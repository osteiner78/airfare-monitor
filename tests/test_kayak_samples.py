"""Tests for plan 018 Phase 2 — structural block signal + sample capture.

The capture harness exists because plan 017's Phase 6 could not re-classify
its own samples: the rendered page text was never persisted, so when
`_BLOCKED_MARKERS` was later corrected against the real interstitial, the
five collected attempts stayed permanently uninterpretable. Every attempt
must leave behind enough to re-judge it later.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.

Everything here is NEW-BEHAVIOR: before Phase 2 these fail with ImportError
(`_looks_blocked_structurally`, `backend.kayak_samples`).

API contract these tests pin:
  - `capture_sample(body_text, record, samples_dir) -> Path | None` writes
    `<iso>.txt` (the body) and `<iso>.json` (the record plus derived fields),
    returning the body path, or None if capture failed for any reason.
"""

import json
from pathlib import Path

import pytest

_INTERSTITIAL = (
    'If you are seeing this page, it means that KAYAK thinks you are a "bot," '
    "and the page you were trying to get to is only useful for humans.\n"
    "But I am not a bot! I'm human!\n"
)


def _results_page(marker: str = "Selecionar", rows: int = 12) -> str:
    """A page long enough, and with enough per-row action buttons, to be
    unambiguously a real results page."""
    row = (
        "TAP AIR PORTUGAL\nGRU-LIS\n10h 25m\n1 parada\nR$ 4.312\n"
        "Detalhes do voo e bagagem\n" + marker + "\n"
    )
    return "Voos de Sao Paulo para Lisboa\n" + row * rows


# --- structural block signal (task 2.5) ---

async def test_structural_signal_flags_short_page_with_no_select_occurrences():
    from backend.sources.kayak import KayakRenderConfig, _looks_blocked_structurally
    assert _looks_blocked_structurally(_INTERSTITIAL, KayakRenderConfig()) is True


async def test_structural_signal_does_not_flag_long_results_page():
    from backend.sources.kayak import KayakRenderConfig, _looks_blocked_structurally
    page = _results_page(marker="Selecionar")
    assert _looks_blocked_structurally(page, KayakRenderConfig(locale="pt-BR")) is False


async def test_structural_signal_does_not_flag_long_page_that_merely_lacks_markers():
    """The signal must key on 'short AND no action buttons', not on 'no known
    marker matched'. A long page with neither a bot marker nor a recognised
    button -- a Kayak redesign, an error page with content, an unexpected
    locale -- is not evidence of a block, and calling it one would silently
    discard real prices."""
    from backend.sources.kayak import KayakRenderConfig, _looks_blocked_structurally
    long_page = "Resultados\n" + ("conteudo da pagina sem botao reconhecido\n" * 200)
    assert len(long_page) > 2000
    assert _looks_blocked_structurally(long_page, KayakRenderConfig()) is False


async def test_structural_signal_follows_the_configured_locale_marker():
    """A pt-BR results page full of 'Selecionar' must not be judged against
    the English token, and vice versa -- otherwise switching the bundle to
    kayak.com.br makes every real page look blocked."""
    from backend.sources.kayak import KayakRenderConfig, _looks_blocked_structurally

    short_pt = "Selecionar\n"
    assert _looks_blocked_structurally(short_pt, KayakRenderConfig(locale="pt-BR")) is False
    assert _looks_blocked_structurally(short_pt, KayakRenderConfig(locale="en-US")) is True


# --- sample capture (task 2.4) ---

def _record(**over) -> dict:
    record = {
        "attempt_n": 3,
        "config_id": "c1-c4",
        "egress_ip": "177.145.72.252",
        "blocked_by_markers": True,
        "blocked_by_structure": True,
        "extracted_rows": 0,
        "validated_rows": 0,
        "outcome": "blocked",
        "elapsed_s": 12.4,
    }
    record.update(over)
    return record


async def test_sample_capture_writes_body_and_sidecar(tmp_path):
    from backend.kayak_samples import capture_sample

    body_path = capture_sample(_INTERSTITIAL, _record(), tmp_path)

    assert body_path is not None
    assert Path(body_path).read_text() == _INTERSTITIAL
    sidecar = Path(body_path).with_suffix(".json")
    assert sidecar.exists()
    assert json.loads(sidecar.read_text())["body_len"] == len(_INTERSTITIAL)


async def test_sample_sidecar_records_config_id_and_blocked_verdict(tmp_path):
    from backend.kayak_samples import capture_sample

    body_path = capture_sample(_results_page(), _record(config_id="c0-baseline",
                                                        blocked_by_markers=False,
                                                        blocked_by_structure=False,
                                                        outcome="extracted"), tmp_path)
    data = json.loads(Path(body_path).with_suffix(".json").read_text())

    assert data["config_id"] == "c0-baseline"
    assert data["blocked_by_markers"] is False
    assert data["blocked_by_structure"] is False
    assert data["outcome"] == "extracted"
    assert data["egress_ip"] == "177.145.72.252"


async def test_sample_capture_survives_unwritable_directory(tmp_path):
    """Capture is telemetry, not the job. A search must never fail because a
    sample could not be written."""
    from backend.kayak_samples import capture_sample

    blocker = tmp_path / "samples"
    blocker.write_text("not a directory")  # mkdir underneath this must fail

    assert capture_sample(_INTERSTITIAL, _record(), blocker) is None


async def test_two_samples_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    """Experiment attempts can land close together, and a lost sample is a lost
    data point that cost a real request."""
    from backend.kayak_samples import capture_sample

    first = capture_sample("first body", _record(attempt_n=1), tmp_path)
    second = capture_sample("second body", _record(attempt_n=2), tmp_path)

    assert first != second
    assert Path(first).read_text() == "first body"
    assert Path(second).read_text() == "second body"

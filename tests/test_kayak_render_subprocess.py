"""Tests for plan 021 Phase 2 — run the browser in its own process.

Every Kayak render this project has ever attempted, sorted by how it was
invoked: ~25 standalone (`docker exec`, `scripts/*` runners) all succeeded;
7 in-app (scheduler tick or `POST /trackers/{id}/search`) all failed with
`Connection closed while reading from the driver`. Seven for seven across
three days. Kayak has never once rendered in production — plan 018's
0-blocks-in-10 and plan 019's 5/5 extraction were all standalone.

The fix is to stop driving Chromium from inside the ASGI worker and hand it
to a freshly `exec`'d child instead, reproducing the environment that has a
~25/25 record.

All offline: the subprocess is mocked throughout, so nothing here launches a
browser.

Labels:
  NEW-BEHAVIOR / FAILURE-MODE  -> must FAIL before implementation, pass after.

Everything here is NEW-BEHAVIOR: before Phase 2 `_render` drives Playwright
in-process and never spawns anything, so these fail on the absent seam.
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BODY = "English\n€\nEuro\nFeedback\nBest\n€654 • 37h 30m\nIberia\n€654\nSelect\n"


@pytest.fixture(autouse=True)
def _no_in_process_browser():
    """Fail fast and offline if _render still drives Playwright in-process.

    Without this, the pre-implementation state does not fail -- it launches a
    real browser against a real Kayak URL and hangs for minutes. A fail-first
    test that reaches the network is worse than no test: it burns live
    requests against the residential IP the experiments depend on. This turns
    that into an immediate, obvious error, and doubles as the assertion that
    the render no longer runs in this process at all.
    """
    def _boom(*args, **kwargs):
        raise AssertionError(
            "in-process Playwright launch attempted -- plan 021 Phase 2 "
            "requires _render to hand the browser to a subprocess"
        )

    with patch("patchright.async_api.async_playwright", _boom):
        yield


class _FakeProc:
    """Stands in for asyncio.subprocess.Process."""

    def __init__(self, returncode=0, stderr=b"", writes=None, hangs=False):
        self.returncode = returncode
        self._stderr = stderr
        self._writes = writes or {}
        self._hangs = hangs
        self.killed = False
        self.waited = False
        self.pid = 4242

    async def communicate(self):
        if self._hangs:
            await asyncio.sleep(3600)
        for path, text in self._writes.items():
            Path(path).write_text(text, encoding="utf-8")
        return b"", self._stderr

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return self.returncode


def _spawn_returning(proc):
    """Patch the exec seam and expose the argv it was called with.

    The seam is `backend.sources.kayak._spawn_render_worker`, not
    `asyncio.create_subprocess_exec`. Under uvloop -- which is what the ASGI
    worker actually runs -- `create_subprocess_exec` is libuv's fork-based
    `uv_spawn`, and this process cannot survive a fork: the child segfaults
    finalising an inherited curl_cffi handle. That is the very bug plan 021
    exists to fix, so the production spawn goes through `os.posix_spawn`
    instead (plan 021 Decision 4, "exec, not fork" -- see
    `.agent/reports/021-phase-1-rootcause.md`). Only the patch target moved;
    every assertion below is unchanged.
    """
    calls = {}

    async def _fake_exec(*args, **kwargs):
        calls["argv"] = args
        calls["kwargs"] = kwargs
        # The worker contract: the parent passes an output path, and a real
        # worker writes the body there. Mirror that so the parent's read
        # succeeds without a browser.
        for arg in args:
            if isinstance(arg, str) and arg.endswith(".txt"):
                proc._writes.setdefault(arg, _BODY)
        return proc

    return patch("backend.sources.kayak._spawn_render_worker", _fake_exec), calls


# --- the happy path ---

async def test_render_returns_the_body_the_worker_wrote():
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(returncode=0)
    spawn, _ = _spawn_returning(proc)
    with spawn:
        body = await KayakSource()._render("https://www.kayak.com/flights/GRU-LIS/2026-10-04")

    assert body == _BODY


async def test_worker_is_exec_launched_not_forked():
    """The whole point of the change (plan 021 Decision 4). multiprocessing
    would inherit the very condition under suspicion -- a forked child of an
    event loop that has already started. exec replaces the process image."""
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(returncode=0)
    spawn, calls = _spawn_returning(proc)
    with spawn:
        await KayakSource()._render("https://www.kayak.com/flights/GRU-LIS/2026-10-04")

    assert calls, "no subprocess was spawned at all"
    argv = " ".join(str(a) for a in calls["argv"])
    assert "kayak_render" in argv
    assert "fork" not in argv


async def test_render_config_round_trips_through_the_worker_contract():
    """The child gets no Python objects, only argv -- so the config has to
    survive serialisation or the evasion bundle silently reverts to defaults
    in production while every unit test still passes."""
    from backend.sources.kayak import KayakRenderConfig, KayakSource

    config = KayakRenderConfig(locale="en-GB", timezone_id="Europe/Zurich")
    proc = _FakeProc(returncode=0)
    spawn, calls = _spawn_returning(proc)
    with spawn:
        await KayakSource(config=config)._render("https://www.kayak.com/x")

    argv = " ".join(str(a) for a in calls["argv"])
    assert "en-GB" in argv
    assert "Europe/Zurich" in argv


# --- failure modes ---

async def test_render_raises_when_the_worker_exits_non_zero():
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(returncode=1, stderr=b"boom")
    spawn, _ = _spawn_returning(proc)
    with spawn:
        with pytest.raises(Exception) as excinfo:
            await KayakSource()._render("https://www.kayak.com/x")

    # Guard against a vacuous pass: the autouse fixture also raises, and a
    # bare pytest.raises(Exception) would happily catch that instead and
    # report green while the subprocess seam does not exist at all.
    assert "in-process Playwright" not in str(excinfo.value)


async def test_render_error_includes_the_worker_stderr():
    """A child that dies silently is undiagnosable from the parent. This is
    the information that would have shortened plan 020 Phase 3 considerably."""
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(returncode=1, stderr=b"TargetClosedError: browser has been closed")
    spawn, _ = _spawn_returning(proc)
    with spawn:
        try:
            await KayakSource()._render("https://www.kayak.com/x")
        except Exception as e:
            assert "TargetClosedError" in str(e)
        else:
            pytest.fail("expected the non-zero exit to raise")


async def test_render_kills_the_worker_when_it_exceeds_the_timeout():
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(hangs=True)
    spawn, _ = _spawn_returning(proc)
    # Patch the cap _render actually reads. Plan 024 Phase 3 replaced the
    # runtime `_WORKER_TIMEOUT_FACTOR * _RENDER_TIMEOUT_S` product with a
    # constant summed at import, so patching _RENDER_TIMEOUT_S stopped
    # reaching it -- these two tests still passed, having waited the real
    # 130s each.
    started = time.monotonic()
    with patch("backend.sources.kayak._WORKER_TIMEOUT_S", 0.05), spawn:
        with pytest.raises(Exception):
            await KayakSource()._render("https://www.kayak.com/x")
    elapsed = time.monotonic() - started

    assert proc.killed, "a hung worker was left running"
    # The patch above must be the cap _render reads, not a constant it was
    # derived from. Without this the test still PASSES when the derivation
    # moves -- it just waits the real budget, which is how a 37s suite became
    # a 297s one unnoticed.
    assert elapsed < 5.0, (
        f"the patched timeout did not take effect ({elapsed:.1f}s elapsed); "
        "_render is reading a different cap than the one patched here"
    )


async def test_render_does_not_leave_the_worker_running_after_a_timeout():
    """Plan 020 Phase 3 found 171 zombie Chromium processes. Killing without
    reaping is how that number gets there."""
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(hangs=True)
    spawn, _ = _spawn_returning(proc)
    with patch("backend.sources.kayak._WORKER_TIMEOUT_S", 0.05), spawn:
        with pytest.raises(Exception):
            await KayakSource()._render("https://www.kayak.com/x")

    assert proc.killed and proc.waited, "worker killed but never reaped"


async def test_search_never_raises_when_the_worker_dies():
    """The contract every other source honours, unchanged by this refactor."""
    from backend.sources.kayak import KayakSource

    proc = _FakeProc(returncode=139, stderr=b"Segmentation fault")
    spawn, _ = _spawn_returning(proc)
    source = KayakSource()
    with spawn:
        results = await source.search("GRU", "LIS", "2026-10-04", None, "EUR", 5)

    assert results == []
    assert source.last_error is not None
    assert source.last_error_level == "ERROR"

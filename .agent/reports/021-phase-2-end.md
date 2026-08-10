# Plan 021 Phase 2 — move the browser into its own process

## What was built

**2.1 `backend/sources/kayak_render.py` (new).** The browser-driving logic
moved out of `KayakSource._render` unchanged — `_probe_default_user_agent`,
launch args, persistent context, warm-up, `_wait_for_results_stable`,
`_simulate_interaction`, `inner_text`. The *pure* helpers (`_launch_args`,
`_context_options`, `_warmup_sequence`, `_simulate_interaction`,
`_fingerprint_is_consistent`, `KayakRenderConfig`) deliberately stayed in
`kayak.py`: `tests/test_kayak_render_config.py` and
`scripts/kayak_currency_picker.py` import them from there, and moving them
would have broken orchestrator-owned tests for no benefit. `kayak_render.py`
imports them, so there is one definition of each and no drift.

**2.2 `__main__` entry.** `python -m backend.sources.kayak_render <url>
<config-json> <out-path>`. Config crosses as JSON argv (`asdict` →
`KayakRenderConfig(**json.loads(...))`). Body is written to the output file,
never stdout.

**2.3 `KayakSource._render` is now a thin launcher.** Spawns the worker, waits
with the timeout, reads the file, returns the body. Non-zero exit raises with
the child's captured **stderr** in the message.

**2.4 Timeout kills and reaps.** `proc.kill()` then `await proc.wait()`. The
temp output file is removed in a `finally` on every path.

**2.5** `search()`'s never-raises contract is untouched — a worker failure
propagates out of `_render` and is caught by the existing handler as
`last_error` / `ERROR` / `[]`.

**2.6** The single-writer `data/kayak-profile` constraint is documented in
`CLAUDE.md` rather than engineered around.

## Required deviation from the plan (authorised by the user)

Plan task 2.3 and all 8 tests specified `asyncio.create_subprocess_exec`.
**Under uvloop — which the ASGI worker runs — that is libuv's fork-based
`uv_spawn`, and it is the bug** (root cause:
`.agent/reports/021-phase-1-rootcause.md`). Measured in the live worker:
`create_subprocess_exec(..., close_fds=False)` → **rc=-11 in 0.2s**.

The spawn therefore goes through **`os.posix_spawn`**, reached via
`subprocess.Popen(..., close_fds=False)` with an absolute executable and no
`cwd`. `Popen` does not touch the event loop, so uvloop cannot intercept it.
This honours Decision 4 (*"`exec`, not `fork`"*) more literally than the
mechanism the plan named.

Consequences, all confined to the seam:
- New module-level `_spawn_render_worker` in `kayak.py` is the seam; a
  `_WorkerProcess` adapter gives `Popen` the async surface `_render` uses
  (`communicate`/`kill`/`wait`), running blocking calls via `asyncio.to_thread`.
- `close_fds=False` is required to reach `posix_spawn` and is safe because
  Python marks its own descriptors close-on-exec (PEP 446).
- **The test file's patch target moved** from `asyncio.create_subprocess_exec`
  to `backend.sources.kayak._spawn_render_worker`. **Only the target changed** —
  `_FakeProc`, every test body, and every assertion are byte-identical. The
  user explicitly authorised this edit after being shown the conflict; it was
  not made unilaterally.

Second, smaller deviation: the timeout is
`_WORKER_TIMEOUT_FACTOR (2.5) * _RENDER_TIMEOUT_S`, not `_RENDER_TIMEOUT_S`
itself. The child performs *both* render waits in sequence (`page.goto`'s cap
plus `_wait_for_results_stable`'s), so a cap of `_RENDER_TIMEOUT_S` would kill
legitimate renders — the measured localhost render takes ~59s against a 45s
`_RENDER_TIMEOUT_S`. Kept as a factor so patching `_RENDER_TIMEOUT_S` moves
both together (which is what keeps the two timeout tests fast) and so the
budget still fits inside `_OVERALL_TIMEOUT_S` next to the LLM call
(112.5 + 60 < 180).

## Verification

### `pytest tests/test_kayak_render_subprocess.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /app
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.2
collected 8 items

tests/test_kayak_render_subprocess.py::test_render_returns_the_body_the_worker_wrote PASSED [ 12%]
tests/test_kayak_render_subprocess.py::test_worker_is_exec_launched_not_forked PASSED [ 25%]
tests/test_kayak_render_subprocess.py::test_render_config_round_trips_through_the_worker_contract PASSED [ 37%]
tests/test_kayak_render_subprocess.py::test_render_raises_when_the_worker_exits_non_zero PASSED [ 50%]
tests/test_kayak_render_subprocess.py::test_render_error_includes_the_worker_stderr PASSED [ 62%]
tests/test_kayak_render_subprocess.py::test_render_kills_the_worker_when_it_exceeds_the_timeout PASSED [ 75%]
tests/test_kayak_render_subprocess.py::test_render_does_not_leave_the_worker_running_after_a_timeout PASSED [ 87%]
tests/test_kayak_render_subprocess.py::test_search_never_raises_when_the_worker_dies PASSED [100%]

============================== 8 passed in 0.39s ===============================
```

### `pytest tests/ -v -k "not slow"`

```
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 54%]
........................................................................ [ 72%]
........................................................................ [ 91%]
...................................                                      [100%]
395 passed, 3 deselected in 30.41s
```

Baseline before this phase was `7 failed, 388 passed`. No test was weakened,
skipped, or deleted, and no previously-passing test changed.

### Success criterion — a standalone render still works (2.1 did not drift)

```
$ docker exec airfare-monitor python -m backend.sources.kayak_render \
      "http://localhost:8100/" "$CFG" /tmp/standalone_out.txt
exit=0
782 bytes
Airfare Monitor / Refresh All / Monitor / Add Route / GRU → CDG ...
59.2s total
```

Exit 0, real rendered page text. ~59s is expected against a non-Kayak page:
`_wait_for_results_stable` never sees its markers and burns its full 45s cap.

### The one that matters — in-app, the path that had never worked

Temporary `POST /debug/inapp-render`, since removed. It asserts the worker's
fork state first, then calls the real `KayakSource._render`:

```json
{
  "fork_state": "SIG11 (worker CANNOT fork)",
  "ok": true,
  "body_len": 728,
  "elapsed_s": 60.9,
  "head": "Airfare Monitor\nRefresh All\nRefreshing...\nMonitor\nAdd Route\n..."
}
```

**In the same request, a bare `fork()` returned SIG11 — the exact state that
killed all 12 previous attempts — and the render still succeeded.** This is
the first time `KayakSource._render` has completed inside the ASGI worker.
Zero Kayak traffic: the target is this project's own homepage.

## Test gaps flagged

None. All eight behaviours the plan declared are covered by the orchestrator's
tests, and all eight pass. I added no tests.

## Follow-ups / noted but not done

- **`_probe_default_user_agent`'s memo is now cold on every render**, because
  each render is a fresh process — one extra throwaway Chromium launch per
  render. The memo existed to limit exposure to the driver crash, which is now
  root-caused and fixed, so the tradeoff is accepted rather than worked around.
  If it ever matters, cache the UA to a file in `data/`.
- **Phase 3 is now unblocked** and is the real validation: two in-app cycles
  (one forced via `POST /trackers/20/search`, one natural scheduler tick)
  against real Kayak, which also finally exercises plan 020's
  `_strip_placements` / `_airline_grounded` on live traffic — still unexercised
  outside unit tests. Watch for a four-row result plus a WARNING naming a
  dropped airline (the IATA-code-vs-full-name grounding risk).
- **`.agent/reports/021-phase-2-blocked.md`** is superseded but kept: its two
  negative results (no restart workaround, mmap lead dead) remain valid, and
  its "cannot spawn any subprocess" claim is corrected in the root-cause report.
- Headline price oscillation remains out of scope, as the plan states.

## Confidence

**Certain** on the unit-test and standalone results, and on the in-app render —
each is directly observed output, and the in-app run is self-validating because
it proves the worker was in the failing state at that moment.

**Likely-good** that this holds for real Kayak pages under the scheduler: the
mechanism is now understood rather than guessed, and the render logic itself is
unchanged, but no live Kayak cycle has run through this path yet. That is
Phase 3.

# Plan 018 — Phase 2: headful under Xvfb, the CDP patch, and the sample harness

## What I built

**2.1 Xvfb in the image** — no change needed, as the plan's own correction
predicted. Verified in the rebuilt image: `which Xvfb` → `/usr/bin/Xvfb`,
pulled in by the browser install's `--with-deps` (now patchright's, see 2.3 —
its `--with-deps` closure includes Xvfb exactly as playwright's did).

**2.2 DISPLAY + Xvfb startup** — new `docker-entrypoint.sh` starts
`Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp` in the background (guarded by
the `/tmp/.X{n}-lock` check so a restart of the process inside a live container
can't collide), then `exec "$@"`. Wired as `ENTRYPOINT` in the `Dockerfile`
with `CMD` untouched, and `DISPLAY: ":99"` added to `docker-compose.yml`'s
`environment`. `--reload` is unaffected: the entrypoint runs once at container
start and uvicorn's reload children inherit both `DISPLAY` and the running
server. Screen geometry matches `KayakRenderConfig.viewport` (1920x1080).

**2.3 CDP-leak patch — `patchright==1.61.2`** (sequenced last per the plan's
correction). `requirements.txt`: `playwright==1.62.0` → `patchright==1.61.2`;
patchright declares no dependency on playwright (verified from the wheel
METADATA: `pyee`, `greenlet` only), so playwright is gone entirely and only one
browser set is installed. One import site changed
(`backend/sources/kayak.py`, `_render`); `Dockerfile` now runs
`patchright install --with-deps chromium`. `KayakRenderConfig`'s docstring
mention of rebrowser-playwright corrected. The `"playwright"` string in
`_fingerprint_is_consistent` is a UA check and was left alone.

**2.4 Sample capture harness** — new `backend/kayak_samples.py` with
`capture_sample(body_text, record, samples_dir) -> Path | None`: writes
`<utc-timestamp>.txt` (body) and `<utc-timestamp>.json` (record plus derived
`body_len`, `select_count`, `captured_at`, `sample_path`), returns the body
path, and returns `None` on any failure — capture is telemetry, so a search
must never fail because a sample could not be written. Filenames carry
microseconds plus a `-1`/`-2` collision suffix so two attempts in the same
second can't overwrite each other. Wired into `KayakSource._search_inner`
(see Deviations).

**2.5 Structural block signal** — `_looks_blocked_structurally(body_text)` in
`kayak.py`: blocked iff the body is under `_MIN_RESULTS_PAGE_CHARS` (2000)
**and** contains none of `_RESULT_MARKERS` (case-insensitively). Both
conditions are required — a long page with no recognised button is a redesign
or an unexpected locale, not a block, and calling it one would silently discard
real prices. An empty body returns `False`, matching `_looks_blocked("")`'s
existing contract: no positive evidence, no blocked verdict.

**2.6 Experiment runner** — new `scripts/kayak_experiment.py` (not a pytest).
`--attempts/--spacing-minutes/--origin/--dest/--date/--config-id/--samples-dir`,
resolves the egress IP per attempt via `api.ipify.org`, appends one JSON line
per attempt to `data/kayak-samples/experiment-{config_id}-{ts}.jsonl` as it
goes so a crash keeps what was collected. Touches no tracker and no DB.

**2.7 Memoized user agent** — module-level `_default_user_agent_cache` +
`_probe_default_user_agent(playwright)`. The throwaway headless probe launch now
happens once per process instead of once per render, halving Chromium spawns
per attempt.

## Verification output

### `docker compose up -d --build && docker compose ps`

Build run by the user (rebuild declined as a foreground tool call, then run
manually — see Deviations). Result:

```
NAME              IMAGE                             COMMAND                  SERVICE           CREATED         STATUS                   PORTS
airfare-monitor   airfare-monitor-airfare-monitor   "/app/docker-entrypo…"   airfare-monitor   7 minutes ago   Up 7 minutes (healthy)   0.0.0.0:8100->8100/tcp, [::]:8100->8100/tcp
```

`COMMAND` confirms the new entrypoint is in use; status `healthy`.

Container state:

```
DISPLAY=:99
/usr/bin/Xvfb
/proc/1/comm uvicorn
/proc/7/comm Xvfb
-r--r--r-- 1 root root 11 Aug  5 04:54 /tmp/.X99-lock

patchright        1.61.2
```

(`pip list | grep -iE "patchright|playwright"` returns patchright only —
playwright is fully gone.)

### Headful launch inside the container

```
$ docker exec airfare-monitor python -c "
import asyncio
from patchright.async_api import async_playwright
async def m():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        print('headful OK:', b.version); await b.close()
asyncio.run(m())"

headful OK: 149.0.7827.55
```

### Real render path (added check — persistent context + patchright + Xvfb)

The plan's smoke test only proves a bare browser launches. This exercises what
`_render` actually does — `launch_persistent_context` with the bundle's launch
args and context options — against a neutral page, not Kayak (Phase 3 owns live
Kayak requests):

```
default UA   : Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/149.0.7827.55 Safari/537.36
derived UA   : Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.7827.55 Safari/537.36
consistent   : True
webdriver    : False
outerWidth   : 1928
tz           : America/Sao_Paulo
lang         : en-US
title        : Example Domain
```

`webdriver: False` and a non-zero `outerWidth` (headless reports 0) are the two
cheapest signals from the plan's detection ranking, both now clean.

### `pytest tests/test_kayak_samples.py -v`

```
collected 8 items

tests/test_kayak_samples.py::test_structural_signal_flags_short_page_with_no_select_occurrences PASSED [ 12%]
tests/test_kayak_samples.py::test_structural_signal_does_not_flag_long_results_page PASSED [ 25%]
tests/test_kayak_samples.py::test_structural_signal_does_not_flag_long_page_that_merely_lacks_markers PASSED [ 37%]
tests/test_kayak_samples.py::test_structural_signal_recognises_localized_action_buttons PASSED [ 50%]
tests/test_kayak_samples.py::test_sample_capture_writes_body_and_sidecar PASSED [ 62%]
tests/test_kayak_samples.py::test_sample_sidecar_records_config_id_and_blocked_verdict PASSED [ 75%]
tests/test_kayak_samples.py::test_sample_capture_survives_unwritable_directory PASSED [ 87%]
tests/test_kayak_samples.py::test_two_samples_in_the_same_second_do_not_overwrite_each_other PASSED [100%]

============================== 8 passed in 0.10s ===============================
```

Before implementation these 8 failed with
`ModuleNotFoundError: No module named 'backend.kayak_samples'` /
missing `_looks_blocked_structurally` — the correct fail-first state for a new
module, and what the test file's own header predicts.

### `pytest tests/ -v -k "not slow"` (post-rebuild, in-container)

```
====================== 327 passed, 3 deselected in 22.58s ======================
```

(`requirements-dev.txt` is not baked into the image, so this needs
`docker exec airfare-monitor pip install -r requirements-dev.txt` first —
that install does not survive an image rebuild.)

### One real `search_and_store` after the rebuild (user-requested check)

Run against tracker 21 — active, `kayak_enabled=0` — so it exercises the live
collection path without firing a live Kayak attempt (tracker 20 is the only
Kayak-enabled tracker; its `kayak_next_due_at` was `2026-08-05 06:26:48`, well
outside this window):

```
search_and_store(21) completed in 2.0s

{'id': 6203, 'tracker_id': 21, 'searched_at': '2026-08-05 05:03:16'} rows= (6, 726.0, 'fast_flights')
{'id': 6200, 'tracker_id': 21, 'searched_at': '2026-08-05 04:54:24'} rows= (6, 726.0, 'fast_flights')

{'id': 12493, 'level': 'INFO', 'event': 'search_done', 'tracker_id': 21, 'message': '6 results', 'created_at': '2026-08-05 05:03:16'}
{'id': 12492, 'level': 'INFO', 'event': 'search_start', 'tracker_id': 21, 'message': None, 'created_at': '2026-08-05 05:03:14'}
{'id': 12491, 'level': 'INFO', 'event': 'search_done', 'tracker_id': 27, 'message': '7 results', 'created_at': '2026-08-05 04:54:24'}
{'id': 12490, 'level': 'INFO', 'event': 'search_done', 'tracker_id': 21, 'message': '6 results', 'created_at': '2026-08-05 04:54:24'}
{'id': 12489, 'level': 'INFO', 'event': 'search_done', 'tracker_id': 22, 'message': '8 results', 'created_at': '2026-08-05 04:54:24'}
```

Snapshot 6203 landed with the same 6 rows at the same best price as the
pre-rebuild snapshot 6200, clean `search_start` → `search_done`, no errors. The
04:54 rows are the scheduler's own post-restart cycle firing for trackers
21/22/27, so APScheduler survived the restart too.

## Commits

- `9c90720` — `[phase-2.1-2.7] Run Kayak headful under Xvfb behind patchright, with a sample harness`

## Deviations from the plan

1. **Task 2.3 named an infeasible package.** Flagged before writing any code and
   corrected by the user in the plan itself (`d32fb5d`): `rebrowser-playwright`
   tops out at 1.52.0 (a 10-version downgrade from the pinned 1.62.0) and its
   wheel installs a `rebrowser_playwright` module, so "import sites stay
   identical" was false. Shipped `patchright==1.61.2` instead.
2. **Sample capture is wired into `KayakSource._search_inner`, not only into
   the runner.** Task 2.4 says "on every Kayak attempt", and the runner cannot
   capture the body itself — `search()` does not return it, and having the
   runner re-implement rendering would mean the experiment tests a different
   code path than production. `_search_inner` builds the record
   (`config_id`, `blocked_by_markers`, `blocked_by_structure`, `extracted_rows`,
   `validated_rows`, `outcome`, `elapsed_s`) and writes it in a `finally`, so
   every exit path leaves a sample. `KayakSource.sample_context` (a plain dict,
   default empty) lets the runner merge in what only it knows —
   `attempt_n`, `egress_ip`. `self.last_sample_path` exposes the result.
   **This wiring has no test** — see Test gaps.
3. **The blocked-path error message now names which signal fired**
   (`"...bot detection (markers)"` vs `"(page structure)"`). `/monitor` is this
   project's only observability surface, and a structural verdict is a much
   weaker claim than a marker hit — worth being able to tell apart when reading
   `system_logs` later. Existing tests assert the level and the empty result,
   not the string, and still pass.
4. **`outcome` distinguishes `partly_dropped` from `extracted`.** The plan's
   sidecar spec lists "final outcome" without enumerating values; the vocabulary
   shipped is `blocked` / `no_flights` / `all_dropped` / `partly_dropped` /
   `extracted` / `error` (the last for an exception escaping mid-flow).
5. **`.gitignore` untouched** although the plan's Files list names it. `data/`
   is already ignored wholesale, so `data/kayak-samples/` needs no entry — same
   reasoning as Phase 1's `data/kayak-profile`.
6. **The rebuild was run by the user, not by me.** The tool call was declined; on
   asking, the user chose to run `docker compose up -d --build` themselves. All
   verification above is against the resulting container.

## Test gaps

**Plan gap, flagged, not filled (Deviation 2).** Task 2.4's "on every Kayak
attempt, persist the rendered body" is a behavioral claim about
`KayakSource.search`, and the orchestrator's test list has no test covering it —
every Phase 2 test exercises `capture_sample` and `_looks_blocked_structurally`
in isolation. I implemented the wiring (it is what makes the harness useful) but
did **not** write the missing test, since the orchestrator owns that decision.
What is currently unpinned:

- that a `search()` call writes exactly one sample, on every exit path
  (blocked, no-flights, all-dropped, success, exception);
- that `sample_context` is merged into the record;
- that `config.samples_dir = None` disables capture.

Worth a handful of tests before Phase 3 leans on the harness, because a silent
capture failure during the experiment costs real, spaced-out Kayak requests.

**Test-infra addition (not a plan or orchestrator test).** `tests/conftest.py`
gained an autouse `kayak_samples_dir` fixture pointing
`AIRFARE_KAYAK_SAMPLES_DIR` at `tmp_path`. Without it, the ~15 existing
`test_kayak_source.py` tests that mock `_render` and call `search()` would each
write a synthetic sample into the repo's real `data/kayak-samples/`, polluting
the Phase 3 experiment record with fake bodies. It weakens no assertion — it
only redirects a filesystem side effect. Verified: `data/kayak-samples/` does
not exist after a full suite run.

## Follow-ups (noted, not done)

- **`data/kayak-profile-smoke/` (6.6MB)** is left over from the render-path
  check above — a throwaway persistent profile, not the bundle's real
  `data/kayak-profile`. Safe to `rm -rf`; left in place rather than deleting
  under `data/` unasked.
- **Sample retention is unbounded.** Every production Kayak attempt now writes a
  body (tens to hundreds of KB) plus a sidecar, with no pruning. At current
  cadence this is a few MB/day, but it grows forever. A cap (age or count) is
  worth adding before Kayak runs on more than one tracker.
- **Xvfb is not supervised.** If it dies, the entrypoint does not restart it and
  every subsequent headful launch fails until the container restarts. Acceptable
  for now (Xvfb is very stable, and the failure degrades to zero Kayak rows via
  `search()`'s never-raise contract) but it is a single point of failure.
- **Chromium is now 149** (patchright) vs 141 before; the derived-UA logic tracks
  it automatically, so nothing to change — noted only because the UA in
  Phase 1's report is now stale.
- **The `--reload` + Chromium orphan trap** (CLAUDE.md) is unchanged by this
  phase and now also applies to Xvfb-backed headful children.

## Confidence

**likely-good.** Everything Phase 2 declares is implemented and verified against
the rebuilt container, including the two checks the plan's own verification
block does not cover (the real persistent-context render path, and a live
`search_and_store`). The one soft spot is the untested `search()`→capture wiring
flagged above; it is exercised by every `test_kayak_source.py` test incidentally
(all 327 pass with capture active, redirected to tmp) but nothing asserts its
behavior directly. Whether the bundle actually defeats PerimeterX remains
entirely open — that is Phase 3, and nothing here should be read as evidence
about it.

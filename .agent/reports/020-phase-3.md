# Phase 3 report — Re-enable and watch one cycle

**Status: blocked / inconclusive.** Task 3.2 (one clean live cycle) could not be
confirmed. Every attempt tonight failed in the browser-render step, before the
extraction logic Phases 1-2 changed ever ran. This report hands the decision
on how to proceed back to the orchestrator, per explicit user instruction
during this session.

## Timeline of what happened, in order

1. **Confirmed Task 3.1 is a no-op.** `trackers.id=20` was already
   `kayak_enabled=1` the whole time (per the user's own note at task start) —
   never disabled during Phases 1-2. `kayak_next_due_at` was `04:10:00` at
   session start (~90 min out), consistent with the natural post-Phase-4
   schedule.

2. **Established the pre-fix baseline.** Checked `git log` for
   `backend/sources/kayak.py`: Phase 1 landed at `2026-08-06T02:14:43Z`
   (`2f2e59d`), Phase 2 at `2026-08-06T02:21:53Z` (`785d169`). The only
   successful Kayak snapshot in the DB, `id=6390` (`searched_at
   2026-08-06 01:29:40`), **predates both** — it is the exact defect run the
   plan's own Context section analyzes (`data/kayak-samples/20260806T012940.952907.txt`).
   **This means no successful Kayak render has happened yet with Phase 1+2
   code live.** Every attempt in this session is a first real attempt at
   validating the fix, not a confirmation of one that already ran clean.

3. **Backed up the DB** (`data/airfare.db.bak-020-phase3`, 183MB) before any
   write.

4. **Deleted the phantom €806 row** (user-approved, explicit go-ahead given
   mid-session): `DELETE FROM flight_prices WHERE id=251714` — the Arajet row
   from snapshot 6390 at the times/carrier of a real row but the price of the
   Expedia placement described in the plan's Context. Verified before/after:
   row gone, the four genuine Kayak rows in that snapshot (€654 "Multiple
   airlines", €732/€775 Iberia, €796 "Multiple airlines") untouched.

5. **Triggered five live cycles** via `POST /trackers/20/search` (same
   endpoint the "Search Now" button uses), forcing `kayak_next_due_at` to
   "now - 1 minute" before each so Kayak would actually run rather than wait
   out its normal 3h-jittered cadence:

   | # | search_start (UTC) | Outcome | Elapsed | Sample sidecar |
   |---|---|---|---|---|
   | 1 | 02:36:13 | `Connection closed while reading from the driver` | ~3m11s incl. random pre-delay | not captured (crash pre-dated this addition in some paths — see note below) |
   | 2 | 02:40:00 | same error | ~9m | — |
   | 3 | 02:51:32 | same error | ~5m | — |
   | 4 | 02:58:11 | same error | 0.34s (near-instant) | `body_len: 0`, `outcome: "error"` |
   | 5 (post-restart) | 05:43:13 | same error | ~11m | — |

   All five produced the identical exception. Attempt 4's sidecar shows the
   failure happens before any page content is read at all (`body_len: 0`),
   i.e. before the LLM extraction call — **the placement-stripping and
   airline-grounding code from Phases 1-2 never got exercised on live data
   tonight.**

6. **Diagnosed and ruled out, in order:**
   - **Zombie Chromium processes**: found 131 (later 171) processes with
     `comm` in `{chrome, chrome-headless-shell, chrome_crashpad}`, **all**
     with `PPid=1` and process state `Z` (zombie/defunct) — the `--reload`
     orphaning trap already documented in `/srv/airfare-monitor/CLAUDE.md`.
     `kill -9` on them was a no-op (already-dead processes can't be
     re-killed) — this ruled out my first instinct that they were holding
     real resources.
   - **Memory**: `cgroup` `memory.current` steady around 596-616MB against a
     1.5GB limit throughout a monitored 10-minute window spanning attempt 4;
     `memory.events` showed `oom 0`, `oom_kill 0` (only a non-zero cumulative
     `max` counter, no spike correlated with the crash). Not memory pressure.
   - **Disk**: 13GB free on the LXC host. Not exhausted.
   - **Isolated launch tests** (`docker exec airfare-monitor python3.12 -c
     ...`, both a plain `p.chromium.launch(headless=True)` and the actual
     `launch_persistent_context('data/kayak-profile', headless=False, ...)`
     matching `KayakRenderConfig`) **both succeeded immediately**, proving
     patchright/Chromium/Xvfb are fine in isolation.
   - **Full container restart** (user-approved): `docker compose restart
     airfare-monitor`, waited for `health: healthy`, confirmed zombies gone.
     **Attempt 5 after the restart failed identically.** This rules out
     "accumulated zombie state" as the actual cause — a restart gives a
     fully clean process table and the crash still reproduced.

7. **Working hypothesis (not proven):** `uvicorn --reload` runs the real ASGI
   worker as a **forked** child process — the same mechanism already named in
   this project's CLAUDE.md for the unrelated "orphaned `multiprocessing-fork`
   SQLite worker" gotcha. `fork()` combined with an already-initialized
   asyncio event loop is a known source of intermittent subprocess-pipe
   corruption, which is exactly the shape of the failure (`patchright`'s
   Node.js driver subprocess's pipe reads as closed immediately). This would
   explain both halves of the evidence: standalone scripts (fresh top-level
   process, never forked) succeed every time, while every attempt through the
   actual running app fails, and a full container restart doesn't help
   because the new worker is fork-spawned the exact same way. **This is a
   hypothesis, not a confirmed root cause** — I did not attempt a fix (e.g.
   trying a non-`--reload` run) since that changes this service's mandated
   Active-dev architecture and needs explicit sign-off, not a unilateral
   change mid-investigation.

8. **Ran the full test suite as a sanity check** after the DB delete and
   container restart (not a Phase 3 plan requirement, but reasonable given
   the destructive/operational actions taken):
   ```
   docker exec airfare-monitor python -m pytest tests/ -k "not slow" -q
   386 passed, 3 deselected in 28.48s
   ```
   No regressions from the DB edit or restart.

## Current live state, for whoever picks this up next

- `trackers.id=20`: `kayak_enabled=1`, `kayak_next_due_at = 2026-08-06
  08:50:53` (naturally rescheduled by attempt 5's failure — I did not force
  it again after the user chose "write a report" over "keep retrying").
- DB backup at `data/airfare.db.bak-020-phase3` (pre-deletion state, in case
  the €806 deletion needs to be reviewed/reverted).
- Phantom row `flight_prices.id=251714` is gone; snapshot 6390's four
  genuine Kayak rows are intact.
- No new Kayak sample body exists from a successful post-fix render — every
  sample captured tonight is from a failed attempt (`body_len: 0` or a page
  that never got read). **`_strip_placements` and `_airline_grounded` remain
  untested on live traffic**, though both have full unit-test coverage from
  Phases 1-2 (`tests/test_kayak_placements.py`, verified passing above).

## Tasks 3.3, 3.4, 3.5 — not attempted

All three depend on a successful render happening first:
- 3.3 (re-check all-time low against a hand render) — no fresh render to
  check against.
- 3.4 (spot-check the captured body for missed placement formats) — no new
  body was captured; every attempt died before or with an empty body.
- 3.5 (watch for airline-grounding dropping legitimate rows) — no extraction
  ran, so there is nothing to watch yet. This remains the single most
  important thing to check the next time Kayak completes a render, live or
  not.

## Decision needed from the orchestrator

Options as presented to the user (who deferred to this report instead of
picking one live):
1. Keep forcing retries now — fork-related asyncio bugs are sometimes
   intermittent and may still succeed on attempt N+1.
2. Leave `kayak_next_due_at` on its natural schedule (next due ~08:50 UTC)
   and treat Phase 3 as pending until a future cycle succeeds, forced or
   natural.
3. Investigate the fork hypothesis properly (e.g. compare uvicorn's actual
   reload/worker-spawn mechanism against the theory above) before deciding
   whether a workaround is worth proposing — this would be a change to how
   the Active-dev service runs and needs explicit buy-in per
   `/srv/CLAUDE.md`'s per-service mode conventions.

No code changes were made in this phase — everything above is
data/process/diagnostic actions (DB delete, container restart, log/process
inspection). `backend/sources/kayak.py` is unchanged from the Phase 2 commit.

## Confidence rating

**needs-review.** The diagnostic work (ruling out zombies/memory/disk,
isolating the failure to the in-app path specifically) is solid, but the root
cause is a hypothesis, not a confirmed fix, and the phase's actual goal — one
clean live cycle exercising the Phase 1-2 code — was not achieved.

# Plan 021 Phase 2 — not implemented: the fix's own mechanism is the broken thing

Phase 2 was **not built**. This report says why, and records two new negative
results that close open questions from
`.agent/reports/021-phase-1-followup-investigation.md` and
`.agent/context/021-driver-segfault-handoff.md`.

## Why Phase 2 was not implemented

Plan 021 Phase 2 says: move the render into `backend/sources/kayak_render.py`
and have `KayakSource._render` launch it with `asyncio.create_subprocess_exec`
(Decision 4, task 2.3).

The follow-up investigation had already established that the live ASGI worker
**cannot `asyncio.create_subprocess_exec` anything at all** — not Chromium,
not the Node driver, not `/bin/echo`. Phase 2's fix is therefore built on the
exact mechanism that is broken. The handoff document states this directly:

> Don't build that move (plan 021 Phase 2) until this bug is understood — a
> "fix" landed on top of an unexplained crash would be luck, not a fix, and
> the plan says so explicitly.

Building it anyway would have produced a **green unit suite and a still-100%-
broken production feature**, because `tests/test_kayak_render_subprocess.py`
mocks the subprocess throughout (by design — it must not launch a browser).
Every one of its 8 tests would pass against a `_render` that cannot spawn a
child in production. That is precisely the false-confidence failure mode plan
021 was written to avoid.

## Re-check: the blocker is still live (2026-08-10)

The findings above were a few days old, so I re-verified rather than trusting
them. Temporary `POST /debug/spawn-probe` route in `backend/main.py`, spawning
`/bin/echo hello` via `asyncio.create_subprocess_exec`. No Kayak traffic.

```
run 1: {"rc":-11,"out":"","err":""}
run 2: {"rc":-11,"out":"","err":""}
run 3: {"rc":-11,"out":"","err":""}
```

`rc=-11` is SIGSEGV, zero stdout, zero stderr. Still 3/3, unchanged.

## New result 1 — a container recreate does NOT clear it

This was the follow-up's **recommended next step #1**, explicitly never cleanly
isolated ("worth 30 seconds to confirm before deciding anything else").

`docker compose up -d --force-recreate`, health-check green (`/` → 200), then
probed immediately, before anything else touched the container:

```
run 1: {"rc":-11,"out":"","err":""}
run 2: {"rc":-11,"out":"","err":""}
run 3: {"rc":-11,"out":"","err":""}
```

**There is no restart workaround.** The bug is present from the first spawn
attempt on a freshly recreated container. Recorded so no future session spends
time on "have you tried restarting it".

## New result 2 — the mmap-count lead is dead

The handoff flagged 236 mapped regions in the live PID 1 versus 37 in a fresh
clone, and asked whether it grows per failed spawn attempt.

| Measurement | `wc -l /proc/1/maps` |
|---|---|
| Live container, 3 days uptime, pre-recreate | 236 |
| **Immediately after `--force-recreate`** | **235** |
| After 3 failed spawn attempts | 235 |

It does **not** accumulate — neither over three days of uptime (236 vs 235)
nor per failed spawn (235 → 235). A freshly recreated container already shows
the elevated count. So 236 was never leaked state; it is just this app's own
module graph (FastAPI, APScheduler, patchright, uvloop) mapped at import time.
The "37 in a fresh clone" comparison was apples-to-oranges — that clone had not
imported the app. **Not a leak, not a symptom. Close this lead.**

## Test state (unchanged, nothing weakened)

`tests/test_kayak_render_subprocess.py`, orchestrator-written, run in-container
(`docker exec airfare-monitor python -m pytest`, after
`pip install -r requirements-dev.txt`):

```
7 failed, 1 passed in 0.27s
```

They fail on real assertions against the absent subprocess seam — not import
or collection errors — so they are correctly fail-first. The one pass,
`test_search_never_raises_when_the_worker_dies`, passes vacuously: `search()`
already swallows every exception, so its contract holds before the refactor
too. No test was modified, weakened, or skipped.

## What is actually needed before Phase 2

The handoff's steps 1-4 (kernel `dmesg` from the Proxmox host, `strace`/`gdb`
on the segfaulting child, loosened `seccomp`/`--privileged` as an experiment).
Its steps 1 and 3 are now partly resolved: step 3 (mmap) is closed as a dead
end above, and the restart question is closed. Step 1 (real kernel segfault
line from the **Proxmox host**, not from inside the unprivileged LXC) remains
the single highest-value action and needs access this session does not have.

Phase 3 remains blocked behind Phase 2, as the plan already requires.

## Cleanup performed

- `backend/main.py` restored byte-for-byte from a pre-edit backup; probe route
  confirmed **404**; `/` confirmed **200**; `git status` shows no drift
  (only the pre-existing untracked `.agent/` files).
- One container recreate, announced and health-verified. No Kayak traffic, no
  DB rows, no tracker state, no `data/kayak-profile` access at any point.
- `requirements-dev.txt` was installed into the running container to run the
  suite (per `CLAUDE.md`; does not survive an image rebuild).

## Confidence

**Certain** that Phase 2 as specified cannot work in production today — it is
a direct, reproduced observation of the exact mechanism, not an inference.
**Certain** on both negative results; each is a direct measurement.
The root cause itself remains **unknown**.

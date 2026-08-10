# Plan 021 — follow-up investigation: what is actually breaking the driver connection

Phase 1 (`.agent/reports/021-phase-1.md`) disconfirmed the `--reload`/fork
hypothesis but left the real mechanism unknown, with an explicit "Phase 3
must wait" instruction. At the user's request, this is a deeper dig before
committing to Phase 2's fix.

## Headline finding

**It is not Chromium- or Node-specific, and Phase 2 as designed will not fix
it.** The live `airfare-monitor` service cannot spawn *any* subprocess via
`asyncio.create_subprocess_exec` — not the patchright driver, not `/bin/echo`,
not a bare `python3.12 -c "print(1)"`. Every one of them dies instantly
(sub-second) with `returncode == -11` (SIGSEGV), producing zero stdout and
zero stderr. Since Phase 2's fix is "spawn `kayak_render.py` via
`asyncio.create_subprocess_exec` from inside `KayakSource._render`, itself
still called from the live ASGI worker," it hits the exact mechanism just
proven broken, for any child process, not only Chromium's.

## What was tested, and ruled out

All of the below were tested by direct reproduction, not inference — either a
controlled variable was changed with the failure persisting, or a variable
was matched and the failure did not reproduce.

| Hypothesis | Test | Result |
|---|---|---|
| `--reload` / fork() of an already-running loop | Phase 1's 2x2 | **Ruled out** — reload OFF fails identically |
| uvloop's own subprocess transport | Standalone script with `uvloop.install()` | Succeeds |
| Many threads racing malloc at fork time | Standalone, 8 malloc-churning threads, with and without uvloop | Succeeds (10/10 each) |
| `uvicorn.Server`'s own setup (signal handlers, loop config) | Minimal `uvicorn.run()` + one route, standalone | Succeeds (4/4) |
| Importing `backend.main`'s full module graph | Same, `import backend.main` for side effects only, no lifespan run | Succeeds (4/4) |
| A running `AsyncIOScheduler` (empty) | Same + `scheduler.start()`, no jobs | Succeeds (4/4) |
| Real tracker jobs registered and firing | Same + real DB init + real per-tracker `add_job(...)` (no-op bodies, so no real network calls) | Succeeds (4/4) |
| `sys.stderr`'s file descriptor (patchright dup2's it into the child) | Compared `fileno()`/`fstat()` in-app vs standalone | Identical (fd 2, same fstat) |
| `SIGPIPE` disposition inheriting across fork+exec | Standalone with `signal.SIG_IGN` on SIGPIPE | Succeeds (5/5) |
| ulimits (open files, processes, stack, address space, locked memory) | `/proc/<pid>/limits`, PID 1 vs worker vs docker-exec shell | Identical across all three |
| Environment variables | `/proc/<pid>/environ` diff, PID 1 vs docker-exec shell | Identical |
| Memory headroom | `docker stats` at time of test | 226MB / 1.5GB (15%), nowhere near the limit |
| Being PID 1 of the container | Throwaway `docker run` with the real image, real entrypoint (Xvfb-then-exec), script as PID 1 | Succeeds (5/5) |
| cgroup limits (`--memory=1.5g --cpus=2.0 --shm-size=1g`, matched exactly) | Same throwaway container, limits matched to `docker-compose.yml` | Succeeds (5/5) |
| Network mode + bind mount (`airfare-monitor_default`, `/srv/airfare-monitor:/app`) | Same throwaway container, both matched | Succeeds (5/5) |
| The **exact** production CLI command (`uvicorn backend.main:app --reload --reload-dir backend`), real app, real entrypoint, real cgroups, real mounts | Throwaway container, zero-tracker DB (to avoid firing real searches) | Succeeds (5/5) |
| **`docker compose run`** — Compose's own byte-for-byte clone of the service definition | Full real app, `--reload` on, zero-tracker DB | Succeeds (3/3) |

That last row is the most important control: it is not a hand-assembled
approximation of the service, it *is* the service definition, run once as a
disposable container instead of the persistent named one. It still works.

## The asymmetry that remains unexplained

Every fresh instantiation of this exact configuration — however faithfully
reproduced, including via Compose's own `run` — works every time. Only the
specific, persistently-named `airfare-monitor` container fails, and it fails
from the very first subprocess-spawn attempt after every recreate tested
today (both cells in Phase 1's discriminator, and the fresh `--reload`-off
recreate). Both a `docker compose up -d --force-recreate` and my throwaway
clones start from what should be equivalently "fresh" processes; only the
named one is broken.

I could not go further with the tooling available in this environment:

- **No host kernel log access.** `/srv/CLAUDE.md` notes `minnie` itself is an
  **unprivileged Proxmox LXC** (`nesting=1 keyctl=1`) running Docker nested
  inside it. `whoami` inside `minnie` reports `root`, but `sysctl -w
  kernel.print-fatal-signals=1` returned "permission denied" and `dmesg`
  returned "Operation not permitted" — this root is LXC-unprivileged-mapped,
  not real host root, so the kernel's own segfault report (which usually
  names the faulting library and offset) is unreachable.
- **No `strace`/`gdb` in the container image** (`python:3.12-slim` base, no
  build tools), and installing them mid-investigation felt like the wrong
  tradeoff against the live service's operational risk versus what's likely
  a deep, narrow finding.
- I did not attempt to reproduce this by deliberately running the real app
  with real (not no-op) tracker jobs in a second instance, because doing so
  risks firing real, duplicate Kayak/Google Flights searches against the
  shared DB and, worse, a second process fighting the first for the
  single-writer `data/kayak-profile` Chromium lock.

## What this changes about the plan

- **Phase 2 as written will not fix the problem.** Its whole premise —
  "hand the browser to a freshly `exec`'d child, which sidesteps whatever the
  ASGI worker is doing" — assumes the worker *can* successfully exec a child
  at all. It cannot, for anything, right now. Moving the render into
  `kayak_render.py` and calling `asyncio.create_subprocess_exec` from
  `KayakSource._render` would die identically to how `/debug/driver-probe`
  died on `/bin/echo`.
- Plan 021's own Decision 5 ("Phase 2 is worth doing regardless of root
  cause") is now in question for a different reason than the plan
  anticipated: not "is process isolation architecturally sound" (yes), but
  "does the specific mechanism proposed (exec from inside this worker) even
  execute" (no, currently).
- The disconfirmed-but-still-true parts of Phase 1 stand: it is not
  `--reload`, not fork-vs-exec choice by itself (posix_spawn wasn't tested in
  isolation, but plain `/bin/echo` fails the same way Node does, so this
  isn't a Node/V8-specific startup quirk either).

## Recommended next steps (not yet acted on)

1. **Confirm whether a full container recreate is a reliable, if temporary,
   workaround** — this wasn't cleanly isolated today because every recreate
   tested was immediately followed by more testing, not a clean "recreate,
   wait, single trivial-probe" cycle. Worth 30 seconds to confirm before
   deciding anything else.
2. **If restarts don't reliably clear it**, the pragmatic path is probably to
   stop trying to spawn Kayak's browser from inside this ASGI worker
   entirely — not into a subprocess *launched on demand*, but into a
   **separate, always-running process/container** that the API talks to
   (e.g., over a local socket or a tiny HTTP endpoint), sidestepping whatever
   is broken about this specific worker's ability to fork+exec at all. That's
   a bigger change than Phase 2 currently scopes.
3. If the user wants the exact kernel-level mechanism (not required to move
   forward, but satisfying): would need `strace -f` on the segfaulting child
   from a build with `strace` installed, or host-level `dmesg`/core dump
   access that this nested-LXC environment doesn't expose from inside.

## Cleanup performed

- All four temporary debug routes (`/debug/stderr-probe`, `/debug/trivial-probe`,
  `/debug/driver-probe`, `/debug/render-probe`) removed from `backend/main.py`;
  confirmed 404 post-removal.
- All throwaway scripts (`_minimal_uvicorn_probe*.py`, `_driver_probe*.py`,
  `_render_probe_uvloop.py`, `_stderr_probe.py`) deleted from the project
  directory (they were bind-mounted, so they existed on the host at
  `/srv/airfare-monitor/`, not just inside the container).
- Two throwaway empty databases (`data/_probe_empty.db`,
  `data/_probe_empty2.db`), created by test containers that shared the real
  bind mount, deleted. Neither was ever referenced by `AIRFARE_DB_PATH` in
  the real service and both had zero tracker rows.
- Three throwaway Docker containers (`airfare-probe-test`,
  `airfare-probe-test2`, `airfare-compose-clone`) stopped and removed; `docker
  ps -a` confirms only `airfare-monitor` remains.
- `docker-compose.yml` was not modified in this follow-up (only during Phase
  1, already reverted and confirmed there).
- `git status` clean except this report file.

## One incidental exposure worth flagging

While diffing environment variables between processes (`docker exec
airfare-monitor env`), the real `DEEPSEEK_API_KEY` (opencode.ai key) value
was printed to this session's tool output in plaintext, for comparison
purposes. It was not written to any file, committed, or sent anywhere beyond
this session's own transcript, but the transcript itself now contains the
live key. Given the `.env` convention exists specifically to keep this out of
logs, **consider rotating that key** if this transcript will be retained or
shared.

# Handoff: "any subprocess spawn segfaults" bug in airfare-monitor's live container

You are being brought in to own root-cause troubleshooting on a bug that has
resisted two rounds of investigation. The user (Oliver) has explicitly
authorized you to request and use **privileged access** — real host root on
the Proxmox host, temporarily loosening container security settings,
installing debugging tools, converting the LXC to privileged mode, whatever
you need. Ask for it directly when you hit a wall that needs it; don't work
around the edges of a permission problem when the fix is "ask for the
permission."

Read `.agent/reports/021-phase-1.md` and
`.agent/reports/021-phase-1-followup-investigation.md` in full before doing
anything else — they contain the complete test matrix from the last two
sessions. This document summarizes and interprets them, but the reports have
the exact commands and raw output.

## What this project is, briefly

`airfare-monitor` is a personal flight-price tracker (FastAPI + SQLite,
running in Docker on a home server called `minnie`). It pulls prices from
Google Flights normally, and optionally from Kayak. Kayak has no API, so
getting its prices means literally rendering the Kayak results page with a
real (headless-ish) Chromium browser and reading the text off the page.
That's not the bug — that part has worked standalone dozens of times. The bug
is in *launching the browser at all* from inside the live, already-running
application process.

## The bug, precisely

The application, as it runs in production right now (container name
`airfare-monitor`, on host `minnie`), cannot successfully launch **any**
subprocess via `asyncio.create_subprocess_exec`. Not just Chromium, not just
the Node.js "driver" process that patchright (the Playwright fork this
project uses) depends on — literally anything. Confirmed with `/bin/echo
hello` and a bare `python3.12 -c "print(1)"`.

Every attempt:
- Dies in well under a second (typically 0-1s).
- Exit status is `-11`, i.e. the child was killed by `SIGSEGV` (segmentation
  fault) — a real, low-level memory-corruption-class crash, not an
  application-level exception.
- Produces **zero** stdout and **zero** stderr. The child appears to die
  before or immediately as it starts running, not partway through doing
  something.

This has been reproduced 12/12 times across two sessions (and matches an
independently-observed 7/7 historical failure rate noted in earlier plans
for this project, all showing the same downstream symptom: patchright's
Python client reporting `"Connection closed while reading from the driver"`,
which is just what it says when the child it spawned closes its output pipe
without ever sending a handshake).

**The single most important fact**: the exact same code, launched as a
one-off command (`docker exec airfare-monitor python somescript.py`) instead
of through a request to the running app, **works every time**. So this is not
a code bug, not a missing dependency, not a broken binary. Something about
*this specific running process* is broken for spawning children, and a
one-off sibling process in the same container is not.

## Why this is hard: the asymmetry

The natural instinct is "compare the working case to the failing case and
find the difference." That's exactly what the last two sessions did,
exhaustively — see the full table in
`021-phase-1-followup-investigation.md`. Every one of the following was
tested by direct reproduction (not guessed at) and **ruled out** as the
differentiator, because matching it in a fresh container still produces a
*working* subprocess spawn:

- `uvicorn --reload` / fork() of an already-running event loop
- `uvloop` (this project's event loop implementation) on its own
- Many concurrent threads racing for malloc locks at fork time
- `uvicorn.Server`'s own signal handlers / setup
- Importing this app's full module graph (FastAPI, APScheduler, etc.)
- A running `AsyncIOScheduler`, empty or with real per-tracker jobs registered
- `sys.stderr`'s file descriptor (patchright dup2's this into the child)
- `SIGPIPE` disposition inheritance across fork+exec
- ulimits (open files, processes, stack, address space, locked memory) — all
  identical between the live process and a fresh one
- Environment variables — identical
- Memory headroom — the container was at 15% of its 1.5GB limit when tested
- Being PID 1 of the container
- The exact cgroup limits (`--memory=1.5g --cpus=2.0 --shm-size=1g`)
- Network mode and the real bind-mounted volume
- The **exact** production launch command, run via `docker compose run`
  (Compose's own mechanism for a one-off container from the *same service
  definition* — this is about as close to "the same container" as you can
  get without it literally being the same container)

All of those, individually and combined, **work** in a freshly created
container. Only the one specific, already-running, persistently-named
`airfare-monitor` container fails — and it fails from the very first spawn
attempt after being freshly recreated too (tested via `docker compose up -d`
with a changed command, then immediately probing — still failed instantly).

**Read that last point twice.** It rules out the simplest remaining
explanation ("it just needs to warm up" / "it accumulates damage over
hours") in the form most people would reach for. Something is wrong *at or
near container start*, but only for the container that Compose creates and
manages under this name/config in this exact way — not for what looks like
an identical clone.

One data point gathered but not chased down: the live container's PID 1 has
**236 memory-mapped regions** (`wc -l /proc/1/maps`) versus **37** in a
freshly started clone doing nothing. `vm.max_map_count` on this host is
262144, so this isn't hitting a hard limit — but it's a real, measured
difference in accumulated process state that nothing above explains, and is
worth understanding rather than dismissing. Does it grow with every failed
spawn attempt? Does a *freshly recreated* production container (not a
same-command clone, the actual named service, recreated and immediately
probed before anything else touches it) already show an elevated count, or
does it only grow after the first request or two?

## What blocked further progress, and where your access should go

The investigation stalled specifically at the point of needing real kernel
forensics:

1. **No host kernel log access.** `minnie` (where Docker runs) is itself an
   **unprivileged Proxmox LXC container** (`nesting=1 keyctl=1` — see
   `/srv/CLAUDE.md`'s Topology section), with Docker running nested inside
   it. Even as `root` *inside* that LXC, `dmesg` returns "Operation not
   permitted" and `sysctl -w kernel.print-fatal-signals=1` returns
   "permission denied." A real SIGSEGV's kernel-level report (which names
   the exact faulting instruction pointer and often the library involved)
   is sitting in a log this session could not reach.
2. **No `strace`/`gdb` in the app's container image** (`python:3.12-slim`
   base — no debugging tools, and installing them mid-investigation felt
   like the wrong call to make unilaterally against a live service).
3. **Did not test loosening Docker's own security options** (`--privileged`,
   `--security-opt seccomp=unconfined`, `--cap-add=ALL`) on the real named
   service specifically, even though `SecurityOpt`/`CapAdd`/`CapDrop` were
   *observed* to be at Docker's defaults (null/empty) and identical between
   the working clones and the failing real container. Identical defaults
   were confirmed; loosening them was not tried as an experiment.

**Important caution before you reach for "it's the nested LXC, disable
nesting":** the LXC-nesting environment is *constant* across every test in
this investigation — the working clones ran inside the exact same LXC as the
failing real container. So nesting-as-a-blanket-restriction cannot by itself
explain why one specific container fails while an identically-configured
fresh one succeeds; at most it explains why *this session* couldn't get
kernel-level detail. Don't let that environmental fact become a premature
explanation for the actual bug — the real mystery is still "what is
different about this one persistent container/process," and that's still
open.

### Concrete next steps, roughly in order of expected value

1. **Get the real kernel segfault message.** This is the highest-value single
   thing you can do, and it needs privileged access:
   - Ask Oliver for genuine root on the Proxmox host itself (not just inside
     the `minnie` LXC), or ask him to run the check for you and paste the
     output. `dmesg -T | grep -i segfault` (or `journalctl -k`) on the
     **Proxmox host**, right after reproducing the crash inside `minnie`,
     should show something like `python3.12[PID]: segfault at ADDR ip IP sp
     SP error CODE in libname.so[range]`. That line alone likely tells you
     which library/offset is actually faulting.
   - Alternative: ask to (temporarily) convert `minnie`'s LXC config to
     privileged, or to raise its confinement (Proxmox LXC config lives at
     `/etc/pve/lxc/<ID>.conf` on the Proxmox host), specifically so `dmesg`
     works from inside it. Reversible, but changes the security posture of
     the whole LXC — flag that tradeoff to Oliver explicitly before doing it,
     don't just do it.
2. **Get a real crash trace from inside the failing process**, as a
   possibly-faster alternative to (1):
   - Install `strace` (and ideally `gdb`) into a debug variant of the image,
     or `docker exec` a statically-linked `strace` binary in if you can get
     one onto the host.
   - `strace -f -e trace=clone,fork,vfork,execve -o /tmp/trace.log <attach to
     the live worker PID or wrap the spawn>` to see exactly which syscall
     the child dies after (or before).
   - Enable core dumps for the crashing child (`ulimit -c unlimited` in the
     container, check `/proc/sys/kernel/core_pattern` — the default pattern
     might need adjusting, which itself may need host-level access if it's
     currently set to pipe into a host-level crash handler you can't reach)
     and inspect the resulting core with `gdb` — this shows you the actual
     crashing frame directly, no interpretation needed.
3. **Chase the mmap-count lead.** Compare `/proc/<pid>/maps` region count
   immediately after a fresh `docker compose up -d` recreate, before any
   request is made, versus after 1 failed spawn, versus after 10. If it
   climbs measurably per attempt, that's a real leak worth naming (even
   though 236 isn't near the hard limit, a leak that scales with request
   volume over days of real uptime could eventually matter, and might also
   be a symptom of whatever the actual corruption is rather than the cause).
4. **Try the loosened-security experiment** explicitly: recreate the *real*
   named service (or as close to it as `docker compose run --service-ports`
   allows) with `--privileged` or `--security-opt seccomp=unconfined` added,
   and see if the spawn succeeds. This wasn't tried. A change in outcome
   would be a strong, actionable clue about which subsystem (seccomp vs
   AppArmor vs something else) is involved — even though, per the caution
   above, it still wouldn't explain the asymmetry with working clones on its
   own (unless it turns out clones inherited more permissive defaults than
   Compose's `up` path does somehow — check for that specifically too, it
   was not directly compared).
5. **If none of the above resolves it in reasonable time**, the fallback
   architecture (already scoped as an option, not yet built) is to stop
   trying to launch Chromium *on demand* from inside this worker process at
   all, and instead run it in a separate, always-alive process or sidecar
   container that the main app talks to over a socket or tiny HTTP call.
   That sidesteps the bug entirely rather than explaining it. Only propose
   falling back to this after a genuine, documented attempt at the above —
   Oliver wants to understand and fix the real cause first, not just route
   around it.

## Relevant files

- `backend/sources/kayak.py` — `KayakSource._render` is where the real
  Chromium launch happens (patchright/`launch_persistent_context`); this is
  the code that plan 021 intends to move into a subprocess worker, which is
  exactly the mechanism now proven broken. Don't build that move (plan
  021 Phase 2) until this bug is understood — a "fix" landed on top of an
  unexplained crash would be luck, not a fix, and the plan says so
  explicitly.
- `.agent/plans/021-kayak-render-isolation.md` — the plan this bug was
  discovered while implementing. Phase 1 is done and its finding
  (`--reload` is not the cause) still stands. Phase 2 is blocked on you.
- `docker-compose.yml`, `docker-entrypoint.sh` — the real service's exact
  launch mechanics (Xvfb startup, `exec "$@"`, resource limits).
- `/srv/CLAUDE.md` — host topology, including the unprivileged-LXC-with-
  Docker-nested-inside-it detail that matters here.
- `/srv/airfare-monitor/CLAUDE.md` — full project conventions and a long
  running history of Kayak-related findings; read the "Kayak" bullets in
  "Future me notes" for context on how much work has already gone into
  making Kayak reliable *once it can actually render*.

## Ground rules

- This is a **live, 24/7 personal service** (`airfare-monitor` also serves
  `https://airfares.osteiner.xyz` through a reverse proxy). Prefer
  non-destructive diagnosis; when you do need to restart/recreate the
  container, that's fine (it's Active-dev, restarts are cheap and expected),
  but say so before doing it and confirm health afterward
  (`docker compose ps`, `curl localhost:8100/`).
- Don't touch `backend/sources/kayak.py`'s render logic, `_strip_placements`,
  `_validate`, or anything else plan 021 marks out of scope — this handoff
  is specifically about the subprocess-spawn bug, not about Kayak's
  extraction logic (which already works fine once a page actually renders).
- Follow this repo's existing conventions: no comments unless the *why* is
  non-obvious, ask before destructive git operations, only commit when
  asked, clean up any temporary debug routes/scripts/containers you create
  before finishing (the last two sessions each added and then removed
  `/debug/*` routes in `backend/main.py` — same pattern is fine, just close
  the loop).
- When you land on a real explanation, write it up as
  `.agent/reports/021-phase-1-rootcause.md` (or similar) with the same rigor
  as the existing reports: a claim plus the reproduction that proves it, not
  a plausible story.
- If you get well and truly stuck again, it's fine to say so plainly and
  suggest the sidecar-process fallback (see step 5 above) — just don't reach
  for it as step 1.

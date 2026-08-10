# Plan 021 — root cause: why the live worker cannot launch Chromium

**Status: SOLVED.** Claim, mechanism, and the reproduction that proves each.

## The claim

The ASGI worker runs **uvloop**. uvloop implements
`asyncio.create_subprocess_exec` in C via libuv's `uv_spawn`, which **`fork()`s**
— it never uses `posix_spawn`. The worker also holds live
**`curl_cffi.Curl`** objects, created by the `flights` (fli) Google Flights
source. After `fork()`, the child finalises an inherited `Curl` object —
`__del__` → `close()` → into libcurl on a handle whose backing state belongs to
the parent — and **segfaults** before it can `execve`.

Patchright launches its Node driver with `asyncio.create_subprocess_exec`. So
every in-app Kayak render dies at browser launch, and patchright reports the
downstream symptom `Connection closed while reading from the driver` — which is
just what it says when the child closes its pipe without handshaking.

Chain:

```
fli Google Flights search  ->  live curl_cffi.Curl objects in the worker
uvloop create_subprocess_exec -> libuv uv_spawn -> fork()
fork() -> child inherits Curl -> __del__ -> close() -> libcurl -> SIGSEGV
patchright sees the dead pipe -> "Connection closed while reading from the driver"
```

## Reproductions

### 1. The kernel names the faulting process, and it is not the browser

From the Proxmox host (`dmesg -T | grep -i segfault`):

```
python3.12[3850100]: segfault at 7aee2e7fc990 ip 00007aee62e0e637 sp 00007fff5f466ce0
    error 4 in libc.so.6[7aee62da2000+163000]
```

The dying process is **`python3.12`**, not `echo`/`node` — so the child dies
*between* `fork()` and `execve()`, while still running the parent's image.
`error 4` = user-mode **read** of a **non-present** page. `ip - libc_base =
0x6c637`, byte-identical across every occurrence.

### 2. `fork()` itself is broken; `posix_spawn` is not

One request, three spawn methods (`POST /debug/fork-matrix`, temporary):

| Method | Result |
|---|---|
| `os.fork()`, child only does `os._exit(7)` | **SIGSEGV** |
| `os.fork()` + `os.execv("/bin/echo")` | **SIGSEGV** |
| `os.posix_spawn("/bin/echo", ...)` | **exit 0** |

`posix_spawn` uses `clone(CLONE_VM|CLONE_VFORK)` — the address space is shared,
not duplicated, so no Python object is ever finalised in a child interpreter.
This is the whole difference.

Also ruled out here: `subprocess._USE_VFORK` and `_USE_POSIX_SPAWN`, toggled
through all four combinations — **all four SIGSEGV**. Not a vfork issue. Thread
count at failure: 5. Not a thread issue.

### 3. The child's own traceback names the culprit

`faulthandler.enable()` before `fork()` is inherited by the child, so the child
dumps its stack as it dies. Captured **4/4 times**, always identical:

```
Fatal Python error: Segmentation fault
Current thread ... (most recent call first):
  File ".../curl_cffi/curl.py", line 705 in close
  File ".../curl_cffi/curl.py", line 312 in __del__
  File "/app/backend/main.py", line 155 in <the os.fork() call>
```

`curl_cffi` is pulled in by `flights 0.9.0` (`curl-cffi>=0.7.4`) — the fli
Google Flights source. It reaches the worker through
`asyncio.to_thread(client.search, ...)` in
`backend/sources/google_flights.py:83`. Live count in the worker: **661**
`curl_cffi` objects, including `curl_cffi.curl.Curl` instances.

### 4. uvloop never reaches `posix_spawn`

Spying on `os.posix_spawn` while spawning `/bin/echo`:

```
asyncio   close_fds=True  rc=0 os.posix_spawn=0   (C fork_exec)
asyncio   close_fds=False rc=0 os.posix_spawn=1   <- safe path
uvloop    close_fds=True  rc=0 os.posix_spawn=0
uvloop    close_fds=False rc=0 os.posix_spawn=0   <- libuv's own C spawn, forks
```

Under plain asyncio, `close_fds=False` routes `subprocess.Popen` to
`os.posix_spawn`. **Under uvloop it does not** — libuv bypasses
`subprocess.Popen` entirely. Confirmed live: `create_subprocess_exec(...,
close_fds=False)` in the worker returned **rc=-11 in 0.2s**.

### 5. The fix works, proven against a genuinely broken worker

`POST /debug/posix-spawn-render` (temporary): assert the worker is broken, then
`os.posix_spawn` a child that runs the real `KayakSource._render`.

```
bare_fork_now: SIG11          <- worker is in the failing state right now
child:  exited=True, code=1, elapsed_s=58.3
```

**58.3 seconds, not 0.34.** Chromium launched, the Node driver connected, CDP
commands were issued — from the very worker where `fork()` was segfaulting in
the same request. The non-zero exit was `Page.goto` timing out against
`http://localhost:8100/`, because the probe's blocking `os.waitpid` froze the
server it was trying to render. A probe artefact, not a render failure.

## Why every earlier session was misled

Two prior investigations ruled out ~15 hypotheses by cloning the container and
failing to reproduce. The clones were innocent for one reason:

> the follow-up's own note — *"zero-tracker DB (to avoid firing real
> searches)"*

**No trackers meant no Google Flights search, which meant no `curl_cffi`
objects, which meant `fork()` was safe.** The precaution taken to keep the
experiment clean is precisely what removed the trigger. `docker compose run`
with the real service definition worked for exactly that reason.

It also explains the rest of the record:
- **Standalone `docker exec` scripts always worked** — they never ran an fli search.
- **A fresh container is broken within seconds** — the scheduler fires searches
  on startup, so contamination precedes the first probe. Hence "broken from the
  very first attempt after a recreate", and hence no restart workaround.
- **Not 100% deterministic across worker lifetimes** — it needs a `Curl` pending
  finalisation at spawn time. Observed both states this session; with 6 active
  trackers on a schedule, the broken state dominates.

## Corrections to earlier reports

- `.agent/reports/021-phase-2-blocked.md` states the worker "cannot spawn any
  subprocess". Precisely: it cannot spawn via any **`fork()`-based** mechanism.
  `os.posix_spawn` works, which is what makes the fix possible.
- The `MADV_DONTFORK` theory is dead — the only `dd` region is `[vvar]`.
- The mmap-count lead is dead (see `021-phase-2-blocked.md`).

## What this means for Phase 2

Phase 2's design — hand the browser to a freshly `exec`'d child — is **correct
and sufficient**, because the child is a new interpreter that never imports fli
or curl_cffi, so patchright's *own* internal fork inside that child is safe.

**One amendment is required.** Plan task 2.3 and every test in
`tests/test_kayak_render_subprocess.py` specify
`asyncio.create_subprocess_exec`. Under uvloop that is the broken path. The
parent's spawn must use **`os.posix_spawn`** (or `subprocess.Popen(...,
close_fds=False)` off the event loop, which routes to it).

This honours Decision 4 — *"`exec`, not `fork`"* — more literally than the
mechanism the plan names; `create_subprocess_exec` under uvloop is `fork`.

## Cleanup performed

- All temporary `/debug/*` routes removed from `backend/main.py`, restored
  byte-for-byte from a pre-edit backup; all confirmed **404**; `/` → **200**.
- `_render_child_probe.py` and all `/tmp` probe artefacts deleted.
- `git status` shows no tracked-file drift.
- One real Google Flights search was issued (114 rows, discarded, **no DB
  writes**). No Kayak traffic, no tracker or `kayak-profile` state touched.
- `requirements-dev.txt` installed into the running container to run the suite.

## Confidence

**Certain.** Every link is directly reproduced: the kernel names the process,
the child's own traceback names the function, the fork/posix_spawn split is a
controlled A/B in one request, the uvloop divergence is measured, and the fix
ran a real 58s browser render against a worker proven broken in that same
request.

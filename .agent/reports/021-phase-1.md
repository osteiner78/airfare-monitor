# Plan 021 — Phase 1: settle the mechanism

## What was done

Added a temporary `POST /debug/render-probe` route to `backend/main.py` that
calls `KayakSource()._render("http://localhost:8100/")` and returns
`{"ok": true, "body_len": N}` or `{"ok": false, "error": "..."}`. No Kayak
network traffic — it renders this project's own homepage, exercising the
identical in-process Playwright launch path at zero cost to the residential
IP.

Ran the full 2x2, 5 runs per cell, sequentially (the persistent Chromium
profile is single-writer, so no two renders ran concurrently). The `--reload`
flag was flipped by editing `docker-compose.yml`'s `command:` line and running
`docker compose up -d` to recreate the container; `/` returned 200 and the
Docker healthcheck reported `healthy` within ~10s in both directions.

## Result — filled 2x2

| | `--reload` ON (current) | `--reload` OFF |
|---|---|---|
| **in-app** (probe route) | 0/5 succeeded — `Connection closed while reading from the driver`, ~0-1s each | 0/5 succeeded — same error, same ~0-1s |
| **standalone** (`docker exec … python`) | 5/5 succeeded, `body_len=712`, 55-64s each | 5/5 succeeded, `body_len=711`, 61-62s each |

Raw output preserved below.

### standalone / reload ON
```
run 1: OK body_len=712  elapsed: 60s
run 2: OK body_len=712  elapsed: 64s
run 3: OK body_len=712  elapsed: 61s
run 4: OK body_len=712  elapsed: 55s
run 5: OK body_len=712  elapsed: 56s
```

### in-app / reload ON
```
run 1: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 2: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 3: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 1s
run 4: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 5: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
```

### in-app / reload OFF (the discriminator)
```
run 1: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 1s
run 2: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 3: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 4: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 0s
run 5: {"ok":false,"error":"Exception: Connection closed while reading from the driver"}  elapsed: 1s
```

### standalone / reload OFF
```
run 1: OK body_len=711  elapsed: 61s
run 2: OK body_len=711  elapsed: 62s
run 3: OK body_len=711  elapsed: 62s
run 4: OK body_len=711  elapsed: 62s
run 5: OK body_len=711  elapsed: 62s
```

(`body_len` differs by 1 byte between the two standalone cells — page content
is timestamp-bearing, not a discrepancy worth chasing.)

## Reading the result

Both "expect" cells reproduced exactly what was already known (in-app/ON:
5/5 fail, identical error text and sub-second timing to the historical
7-for-7; standalone: 5/5 succeed, ~60s each, consistent with the render doing
a real kayak.com warm-up navigation plus the full `_wait_for_results_stable`
cap against a page that never prints its result markers) — the probe is
faithful.

**in-app/OFF failed too, with the same error and the same sub-second timing
as in-app/ON.** Per the plan's own decision tree: **`--reload` is not the
variable.** The `fork()`-against-a-running-event-loop hypothesis is
disconfirmed as stated.

Per Decision 5: **Phase 2 (process isolation) still stands** — it fixes
"crashing Chromium can destabilize the API worker" regardless of root cause,
and it works in both Active-dev and Stable mode. **Phase 3 must wait.** Re-
running plan 020's live cycle now would validate nothing; a green result
would be luck, not evidence, exactly as the plan warns.

## Open question for Phase 3, unresolved by this phase

If not `--reload`/fork, what is different between a `docker exec` process and
the uvicorn ASGI worker that reliably breaks patchright's Node driver
connection in well under a second? Both run in the same container, same
image, same user, same `DISPLAY=:99`. Candidates not tested here: uvicorn's
own signal handling, some asyncio-loop-policy difference between a bare
`asyncio.run()` script and uvicorn's loop setup, or a resource (Xvfb
connection, some fd) held or shaped differently by the long-running ASGI
process by the time a request comes in versus a freshly started interpreter.
Phase 2's subprocess isolation sidesteps this without answering it — the
child is a freshly exec'd process either way, so this question does not block
Phase 2, only Phase 3.

## Cleanup performed

- `docker-compose.yml`'s `command:` reverted to the original `--reload
  --reload-dir backend` form; container recreated; healthcheck green;
  confirmed with `git status` / `git diff --stat` — clean, no drift from the
  committed version.
- `/debug/render-probe` route removed from `backend/main.py`; confirmed 404
  post-removal.
- Standalone probe script (`_render_probe_standalone.py`, never committed —
  copied into the container and job tmp dir only) deleted from both
  locations.
- No Kayak trackers, DB rows, or `kayak-profile` state were touched — the
  probe never navigates to a Kayak results page.

## Total downtime

Two container recreations (`docker compose up -d`), each health-check-green
within ~10s. No requests were in flight during either recreation (verified
manually, no automated cutover needed for a personal-scale service per
`/srv/CLAUDE.md`'s Active-dev model).

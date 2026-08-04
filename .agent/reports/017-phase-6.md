# Phase 6 — Live verification against a real opted-in tracker (interim)

**Status: in progress.** This is an interim report — tasks 6.1/6.2 are
confirmed, 6.5's sample collection is 5 of ~10 attempts in, and this file
will be updated as more natural-cadence attempts land. No code changes were
made as part of phase 6 itself (per plan scope); one code change was made as
an explicitly-authorized out-of-band follow-up (see "Follow-up applied"
below) because it was a hard blocker to any live verification at all.

## Setup

- Tracker: **id 20, GRU→ZRH, 2026-08-21** — the exact route that motivated
  this plan (real live data on 2026-08-04: GRU→ZRH TP88+TP934 €711 on
  Google Flights vs. Kayak's separate TP84+TP934 combination).
- Enabled via `PATCH /trackers/20/toggle-kayak` at 2026-08-04 17:46:59
  (task 6.1). Confirmed `kayak_enabled: 1`.

## Follow-up applied (out of phase-6 scope, explicit user authorization)

The first live attempt failed before ever reaching Kayak's page:

```
PermissionDeniedError: Error code: 403 - {'type': 'error', 'error':
{'type': 'RegionError', 'message': 'The latest version of this model is
only available hosted in China and requires explicit opt in:
https://opencode.ai/workspace/wrk_01KQP328TZAG7GSG1MPTHDH6TB/go'}}
```

Not a code bug — a regional access gate on the opencode.ai Go-subscription
workspace for `deepseek-v4-flash`. User opted in via that URL. Next attempt
then hit a second, different blocker on the same model:

```
RateLimitError: Error code: 429 - {'type': 'error', 'error': {'type':
'GoUsageLimitError', 'message': 'Monthly usage limit reached. Resets in 1
day. ...'}}
```

User pointed at opencode Zen's docs (`https://opencode.ai/docs/zen`), which
list a **free** `deepseek-v4-flash-free` model on a separate endpoint
(`https://opencode.ai/zen/v1`, not `.../zen/go/v1`). Tested directly with the
existing `DEEPSEEK_API_KEY` value:

```python
AsyncOpenAI(api_key=api_key, base_url="https://opencode.ai/zen/v1")
    .chat.completions.create(model="deepseek-v4-flash-free", ...)
→ SUCCESS: "ok"
```

Same key works, no separate signup, no usage cap hit since. With explicit
user sign-off, updated `backend/sources/kayak.py`:

```python
_LLM_BASE_URL = "https://opencode.ai/zen/v1"      # was ".../zen/go/v1"
_LLM_MODEL = "deepseek-v4-flash-free"              # was "deepseek-v4-flash"
```

Comment block above the constants updated to record why. Container hot-reloaded
cleanly (`WatchFiles detected changes... Reloading...` → clean startup).
This was necessary before *any* further verification could proceed — without
it, every Kayak attempt fails identically at the LLM layer regardless of
Kayak's own behavior, which would have made 6.5's sample meaningless (10
copies of the same access error, not real reliability data).

## Task 6.2 — manual trigger, pipeline confirmed end-to-end

Direct `KayakSource().search('GRU', 'ZRH', '2026-08-21', None, 'EUR', 5)`
call (bypassing the scheduler's due-check, to test the pipeline in
isolation) after the endpoint fix: full render → `_looks_blocked` →
`_extract` → `_validate` pipeline ran in ~68s with **no exception**, correct
`last_error` handling (`WARNING`, "Kayak extraction found no flights").
Confirms the auth/plumbing fix is real and the never-raises contract holds.

## A silently-missed bot block (real evidence for the reliability follow-up plan)

Inspected the raw rendered page text directly (`_render` + `_looks_blocked`
called standalone, not through `search()`) for the same route/date. The page
was Kayak's actual bot-detection interstitial:

```
If you are seeing this page, it means that KAYAK thinks you are a "bot,"
and the page you were trying to get to is only useful for humans.
...
But I am not a bot! I'm human!
```

`_looks_blocked()` returned **`False`** for this text. Current marker list
(`backend/sources/kayak.py`, `_BLOCKED_MARKERS`): `"verify you are human"`,
`"unusual traffic"`, `"are you a robot"`, `"captcha"`, `"access denied"`,
`"automated queries"` — none match Kayak's actual wording. This is exactly
the "silent variant" the Phase 2 plan anticipated (a block with no CAPTCHA
marker falls through to `_extract` returning `[]`, logged as `WARNING`
"no flights found", not as a block). **Not fixed here** — out of phase-6
scope by the plan's own design ("this plan ships defaults + the telemetry
needed to run that [reliability tuning] experiment," not the tuning itself).
Recommend adding a marker matching `"kayak thinks you are"` or similar as
part of the reliability follow-up plan, now backed by real page text instead
of a guess.

Given this, it's likely (though not provable after the fact — the raw text
wasn't captured) that the two earlier LLM-layer failures (RegionError,
RateLimitError) also happened on blocked renders, since both reached the
LLM call at all only because `_looks_blocked` had already returned `False`
for whatever text was rendered.

## An unexpected exception class: `Connection closed while reading from the driver`

A **fully natural, unforced attempt** (scheduler's own due-check, own
pre-render jitter delay, `delay=True` default — not one of my manual
`delay=False` calls) ran at 23:00:28–23:08:31 and failed with:

```
kayak_search_error: KayakSource: Exception: Connection closed while reading
from the driver
```

Container log shows the underlying cause was inside Playwright's own driver
connection setup, not the page render itself:

```
RuntimeError: Connection.init: unable to perform operation on
<WriteUnixTransport closed=True reading=False ...>; the handler is closed
```

No OOM: `docker stats` showed 150.8MiB / 1.5GiB (10%) at the time, and
`dmesg` has no OOM-killer entries. **Stronger evidence than a timeout theory:**
a 170MB Linux core dump (`core`, ELF, `from '/usr/local/bin/python3.12 -B -c
from multiprocessing.spawn import spawn_main...'`) landed at the project
root at 23:08:04 — seconds before the `kayak_search_error` at 23:08:31 —
meaning a Python multiprocessing worker actually **crashed** (signal-level),
not merely timed out. No `gdb` available in this environment to get a
backtrace; `strings` on the core turned up nothing more specific than stdlib
docstrings. This could still be timeout-adjacent (Plan Task 2.13's
already-flagged budget-doesn't-add-up concern might be what triggered
whatever tore the worker down), but it's now confirmed as a real crash, not
just a cancelled coroutine. Caught cleanly by `search()`'s generic exception
handler regardless (`last_error` set, `[]` returned, no crash reaching the
API) — the never-raises contract held even for an exception class the tests
don't explicitly cover. Core file was 170MB of debris with no actionable
backtrace extractable here; deleted after inspection. Not fixed here — same
phase-6 scope boundary, but flagged clearly below for the follow-up.

## Tasks 6.3 / 6.4 — confounded by an unrelated pre-existing bug

Both real production-path attempts today (17:47 and 23:00) coincided with
the *main* `FallbackSource` loop also failing in the same cycle:

```
search_error: FallbackSource: fli: fli returned no results (route may
genuinely have none, or Google's API may be rejecting the request
upstream); fast_flights: TypeError: unsupported format string passed to
NoneType.__format__
```

Confirmed **pre-existing and unrelated to this plan** — occurs 61 times
across the last 500 system_logs rows, earliest at 2026-08-03 20:14:55 (a day
before Kayak was touched), across multiple trackers. This means both
observed Kayak-due cycles produced a genuinely empty snapshot (0 rows from
any source), wiping tracker 20's dashboard price
(`best_price`/`best_source` → `null`) until the next successful cycle
self-healed it (confirmed once: null → €799/`fast_flights` ~14 min later).
This is the expected, documented degradation behavior working correctly
(Phase 1/3's design), just not the specific scenario 6.3/6.4 wanted to
observe (Kayak failing *while* fli/fast_flights succeeds, to confirm the
displayed price stays undisturbed). That clean scenario hasn't happened yet
in the samples collected so far. **Flagging the `fast_flights` TypeError as
a separate, real, frequent bug** worth its own small follow-up — not fixed
here, out of scope for this plan and this phase.

`kayak_next_due_at` advancing correctly on both success and failure is
confirmed either way (17:47→21:17:21, 23:08→2026-08-05 02:10:17) — no
hot-retry, per Decision 5/task 3.4.

## Task 6.5 — sample so far (5 of ~10 target attempts)

| # | Time | Path | Outcome | Notes |
|---|------|------|---------|-------|
| 1 | 17:47:59 | scheduler, manual `delay=False` | ERROR (LLM layer) | RegionError, pre-fix. Render/block status unknown (text not captured). |
| 2 | ~18:0x | direct `search()` | ERROR (LLM layer) | RateLimitError, pre-fix. Render/block status unknown. |
| 3 | ~18:1x (post-fix) | direct `search()` | WARNING, 0 flights | Pipeline ran clean; later shown (via #5) to likely have been a silent block. |
| 4 | ~18:2x | direct `_render`+`_looks_blocked` | **Confirmed blocked**, undetected by markers | Raw text captured — real bot-detection interstitial. |
| 5 | 23:00:28–23:08:31 | scheduler, natural cadence, `delay=True` | ERROR (exception) | `Connection closed while reading from the driver` — Playwright driver-init failure, likely timeout-budget related, not a Kayak-side block. |

Zero successful extractions yet. `_looks_blocked`'s marker gap means the
true block-rate among these 5 is probably higher than the raw counts show
(attempts 1–3 could plausibly all have been blocked and silently
misclassified, given #4 was confirmed blocked from the same burst).

**Note on cadence discipline:** attempts 1–4 happened within roughly a
30-minute window during active debugging (necessary to isolate and fix the
RegionError/RateLimitError blockers) — a burst pattern, not the plan's
intended one-request-per-~3h discipline (Decision 10). From here forward,
no further manual triggers — remaining samples should come from the
scheduler's own natural ~3h jittered cadence (`kayak_next_due_at` is
currently `2026-08-05 02:10:17`).

## Task 6.6 — spot-check against kayak.com by hand

**Not yet possible.** No successful extraction has landed yet to compare a
quoted price against kayak.com by hand. Deferred until a successful sample
appears.

## Verification

```
docker exec airfare-monitor python -m pytest tests/ -v -k "not slow"
290 passed, 3 deselected in 23.96s
```

No regressions from the endpoint/model constant change.

## Open items before this report can be finalized

1. Reach ~10 total Kayak attempts via natural cadence (5 more needed, at
   ~3h jittered spacing — roughly another 12-18h of real time).
2. Get at least one clean success/failure pair where Kayak's own outcome is
   decoupled from the `fast_flights` TypeError bug, to properly confirm
   6.3/6.4.
3. Get at least one successful extraction to hand-verify against kayak.com
   (6.6).

## Follow-ups noted, not fixed (out of phase-6 scope)

- `_BLOCKED_MARKERS` in `backend/sources/kayak.py` doesn't match Kayak's
  actual bot-detection page text (confirmed real wording above). Belongs to
  the reliability follow-up plan per Decision 9.
- Timeout budget mismatch flagged in plan Task 2.13 may be implicated in a
  real crash (`Connection closed while reading from the driver`, backed by a
  170MB core dump from a crashed multiprocessing worker) rather than staying
  theoretical. No backtrace was obtainable (`gdb` not installed in this
  environment) — if this recurs, installing `gdb` in the image and capturing
  the next core dump before deleting it would help root-cause it. Worth
  prioritizing in the reliability follow-up plan.
- `fast_flights: TypeError: unsupported format string passed to
  NoneType.__format__` — pre-existing, unrelated to Kayak, occurring
  frequently (61/500 recent log rows) since at least 2026-08-03. Separate
  small bug, not part of plan 017.

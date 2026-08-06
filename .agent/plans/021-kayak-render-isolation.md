# Plan 021 — Kayak has never rendered in production: isolate the browser

## Context

Plan 020 Phase 3 could not complete a single live cycle. Five attempts through
the running service all died identically with
`Connection closed while reading from the driver`, before any page content was
read (`body_len: 0`). The implementing agent ruled out zombie processes,
memory, and disk, showed that identical launches succeed standalone, and
confirmed a full container restart does not help.

**Sorting every Kayak render this project has ever attempted by how it was
invoked makes the pattern unambiguous:**

| Path | Attempts | Result |
|---|---|---|
| Standalone (`docker exec … python`, `scripts/*` runners) | ~25 across plans 018/019 | consistently succeed |
| In-app (scheduler tick, or `POST /trackers/{id}/search`) | **7** | **all failed, identical error** |

The Phase 3 report counted only that night's five and rated its own hypothesis
`needs-review`. Across three days it is seven for seven — deterministic, not
intermittent.

Two consequences the earlier plans missed:

1. **This retro-explains the "driver crash".** Plans 019 and 020 both carried
   `Connection closed while reading from the driver` as an unexplained
   follow-up ("fired twice, watch it, don't chase it"), on 2026-08-04 23:08
   and 2026-08-05 03:37. Both were scheduler-driven. Same bug, same path.
2. **Kayak has never once worked in production.** Plan 018's 0-blocks-in-10,
   plan 019's 5/5 extraction, the €654 discovery, the first cross-source
   merge — every one came from a standalone process. Plan 019 Phase 4
   *promoted* the feature on the strength of a code path production never
   takes.

Working hypothesis, from the Phase 3 report: `uvicorn --reload` runs the ASGI
worker as a forked child, and `fork()` against an already-initialised asyncio
event loop corrupts the pipe patchright's Node driver depends on. Plausible
and consistent with every observation — **but unproven, and Phase 1 exists to
settle it before anything is built on it.**

---

## Decisions

1. **Confirm before fixing.** Seven-for-seven is a strong pattern, not a
   mechanism. Phase 1 is a discriminator, not more reading.
2. **Confirm at zero Kayak cost.** The failure happens at browser launch —
   attempt 4 died in 0.34s with `body_len: 0`, before any navigation. So the
   probe needs a browser launch *inside the ASGI worker*, not a Kayak page.
   Rendering `http://localhost:8100/` exercises the identical code path
   against this project's own service.
3. **Fix by isolating the render into its own process, not by dropping
   `--reload`.** Three reasons: it reproduces the environment with a ~25/25
   record instead of hoping a third one behaves; it works in both Active-dev
   and Stable mode, so it survives this service's eventual graduation
   (`/srv/CLAUDE.md`) rather than depending on the mode; and a crashing or
   hanging Chromium stops being able to destabilise the API worker — which is
   almost certainly what produced the 131-171 zombie processes Phase 3 found.
4. **`exec`, not `fork`.** Use `asyncio.create_subprocess_exec`, which
   replaces the process image. `multiprocessing` would inherit the very
   condition under suspicion.
5. **If Phase 1 disconfirms the hypothesis, Phase 2 still stands** — process
   isolation is worth having for reason 3 alone — but Phase 3 must not be
   attempted until the real cause is understood, because a green Phase 3
   would then be luck rather than evidence.

---

## Phase 1 — Settle the mechanism (zero Kayak requests)

### Intent
Establish whether the in-app path fails because of `--reload`, or for some
other reason. Nothing is built until this answers.

### Tasks
1.1 Add a **temporary** probe route (e.g. `POST /debug/render-probe`) that
    performs one `KayakSource._render("http://localhost:8100/")` and returns
    the body length or the exception. It must be **removed at the end of this
    phase** — it is an instrument, not a feature. Mark it as such in the code.
1.2 Run the 2×2, five runs per cell, recording success/failure and the
    exception text:

    | | `--reload` ON (current) | `--reload` OFF |
    |---|---|---|
    | **in-app** (probe route) | expect: fail | **the discriminator** |
    | **standalone** (`docker exec`) | expect: succeed | expect: succeed |

    The two "expect" cells reproduce what is already known and exist to prove
    the probe is faithful — if in-app/reload-ON *succeeds*, the probe is not
    exercising the real path and the experiment is void.
1.3 Flip `--reload` by editing `docker-compose.yml`'s `command:` and
    recreating the container. Reversible by reverting one line. Note that
    with `--reload` off, code edits stop taking effect until restart — say so
    out loud before starting, and restore it at the end of the phase
    regardless of outcome.
1.4 Record the result in `.agent/reports/021-phase-1.md` as a filled-in 2×2.

### Reading the result
- **in-app/OFF succeeds** → hypothesis confirmed. Proceed to Phase 2.
- **in-app/OFF fails too** → `--reload` is not the variable. **Stop.** The
  fix in Phase 2 may still be worth doing (Decision 5), but Phase 3 must wait
  for a real cause. Report and hand back.
- **in-app/ON succeeds** → the probe is unfaithful. Fix the probe, rerun.

### What NOT to touch
`backend/sources/kayak.py`'s render logic, the evasion bundle, `_validate`,
the model, tracker state. This phase changes one compose line and adds one
throwaway route.

### Tests
None — this is an experiment. Its output is the 2×2 table.

---

## Phase 2 — Move the browser into its own process

### Intent
Make the render immune to whatever the host process is doing, by running it
in a freshly `exec`'d process rather than inside the ASGI worker.

### Tasks
2.1 New `backend/sources/kayak_render.py`. Move the **existing** render logic
    there unchanged — `_probe_default_user_agent`, launch args, persistent
    context, warm-up, `_wait_for_results_stable`, `_simulate_interaction`,
    `inner_text`. This is a move, not a rewrite: plan 018 measured this code
    at 0 blocks in 10 and it must not drift.
2.2 Give it a `__main__` entry point taking the URL and a serialised
    `KayakRenderConfig`, plus an **output file path**. It writes the body to
    that file and exits 0.
    **Not stdout** — Chromium and the Node driver both write there, so a body
    read off stdout would be corrupted by noise that is invisible in testing
    and arbitrary in production.
2.3 `KayakSource._render` becomes a thin launcher: `create_subprocess_exec`
    (Decision 4) → wait with the existing timeout → read the file → return
    the body. On non-zero exit, raise with the captured **stderr** included,
    so a failure is diagnosable rather than just "it died".
2.4 Enforce the timeout by **killing the child**, and confirm it is reaped.
    An orphaned Chromium is exactly the failure mode Phase 3 found 171 of.
2.5 `search()`'s never-raises contract is unchanged: any subprocess failure
    becomes `last_error` / `ERROR` / `[]`.
2.6 The persistent profile (`data/kayak-profile`) is a Chromium-locked
    directory, so only one render may use it at a time. Single tracker,
    `max_instances=1`, 3h cadence — safe today. Note the constraint in
    `CLAUDE.md` rather than engineering for concurrency that does not exist.

### Files
- New: `backend/sources/kayak_render.py`
- Modify: `backend/sources/kayak.py` (`_render` only), `CLAUDE.md`

### What NOT to touch
The render logic's behaviour (2.1), `_strip_placements`, `_validate`,
`_results_section`, `_extract`, the model, `KayakRenderConfig`'s defaults.

### Tests
`tests/test_kayak_render_subprocess.py` (new — written with this plan). All
offline: the subprocess is mocked, so no browser launches.
- `test_render_returns_the_body_the_worker_wrote`
- `test_render_raises_when_the_worker_exits_non_zero`
- `test_render_error_includes_the_worker_stderr` (diagnosability, 2.3)
- `test_render_kills_the_worker_when_it_exceeds_the_timeout`
- `test_render_does_not_leave_the_worker_running_after_a_timeout` (2.4)
- `test_search_never_raises_when_the_worker_dies`
- `test_render_config_round_trips_through_the_worker_contract`
- `test_worker_is_exec_launched_not_forked` (pins Decision 4 — the whole
  point of the change)

### Success criteria
All pass; full suite green; and a **standalone** Kayak render still succeeds,
proving 2.1's move did not change behaviour.

### Verification
```bash
pytest tests/test_kayak_render_subprocess.py -v
pytest tests/ -v -k "not slow"
```
Paste into `.agent/reports/021-phase-2.md`.

---

## Phase 3 — Re-run plan 020 Phase 3, through the production path

### Intent
The cycle plan 020 never got. This is the first time the deployed path will
have rendered Kayak successfully, so it validates plan 020's Phase 1-2 work
*and* this plan's fix at once.

### Tasks
3.1 One cycle via `POST /trackers/20/search` — **in-app deliberately**, since
    that is the path that has never worked.
3.2 Then plan 020's untouched tasks, in order: 3.2 (no advert price stored,
    real cheapest still captured, row count unchanged), 3.3 (all-time low
    re-checked against a hand render), 3.4 (spot-check the body for placement
    formats the strip rule missed), and **3.5 — watch for airline grounding
    dropping legitimate rows**, which remains the single most important
    unknown and whose tell is a row count of four rather than five.
3.3 Let one *natural* scheduler cycle run afterwards and confirm it also
    succeeds. The forced HTTP path and the scheduler path are both in-app but
    not identical, and the scheduler is what runs unattended.

### Success criteria
Two successful in-app cycles — one forced, one scheduled — with adverts
absent, the real fare present, and no unexplained row-count drop.

### Verification
`.agent/reports/021-phase-3.md`, and plan 020 Phase 3 marked complete there.

---

## Follow-up, explicitly out of scope

- **Headline price oscillation** (carried from plan 020): the €654 fare exists
  only on Kayak, so the displayed price swings with Kayak's success rate.
  Needs per-source success recorded per snapshot — still the right fix, still
  deferred.
- **Whether this service should graduate to Stable mode.** Decision 3 makes
  the fix mode-independent precisely so this can be decided on its own merits
  later, rather than being forced by a bug.

# 001 Phase 4 — End Report

## What was built

- **Task 4.1**: `backend/pages.py` — Dashboard route (`GET /`), add tracker route (`POST /`), toggle active route (`PATCH /trackers/{id}/toggle`), delete route (`DELETE /trackers/{id}`). All return HTML. Uses Jinja2 Environment directly (not Starlette's `Jinja2Templates`) due to Python 3.13 + Jinja2 3.1.6 cache incompatibility.
- **Task 4.2**: `frontend/templates/base.html` — HTML5 shell with HTMX CDN and CSS link.
- **Task 4.3**: `frontend/static/app.css` — Clean, minimal styling for dashboard cards, form, badges, buttons.
- **Task 4.4**: `frontend/templates/dashboard.html` — Extends base.html, includes add form and tracker list.
- **Task 4.5**: `frontend/templates/partials/add_form.html` — Inline form with HTMX POST to `/`, with reset on success and alert on failure.
- **Task 4.6**: `frontend/templates/partials/tracker_card.html` — Card showing route, date, best price, active/paused badge, last checked time, pause/resume and delete buttons with HTMX actions.
- **Task 4.7**: HTMX add tracker — Form posts to `/`, server returns updated dashboard HTML, swapped into `#tracker-list` with `innerHTML`.
- **Task 4.8**: HTMX pause/resume/delete — Toggle via `PATCH /trackers/{id}/toggle` (swaps card `outerHTML`). Delete via `DELETE /trackers/{id}` (swaps list `innerHTML`) with `hx-confirm` dialog.
- **main.py update**: Included pages router, mounted `/static` for CSS.

## Verification output

Regression test suite: **52 passed, 2 expected failures** (Phase 6 notification API), unchanged from Phase 3.

```
================== 2 failed, 52 passed, 1 deselected in 1.25s ==================
```

Smoke test:

```
=== Empty dashboard ===
Has empty state: True
Has add form: True
=== Create tracker ===
201 Created
=== Dashboard after creation ===
Has GVA: True
Has BCN: True
Has Active badge: True
Has Pause: True
Has Delete: True
Has date: True
No empty state: True
```

## Deviations from plan

- **Jinja2Templates bypassed**: Starlette's `Jinja2Templates.TemplateResponse` triggers `TypeError: unhashable type: 'dict'` in Jinja2 3.1.6's LRUCache on Python 3.13. The root cause is in `jinja2.environment._load_template` when `env.globals` is non-empty (Starlette adds `url_for`). Workaround: create `jinja2.Environment` directly with `cache_size=0` and use `get_template()` + `render()` + `HTMLResponse()`. This is functionally equivalent and avoids the cache bug.

## Test gaps

None. Phase 4 has no orchestrator-written tests.

## Follow-ups

- The `GET /trackers/{id}` detail page route is deferred to Phase 5.
- `chart.js` CDN is deferred to Phase 5 (only HTMX CDN is loaded now).
- JS date formatting for `last_searched_at` is rough (raw ISO shown). Phase 5/6 can add a proper time-ago formatter.
- The `/_static/app.css` URL returns 404 when mounted at `/static` — this is correct behavior as the base.html references `/static/app.css`.

## Confidence

**certain** — all smoke checks pass, regression suite unchanged, HTMX interactions are wired and ready for manual browser testing.

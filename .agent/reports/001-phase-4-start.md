# 001 Phase 4 — Start Report

## Scope

Phase 4 builds the frontend dashboard: `GET /` returns an HTML page with tracker cards, an inline add form powered by HTMX, and pause/resume/delete controls that operate without page reload.

## Tasks

| # | Task | Files |
|---|------|-------|
| 4.1 | Implement `pages.py` — dashboard route + HTMX handlers | `backend/pages.py` |
| 4.2 | Create `base.html` shell with HTMX CDN + CSS link | `frontend/templates/base.html` |
| 4.3 | Create `app.css` | `frontend/static/app.css` |
| 4.4 | Create `dashboard.html` | `frontend/templates/dashboard.html` |
| 4.5 | Create `add_form.html` partial | `frontend/templates/partials/add_form.html` |
| 4.6 | Create `tracker_card.html` partial | `frontend/templates/partials/tracker_card.html` |
| 4.7 | Wire HTMX: add tracker (form POST -> list swap) | included in templates |
| 4.8 | Wire HTMX: pause/resume/delete | included in templates |

## Tests

Phase 4 has no orchestrator-written tests. Verification is via the plan's HTTP smoke tests.

## Pre-work observations

- `get_tracker_summaries()` returns `best_price` and `last_searched_at` fields not present in `TrackerResponse` — these are exactly what the dashboard cards need.
- Pages router routes (`/`, `/trackers/{id}/toggle`, `/trackers/{id}`) are separate from the API router's `/api/*` routes — no conflicts.
- The `/trackers/{id}` detail route is deferred to Phase 5 (Task 5.1).
- `update_tracker()` in `db.py` works with Python bools directly since SQLite treats `True`/`False` as `1`/`0`.
- `main.py` needs two additions: include the pages router and mount static files at `/static`.

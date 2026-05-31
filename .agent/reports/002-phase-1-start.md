# 002 Phase 1 — Start Report

## Scope

Phase 1 refactors the HTMX response architecture for the detail page. Currently `POST /trackers/{id}/search` and `PATCH /trackers/{id}/toggle-detail` return full `tracker.html` (with `<html>`, `<head>`, `<body>`, headers, error banner). These HTMX responses embed a full HTML page inside a div, causing the pause duplication bug. The fix: extract the variable detail content into a standalone partial `detail_content.html` and have those routes return it instead.

## Tests expected to turn green

- `test_detail_page_does_not_embed_full_html_in_detail_content` (currently fails — search-now returns full HTML with `<html>` tags)

## Pre-work observations

- 13 of 17 `test_pages.py` tests pass out of the box — the pages routes from plan 001 already implement the basic behavior.
- The plan lists 8 Phase-1 tests but the actual test file has 17 (orchestrator added extra ones). 15 pass already; only the partial-architecture test and the booking-URL-column test (Phase 2) fail.
- `_build_detail_context` remains unchanged — only the route response template changes.
- HTMX executes `<script>` tags inside swapped content by default, so the chart scripts in the partial will work.

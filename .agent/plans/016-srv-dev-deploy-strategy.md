# Plan 016 — /srv Multi-Service Dev/Deploy Strategy (minnie)

**Date:** 2026-06-03
**Host:** minnie (`192.168.1.230`), Debian 13 LXC
**Status:** CLAUDE.md updated; airfare-monitor compose flip pending.

## Context

minnie will host several personal APIs (4–6), each its own Docker container under
`/srv/<service>/`. We need a development workflow that keeps the notebook-style
"edit and see it immediately" loop for the service being built, while keeping the
other services rock-stable — without confusing mode-toggling.

**Decision:** a per-service **hybrid**, where the mode is *fixed in each service's
own `docker-compose.yml`* (not toggled per command):

- **Active dev (#1)** — the service under active development. Compose bind-mounts
  the source (`.:/app`) and runs `uvicorn --reload`. Edits apply live, no deploy
  step. You're editing the live service, but the blast radius is just that one
  service.
- **Stable (#2)** — matured services. Compose runs the baked image; updates go
  through `deploy.sh` (git pull + rebuild). Reproducible, unaffected by editing.

**Lifecycle:** every service is *born Active dev* while built, then *graduates to
Stable* once it settles. The mode is self-evident from its compose (presence of
`.:/app` + `--reload`) and recorded in `/srv/CLAUDE.md`.

Rejected: #4 (no Docker) loses the per-service isolation that's the whole point of
co-hosting; #5 (two-mode override files) and #3 (separate dev checkout) add
toggling/duplication the user finds error-prone.

## Conventions (recorded in `/srv/CLAUDE.md`)

- One folder per service in `/srv`, own git repo, own compose, own host port from
  8100 up. Port + mode registry lives in `/srv/CLAUDE.md`.
- `/srv/CLAUDE.md` stays in `/srv` (directory-scoped; parent-dir CLAUDE.md is
  auto-loaded when working in any `/srv/<service>`). NOT `~/.claude/` (that's the
  global, dotfiles-managed config).
- One Caddy block per service on the VPS → `192.168.1.230:<port>`. Wildcard
  `*.osteiner.xyz` DNS already covers every subdomain — no per-subdomain record.
- Keep per-service `deploy.resources.limits` so one service can't starve others.
- Risky DB/schema work → point `AIRFARE_DB_PATH` (or per-service equivalent) at a
  copy, never the live DB.

## Steps

### 1. Flip airfare-monitor to Active dev (#1)  — PENDING (changes running service)
Edit `/srv/airfare-monitor/docker-compose.yml`:
- Replace volume `./data:/app/data` with `.:/app` (the `.` mount already includes
  `data/`, and `AIRFARE_DB_PATH=/app/data/airfare.db` keeps persistence).
- Add `command: uvicorn backend.main:app --host 0.0.0.0 --port 8100 --reload --reload-dir backend`.
- Keep `environment`, `healthcheck`, `restart`, and `deploy.resources.limits`.

Then `docker compose up -d` (no `--build` — image already built).

### 2. Update `/srv/CLAUDE.md`  — DONE
Added a "Development model" section, a Mode column in the service registry, the
graduation steps, and deploy clarification (deploy.sh = Stable services only).

### 3. `deploy.sh` — keep as-is
Stays in `airfare-monitor` (harmless while Active; used when it graduates). Every
Stable service ships the same script.

### 4. Recipe for each future service
New folder in `/srv` → `Dockerfile` + `docker-compose.yml` (Active dev while
building) + `data/` + next free port (8101, 8102, …) → register in
`/srv/CLAUDE.md` → add Caddy block on VPS → `caddy reload`.

## Verification
- `docker compose ps` → `airfare-monitor` **healthy**.
- `touch backend/main.py` (or make a real edit) → `docker compose logs` shows
  `WatchFiles detected changes` / `Application startup complete` → change is live
  without a rebuild.
- `curl -sf http://localhost:8100/` → 200 (local).
- `curl -sf https://airfares.osteiner.xyz/` → 200 (public, unchanged).
- `/srv/CLAUDE.md` registry matches reality (airfare-monitor = Active dev #1).

## Resolved
Domain is `airfares.osteiner.xyz` (VPS Caddy block + cert confirmed live). Earlier
candidates `airfare`/`airfaires` are retired.

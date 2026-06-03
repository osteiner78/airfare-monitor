# Plan 014 — Deploy to Development Server

**Date:** 2026-06-02
**Architecture:** Single LXC + Docker Compose (Option A)

## Context

- Proxmox server at `192.168.1.90` with WireGuard tunnel to an internet-facing VPS
- VPS runs Caddy as reverse proxy, already routing existing services
- 4-6 services planned, starting with airfare-monitor
- Airfare Monitor: FastAPI + uvicorn, SQLite (WAL mode), APScheduler background jobs, Jinja2 templates, HTMX frontend
- Scheduler must run 24/7 (checks every 1-3 hours)
- Backups: Proxmox LXC-level backups cover everything

## Architecture Overview

```
Internet → VPS (Caddy reverse proxy) ──WireGuard──→ Proxmox LXC (192.168.1.x)
                                                       │
                                                       ├── airfare-monitor :8100 (uvicorn)
                                                       ├── other-service-1 :8101
                                                       └── ... more containers
```

Caddy on the VPS reverse-proxies `airfare.yourdomain.com` → `<LXC_WG_IP>:8100`.

## Phases

### Phase 1 — Dockerfile

Create a multi-stage Dockerfile for the airfare-monitor project.

**Requirements:**
- Base: `python:3.12-slim` (matches `requires-python = ">=3.12"`)
- Copy only what's needed: `backend/`, `frontend/`, `requirements.txt`
- Install dependencies (excluding test deps — pytest, httpx, pytest-asyncio are dev-only)
- Expose port 8100
- Run `uvicorn backend.main:app --host 0.0.0.0 --port 8100`
- `data/` directory should be a bind-mount (volume), not in the image
- `.dockerignore` to exclude `data/`, `tests/`, `__pycache__`, `.git`, `.agent/`, `*.db*`

**Verification:** `docker build -t airfare-monitor .` succeeds. `docker run --rm airfare-monitor` starts and binds to 8100.

### Phase 2 — Docker Compose

Create `docker-compose.yml` with:

- `airfare-monitor` service
  - Build from `./`
  - Port mapping: `127.0.0.1:8100:8100` (only on LXC localhost — Caddy on VPS reaches it via WireGuard but we bind to all interfaces since it's a separate machine; actually, Caddy on VPS will proxy to `<LXC_WG_IP>:8100`, so bind to `0.0.0.0` inside the container)
  - Volume: `./data:/app/data` (bind mount for SQLite persistence)
  - Environment: `AIRFARE_DB_PATH=/app/data/airfare.db`
  - Restart policy: `unless-stopped`
  - Health check: `curl -f http://localhost:8100/ || exit 1`
  - Resource limits (modest: 256MB memory, 0.5 CPU)

**Verification:** `docker compose up -d` starts the service, `docker compose ps` shows healthy, `curl http://localhost:8100` returns HTML.

### Phase 3 — Proxmox LXC Provisioning

Create a new LXC on the Proxmox server:

- **OS:** Ubuntu 26.04
- **Resources:** 2 vCPUs, 2GB RAM, 20GB disk
- **Docker nesting:** Set `Features: nesting=1,keyctl=1` in the LXC config
- **Network:** Static IP on your home LAN (e.g., `192.168.1.95`), also reachable via WireGuard subnet
- **WireGuard:** Add this LXC's IP to the WireGuard config on both the Proxmox host and the VPS so the VPS can reach the LXC on the WireGuard interface

Setup script (run inside the LXC):
```bash
apt update && apt install -y docker.io docker-compose-plugin git curl
systemctl enable --now docker
```

**Verification:** `docker run hello-world` works. VPS can `curl http://<LXC_WG_IP>:8100` (once service is deployed).

### Phase 4 — Caddy Reverse Proxy on VPS

Add a Caddy config block on the VPS that reverse-proxies to the LXC via WireGuard:

```
airfare.osteiner.xyz {
    reverse_proxy <LXC_WG_IP>:8100
}
```

(or use the domain/subdomain you prefer)

**Verification:** Visiting `https://airfare.yourdomain.com` shows the dashboard after deployment.

### Phase 5 — Data Migration

Copy your existing `data/airfare.db` from your workstation to the LXC:

```bash
scp data/airfare.db user@192.168.1.<LXC_IP>:/srv/airfare-monitor/data/airfare.db
```

Make sure the `data/` directory exists on the LXC first. The Docker volume bind-mount (`./data:/app/data`) will pick it up on next start.

### Phase 6 — Deployment Script

Create `deploy.sh` on the LXC at `/srv/airfare-monitor/` that:

1. `git pull`
2. `docker compose up -d --build`
3. `docker compose ps` to verify

## Files to Create

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage image build |
| `.dockerignore` | Exclude dev/test/build artifacts |
| `docker-compose.yml` | Service orchestration |

## Resolved Decisions

- **Domain:** `airfare.osteiner.xyz`
- **LXC OS:** Debian 12
- **Data migration:** Copy existing `data/airfare.db` to the LXC

## Open Decisions

- **LXC IP:** What static IP to assign? (needs to be free on your LAN and in the WireGuard subnet)

## What This Doesn't Cover

- CI/CD pipelines (manual deploy for now)
- Monitoring/alerting (log into the LXC and check logs)
- Database backup (Proxmox LXC backup covers it)
- Multi-service compose (will add other services to the same compose file later)

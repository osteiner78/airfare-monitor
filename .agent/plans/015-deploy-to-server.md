# Plan 014 — Deploy airfare-monitor to the Development Server

**Date:** 2026-06-02 (revised 2026-06-03)
**Architecture:** Single LXC + Docker Compose
**Status:** Repo artifacts complete; server provisioning pending.

## Context

Goal: run airfare-monitor 24/7 on the home Proxmox server, reachable from the
internet at `https://airfare.osteiner.xyz`.

The app is FastAPI + uvicorn with an **in-process APScheduler** (so it must run as
a **single uvicorn worker** — multiple workers would double-fire scheduled jobs),
SQLite in WAL mode, and server-rendered Jinja2/HTMX templates loaded via
**relative paths** (`frontend/templates`, `frontend/static`). The container
therefore must run with `WORKDIR /app` and start the app from there.

- Proxmox server with a WireGuard tunnel to an internet-facing VPS (garfield)
- VPS runs Caddy as the public reverse proxy, already routing other services
- 4–6 services planned; airfare-monitor is the first
- Scheduler runs continuously (checks every 1–3 hours)
- Backups: Proxmox LXC-level backups cover everything

## Topology

```
Internet → VPS (Caddy, 104.168.120.158) ──WireGuard (10.0.0.1)──→ Proxmox LXC (192.168.1.230)
                                                                     │
                                                                     └── airfare-monitor :8100 (uvicorn, 1 worker)
```

Caddy on the VPS reverse-proxies `airfare.osteiner.xyz` → `192.168.1.230:8100`.

| Thing | Value |
|-------|-------|
| LXC LAN IP | `192.168.1.230` |
| WireGuard tunnel endpoint (VPS↔Proxmox) | `10.0.0.1` |
| VPS external IP | `104.168.120.158` |
| LXC OS | Debian 13 (trixie) |
| Domain | `airfare.osteiner.xyz` |
| App port | `8100` |

---

## Part 1 — Repo artifacts (DONE)

These files live in the repo and are committed-ready. Build context excludes
dev/test/data via `.dockerignore`.

### Files

| File | State | Notes |
|------|-------|-------|
| `Dockerfile` | done | `python:3.12-slim`, `WORKDIR /app`, runtime-only deps, `PYTHONUNBUFFERED=1`, single-worker uvicorn on 8100 |
| `docker-compose.yml` | done | build, `./data` bind-mount, `AIRFARE_DB_PATH` env, stdlib-Python healthcheck, `restart: unless-stopped`, 256M/0.5cpu limits |
| `.dockerignore` | done | excludes `data/`, `tests/`, `.agent/`, `*.db*`, `.git`, caches |
| `requirements.txt` | done | runtime deps only |
| `requirements-dev.txt` | done | `-r requirements.txt` + pytest/pytest-asyncio/httpx |
| `deploy.sh` | done | pull → `up -d --build` → `ps` (executable) |
| `CLAUDE.md` | done | install line split into runtime vs dev/tests |

### Two defects that were fixed

1. **Healthcheck used `curl`**, which `python:3.12-slim` does not ship → the
   container would report `unhealthy` forever. Replaced with a stdlib check:
   ```yaml
   test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8100/').status==200 else 1)"]
   ```
   It hits `/` (the dashboard, `backend/pages.py:263`). There is no dedicated
   `/health` route; adding one (to avoid a DB query every 30s) is an optional
   future nicety.

2. **Test deps were baked into the runtime image.** Split into
   `requirements.txt` (runtime) and `requirements-dev.txt` (`-r requirements.txt`
   + test deps). The Dockerfile installs only `requirements.txt`.
   **Workflow note:** running tests locally is now
   `pip install -r requirements-dev.txt`.

### Reference: final container files

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY frontend/ ./frontend/
RUN mkdir -p /app/data
ENV AIRFARE_DB_PATH=/app/data/airfare.db
EXPOSE 8100
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8100"]
```

`deploy.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git pull --recurse-submodules
docker compose up -d --build
docker compose ps
```

### Local verification (skipped this session)

No Docker runtime on the workstation, so the build was not run locally; verify on
the LXC instead (below). If verifying locally later:
```bash
docker build -t airfare-monitor .
docker compose up -d && sleep 15
docker compose ps                 # STATUS should read "healthy"
curl -sf http://localhost:8100/ | head
docker compose logs --tail=30     # scheduler started, no tracebacks
docker compose down
```

---

## Part 2 — Server runbook (PENDING — run on the server, no SSH from the workstation)

### A. Create the LXC on Proxmox (Debian 13 trixie)
- Download CT template `debian-13-standard` (Proxmox: *local* storage → CT
  Templates), or `pveam available | grep debian-13`.
- Create CT: **2 vCPU, 2 GB RAM, 20 GB disk**, static IP `192.168.1.230/24`,
  gateway = LAN router.
- Enable Docker nesting — in `/etc/pve/lxc/<ID>.conf` on the Proxmox host:
  ```
  features: nesting=1,keyctl=1
  ```
  (unprivileged container is fine with these two features).

### B. Install Docker inside the LXC
```bash
apt update && apt install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian trixie stable" > /etc/apt/sources.list.d/docker.list
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
systemctl enable --now docker
docker run --rm hello-world      # verify
```
(If `download.docker.com/linux/debian` has no `trixie` dir yet, substitute
`bookworm` — Docker CE is forward-compatible.)

### C. Get the code onto the LXC
```bash
mkdir -p /srv && cd /srv
git clone <your-repo-url> airfare-monitor   # or rsync the working tree
cd airfare-monitor
mkdir -p data
```

### D. Migrate the existing database
From the workstation (seed the bind-mount **before** the first `up`):
```bash
scp data/airfare.db root@192.168.1.230:/srv/airfare-monitor/data/airfare.db
```
WAL/SHM sidecars are optional to copy; SQLite rebuilds them.

### E. Start the stack
```bash
cd /srv/airfare-monitor
./deploy.sh
docker compose ps                          # STATUS "healthy" after ~15s
curl -sf http://localhost:8100/ | head     # local to the LXC
docker compose logs --tail=30              # scheduler firing, no tracebacks
```

### F. WireGuard reachability (the key prerequisite)
Caddy on the VPS must reach `192.168.1.230:8100` across the tunnel. Easiest path:
**route the home LAN over WireGuard** so the VPS can hit the LXC's LAN IP.
- On the **VPS** WG peer config, add the home subnet to `AllowedIPs`:
  `AllowedIPs = 10.0.0.0/24, 192.168.1.0/24`
- On the **Proxmox host** (WG endpoint `10.0.0.1`), enable IP forwarding
  (`net.ipv4.ip_forward=1`) and ensure it routes/NATs to `192.168.1.0/24`.
- Verify from the VPS: `curl -sf http://192.168.1.230:8100/ | head`.

Alternative if you'd rather not route the whole LAN: install WireGuard *inside*
the LXC, give it a `10.0.0.x` address, and point Caddy at that instead.

### G. Caddy on the VPS
- DNS: add an `A` record `airfare.osteiner.xyz → 104.168.120.158` (needed for
  Caddy's automatic TLS).
- Add to the VPS Caddyfile:
  ```
  airfare.osteiner.xyz {
      reverse_proxy 192.168.1.230:8100
  }
  ```
  (use `10.0.0.x:8100` instead if you chose the in-LXC-WireGuard alternative).
- `caddy reload` (or `systemctl reload caddy`).

---

## End-to-end success criteria
1. `docker compose ps` on the LXC shows `airfare-monitor` **healthy**.
2. From the VPS, `curl http://192.168.1.230:8100/` returns dashboard HTML.
3. `https://airfare.osteiner.xyz` loads the dashboard with a valid cert.
4. LXC logs show APScheduler firing tracker jobs on schedule.

## Resolved decisions
- **Domain:** `airfare.osteiner.xyz`
- **LXC OS:** Debian 13 (trixie) — smaller/no-snapd, guaranteed Proxmox template
  + Docker repo support; safest base for Docker-in-LXC
- **LXC IP:** `192.168.1.230` (LAN); reachable from the VPS via the WG-routed LAN
- **Data migration:** copy existing `data/airfare.db` to the LXC
- **Healthcheck:** stdlib-Python (no curl in slim image)
- **Dev deps:** split out of the runtime image

## Out of scope
CI/CD pipelines, monitoring/alerting, app-level DB backups (Proxmox LXC backup
covers it), multi-service compose (other services added to the same compose file
later).

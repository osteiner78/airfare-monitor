# Deploy airfare-monitor to the development server

## Context

Goal: run airfare-monitor 24/7 on the home Proxmox server, reachable from the
internet at `https://airfare.osteiner.xyz`. The app is FastAPI + uvicorn with an
**in-process APScheduler** (must be a single worker), SQLite in WAL mode, and
server-rendered Jinja2/HTMX templates loaded via **relative paths**
(`frontend/templates`, `frontend/static`) — so the container must run with
`WORKDIR /app` and the app started from there (the existing Dockerfile already
does this).

Topology (from user):
- LXC LAN IP: `192.168.1.230`
- WireGuard tunnel endpoint (existing VPS↔Proxmox): `10.0.0.1`
- VPS external IP: `104.168.120.158`, runs Caddy as the public reverse proxy
- LXC OS: **Debian 13 (trixie)**

The repo already has `Dockerfile`, `docker-compose.yml`, and `.dockerignore`
(untracked). They are mostly correct; this plan fixes two defects, adds a
`deploy.sh`, and provides a copy-paste server runbook. **Scope this session:**
finalize repo artifacts + verify locally + produce the server runbook. No SSH /
no remote execution from this machine.

## What's already correct (leave as-is)

- `Dockerfile`: `python:3.12-slim`, `WORKDIR /app`, copies `backend/` +
  `frontend/`, `mkdir -p /app/data`, `ENV AIRFARE_DB_PATH=/app/data/airfare.db`,
  single-worker `uvicorn ... --port 8100`. Single worker is required so
  APScheduler doesn't double-fire — do **not** add `--workers`.
- `docker-compose.yml`: `build: .`, `volumes: ./data:/app/data`,
  `restart: unless-stopped`, `8100:8100`, modest resource limits.
- `.dockerignore`: excludes `data/`, `tests/`, `.agent/`, `*.db*`, `.git`, caches.

## Defects to fix

### 1. Healthcheck uses `curl`, which `python:3.12-slim` does not ship

`docker-compose.yml:11` runs `curl -f http://localhost:8100/`. There is no curl
in the slim image, so the container is marked **unhealthy** forever. Replace with
a stdlib Python check (no extra package, no image bloat):

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8100/').status==200 else 1)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

The check hits `/` (the dashboard, `backend/pages.py:263`) — there is no
dedicated `/health` route. Adding one is an optional future nicety (avoids a DB
query every 30s); not doing it now to keep the change surgical.

### 2. Test deps land in the runtime image

`requirements.txt` bundles `pytest`, `pytest-asyncio`, `httpx`. Plan 014 asked to
exclude dev deps. Split them:

- `requirements.txt` → runtime only (`fastapi`, `uvicorn[standard]`, `aiosqlite`,
  `apscheduler`, `flights`, `jinja2`, `python-multipart`).
- New `requirements-dev.txt`:
  ```
  -r requirements.txt
  pytest>=8.2
  pytest-asyncio>=0.23
  httpx>=0.27
  ```
- Dockerfile keeps `pip install -r requirements.txt` (now runtime-only).
- **Workflow change to note:** running tests locally is now
  `pip install -r requirements-dev.txt`. Update the install line in project
  `CLAUDE.md` accordingly.

## Files to create / change (repo side)

| File | Change |
|------|--------|
| `docker-compose.yml` | Fix healthcheck (Python stdlib); add explicit `environment: AIRFARE_DB_PATH=/app/data/airfare.db` for clarity |
| `requirements.txt` | Remove the three test deps |
| `requirements-dev.txt` | New — `-r requirements.txt` + the test deps |
| `deploy.sh` | New — pull, rebuild, show status |
| `CLAUDE.md` | One-line: tests use `requirements-dev.txt` |

`deploy.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
git pull --recurse-submodules
docker compose up -d --build
docker compose ps
```

## Local verification (run on this workstation during execution)

```bash
docker build -t airfare-monitor .
docker compose up -d
sleep 15
docker compose ps                  # STATUS should read "healthy"
curl -sf http://localhost:8100/ | head   # dashboard HTML
docker compose logs --tail=30      # scheduler started, no tracebacks
docker compose down
```
Success = image builds, container reports `healthy`, `/` returns HTML, logs show
the scheduler starting cleanly.

## Server runbook (you run these; no SSH from here)

### A. Create the LXC on Proxmox (Debian 13 trixie)
- Download CT template `debian-13-standard` (Proxmox: *local* storage → CT
  Templates → Templates), or `pveam available | grep debian-13`.
- Create CT: **2 vCPU, 2 GB RAM, 20 GB disk**, static IP `192.168.1.230/24`,
  gateway = your LAN router.
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
(If `download.docker.com/linux/debian` has no `trixie` dir yet at deploy time,
substitute `bookworm` — Docker CE is forward-compatible.)

### C. Get the code onto the LXC
```bash
mkdir -p /srv && cd /srv
git clone <your-repo-url> airfare-monitor   # or rsync the working tree
cd airfare-monitor
mkdir -p data
```

### D. Migrate the existing database
From this workstation (copy the live SQLite DB into the bind-mount):
```bash
scp data/airfare.db root@192.168.1.230:/srv/airfare-monitor/data/airfare.db
```
Do this **before** first `up` so the volume is seeded. WAL/SHM sidecars are
optional to copy; SQLite rebuilds them.

### E. Start the stack
```bash
cd /srv/airfare-monitor
./deploy.sh
curl -sf http://localhost:8100/ | head    # local to the LXC
```

### F. WireGuard reachability (the key prerequisite)
Caddy on the VPS must reach `192.168.1.230:8100` across the tunnel. Easiest path:
**route the home LAN over WireGuard** so the VPS can hit the LXC's LAN IP:
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
- Verify: open `https://airfare.osteiner.xyz` → dashboard loads over HTTPS.

## End-to-end success criteria
1. `docker compose ps` on the LXC shows `airfare-monitor` **healthy**.
2. From the VPS, `curl http://192.168.1.230:8100/` returns dashboard HTML.
3. `https://airfare.osteiner.xyz` loads the dashboard with a valid cert.
4. LXC logs show the APScheduler firing tracker jobs on schedule.

## Out of scope (per plan 014)
CI/CD, monitoring/alerting, app-level DB backups (Proxmox LXC backup covers it),
multi-service compose (other services added to the same compose file later).

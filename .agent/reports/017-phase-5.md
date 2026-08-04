# Phase 5 — Docker/infra: Chromium in the main container, shm, limits, secrets

## What was built

- `Dockerfile`: added `RUN playwright install --with-deps chromium` immediately after
  `pip install -r requirements.txt`, per 5.1. Browsers land in
  `/root/.cache/ms-playwright`, outside the `.:/app` bind mount.
- `docker-compose.yml`: added `shm_size: 1gb` (5.2), raised
  `deploy.resources.limits` from `256M`/`0.5` cpu to `1.5G`/`2.0` cpus (5.3), and
  added `env_file: .env` (5.4) — the first secret this project has needed.
- `/srv/airfare-monitor/.env` created (gitignored, mode `600`) with
  `DEEPSEEK_API_KEY` set to the key the user supplied interactively (5.5).
- `/srv/airfare-monitor/CLAUDE.md`: updated the Kayak future-me note with the
  Phase 5 outcome and a discovery (below), added a Playwright/`--reload`
  orphaning gotcha, and added a Phase 5 Docker/infra summary note (5.7, in-project
  half).
- `/srv/CLAUDE.md`: added a `shm_size` convention bullet with `airfare-monitor`
  as the concrete precedent (5.7, outside-project half — done after explicit
  user confirmation, since it's outside `/srv/airfare-monitor/`).

## Verification output

```
$ docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -i airfare   # before
airfare-monitor-airfare-monitor:latest	352MB

$ docker compose up -d --build
[...]
 Image airfare-monitor-airfare-monitor  Built
 Container airfare-monitor  Recreate
 Container airfare-monitor  Recreated
 Container airfare-monitor  Starting
 Container airfare-monitor  Started

$ docker compose ps
NAME              IMAGE                             COMMAND                  SERVICE           CREATED          STATUS                    PORTS
airfare-monitor   airfare-monitor-airfare-monitor   "uvicorn backend.mai…"   airfare-monitor   38 seconds ago   Up 35 seconds (healthy)   0.0.0.0:8100->8100/tcp, [::]:8100->8100/tcp

$ docker inspect airfare-monitor --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.ShmSize}}'
1610612736 2000000000 1073741824
# = 1.5G memory, 2.0 cpus, 1GB shm — matches docker-compose.yml

$ docker exec airfare-monitor python -c "from playwright.async_api import async_playwright; print('ok')"
ok

$ docker exec airfare-monitor python -c "import os; assert os.environ['DEEPSEEK_API_KEY']; print('key ok')"
key ok

$ docker stats airfare-monitor --no-stream
CONTAINER ID   NAME              CPU %     MEM USAGE / LIMIT   MEM %     NET I/O          BLOCK I/O        PIDS
e38d8c64b3ce   airfare-monitor   0.17%     117.4MiB / 1.5GiB   7.64%     261kB / 32.5kB   1.5MB / 7.75MB   10

$ docker exec airfare-monitor pip install --no-cache-dir -r requirements-dev.txt
[...]
Successfully installed iniconfig-2.3.0 packaging-26.2 pluggy-1.6.0 pytest-9.1.1 pytest-asyncio-1.4.0

$ docker exec airfare-monitor python -m pytest tests/ -v -k "not slow"
[...]
====================== 290 passed, 3 deselected in 23.55s ======================

$ docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -i airfare   # after
airfare-monitor-airfare-monitor:latest	2.13GB

$ df -h /   # after
/dev/mapper/data--nvme-vm--230--disk--0   49G   31G   16G  67% /

$ curl -sS -o /dev/null -w "%{http_code}\n" http://localhost:8100/
200
```

## Commit hash(es)

`[phase-5.1-5.7] Bundle Chromium, size limits, and .env secrets for Kayak` — see `git log`.

## Deviations from the plan

1. **Image size grew far more than the plan's 300-400MB estimate: 352MB → 2.13GB
   (+1.78GB).** `RUN playwright install --with-deps chromium` pulls not just
   Chromium/ffmpeg/headless-shell (~300MB combined, matching the plan's estimate)
   but a full `apt --with-deps` closure — X11 libs, Mesa/GL, fontconfig,
   `fonts-wqy-zenhei` (CJK fonts), xvfb, etc. Still comfortably inside the
   16G free remaining on `minnie` (61% → 67% used). Noted in both CLAUDE.md
   files as the real figure other services should budget from.
2. **Did not touch `backend/sources/kayak.py`'s `_LLM_BASE_URL`/`_LLM_MODEL`
   constants**, even though the API key the user provided during 5.5 turned out
   to be an **opencode.ai Go proxy key** (opencode Go subscription, includes
   DeepSeek V4 Flash), not a native DeepSeek API key — `kayak.py`'s current
   `_LLM_BASE_URL = "https://api.deepseek.com"` will not authenticate against it.
   That file is Phase 2 scope, already shipped and committed, and the user asked
   for Phase 5 only; fixing the endpoint there would have been scope creep on a
   different phase. Documented prominently as a required follow-up in
   `/srv/airfare-monitor/CLAUDE.md` (with the endpoint/model details found via
   `WebFetch` against opencode's docs — **flagged there as not independently
   verified against the raw API**, since two fetches disagreed on whether the
   model id needs an `opencode/` prefix) so Phase 6 doesn't hit a silent,
   unexplained auth failure.
3. **`docker exec airfare-monitor pip install -r requirements-dev.txt` was run
   manually before the in-container pytest run**, matching the pattern visible
   in Phases 3-4's reports (pytest was available in-container there too, but
   this project's convention — `/srv/CLAUDE.md` and this project's own
   `CLAUDE.md` — deliberately keeps `requirements-dev.txt` out of the
   `Dockerfile`). This rebuild wiped whatever manual install a prior session had
   done, so it had to be redone. Not persisted — will need repeating after any
   future image rebuild. Not a plan deviation exactly (the plan's own Phase 5
   verification block includes the in-container pytest command), but worth
   flagging since it required an undocumented extra step to make that
   verification command work.

## Test gaps / new tests

None — Phase 5 is infra-only, no new pytest files per the plan (matches the
precedent set by plan 016's Phase 3).

## Follow-ups (not done — out of scope for this phase)

- **Fix `kayak.py`'s `_LLM_BASE_URL`/`_LLM_MODEL`** to point at the opencode.ai
  Go proxy (base URL `https://opencode.ai/zen/go/v1`, model likely
  `deepseek-v4-flash` — verify live, the exact model-id prefixing was
  inconsistent across two fetched doc pages) before attempting Phase 6's live
  verification. This is required for Kayak to actually authenticate; without it
  every real Kayak attempt will fail at the LLM call step with a clean but
  uninformative `ERROR`-level `last_error`.
- Phase 5.6's "confirm build time growth is acceptable" — build took ~2 minutes
  total, dominated by Chromium/headless-shell downloads (~50s) and image export
  (~68s); not flagged as a problem, just noting it's no longer a sub-30s build.

## Confidence

**likely-good** — every plan task (5.1-5.7) completed and verified against the
plan's own commands, full test suite green post-rebuild, service healthy and
serving traffic. Downgraded from "certain" only because of the opencode.ai
endpoint discovery: Phase 5's own success criteria (infra runs, key present,
limits/shm correct) are fully met, but the *practical* next step (Phase 6) is
now known to be blocked on a Phase 2 fix that this session deliberately left
undone to respect scope.

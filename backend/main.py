from contextlib import asynccontextmanager
from datetime import datetime

import backend.scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request

from fastapi.staticfiles import StaticFiles

from backend.api import router as api_router
from backend.db import (
    DEFAULT_INTERVAL_MINUTES,
    get_db_path,
    get_latest_snapshot,
    init_db,
    list_trackers,
)
from backend.pages import router as pages_router

_initialized_paths: set[str] = set()


async def _startup() -> None:
    path = get_db_path()
    if path not in _initialized_paths:
        await init_db(path)
        _initialized_paths.add(path)

    if backend.scheduler.scheduler is None:
        backend.scheduler.scheduler = AsyncIOScheduler()
    if not backend.scheduler.scheduler.running:
        backend.scheduler.scheduler.start()

    trackers = await list_trackers()
    for tracker in trackers:
        if tracker["active"]:
            backend.scheduler.add_tracker_job(
                tracker["id"],
                tracker["interval_minutes"],
                run_immediately=await _tracker_is_overdue(tracker),
            )


async def _tracker_is_overdue(tracker: dict) -> bool:
    """Should this tracker search the moment the worker starts?

    Unconditional `run_immediately=True` meant every `--reload` -- i.e. every
    edit under `backend/` -- fired a live search for every active tracker.
    Measured 2026-08-11: 144 snapshots in one day against ~24 expected at
    60 min x 6 trackers, with 78 in the single hour spent editing code. That is
    real upstream request volume against a source that had already returned
    zero rows once that night.

    Overdue-only keeps the behaviour that actually matters (a genuine restart
    after downtime refreshes at once) and drops the part that never did (a
    restart seconds after the last search re-running everything).
    """
    latest = await get_latest_snapshot(tracker["id"])
    if latest is None:
        return True
    age = _snapshot_age_minutes(latest.get("searched_at"))
    if age is None:
        return True
    return age >= (tracker["interval_minutes"] or DEFAULT_INTERVAL_MINUTES)


def _snapshot_age_minutes(searched_at) -> float | None:
    if not searched_at:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            observed = datetime.strptime(str(searched_at).split(".")[0], fmt)
        except ValueError:
            continue
        return (datetime.now() - observed).total_seconds() / 60.0
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    yield
    if backend.scheduler.scheduler and backend.scheduler.scheduler.running:
        backend.scheduler.scheduler.remove_all_jobs()
        backend.scheduler.scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.include_router(pages_router)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.middleware("http")
async def ensure_db_initialized(request: Request, call_next):
    path = get_db_path()
    if path not in _initialized_paths:
        await init_db(path)
        _initialized_paths.add(path)
    return await call_next(request)

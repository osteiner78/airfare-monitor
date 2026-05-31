from contextlib import asynccontextmanager

import backend.scheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request

from backend.api import router
from backend.db import get_db_path, init_db, list_trackers

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
            backend.scheduler.add_tracker_job(tracker["id"], tracker["interval_minutes"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    yield
    if backend.scheduler.scheduler and backend.scheduler.scheduler.running:
        backend.scheduler.scheduler.remove_all_jobs()
        backend.scheduler.scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def ensure_db_initialized(request: Request, call_next):
    path = get_db_path()
    if path not in _initialized_paths:
        await init_db(path)
        _initialized_paths.add(path)
    return await call_next(request)

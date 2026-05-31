import pytest
import pytest_asyncio
import aiosqlite
from unittest.mock import AsyncMock


@pytest_asyncio.fixture
async def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("AIRFARE_DB_PATH", path)
    from backend.db import init_db
    await init_db(path)
    return path


@pytest_asyncio.fixture
async def db_conn(db_path):
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("AIRFARE_DB_PATH", path)
    monkeypatch.setattr("backend.scheduler.search_and_store", AsyncMock(return_value=None))
    from backend.main import app
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

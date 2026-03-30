"""
Shared pytest fixtures.

- test_settings: uses in-memory SQLite, temp data dirs
- engine / db: async SQLModel engine + session
- client: async httpx TestClient wired to the FastAPI app
"""
import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


# ── Force test settings before any platform import reads .env ─────────────────

@pytest.fixture(scope="session", autouse=True)
def set_test_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("data")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["DATA_DIR"] = str(tmp)
    os.environ["RAW_DATA_DIR"] = str(tmp / "raw")
    os.environ["PROCESSED_DATA_DIR"] = str(tmp / "processed")
    os.environ["APP_ENV"] = "testing"
    os.environ["CELERY_BROKER_URL"] = "memory://"
    os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
    (tmp / "raw").mkdir(parents=True, exist_ok=True)
    (tmp / "processed").mkdir(parents=True, exist_ok=True)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """In-memory SQLite engine, fresh per test."""
    # Import models so SQLModel knows about them
    import bgdata.models.institution  # noqa
    import bgdata.models.data_file  # noqa
    import bgdata.models.dataset  # noqa

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient with overridden DB session."""
    from bgdata.database import get_session
    from bgdata.main import app

    async def override_session():
        async with AsyncSession(db_engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def sample_institution_data():
    return {"slug": "test_inst", "name": "Test Institution", "base_url": "https://example.com"}

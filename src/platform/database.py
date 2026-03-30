"""
Database engine, session management, and table initialisation.
Uses SQLModel (SQLAlchemy under the hood) with async support.
"""
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from platform.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is not None:
        return _engine

    cfg = settings or get_settings()

    connect_args: dict = {}
    kwargs: dict = {}

    if cfg.is_sqlite:
        # SQLite needs check_same_thread=False and a StaticPool for async
        connect_args["check_same_thread"] = False
        kwargs["poolclass"] = StaticPool

    _engine = create_async_engine(
        cfg.database_url,
        echo=cfg.app_debug,
        connect_args=connect_args,
        **kwargs,
    )
    return _engine


async def init_db(settings: Settings | None = None) -> None:
    """Create all tables. Called on application startup."""
    cfg = settings or get_settings()
    cfg.ensure_dirs()

    engine = get_engine(cfg)

    # Import models so SQLModel knows about them before create_all
    import platform.models.institution  # noqa: F401
    import platform.models.data_file  # noqa: F401
    import platform.models.dataset  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    logger.info("Database tables created / verified.")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session per request."""
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session

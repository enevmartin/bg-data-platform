"""
FastAPI application factory.

Startup sequence:
  1. Ensure data directories exist
  2. Create / verify database tables
  3. Seed institutions if DB is empty
  4. Mount all API routers
  5. Mount dashboard router
"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from platform.config import get_settings
from platform.database import get_engine, init_db

logging.basicConfig(
    level=get_settings().log_level,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    cfg.ensure_dirs()
    await init_db(cfg)
    await _seed_institutions()
    logger.info("BG Data Platform ready at http://%s:%d", cfg.app_host, cfg.app_port)
    yield
    engine = get_engine()
    await engine.dispose()


async def _seed_institutions() -> None:
    """Insert BNB and NSI if the institutions table is empty."""
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession
    from platform.models.institution import Institution
    from platform.database import get_engine

    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        existing = (await session.exec(select(Institution))).first()
        if existing:
            return

        institutions = [
            Institution(
                slug="bnb",
                name="Bulgarian National Bank",
                base_url="https://www.bnb.bg",
                description="BNB statistical data: exchange rates, monetary statistics, interest rates",
            ),
            Institution(
                slug="nsi",
                name="National Statistical Institute",
                base_url="https://www.nsi.bg",
                description="NSI national statistics: population, economy, labour, agriculture",
            ),
        ]
        for inst in institutions:
            session.add(inst)
        await session.commit()
        logger.info("Seeded %d institutions", len(institutions))


def create_app() -> FastAPI:
    cfg = get_settings()

    app = FastAPI(
        title="BG Data Platform",
        description="Bulgarian government statistical data pipeline — scraping, processing, analytics",
        version="0.1.0",
        lifespan=lifespan,
        debug=cfg.app_debug,
    )

    # ── API routers ───────────────────────────────────────────────────────────
    from platform.api.institutions import router as institutions_router
    from platform.api.files import router as files_router
    from platform.api.datasets import router as datasets_router
    from platform.api.quality import router as quality_router
    from platform.api.scrapers import router as scrapers_router

    app.include_router(institutions_router)
    app.include_router(files_router)
    app.include_router(datasets_router)
    app.include_router(quality_router)
    app.include_router(scrapers_router)

    # ── Dashboard HTML router ─────────────────────────────────────────────────
    from platform.dashboard.router import router as dashboard_router

    app.include_router(dashboard_router)

    return app


app = create_app()

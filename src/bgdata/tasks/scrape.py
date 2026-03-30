"""
Celery task: run_scraper(institution_slug)

Runs entirely synchronously inside Celery (no event loop magic needed —
we spin up a fresh asyncio loop per task invocation).
"""
import asyncio
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from bgdata.config import get_settings
from bgdata.models.institution import Institution
from bgdata.scrapers.base import ScraperResult
from bgdata.scrapers.registry import get_scraper_class
from bgdata.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="bgdata.scrape.run_scraper", max_retries=0)
def run_scraper(self, institution_slug: str) -> dict:
    """
    Celery entry point.  Looks up the institution in DB, instantiates the
    correct scraper, and runs it.  Returns a result dict.
    """
    logger.info("Task run_scraper started for '%s'", institution_slug)
    self.update_state(state="STARTED", meta={"institution": institution_slug})

    cfg = get_settings()

    async def _run() -> dict:
        engine = create_async_engine(cfg.database_url)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            # Fetch institution
            stmt = select(Institution).where(Institution.slug == institution_slug)
            rows = await session.exec(stmt)
            institution = rows.first()

            if institution is None:
                raise ValueError(f"Institution '{institution_slug}' not found in DB")

            scraper_cls = get_scraper_class(institution_slug)
            result = ScraperResult(institution_slug)

            async with scraper_cls(institution.id, cfg) as scraper:
                await scraper.run(session, result)

            # Update institution stats
            from datetime import datetime, timezone
            from sqlmodel import select as sel

            institution.last_scraped_at = datetime.now(timezone.utc)
            institution.total_files += result.files_downloaded
            institution.total_size_bytes += result.total_bytes
            session.add(institution)
            await session.commit()

        await engine.dispose()
        result.finish()
        return result.to_dict()

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
    except Exception as exc:
        logger.error("run_scraper failed for '%s': %s", institution_slug, exc)
        self.update_state(state="FAILURE", meta={"error": str(exc)})
        raise

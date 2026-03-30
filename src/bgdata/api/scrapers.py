from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.database import get_session
from bgdata.models.institution import Institution
from bgdata.scrapers.registry import list_slugs
from bgdata.tasks.celery_app import celery_app
from bgdata.tasks.scrape import run_scraper

router = APIRouter(prefix="/api/scrapers", tags=["scrapers"])


@router.get("")
async def list_scrapers() -> list[str]:
    """Return all registered scraper slugs."""
    return list_slugs()


@router.post("/{institution_slug}/run")
async def trigger_scraper(
    institution_slug: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trigger a Celery scrape task. Returns the task_id for status polling."""
    rows = await session.exec(
        select(Institution).where(Institution.slug == institution_slug)
    )
    institution = rows.first()
    if institution is None:
        raise HTTPException(status_code=404, detail=f"Institution '{institution_slug}' not found")

    task = run_scraper.delay(institution_slug)
    return {
        "task_id": task.id,
        "institution_slug": institution_slug,
        "status": "PENDING",
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """Poll the status of a Celery task."""
    result = AsyncResult(task_id, app=celery_app)
    try:
        status = result.status
        result_data = result.result if result.ready() else None
        if isinstance(result_data, Exception):
            result_data = str(result_data)
    except Exception:
        status = "UNKNOWN"
        result_data = None
    return {
        "task_id": task_id,
        "status": status,
        "result": result_data,
    }

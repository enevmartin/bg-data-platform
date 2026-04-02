"""
Dashboard HTML router — Jinja2 + HTMX pages.
"""
import json
import logging
from pathlib import Path
from typing import Optional

import polars as pl
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.dashboard.charts import (
    bar_chart,
    distribution_chart,
    files_per_month_chart,
    gauge_chart,
    line_chart,
)
from bgdata.database import get_session
from bgdata.models.data_file import DataFile, FileStatus
from bgdata.models.dataset import Dataset, DatasetStatus
from bgdata.models.institution import Institution
from bgdata.tasks.celery_app import celery_app
from bgdata.tasks.scrape import run_scraper

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

router = APIRouter(tags=["dashboard"])


# ── Index ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    institutions = (await session.exec(select(Institution))).all()

    files = (await session.exec(select(DataFile))).all()
    monthly: dict[str, int] = {}
    for f in files:
        if f.downloaded_at:
            key = f.downloaded_at.strftime("%Y-%m")
            monthly[key] = monthly.get(key, 0) + 1

    chart_option = files_per_month_chart(monthly) if monthly else {}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "institutions": institutions,
            "files_chart": json.dumps(chart_option),
            "total_files": len(files),
        },
    )


# ── HTMX: pipeline status partial ────────────────────────────────────────────

@router.get("/htmx/pipeline-status", response_class=HTMLResponse)
async def pipeline_status_partial(
    request: Request, session: AsyncSession = Depends(get_session)
):
    recent_files = (
        await session.exec(
            select(DataFile).order_by(DataFile.created_at.desc()).limit(10)
        )
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="partials/pipeline_status.html",
        context={"recent_files": recent_files},
    )


# ── Datasets browser ─────────────────────────────────────────────────────────

@router.get("/datasets", response_class=HTMLResponse)
async def datasets_page(
    request: Request,
    q: Optional[str] = None,
    institution_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Dataset).order_by(Dataset.created_at.desc()).limit(100)
    if institution_id:
        stmt = stmt.where(Dataset.institution_id == institution_id)
    datasets = (await session.exec(stmt)).all()

    if q:
        q_lower = q.lower()
        datasets = [d for d in datasets if q_lower in d.name.lower()]

    institutions = (await session.exec(select(Institution))).all()

    return templates.TemplateResponse(
        request=request,
        name="datasets.html",
        context={
            "datasets": datasets,
            "institutions": institutions,
            "q": q or "",
            "selected_institution": institution_id,
        },
    )


# ── Single dataset ────────────────────────────────────────────────────────────

@router.get("/datasets/{dataset_id}", response_class=HTMLResponse)
async def dataset_detail(
    dataset_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    dataset = await session.get(Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    gauge = {}
    dist_charts: list[dict] = []
    ts_chart: dict = {}
    quality = dataset.quality_report or {}

    if dataset.parquet_path:
        path = Path(dataset.parquet_path)
        if path.exists():
            df = pl.read_parquet(str(path))

            if quality:
                gauge = gauge_chart("Quality Score", quality.get("quality_score", 0))

            numeric_cols = [
                c for c in df.columns
                if df[c].dtype in (
                    pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                    pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
                    pl.Float32, pl.Float64,
                )
            ][:5]
            for col in numeric_cols:
                opt = distribution_chart(df, col)
                if opt:
                    dist_charts.append(opt)

            date_cols = [
                c for c in df.columns
                if df[c].dtype in (pl.Date, pl.Datetime)
            ]
            if date_cols and numeric_cols:
                date_col = date_cols[0]
                val_col = numeric_cols[0]
                try:
                    sorted_df = df.select([date_col, val_col]).drop_nulls().sort(date_col)
                    x = [str(v) for v in sorted_df[date_col].to_list()]
                    y = [float(v) for v in sorted_df[val_col].to_list()]
                    ts_chart = line_chart(
                        f"{val_col} over time",
                        x,
                        [{"name": val_col, "data": y}],
                    )
                except Exception:
                    pass

    return templates.TemplateResponse(
        request=request,
        name="dataset.html",
        context={
            "dataset": dataset,
            "quality": quality,
            "gauge_chart": json.dumps(gauge),
            "dist_charts": [json.dumps(c) for c in dist_charts],
            "ts_chart": json.dumps(ts_chart),
        },
    )


# ── Pipeline dashboard ────────────────────────────────────────────────────────

async def _pipeline_counts(session: AsyncSession) -> dict:
    """Aggregate counts across pipeline stages."""
    from bgdata.models.data_file import FileStatus

    files = (await session.exec(select(DataFile))).all()
    datasets = (await session.exec(select(Dataset))).all()

    return {
        "downloaded": sum(1 for f in files if f.status == FileStatus.DOWNLOADED),
        "processing": sum(1 for f in files if f.status == FileStatus.PROCESSING),
        "processed": sum(1 for f in files if f.status == FileStatus.PROCESSED),
        "datasets_ready": sum(1 for d in datasets if d.status in (DatasetStatus.READY, DatasetStatus.ANALYZING)),
        "datasets_analyzed": sum(1 for d in datasets if d.status == DatasetStatus.ANALYZED),
    }


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_page(
    request: Request, session: AsyncSession = Depends(get_session)
):
    counts = await _pipeline_counts(session)
    institutions = (await session.exec(select(Institution))).all()
    datasets = (await session.exec(select(Dataset))).all()
    files = (await session.exec(select(DataFile))).all()

    # Per-institution rows
    inst_map = {i.id: i for i in institutions}
    from collections import defaultdict
    inst_files: dict = defaultdict(list)
    inst_datasets: dict = defaultdict(list)
    for f in files:
        inst_files[f.institution_id].append(f)
    for d in datasets:
        inst_datasets[d.institution_id].append(d)

    institution_rows = []
    for inst in institutions:
        ifiles = inst_files[inst.id]
        idatasets = inst_datasets[inst.id]
        scores = [
            d.quality_report["quality_score"]
            for d in idatasets
            if d.quality_report and "quality_score" in d.quality_report
        ]
        institution_rows.append({
            "id": inst.id,
            "name": inst.name,
            "downloaded": sum(1 for f in ifiles if f.status == FileStatus.DOWNLOADED),
            "processed": sum(1 for f in ifiles if f.status == FileStatus.PROCESSED),
            "datasets": len(idatasets),
            "analyzed": sum(1 for d in idatasets if d.status == DatasetStatus.ANALYZED),
            "avg_quality": round(sum(scores) / len(scores)) if scores else None,
        })

    # Quality score histogram
    quality_hist: dict = {}
    all_scores = [
        d.quality_report["quality_score"]
        for d in datasets
        if d.quality_report and "quality_score" in d.quality_report
    ]
    if all_scores:
        buckets = {"0–59": 0, "60–79": 0, "80–89": 0, "90–100": 0}
        for s in all_scores:
            if s >= 90:
                buckets["90–100"] += 1
            elif s >= 80:
                buckets["80–89"] += 1
            elif s >= 60:
                buckets["60–79"] += 1
            else:
                buckets["0–59"] += 1
        quality_hist = bar_chart(
            "Datasets by Quality Score",
            list(buckets.keys()),
            "Datasets",
            list(buckets.values()),
        )

    return templates.TemplateResponse(
        request=request,
        name="pipeline.html",
        context={
            "counts": counts,
            "institutions": institutions,
            "institution_rows": institution_rows,
            "quality_hist": json.dumps(quality_hist) if quality_hist else None,
        },
    )


@router.get("/htmx/pipeline-counts", response_class=HTMLResponse)
async def pipeline_counts_partial(
    request: Request, session: AsyncSession = Depends(get_session)
):
    counts = await _pipeline_counts(session)
    return templates.TemplateResponse(
        request=request,
        name="partials/pipeline_counts.html",
        context={"counts": counts},
    )


# ── Scraper control panel ─────────────────────────────────────────────────────

@router.get("/scrapers", response_class=HTMLResponse)
async def scrapers_page(
    request: Request, session: AsyncSession = Depends(get_session)
):
    institutions = (await session.exec(select(Institution))).all()
    return templates.TemplateResponse(
        request=request,
        name="scraper.html",
        context={"institutions": institutions},
    )


@router.post("/scrapers/{institution_slug}/run", response_class=HTMLResponse)
async def trigger_scraper_htmx(
    institution_slug: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rows = await session.exec(
        select(Institution).where(Institution.slug == institution_slug)
    )
    institution = rows.first()

    if institution is None:
        return HTMLResponse(
            f'<span class="badge badge-error">Institution "{institution_slug}" not found</span>',
            status_code=404,
        )

    task = run_scraper.delay(institution_slug)
    return templates.TemplateResponse(
        request=request,
        name="partials/task_badge.html",
        context={
            "task_id": task.id,
            "institution_slug": institution_slug,
            "status": "PENDING",
        },
    )


@router.get("/htmx/task/{task_id}", response_class=HTMLResponse)
async def task_status_badge(task_id: str, request: Request):
    result = AsyncResult(task_id, app=celery_app)
    return templates.TemplateResponse(
        request=request,
        name="partials/task_badge.html",
        context={
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
        },
    )

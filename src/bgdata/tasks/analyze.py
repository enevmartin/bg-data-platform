"""
Celery task: analyze_dataset(dataset_id)

Loads the parquet file for a Dataset, runs DataQualityChecker,
and stores the QualityReport JSON back into the Dataset record.
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.config import get_settings
from bgdata.models.dataset import Dataset, DatasetStatus
from bgdata.quality.checker import DataQualityChecker
from bgdata.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="bgdata.analyze.analyze_dataset", max_retries=1)
def analyze_dataset(self, dataset_id: int) -> dict:
    cfg = get_settings()

    async def _run() -> dict:
        engine = create_async_engine(cfg.database_url)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = select(Dataset).where(Dataset.id == dataset_id)
            rows = await session.exec(stmt)
            dataset: Dataset | None = rows.first()

            if dataset is None:
                raise ValueError(f"Dataset id={dataset_id} not found")

            if not dataset.parquet_path:
                raise ValueError(f"Dataset id={dataset_id} has no parquet_path")

            parquet_path = Path(dataset.parquet_path)
            if not parquet_path.exists():
                raise FileNotFoundError(str(parquet_path))

            dataset.status = DatasetStatus.ANALYZING
            session.add(dataset)
            await session.commit()

            df = pl.read_parquet(str(parquet_path))
            checker = DataQualityChecker()
            report = checker.check(df, dataset_name=dataset.name)

            dataset.quality_report = report.to_dict()
            dataset.status = DatasetStatus.ANALYZED
            dataset.analyzed_at = datetime.now(timezone.utc)
            session.add(dataset)
            await session.commit()

        await engine.dispose()
        return {"dataset_id": dataset_id, "quality_score": report.quality_score}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

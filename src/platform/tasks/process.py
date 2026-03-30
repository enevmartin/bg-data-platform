"""
Celery task: process_file(data_file_id)

Reads a downloaded DataFile, runs the appropriate processor,
saves the resulting DataFrame as a parquet file, and creates Dataset records.
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from platform.config import get_settings
from platform.models.data_file import DataFile, FileStatus
from platform.models.dataset import Dataset, DatasetStatus
from platform.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_processor(file_path: Path):
    from platform.processors.csv import CSVProcessor
    from platform.processors.excel import ExcelProcessor
    from platform.processors.pdf import PDFProcessor

    suffix = file_path.suffix.lower()
    for cls in (ExcelProcessor, CSVProcessor, PDFProcessor):
        instance = cls()
        if instance.can_handle(file_path):
            return instance
    return None


@celery_app.task(bind=True, name="platform.process.process_file", max_retries=2)
def process_file(self, data_file_id: int) -> dict:
    cfg = get_settings()

    async def _run() -> dict:
        engine = create_async_engine(cfg.database_url)
        datasets_created = []

        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = select(DataFile).where(DataFile.id == data_file_id)
            rows = await session.exec(stmt)
            data_file: DataFile | None = rows.first()

            if data_file is None:
                raise ValueError(f"DataFile id={data_file_id} not found")

            if not data_file.local_path:
                raise ValueError(f"DataFile id={data_file_id} has no local_path")

            file_path = Path(data_file.local_path)
            if not file_path.exists():
                data_file.status = FileStatus.FAILED
                data_file.error_message = f"File not found on disk: {file_path}"
                session.add(data_file)
                await session.commit()
                raise FileNotFoundError(str(file_path))

            processor = _get_processor(file_path)
            if processor is None:
                logger.warning("No processor for %s", file_path)
                data_file.status = FileStatus.FAILED
                data_file.error_message = f"Unsupported file type: {file_path.suffix}"
                session.add(data_file)
                await session.commit()
                return {"data_file_id": data_file_id, "datasets": []}

            data_file.status = FileStatus.PROCESSING
            session.add(data_file)
            await session.commit()

            try:
                frames = processor.process(file_path)
            except Exception as exc:
                data_file.status = FileStatus.FAILED
                data_file.error_message = str(exc)
                session.add(data_file)
                await session.commit()
                raise

            processed_dir = cfg.processed_data_dir / data_file.filename
            processed_dir.mkdir(parents=True, exist_ok=True)

            for i, df in enumerate(frames):
                sheet = f"sheet_{i}" if len(frames) > 1 else "main"
                parquet_path = processed_dir / f"{sheet}.parquet"

                try:
                    df.write_parquet(str(parquet_path))
                except Exception as exc:
                    logger.error("Failed to write parquet %s: %s", parquet_path, exc)
                    continue

                dataset = Dataset(
                    name=f"{data_file.filename} — {sheet}",
                    data_file_id=data_file.id,
                    institution_id=data_file.institution_id,
                    sheet_name=sheet,
                    row_count=df.height,
                    column_count=df.width,
                    status=DatasetStatus.READY,
                    column_schema={c: str(df[c].dtype) for c in df.columns},
                    parquet_path=str(parquet_path),
                )
                session.add(dataset)
                await session.flush()
                datasets_created.append(dataset.id)

            data_file.status = FileStatus.PROCESSED
            data_file.processed_at = datetime.now(timezone.utc)
            session.add(data_file)
            await session.commit()

        await engine.dispose()
        return {"data_file_id": data_file_id, "datasets": datasets_created}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()

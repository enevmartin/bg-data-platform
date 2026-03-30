from typing import Any, Optional

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.database import get_session
from bgdata.models.dataset import Dataset, DatasetRead

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetRead])
async def list_datasets(
    institution_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Dataset)
    if institution_id is not None:
        stmt = stmt.where(Dataset.institution_id == institution_id)
    if status is not None:
        stmt = stmt.where(Dataset.status == status)
    stmt = stmt.order_by(Dataset.created_at.desc()).offset(offset).limit(limit)
    rows = await session.exec(stmt)
    return rows.all()


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(dataset_id: int, session: AsyncSession = Depends(get_session)):
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds


@router.get("/{dataset_id}/data")
async def get_dataset_data(
    dataset_id: int,
    limit: int = Query(100, ge=1, le=10_000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not ds.parquet_path:
        raise HTTPException(status_code=404, detail="Dataset has no data file")

    from pathlib import Path

    path = Path(ds.parquet_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Data file not found on disk")

    df = pl.read_parquet(str(path)).slice(offset, limit)
    return {
        "dataset_id": dataset_id,
        "total_rows": ds.row_count,
        "offset": offset,
        "limit": limit,
        "columns": df.columns,
        "rows": df.to_dicts(),
    }


@router.get("/{dataset_id}/export")
async def export_dataset_csv(
    dataset_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Stream the full dataset as a CSV download."""
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if not ds.parquet_path:
        raise HTTPException(status_code=404, detail="No data file available")

    from pathlib import Path
    import io

    path = Path(ds.parquet_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Data file not found on disk")

    df = pl.read_parquet(str(path))
    buf = io.BytesIO()
    df.write_csv(buf)
    buf.seek(0)

    safe_name = ds.name.replace("/", "_").replace(" ", "_")
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )

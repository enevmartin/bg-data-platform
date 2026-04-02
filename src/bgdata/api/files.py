from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.database import get_session
from bgdata.models.data_file import DataFile, DataFileRead, FileStatus

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("", response_model=list[DataFileRead])
async def list_files(
    institution_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(DataFile)
    if institution_id is not None:
        stmt = stmt.where(DataFile.institution_id == institution_id)
    if status is not None:
        stmt = stmt.where(DataFile.status == status)
    stmt = stmt.order_by(DataFile.created_at.desc()).offset(offset).limit(limit)
    rows = await session.exec(stmt)
    return rows.all()


@router.get("/{file_id}", response_model=DataFileRead)
async def get_file(file_id: int, session: AsyncSession = Depends(get_session)):
    f = await session.get(DataFile, file_id)
    if f is None:
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.post("/process-pending")
async def process_pending_files(
    institution_id: Optional[int] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Queue process_file tasks for all DOWNLOADED files (xlsx/xls/csv only — skip pdf)."""
    from bgdata.tasks.process import process_file

    stmt = select(DataFile).where(DataFile.status == FileStatus.DOWNLOADED)
    if institution_id is not None:
        stmt = stmt.where(DataFile.institution_id == institution_id)
    files = (await session.exec(stmt)).all()

    processable_mimes = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "text/csv",
    }
    task_ids = []
    skipped = 0
    for f in files:
        if f.mime_type not in processable_mimes:
            skipped += 1
            continue
        task = process_file.delay(f.id)
        task_ids.append(task.id)

    return {"queued": len(task_ids), "skipped_pdf": skipped, "task_ids": task_ids[:20]}

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from bgdata.database import get_session
from bgdata.models.dataset import Dataset

router = APIRouter(prefix="/api/datasets", tags=["quality"])


@router.get("/{dataset_id}/quality")
async def get_quality_report(
    dataset_id: int, session: AsyncSession = Depends(get_session)
):
    ds = await session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if ds.quality_report is None:
        raise HTTPException(status_code=404, detail="Quality report not yet available")
    return ds.quality_report

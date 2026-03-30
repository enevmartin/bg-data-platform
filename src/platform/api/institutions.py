from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from platform.database import get_session
from platform.models.institution import Institution, InstitutionRead

router = APIRouter(prefix="/api/institutions", tags=["institutions"])


@router.get("", response_model=list[InstitutionRead])
async def list_institutions(session: AsyncSession = Depends(get_session)):
    rows = await session.exec(select(Institution).order_by(Institution.name))
    return rows.all()


@router.get("/{institution_id}", response_model=InstitutionRead)
async def get_institution(institution_id: int, session: AsyncSession = Depends(get_session)):
    inst = await session.get(Institution, institution_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="Institution not found")
    return inst

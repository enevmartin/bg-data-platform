from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class InstitutionBase(SQLModel):
    slug: str = Field(unique=True, index=True, max_length=64)
    name: str = Field(max_length=256)
    base_url: str = Field(max_length=512)
    description: Optional[str] = None
    is_active: bool = True


class Institution(InstitutionBase, table=True):
    __tablename__ = "institutions"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_scraped_at: Optional[datetime] = None
    total_files: int = Field(default=0)
    total_size_bytes: int = Field(default=0)


class InstitutionCreate(InstitutionBase):
    pass


class InstitutionRead(InstitutionBase):
    id: int
    created_at: datetime
    last_scraped_at: Optional[datetime]
    total_files: int
    total_size_bytes: int

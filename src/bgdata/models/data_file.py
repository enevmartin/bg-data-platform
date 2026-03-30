from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class FileStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DataFileBase(SQLModel):
    url: str = Field(max_length=2048, index=True)
    filename: str = Field(max_length=512)
    institution_id: int = Field(foreign_key="institutions.id", index=True)
    category: Optional[str] = Field(default=None, max_length=128)
    mime_type: Optional[str] = Field(default=None, max_length=128)


class DataFile(DataFileBase, table=True):
    __tablename__ = "data_files"

    id: Optional[int] = Field(default=None, primary_key=True)
    sha256_hash: Optional[str] = Field(default=None, max_length=64, index=True)
    file_size: int = Field(default=0)
    local_path: Optional[str] = Field(default=None, max_length=1024)
    status: FileStatus = Field(default=FileStatus.PENDING)
    downloaded_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    etag: Optional[str] = Field(default=None, max_length=256)
    last_modified: Optional[str] = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DataFileCreate(DataFileBase):
    pass


class DataFileRead(DataFileBase):
    id: int
    sha256_hash: Optional[str]
    file_size: int
    local_path: Optional[str]
    status: FileStatus
    downloaded_at: Optional[datetime]
    processed_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime

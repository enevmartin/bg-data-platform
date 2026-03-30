from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class DatasetStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"


class DatasetBase(SQLModel):
    name: str = Field(max_length=512)
    data_file_id: int = Field(foreign_key="data_files.id", index=True)
    institution_id: int = Field(foreign_key="institutions.id", index=True)
    sheet_name: Optional[str] = Field(default=None, max_length=256)
    row_count: int = Field(default=0)
    column_count: int = Field(default=0)


class Dataset(DatasetBase, table=True):
    __tablename__ = "datasets"

    id: Optional[int] = Field(default=None, primary_key=True)
    status: DatasetStatus = Field(default=DatasetStatus.PENDING)
    # Stored as JSON: {"col_name": "dtype_string", ...}
    column_schema: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    # Serialised QualityReport JSON
    quality_report: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    # Relative path to the processed parquet file
    parquet_path: Optional[str] = Field(default=None, max_length=1024)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    analyzed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class DatasetCreate(DatasetBase):
    pass


class DatasetRead(DatasetBase):
    id: int
    status: DatasetStatus
    column_schema: Optional[dict[str, Any]]
    quality_report: Optional[dict[str, Any]]
    parquet_path: Optional[str]
    created_at: datetime
    analyzed_at: Optional[datetime]

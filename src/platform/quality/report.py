"""
QualityReport — pydantic v2 model, fully serialisable to JSON.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class ColumnStats(BaseModel):
    name: str
    dtype: str
    total_count: int
    non_null_count: int
    missing_pct: float = Field(ge=0.0, le=100.0)
    unique_count: int
    is_numeric: bool
    # Only populated for numeric columns
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    outlier_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    sample_values: list[Any] = Field(default_factory=list)


class QualityReport(BaseModel):
    dataset_name: str
    row_count: int
    column_count: int

    # Per-column stats
    columns: list[ColumnStats] = Field(default_factory=list)

    # Aggregate metrics (0–100)
    overall_missing_pct: float = Field(ge=0.0, le=100.0)
    duplicate_row_pct: float = Field(ge=0.0, le=100.0)
    avg_outlier_pct: float = Field(ge=0.0, le=100.0)

    # Composite quality score (0–100, higher = better)
    quality_score: float = Field(ge=0.0, le=100.0)

    # Human-readable recommendations
    recommendations: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

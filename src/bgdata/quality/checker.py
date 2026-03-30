"""
DataQualityChecker — ported from data_quality/utils/metric_utils.py.

Ported logic:
  - completeness(): missing_pct per column (metric_utils.DataQualityMetrics.completeness)
  - outlier_detection(): IQR method (metric_utils.DataQualityMetrics.outlier_detection)
  - quality_score: weighted composite (completeness 40%, duplicates 30%, outliers 30%)

Works on polars DataFrames (not pandas).
Returns a QualityReport pydantic model.
"""
import logging
from typing import Any

import polars as pl

from bgdata.quality.report import ColumnStats, QualityReport

logger = logging.getLogger(__name__)

# Composite score weights (must sum to 1.0)
WEIGHT_COMPLETENESS = 0.40
WEIGHT_DUPLICATES = 0.30
WEIGHT_OUTLIERS = 0.30

# IQR multiplier for outlier bounds (standard: 1.5)
IQR_MULTIPLIER = 1.5

# Recommendation thresholds
MISSING_WARN_PCT = 5.0
MISSING_HIGH_PCT = 20.0
OUTLIER_WARN_PCT = 5.0
DUPLICATE_WARN_PCT = 1.0


class DataQualityChecker:
    """
    Analyses a polars DataFrame and produces a QualityReport.

    Usage:
        checker = DataQualityChecker()
        report = checker.check(df, dataset_name="my_dataset")
    """

    def check(self, df: pl.DataFrame, dataset_name: str = "dataset") -> QualityReport:
        if df.is_empty():
            return QualityReport(
                dataset_name=dataset_name,
                row_count=0,
                column_count=0,
                overall_missing_pct=100.0,
                duplicate_row_pct=0.0,
                avg_outlier_pct=0.0,
                quality_score=0.0,
                recommendations=["Dataset is empty."],
            )

        row_count = df.height
        col_count = df.width
        recommendations: list[str] = []

        # ── Per-column statistics ─────────────────────────────────────────────
        col_stats: list[ColumnStats] = []
        total_missing = 0
        outlier_pcts: list[float] = []

        for col_name in df.columns:
            series = df[col_name]
            non_null = series.drop_nulls()
            non_null_count = len(non_null)
            missing_count = row_count - non_null_count
            missing_pct = (missing_count / row_count) * 100.0 if row_count else 0.0
            total_missing += missing_count

            is_numeric = series.dtype in (
                pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64,
                pl.Float32, pl.Float64,
            )

            # Numeric stats + IQR outlier detection
            col_min = col_max = col_mean = col_std = outlier_pct = None
            if is_numeric and non_null_count >= 4:
                try:
                    numeric = non_null.cast(pl.Float64)
                    col_min = float(numeric.min())
                    col_max = float(numeric.max())
                    col_mean = float(numeric.mean())
                    col_std = float(numeric.std()) if non_null_count > 1 else 0.0

                    # IQR outlier detection (ported from metric_utils.outlier_detection)
                    q1 = float(numeric.quantile(0.25, interpolation="linear"))
                    q3 = float(numeric.quantile(0.75, interpolation="linear"))
                    iqr = q3 - q1
                    if iqr > 0:
                        lower = q1 - IQR_MULTIPLIER * iqr
                        upper = q3 + IQR_MULTIPLIER * iqr
                        n_outliers = int(((numeric < lower) | (numeric > upper)).sum())
                        outlier_pct = (n_outliers / non_null_count) * 100.0
                        outlier_pcts.append(outlier_pct)
                    else:
                        outlier_pct = 0.0
                        outlier_pcts.append(0.0)
                except Exception as exc:
                    logger.debug("Numeric stats failed for '%s': %s", col_name, exc)

            # Sample values (up to 5 non-null)
            try:
                samples: list[Any] = non_null.head(5).to_list()
            except Exception:
                samples = []

            stats = ColumnStats(
                name=col_name,
                dtype=str(series.dtype),
                total_count=row_count,
                non_null_count=non_null_count,
                missing_pct=round(missing_pct, 2),
                unique_count=series.n_unique(),
                is_numeric=is_numeric,
                min=round(col_min, 4) if col_min is not None else None,
                max=round(col_max, 4) if col_max is not None else None,
                mean=round(col_mean, 4) if col_mean is not None else None,
                std=round(col_std, 4) if col_std is not None else None,
                outlier_pct=round(outlier_pct, 2) if outlier_pct is not None else None,
                sample_values=samples,
            )
            col_stats.append(stats)

            # Per-column recommendations
            if missing_pct >= MISSING_HIGH_PCT:
                recommendations.append(
                    f"Column '{col_name}' has {missing_pct:.1f}% missing values — "
                    "consider imputation or dropping this column."
                )
            elif missing_pct >= MISSING_WARN_PCT:
                recommendations.append(
                    f"Column '{col_name}' has {missing_pct:.1f}% missing values."
                )

            if outlier_pct is not None and outlier_pct >= OUTLIER_WARN_PCT:
                recommendations.append(
                    f"Column '{col_name}' has {outlier_pct:.1f}% outliers (IQR method) — "
                    "verify data integrity."
                )

        # ── Aggregate metrics ─────────────────────────────────────────────────
        total_cells = row_count * col_count
        overall_missing_pct = (total_missing / total_cells * 100.0) if total_cells else 0.0

        # Duplicate rows
        try:
            n_dupes = row_count - df.unique().height
            duplicate_row_pct = (n_dupes / row_count * 100.0) if row_count else 0.0
        except Exception:
            n_dupes = 0
            duplicate_row_pct = 0.0

        avg_outlier_pct = (
            sum(outlier_pcts) / len(outlier_pcts) if outlier_pcts else 0.0
        )

        if duplicate_row_pct >= DUPLICATE_WARN_PCT:
            recommendations.append(
                f"{duplicate_row_pct:.1f}% duplicate rows detected — consider deduplication."
            )

        # ── Composite quality score (0–100, higher = better) ─────────────────
        # Ported from data_quality metric scoring pattern:
        #   completeness_score  = 100 - overall_missing_pct
        #   uniqueness_score    = 100 - duplicate_row_pct
        #   outlier_score       = 100 - avg_outlier_pct
        # Weighted sum:
        completeness_score = max(0.0, 100.0 - overall_missing_pct)
        uniqueness_score = max(0.0, 100.0 - duplicate_row_pct)
        outlier_score = max(0.0, 100.0 - avg_outlier_pct)

        quality_score = (
            WEIGHT_COMPLETENESS * completeness_score
            + WEIGHT_DUPLICATES * uniqueness_score
            + WEIGHT_OUTLIERS * outlier_score
        )

        if not recommendations:
            recommendations.append("Data quality looks good — no major issues detected.")

        return QualityReport(
            dataset_name=dataset_name,
            row_count=row_count,
            column_count=col_count,
            columns=col_stats,
            overall_missing_pct=round(overall_missing_pct, 2),
            duplicate_row_pct=round(duplicate_row_pct, 2),
            avg_outlier_pct=round(avg_outlier_pct, 2),
            quality_score=round(quality_score, 2),
            recommendations=recommendations,
        )

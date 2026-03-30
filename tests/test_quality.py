"""
Tests for DataQualityChecker — uses synthetic polars DataFrames.
"""
import polars as pl
import pytest

from platform.quality.checker import DataQualityChecker, IQR_MULTIPLIER
from platform.quality.report import QualityReport


@pytest.fixture
def checker():
    return DataQualityChecker()


# ── Basic functioning ─────────────────────────────────────────────────────────

def test_empty_df_returns_zero_score(checker):
    df = pl.DataFrame({"a": []})
    report = checker.check(df, "empty")
    assert report.quality_score == 0.0
    assert "empty" in report.recommendations[0].lower()


def test_perfect_df_scores_high(checker):
    df = pl.DataFrame({
        "id": list(range(1, 101)),
        "value": [float(i) for i in range(1, 101)],
        "label": [f"item_{i}" for i in range(1, 101)],
    })
    report = checker.check(df, "perfect")
    assert report.quality_score >= 90.0
    assert report.overall_missing_pct == 0.0
    assert report.duplicate_row_pct == 0.0


def test_missing_values_reduce_score(checker):
    import random
    random.seed(42)
    values = [float(i) if i % 3 != 0 else None for i in range(100)]
    df = pl.DataFrame({"value": values})
    report = checker.check(df, "with_missing")
    assert report.overall_missing_pct > 0
    assert report.quality_score < 100.0


def test_duplicate_rows_detected(checker):
    df = pl.DataFrame({
        "a": [1, 1, 2, 3, 4],
        "b": ["x", "x", "y", "z", "w"],
    })
    report = checker.check(df, "with_dupes")
    assert report.duplicate_row_pct > 0.0
    assert any("duplicate" in r.lower() for r in report.recommendations)


# ── IQR outlier detection ─────────────────────────────────────────────────────

def test_iqr_outlier_detection(checker):
    """The 1000.0 is a clear outlier — IQR method must flag it."""
    values = list(range(1, 101)) + [1000]  # 101 values, last is outlier
    df = pl.DataFrame({"v": [float(x) for x in values]})
    report = checker.check(df, "with_outlier")

    col = next(c for c in report.columns if c.name == "v")
    assert col.outlier_pct is not None
    assert col.outlier_pct > 0.0


def test_no_outliers_in_uniform_data(checker):
    df = pl.DataFrame({"v": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]})
    report = checker.check(df, "uniform")
    col = next(c for c in report.columns if c.name == "v")
    # IQR = 0 → no outliers
    assert col.outlier_pct == 0.0 or col.outlier_pct is None


# ── Column stats ──────────────────────────────────────────────────────────────

def test_numeric_column_stats_populated(checker):
    df = pl.DataFrame({"val": [1.0, 2.0, 3.0, 4.0, 5.0]})
    report = checker.check(df, "numeric_stats")
    col = report.columns[0]
    assert col.is_numeric
    assert col.min == 1.0
    assert col.max == 5.0
    assert col.mean == 3.0


def test_string_column_no_numeric_stats(checker):
    df = pl.DataFrame({"label": ["a", "b", "c"]})
    report = checker.check(df, "string_col")
    col = report.columns[0]
    assert not col.is_numeric
    assert col.min is None
    assert col.mean is None


def test_sample_values_populated(checker):
    df = pl.DataFrame({"x": [10, 20, 30, 40, 50, 60]})
    report = checker.check(df, "samples")
    col = report.columns[0]
    assert len(col.sample_values) <= 5
    assert len(col.sample_values) > 0


# ── QualityReport serialisation ───────────────────────────────────────────────

def test_report_serialises_to_dict(checker):
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    report = checker.check(df, "serialise_test")
    d = report.to_dict()
    assert "quality_score" in d
    assert "columns" in d
    assert isinstance(d["columns"], list)


def test_quality_score_bounded(checker):
    df = pl.DataFrame({"a": [1, 2, 3]})
    report = checker.check(df, "bounded")
    assert 0.0 <= report.quality_score <= 100.0


# ── Recommendations ───────────────────────────────────────────────────────────

def test_high_missing_generates_recommendation(checker):
    values = [None] * 30 + list(range(70))  # 30% missing
    df = pl.DataFrame({"val": values})
    report = checker.check(df, "high_missing")
    assert any("30" in r or "missing" in r.lower() for r in report.recommendations)

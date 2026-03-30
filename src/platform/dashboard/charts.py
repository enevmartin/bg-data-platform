"""
ECharts option dict helpers.
Each function returns a plain Python dict that can be JSON-serialised and
passed directly to echarts.init().setOption(option).
"""
from typing import Any

import polars as pl


def bar_chart(
    title: str,
    categories: list[str],
    series_name: str,
    values: list[float | int],
    color: str = "#5470c6",
) -> dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"rotate": 30}},
        "yAxis": {"type": "value"},
        "series": [{"name": series_name, "type": "bar", "data": values, "itemStyle": {"color": color}}],
        "grid": {"containLabel": True},
    }


def line_chart(
    title: str,
    x_data: list[str],
    series: list[dict],  # [{"name": ..., "data": [...]}]
) -> dict[str, Any]:
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"top": 30},
        "xAxis": {"type": "category", "data": x_data, "boundaryGap": False},
        "yAxis": {"type": "value"},
        "series": [
            {"name": s["name"], "type": "line", "data": s["data"], "smooth": True}
            for s in series
        ],
        "grid": {"containLabel": True, "top": 60},
    }


def gauge_chart(title: str, value: float, max_val: float = 100.0) -> dict[str, Any]:
    """Quality score gauge — colour zones: red 0-60, yellow 60-80, green 80-100."""
    return {
        "title": {"text": title, "left": "center"},
        "series": [
            {
                "type": "gauge",
                "min": 0,
                "max": max_val,
                "data": [{"value": round(value, 1), "name": "Score"}],
                "axisLine": {
                    "lineStyle": {
                        "width": 20,
                        "color": [
                            [0.6, "#ee6666"],
                            [0.8, "#fac858"],
                            [1.0, "#91cc75"],
                        ],
                    }
                },
                "pointer": {"itemStyle": {"color": "auto"}},
                "detail": {
                    "valueAnimation": True,
                    "formatter": "{value}",
                    "color": "auto",
                    "fontSize": 24,
                },
            }
        ],
    }


def distribution_chart(df: pl.DataFrame, column: str, bins: int = 20) -> dict[str, Any]:
    """Histogram-style bar chart for a numeric column."""
    try:
        series_data = df[column].drop_nulls().cast(pl.Float64)
        if series_data.is_empty():
            return {}

        mn = float(series_data.min())
        mx = float(series_data.max())
        if mn == mx:
            return bar_chart(f"Distribution: {column}", [str(mn)], column, [len(series_data)])

        step = (mx - mn) / bins
        boundaries = [mn + i * step for i in range(bins + 1)]
        labels = [f"{boundaries[i]:.2f}–{boundaries[i+1]:.2f}" for i in range(bins)]
        counts = [0] * bins
        for val in series_data.to_list():
            idx = min(int((val - mn) / step), bins - 1)
            counts[idx] += 1

        return bar_chart(f"Distribution: {column}", labels, column, counts, color="#73c0de")
    except Exception:
        return {}


def files_per_month_chart(monthly_counts: dict[str, int]) -> dict[str, Any]:
    """Bar chart: files scraped per calendar month."""
    months = sorted(monthly_counts.keys())
    counts = [monthly_counts[m] for m in months]
    return bar_chart("Files Scraped per Month", months, "Files", counts, color="#5470c6")

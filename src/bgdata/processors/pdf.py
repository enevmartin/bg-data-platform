"""
PDFProcessor — extracts tables from PDF files using pdfplumber.

pdfplumber is significantly better than PyPDF2 for structured table extraction.
Returns one polars DataFrame per extracted table (may span multiple pages).
"""
import logging
from pathlib import Path

import polars as pl

from bgdata.processors.base import BaseProcessor, snake_case

logger = logging.getLogger(__name__)


class PDFProcessor(BaseProcessor):
    supported_extensions = frozenset([".pdf"])

    def process(self, file_path: Path) -> list[pl.DataFrame]:
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed — cannot process PDF files")
            return []

        frames: list[pl.DataFrame] = []

        try:
            with pdfplumber.open(str(file_path)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()
                    if not tables:
                        continue

                    for tbl_idx, raw_table in enumerate(tables):
                        df = self._table_to_dataframe(raw_table, page_num, tbl_idx)
                        if df is not None:
                            frames.append(df)

        except Exception as exc:
            logger.error("Failed to process PDF %s: %s", file_path, exc)

        logger.debug("PDF %s → %d tables extracted", file_path.name, len(frames))
        return frames

    def _table_to_dataframe(
        self, raw_table: list[list], page_num: int, tbl_idx: int
    ) -> pl.DataFrame | None:
        if not raw_table or len(raw_table) < 2:
            return None

        # First non-empty row → headers
        header_row = raw_table[0]
        col_names: list[str] = []
        seen: dict[str, int] = {}

        for i, cell in enumerate(header_row):
            base = snake_case(str(cell)) if cell else f"col_{i}"
            cnt = seen.get(base, 0)
            seen[base] = cnt + 1
            col_names.append(f"{base}_{cnt}" if cnt else base)

        data_rows = raw_table[1:]
        col_data: dict[str, list] = {c: [] for c in col_names}

        for row in data_rows:
            padded = list(row) + [None] * max(0, len(col_names) - len(row))
            for col, val in zip(col_names, padded[: len(col_names)]):
                text = str(val).strip() if val is not None else None
                col_data[col].append(text if text else None)

        try:
            df = pl.DataFrame(col_data)
            df = df.filter(~pl.all_horizontal(pl.all().is_null()))
            return df if not df.is_empty() else None
        except Exception as exc:
            logger.warning(
                "Could not build DataFrame from PDF table p%d[%d]: %s",
                page_num,
                tbl_idx,
                exc,
            )
            return None

"""
CSVProcessor — reads CSV files with automatic encoding and delimiter detection.

Features:
  - chardet encoding detection
  - Handles BOM (UTF-8-BOM, UTF-16)
  - Delimiter sniffing (comma, semicolon, tab, pipe)
  - snake_case column renaming
"""
import csv
import io
import logging
from pathlib import Path

import chardet
import polars as pl

from platform.processors.base import BaseProcessor, snake_case

logger = logging.getLogger(__name__)

CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


def _detect_encoding(raw: bytes) -> str:
    result = chardet.detect(raw[:32_768])
    encoding = result.get("encoding") or "utf-8"
    # Normalise common aliases
    encoding = encoding.upper()
    if encoding in ("ASCII", "UTF-8-SIG"):
        return "utf-8-sig"
    if encoding.startswith("UTF-16"):
        return "utf-16"
    return encoding.lower()


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(CANDIDATE_DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        return ","


class CSVProcessor(BaseProcessor):
    supported_extensions = frozenset([".csv", ".tsv", ".txt"])

    def process(self, file_path: Path) -> list[pl.DataFrame]:
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            logger.error("Cannot read %s: %s", file_path, exc)
            return []

        encoding = _detect_encoding(raw)

        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")

        # Strip BOM
        text = text.lstrip("\ufeff")
        sample = "\n".join(text.splitlines()[:20])
        delimiter = _detect_delimiter(sample)

        try:
            df = pl.read_csv(
                io.StringIO(text),
                separator=delimiter,
                infer_schema_length=10_000,
                ignore_errors=True,
                null_values=["", "NULL", "null", "N/A", "n/a", "NA", "-", "--"],
                truncate_ragged_lines=True,
            )
        except Exception as exc:
            logger.error("polars CSV parse failed for %s: %s", file_path, exc)
            return []

        # Rename columns to snake_case
        rename_map = {c: snake_case(c) for c in df.columns}
        df = df.rename(rename_map)

        # Drop entirely-null rows
        df = df.filter(~pl.all_horizontal(pl.all().is_null()))

        if df.is_empty():
            return []

        logger.debug("CSV %s → %d rows × %d cols", file_path.name, df.height, df.width)
        return [df]

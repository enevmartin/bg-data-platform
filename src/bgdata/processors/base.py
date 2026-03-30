"""
BaseProcessor — reads a DataFile from disk, returns a polars DataFrame.
"""
import logging
import re
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


def snake_case(name: str) -> str:
    """Convert an arbitrary column header to snake_case."""
    s = str(name).strip()
    s = re.sub(r"[\s\-/\\]+", "_", s)
    s = re.sub(r"[^\w]", "", s)
    s = re.sub(r"_+", "_", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_") or "col"


class BaseProcessor:
    """
    Abstract file processor.
    Sub-classes must implement process(file_path) → list[pl.DataFrame].
    """

    supported_extensions: frozenset[str] = frozenset()

    def process(self, file_path: Path) -> list[pl.DataFrame]:
        raise NotImplementedError

    def can_handle(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.supported_extensions

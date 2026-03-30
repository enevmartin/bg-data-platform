"""
Tests for file processors — Excel, CSV, PDF.
Uses synthetic in-memory files so no external data is needed.
"""
import io
import tempfile
from pathlib import Path

import polars as pl
import pytest


# ── Excel ─────────────────────────────────────────────────────────────────────

class TestExcelProcessor:
    def _make_xlsx(self, rows: list[list]) -> Path:
        """Create a minimal xlsx file with openpyxl and return its path."""
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)

        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        wb.save(tmp.name)
        tmp.close()
        return Path(tmp.name)

    def test_basic_xlsx(self):
        from bgdata.processors.excel import ExcelProcessor

        path = self._make_xlsx([
            ["Name", "Value", "Date"],
            ["Alpha", 10, "2024-01-01"],
            ["Beta", 20, "2024-02-01"],
            ["Gamma", 30, "2024-03-01"],
        ])
        try:
            processor = ExcelProcessor()
            frames = processor.process(path)
            assert len(frames) == 1
            df = frames[0]
            assert df.height == 3
            assert "name" in df.columns
            assert "value" in df.columns
        finally:
            path.unlink(missing_ok=True)

    def test_empty_xlsx_returns_no_frames(self):
        from bgdata.processors.excel import ExcelProcessor
        import openpyxl

        wb = openpyxl.Workbook()
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        wb.save(tmp.name)
        tmp.close()
        path = Path(tmp.name)
        try:
            frames = ExcelProcessor().process(path)
            assert frames == []
        finally:
            path.unlink(missing_ok=True)

    def test_can_handle_extensions(self):
        from bgdata.processors.excel import ExcelProcessor
        p = ExcelProcessor()
        assert p.can_handle(Path("report.xlsx"))
        assert p.can_handle(Path("report.xls"))
        assert not p.can_handle(Path("report.csv"))


# ── CSV ───────────────────────────────────────────────────────────────────────

class TestCSVProcessor:
    def _write_csv(self, content: str, suffix: str = ".csv") -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False, encoding="utf-8"
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name)

    def test_comma_delimited(self):
        from bgdata.processors.csv import CSVProcessor

        path = self._write_csv("Name,Value,Category\nAlpha,10,A\nBeta,20,B\nGamma,30,C\n")
        try:
            frames = CSVProcessor().process(path)
            assert len(frames) == 1
            df = frames[0]
            assert df.height == 3
            assert "name" in df.columns
        finally:
            path.unlink(missing_ok=True)

    def test_semicolon_delimited(self):
        from bgdata.processors.csv import CSVProcessor

        path = self._write_csv("Name;Value;Category\nAlpha;10;A\nBeta;20;B\n")
        try:
            frames = CSVProcessor().process(path)
            assert len(frames) == 1
            assert frames[0].height == 2
        finally:
            path.unlink(missing_ok=True)

    def test_tab_delimited(self):
        from bgdata.processors.csv import CSVProcessor

        path = self._write_csv("Name\tValue\nAlpha\t10\nBeta\t20\n")
        try:
            frames = CSVProcessor().process(path)
            assert frames[0].height == 2
        finally:
            path.unlink(missing_ok=True)

    def test_columns_snake_cased(self):
        from bgdata.processors.csv import CSVProcessor

        path = self._write_csv("My Column,Another Value\n1,2\n")
        try:
            frames = CSVProcessor().process(path)
            cols = frames[0].columns
            assert all(" " not in c for c in cols)
        finally:
            path.unlink(missing_ok=True)

    def test_can_handle_extensions(self):
        from bgdata.processors.csv import CSVProcessor

        p = CSVProcessor()
        assert p.can_handle(Path("data.csv"))
        assert p.can_handle(Path("data.tsv"))
        assert not p.can_handle(Path("data.xlsx"))

    def test_bom_stripped(self):
        from bgdata.processors.csv import CSVProcessor

        # Write UTF-8 BOM file
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.write(b"\xef\xbb\xbfName,Value\nAlpha,10\n")
        tmp.close()
        path = Path(tmp.name)
        try:
            frames = CSVProcessor().process(path)
            assert frames[0].height == 1
            # BOM should not appear in column names
            for col in frames[0].columns:
                assert "\ufeff" not in col
        finally:
            path.unlink(missing_ok=True)


# ── PDF ───────────────────────────────────────────────────────────────────────

class TestPDFProcessor:
    def test_can_handle_pdf(self):
        from bgdata.processors.pdf import PDFProcessor

        p = PDFProcessor()
        assert p.can_handle(Path("data.pdf"))
        assert not p.can_handle(Path("data.xlsx"))

    def test_missing_file_returns_empty(self):
        from bgdata.processors.pdf import PDFProcessor

        frames = PDFProcessor().process(Path("/nonexistent/path/file.pdf"))
        assert frames == []


# ── snake_case helper ─────────────────────────────────────────────────────────

def test_snake_case():
    from bgdata.processors.base import snake_case

    assert snake_case("Hello World") == "hello_world"
    assert snake_case("CamelCase") == "camel_case"
    assert snake_case("already_snake") == "already_snake"
    assert snake_case("  spaces  ") == "spaces"
    assert snake_case("col-name/with\\slashes") == "col_name_with_slashes"
    assert snake_case("") == "col"  # fallback for empty

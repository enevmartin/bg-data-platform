"""
Tests for scraper logic.

Uses httpx mock transport to avoid real network calls.
Tests link extraction and deduplication without live sites.
"""
import hashlib
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from platform.scrapers.bnb import BNBScraper, DOWNLOAD_EXTENSIONS
from platform.scrapers.nsi import NSIScraper
from platform.scrapers.registry import REGISTRY, get_scraper_class, list_slugs


# ── Registry tests ─────────────────────────────────────────────────────────────

def test_registry_contains_bnb_and_nsi():
    assert "bnb" in REGISTRY
    assert "nsi" in REGISTRY


def test_registry_list_slugs():
    slugs = list_slugs()
    assert "bnb" in slugs
    assert "nsi" in slugs


def test_registry_get_scraper_class():
    cls = get_scraper_class("bnb")
    assert cls is BNBScraper


def test_registry_unknown_slug_raises():
    with pytest.raises(KeyError, match="No scraper registered"):
        get_scraper_class("nonexistent_institution")


# ── BNBScraper link extraction ─────────────────────────────────────────────────

def test_bnb_extract_links_finds_xlsx():
    from bs4 import BeautifulSoup

    html = """
    <html><body>
      <a href="/stats/data.xlsx">Download Excel</a>
      <a href="/stats/report.pdf">Download PDF</a>
      <a href="/about">About</a>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    scraper = BNBScraper.__new__(BNBScraper)
    scraper.cfg = MagicMock()
    scraper.base_url = "https://www.bnb.bg"

    links = scraper._extract_download_links(soup, "https://www.bnb.bg/stats/", "exchange_rates")

    urls = [l["url"] for l in links]
    assert any("data.xlsx" in u for u in urls)
    assert any("report.pdf" in u for u in urls)
    # /about is not a download link
    assert not any("about" in u for u in urls)


def test_bnb_extract_links_deduplicates():
    from bs4 import BeautifulSoup

    html = """<html><body>
      <a href="/data.xlsx">File 1</a>
      <a href="/data.xlsx">File 1 again</a>
    </body></html>"""
    soup = BeautifulSoup(html, "lxml")
    scraper = BNBScraper.__new__(BNBScraper)
    scraper.cfg = MagicMock()
    scraper.base_url = "https://www.bnb.bg"

    links = scraper._extract_download_links(soup, "https://www.bnb.bg/", "rates")
    assert len(links) == 1


def test_bnb_extract_links_empty_page():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    scraper = BNBScraper.__new__(BNBScraper)
    scraper.cfg = MagicMock()
    scraper.base_url = "https://www.bnb.bg"

    links = scraper._extract_download_links(soup, "https://www.bnb.bg/", "rates")
    assert links == []


# ── NSIScraper link extraction ─────────────────────────────────────────────────

def test_nsi_extract_links():
    from bs4 import BeautifulSoup

    html = """<html><body>
      <a href="http://nsi.bg/files/population.xls">Population data</a>
      <a href="http://nsi.bg/files/economy.xlsx">Economy</a>
      <a href="http://nsi.bg/about">About NSI</a>
    </body></html>"""
    soup = BeautifulSoup(html, "lxml")
    scraper = NSIScraper.__new__(NSIScraper)
    scraper.cfg = MagicMock()
    scraper.base_url = "https://www.nsi.bg"

    links = scraper.extract_links(soup, "https://www.nsi.bg/en/content/", "population")

    assert len(links) == 2
    assert any("population.xls" in l["url"] for l in links)
    assert any("economy.xlsx" in l["url"] for l in links)


def test_nsi_extract_links_builds_valid_filenames():
    from bs4 import BeautifulSoup

    html = """<html><body>
      <a href="/download/report 2024.xlsx">Report 2024</a>
    </body></html>"""
    soup = BeautifulSoup(html, "lxml")
    scraper = NSIScraper.__new__(NSIScraper)
    scraper.cfg = MagicMock()
    scraper.base_url = "https://www.nsi.bg"

    links = scraper.extract_links(soup, "https://www.nsi.bg/stats/", "economy")
    assert len(links) == 1
    filename = links[0]["filename"]
    # Filename should not contain spaces
    assert " " not in filename


# ── BaseScraper filename helpers ───────────────────────────────────────────────

def test_filename_from_url():
    from platform.scrapers.base import BaseScraper

    scraper = BaseScraper.__new__(BaseScraper)
    assert scraper._filename_from_url("https://example.com/data/stats_2024.xlsx") == "stats_2024.xlsx"


def test_filename_from_url_sanitises():
    from platform.scrapers.base import BaseScraper

    scraper = BaseScraper.__new__(BaseScraper)
    fn = scraper._filename_from_url("https://example.com/data/report name (1).pdf")
    assert " " not in fn
    assert "(" not in fn

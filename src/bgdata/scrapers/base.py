"""
BaseScraper — async, production-grade.

Features ported from bg-data-scrapers/scrapers/scrapers/base.py:
  - SHA-256 deduplication (skip download if hash already in DB)
  - ETag / Last-Modified cache headers
  - Streaming download for large files
  - Exponential backoff retry loop (up to max_retries, respects Retry-After)
  - Rate-limiting (configurable delay between requests)

New in this version:
  - Fully async (httpx.AsyncClient)
  - Stores DataFile record in SQLModel DB
  - Saves to data/raw/{institution}/{YYYY-MM}/{filename}
"""
import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from bgdata.config import Settings, get_settings
from bgdata.models.data_file import DataFile, FileStatus

logger = logging.getLogger(__name__)

MIME_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".json": "application/json",
    ".zip": "application/zip",
}


class ScraperResult:
    """Collected outcome of a single scrape run."""

    def __init__(self, institution_slug: str) -> None:
        self.institution_slug = institution_slug
        self.started_at: datetime = datetime.now(timezone.utc)
        self.finished_at: Optional[datetime] = None
        self.files_found: int = 0
        self.files_downloaded: int = 0
        self.files_skipped: int = 0
        self.files_failed: int = 0
        self.total_bytes: int = 0
        self.errors: list[dict] = []

    def finish(self) -> None:
        self.finished_at = datetime.now(timezone.utc)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        return {
            "institution": self.institution_slug,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": self.duration_seconds,
            "files_found": self.files_found,
            "files_downloaded": self.files_downloaded,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
            "total_bytes": self.total_bytes,
            "errors": self.errors,
        }


class BaseScraper:
    """
    Async base scraper.  Sub-classes must implement:
        - institution_slug: str  (class attribute)
        - async run(session, result) -> None
    """

    institution_slug: str = ""

    def __init__(
        self,
        institution_id: int,
        settings: Settings | None = None,
    ) -> None:
        self.institution_id = institution_id
        self.cfg = settings or get_settings()

        self._client: httpx.AsyncClient | None = None

    # ── HTTP client ──────────────────────────────────────────────────────────

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "User-Agent": self.cfg.scraper_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            timeout=httpx.Timeout(
                connect=10.0,
                read=self.cfg.scraper_request_timeout,
                write=10.0,
                pool=5.0,
            ),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "BaseScraper":
        self._client = self._build_client()
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("BaseScraper must be used as an async context manager")
        return self._client

    # ── Request with retry + backoff ─────────────────────────────────────────

    async def _request(
        self,
        url: str,
        method: str = "GET",
        stream: bool = False,
        extra_headers: dict | None = None,
    ) -> httpx.Response:
        """
        Make an HTTP request with exponential backoff retry.
        Respects Retry-After header when present.
        Raises httpx.HTTPStatusError after max_retries exhausted.
        """
        headers = extra_headers or {}
        last_exc: Exception = RuntimeError("No attempts made")

        for attempt in range(self.cfg.scraper_max_retries):
            try:
                if stream:
                    # Caller is responsible for closing the response
                    req = self.client.build_request(method, url, headers=headers)
                    response = await self.client.send(req, stream=True)
                else:
                    response = await self.client.request(method, url, headers=headers)

                response.raise_for_status()
                await asyncio.sleep(self.cfg.scraper_request_delay)
                return response

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # Respect Retry-After (e.g. 429 Too Many Requests)
                retry_after = exc.response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = self.cfg.scraper_request_delay * (2**attempt)
                else:
                    wait = self.cfg.scraper_request_delay * (2**attempt)

                if attempt < self.cfg.scraper_max_retries - 1:
                    logger.warning(
                        "Request failed (attempt %d/%d) %s — %s. Retrying in %.1fs",
                        attempt + 1,
                        self.cfg.scraper_max_retries,
                        url,
                        exc.response.status_code,
                        wait,
                    )
                    await asyncio.sleep(wait)

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                wait = self.cfg.scraper_request_delay * (2**attempt)
                if attempt < self.cfg.scraper_max_retries - 1:
                    logger.warning("Network error on %s: %s. Retrying in %.1fs", url, exc, wait)
                    await asyncio.sleep(wait)

        raise last_exc

    # ── HTML fetching ─────────────────────────────────────────────────────────

    async def fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a page and return parsed BeautifulSoup, or None on failure."""
        try:
            response = await self._request(url)
            return BeautifulSoup(response.text, "lxml")
        except Exception as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            return None

    async def fetch_soup_js(self, url: str, wait_selector: str = "body") -> Optional[BeautifulSoup]:
        """
        Fetch a JavaScript-rendered page via Playwright (headless Chromium).
        Falls back to fetch_soup() if Playwright is unavailable.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not available, falling back to static fetch for %s", url)
            return await self.fetch_soup(url)

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(
                        user_agent=self.cfg.scraper_user_agent,
                        java_script_enabled=True,
                    )
                    await page.goto(url, wait_until="networkidle", timeout=30_000)
                    await page.wait_for_selector(wait_selector, timeout=10_000)
                    html = await page.content()
                finally:
                    await browser.close()
            return BeautifulSoup(html, "lxml")
        except Exception as exc:
            logger.error("Playwright fetch failed for %s: %s — falling back to static", url, exc)
            return await self.fetch_soup(url)

    def full_url(self, base: str, path: str) -> str:
        return urljoin(base, path)

    # ── Download with deduplication ──────────────────────────────────────────

    async def download_file(
        self,
        url: str,
        db_session,  # AsyncSession — avoid circular import by not typing here
        result: ScraperResult,
        category: Optional[str] = None,
        filename_override: Optional[str] = None,
    ) -> Optional[DataFile]:
        """
        Download a file with SHA-256 deduplication and streaming support.

        Steps:
        1. HEAD request to check ETag / Last-Modified
        2. If DataFile exists with same ETag → skip (unchanged)
        3. Download with streaming (chunk-by-chunk SHA-256 calculation)
        4. If hash matches existing record → skip (unchanged content)
        5. Save to data/raw/{slug}/{YYYY-MM}/{filename}
        6. Create / update DataFile record
        """
        from sqlmodel import select

        result.files_found += 1

        # Derive filename
        filename = filename_override or self._filename_from_url(url)
        mime_type = MIME_MAP.get(Path(filename).suffix.lower(), "application/octet-stream")

        # ── Check ETag / Last-Modified first (cheap HEAD request) ─────────────
        existing: Optional[DataFile] = None
        try:
            stmt = select(DataFile).where(
                DataFile.url == url,
                DataFile.institution_id == self.institution_id,
            )
            rows = await db_session.exec(stmt)
            existing = rows.first()
        except Exception as exc:
            logger.warning("DB lookup failed for %s: %s", url, exc)

        # Try HEAD to check cache headers
        etag: Optional[str] = None
        last_modified: Optional[str] = None
        try:
            head = await self._request(url, method="HEAD")
            etag = head.headers.get("ETag")
            last_modified = head.headers.get("Last-Modified")
        except Exception:
            pass  # HEAD not supported — proceed with full download

        if existing and etag and etag == existing.etag:
            logger.info("Skipped (ETag match): %s", url)
            result.files_skipped += 1
            return existing

        # ── Streaming download ────────────────────────────────────────────────
        try:
            response = await self._request(url, stream=True)
        except Exception as exc:
            logger.error("Download failed %s: %s", url, exc)
            result.files_failed += 1
            result.errors.append({"url": url, "error": str(exc)})
            return None

        save_path = self._build_save_path(filename)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        hash_obj = hashlib.sha256()
        total_bytes = 0
        max_bytes = self.cfg.scraper_max_file_size_mb * 1024 * 1024

        try:
            with save_path.open("wb") as fh:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    hash_obj.update(chunk)
                    fh.write(chunk)
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        logger.warning("File too large, stopping: %s", url)
                        break
        finally:
            await response.aclose()

        sha256 = hash_obj.hexdigest()

        # ── SHA-256 deduplication ─────────────────────────────────────────────
        if existing and existing.sha256_hash == sha256:
            logger.info("Skipped (hash match): %s", url)
            save_path.unlink(missing_ok=True)
            result.files_skipped += 1
            return existing

        # ── Persist DataFile record ───────────────────────────────────────────
        now = datetime.utcnow()
        if existing:
            existing.sha256_hash = sha256
            existing.file_size = total_bytes
            existing.local_path = str(save_path)
            existing.mime_type = mime_type
            existing.etag = etag
            existing.last_modified = last_modified
            existing.downloaded_at = now
            existing.status = FileStatus.DOWNLOADED
            existing.error_message = None
            db_session.add(existing)
            data_file = existing
        else:
            data_file = DataFile(
                url=url,
                filename=filename,
                institution_id=self.institution_id,
                category=category,
                sha256_hash=sha256,
                file_size=total_bytes,
                local_path=str(save_path),
                mime_type=mime_type,
                etag=etag,
                last_modified=last_modified,
                downloaded_at=now,
                status=FileStatus.DOWNLOADED,
            )
            db_session.add(data_file)

        await db_session.commit()
        await db_session.refresh(data_file)

        result.files_downloaded += 1
        result.total_bytes += total_bytes
        logger.info("Downloaded %s → %s (%d bytes)", url, save_path, total_bytes)
        return data_file

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        name = os.path.basename(parsed.path)
        if not name or "." not in name:
            name = f"file_{abs(hash(url)) % 1_000_000}"
        # Sanitise
        return re.sub(r"[^\w\-_\.]", "_", name)

    def _build_save_path(self, filename: str) -> Path:
        now = datetime.now(timezone.utc)
        return (
            self.cfg.raw_data_dir
            / self.institution_slug
            / f"{now.year}-{now.month:02d}"
            / filename
        )

    # ── Abstract run ─────────────────────────────────────────────────────────

    async def run(self, db_session, result: ScraperResult) -> None:  # noqa: D102
        raise NotImplementedError

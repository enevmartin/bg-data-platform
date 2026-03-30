"""
NSIScraper — National Statistical Institute (NSI) of Bulgaria.

Target: https://www.nsi.bg/en/content/
NSI organises data by category pages. Each category page contains
<a href="...xls/xlsx/pdf/..."> download links.

Ported from bg-data-scrapers/scrapers/scrapers/nsi_scraper.py:
  - extract_links() link-extraction pattern (file extension filter)
  - extract_categories() category container traversal
  - process_category() per-category download loop
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bgdata.config import Settings, get_settings
from bgdata.scrapers.base import BaseScraper, ScraperResult

logger = logging.getLogger(__name__)

DOWNLOAD_EXTENSIONS = frozenset([".xls", ".xlsx", ".csv", ".pdf", ".doc", ".docx", ".zip"])

# Known NSI statistics sections (path relative to nsi_base_url)
NSI_SECTIONS: list[tuple[str, str]] = [
    ("population", "/en/content/2978"),
    ("economy", "/en/content/2985"),
    ("labour", "/en/content/2979"),
    ("agriculture", "/en/content/2980"),
    ("industry", "/en/content/2981"),
    ("trade", "/en/content/2982"),
    ("social", "/en/content/2983"),
    ("regional", "/en/content/2984"),
    ("environment", "/en/content/6584"),
    ("prices", "/en/content/2986"),
]


class NSIScraper(BaseScraper):
    institution_slug = "nsi"

    def __init__(self, institution_id: int, settings: Settings | None = None) -> None:
        super().__init__(institution_id, settings)
        self.base_url = self.cfg.nsi_base_url

    def extract_links(
        self, soup: BeautifulSoup, page_url: str, category: str
    ) -> list[dict]:
        """
        Extract download links from a page.
        Ported from NSIScraper.extract_links() in the original repo.
        """
        links = []
        seen: set[str] = set()

        for tag in soup.find_all("a", href=True):
            href: str = tag["href"]
            clean = href.lower().split("?")[0]

            if any(clean.endswith(ext) for ext in DOWNLOAD_EXTENSIONS):
                full_url = urljoin(page_url, href)
                if full_url in seen:
                    continue
                seen.add(full_url)

                title = tag.get_text(strip=True) or ""
                filename = re.sub(r"[^\w\-_\.]", "_", title or full_url.split("/")[-1])
                ext = "." + clean.rsplit(".", 1)[-1]
                if not filename.endswith(ext):
                    filename = filename + ext

                links.append(
                    {"url": full_url, "filename": filename, "category": category}
                )
        return links

    def extract_sub_categories(self, soup: BeautifulSoup, page_url: str) -> list[dict]:
        """
        Discover sub-category page links from a section landing page.
        NSI uses <div class="category-container"> or regular nav links.
        Ported from NSIScraper.extract_categories().
        """
        categories = []
        seen: set[str] = set()

        # Try explicit category containers first
        for elem in soup.select("div.category-container, div.views-row, li.menu-item"):
            link = elem.select_one("a[href]")
            if link is None:
                continue
            href = link["href"]
            full_url = urljoin(page_url, href)
            if full_url in seen or full_url == page_url:
                continue
            seen.add(full_url)
            title = link.get_text(strip=True) or href
            categories.append({"title": title, "url": full_url})

        return categories

    async def _scrape_section(
        self, category: str, path: str, db_session, result: ScraperResult
    ) -> None:
        page_url = urljoin(self.base_url, path)
        logger.info("[NSI] Scraping section '%s' → %s", category, page_url)

        soup = await self.fetch_soup(page_url)
        if soup is None:
            logger.warning("[NSI] Could not fetch section page: %s", page_url)
            return

        # First try direct download links on the section page
        links = self.extract_links(soup, page_url, category)

        # If no direct links, look for sub-category pages
        if not links:
            sub_cats = self.extract_sub_categories(soup, page_url)
            for sub in sub_cats[:20]:  # cap sub-category crawl
                sub_soup = await self.fetch_soup(sub["url"])
                if sub_soup:
                    links.extend(
                        self.extract_links(sub_soup, sub["url"], category)
                    )

        logger.info("[NSI] Found %d download links in '%s'", len(links), category)

        for link in links:
            await self.download_file(
                url=link["url"],
                db_session=db_session,
                result=result,
                category=link["category"],
                filename_override=link["filename"] or None,
            )

    async def run(self, db_session, result: ScraperResult) -> None:
        logger.info("[NSI] Starting scrape run")
        for category, path in NSI_SECTIONS:
            try:
                await self._scrape_section(category, path, db_session, result)
            except Exception as exc:
                logger.error("[NSI] Section '%s' failed: %s", category, exc)
                result.errors.append({"section": category, "error": str(exc)})
        logger.info("[NSI] Finished. %s", result.to_dict())

"""
BNBScraper — Bulgarian National Bank statistical data.

Target: https://www.bnb.bg/en/Statistics/
Sections scraped:
  - Exchange Rates     → /en/Statistics/StExternalSector/StExchangeRates/
  - Monetary Stats     → /en/Statistics/StMonetaryStatistics/
  - Interest Rates     → /en/Statistics/StInterestRates/
  - Banking System     → /en/Statistics/StBankSystem/
  - Balance of Payments→ /en/Statistics/StExternalSector/StBalanceOfPayments/

Link extraction: BNB serves downloadable Excel/PDF files as <a href="...xlsx"> etc.
"""
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bgdata.config import Settings, get_settings
from bgdata.scrapers.base import BaseScraper, ScraperResult

logger = logging.getLogger(__name__)

# Data sections to scrape: (category_label, path_relative_to_base_url)
# Note: BNB does not serve download links on its /en/ landing pages.
# Actual bulk files are under /Statistics/ (Bulgarian-language paths) in the
# bnb_download folder.  Each path below is a section page that contains
# <a href="/bnbweb/groups/public/documents/bnb_download/...xlsx"> links
# directly in the static HTML — no JavaScript interaction required.
BNB_SECTIONS: list[tuple[str, str]] = [
    ("monetary_statistics", "/Statistics/StMonetaryInterestRate/StMonetaryStatistics/index.htm"),
    ("interest_rates", "/Statistics/StMonetaryInterestRate/StInterestRate/StIRInterestRate/index.htm"),
    ("balance_of_payments", "/Statistics/StExternalSector/StBalancePayments/StSearchStandard/index.htm"),
    ("external_debt", "/Statistics/StExternalSector/StGrossExternalDebt/index.htm"),
    ("foreign_trade_exports", "/Statistics/StExternalSector/StForeignTrade/StFTExports/index.htm"),
    ("foreign_trade_imports", "/Statistics/StExternalSector/StForeignTrade/StFTImports/index.htm"),
    ("direct_investments_in", "/Statistics/StExternalSector/StDirectInvestments/StDIBulgaria/index.htm"),
    ("international_investment_position", "/Statistics/StExternalSector/StInternationalInvestmentPosition/index.htm"),
]

DOWNLOAD_EXTENSIONS = frozenset([".xlsx", ".xls", ".csv", ".pdf", ".zip"])


class BNBScraper(BaseScraper):
    institution_slug = "bnb"

    def __init__(self, institution_id: int, settings: Settings | None = None) -> None:
        super().__init__(institution_id, settings)
        self.base_url = self.cfg.bnb_base_url

    def _extract_download_links(
        self, soup: BeautifulSoup, page_url: str, category: str
    ) -> list[dict]:
        """
        Extract file download links from a BNB statistics page.
        BNB uses standard <a href="...xlsx"> patterns.
        Returns list of {url, filename, category}.
        """
        links = []
        seen_urls: set[str] = set()

        for tag in soup.find_all("a", href=True):
            href: str = tag["href"]
            suffix = href.lower().split("?")[0]

            if any(suffix.endswith(ext) for ext in DOWNLOAD_EXTENSIONS):
                full_url = urljoin(page_url, href)
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                filename = full_url.split("/")[-1].split("?")[0]
                links.append(
                    {"url": full_url, "filename": filename, "category": category}
                )

        return links

    async def _scrape_section(
        self, category: str, path: str, db_session, result: ScraperResult
    ) -> None:
        page_url = urljoin(self.base_url, path)
        logger.info("[BNB] Scraping section '%s' → %s", category, page_url)

        soup = await self.fetch_soup(page_url)
        if soup is None:
            logger.warning("[BNB] Could not fetch section: %s", page_url)
            return

        links = self._extract_download_links(soup, page_url, category)
        logger.info("[BNB] Found %d download links in '%s'", len(links), category)

        for link in links:
            await self.download_file(
                url=link["url"],
                db_session=db_session,
                result=result,
                category=link["category"],
                filename_override=link["filename"] or None,
            )

    async def run(self, db_session, result: ScraperResult) -> None:
        logger.info("[BNB] Starting scrape run")
        for category, path in BNB_SECTIONS:
            try:
                await self._scrape_section(category, path, db_session, result)
            except Exception as exc:
                logger.error("[BNB] Section '%s' failed: %s", category, exc)
                result.errors.append({"section": category, "error": str(exc)})
        logger.info("[BNB] Finished. %s", result.to_dict())

"""
ScraperRegistry — maps institution slug → scraper class.

To add a new scraper:
  1. Create src/platform/scrapers/my_scraper.py with a class that extends BaseScraper
  2. Set institution_slug = "my_slug" on the class
  3. Register it here: REGISTRY["my_slug"] = MyNewScraper
"""
from bgdata.scrapers.base import BaseScraper
from bgdata.scrapers.bnb import BNBScraper
from bgdata.scrapers.nsi import NSIScraper

REGISTRY: dict[str, type[BaseScraper]] = {
    BNBScraper.institution_slug: BNBScraper,
    NSIScraper.institution_slug: NSIScraper,
}


def get_scraper_class(slug: str) -> type[BaseScraper]:
    cls = REGISTRY.get(slug)
    if cls is None:
        available = ", ".join(REGISTRY.keys())
        raise KeyError(f"No scraper registered for slug '{slug}'. Available: {available}")
    return cls


def list_slugs() -> list[str]:
    return list(REGISTRY.keys())

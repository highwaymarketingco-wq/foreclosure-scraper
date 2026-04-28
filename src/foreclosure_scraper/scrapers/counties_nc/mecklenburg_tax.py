"""Mecklenburg County (NC) tax foreclosure sales — Kania Law Firm runs the calendar."""
from __future__ import annotations

from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ..law_firms._helpers import parse_blocks

URLS = (
    "https://www.kanialawfirm.com/tax-foreclosure-sales/",
    "https://www.kanialawfirm.com/upcoming-sales/",
    "https://taxforeclosures.kanialawfirm.com/",
)


class MecklenburgTaxForeclosures(BaseScraper):
    slug = "counties_nc.mecklenburg_tax"
    name = "Mecklenburg County (NC) Tax Foreclosure (Kania Law)"
    category = "county_tax"
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url in URLS:
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            tree = HTMLParser(html)
            text = tree.body.text(separator="\n") if tree.body else ""
            for li in parse_blocks(text, source_slug=self.slug, source_url=url):
                # All Kania listings default to NC; county is best-effort from text
                if not li.state:
                    li.state = "NC"
                out.append(li)
        return out

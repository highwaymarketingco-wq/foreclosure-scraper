"""Buncombe County (NC) tax foreclosure sales."""
from __future__ import annotations

from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ..law_firms._helpers import parse_blocks

URLS = (
    "https://www.buncombecounty.org/governing/depts/tax/foreclosure.aspx",
    "https://www.buncombecounty.org/governing/depts/tax/foreclosed-properties.aspx",
)


class BuncombeTax(BaseScraper):
    slug = "counties_nc.buncombe_tax"
    name = "Buncombe County (NC) Tax Foreclosures"
    category = "county_tax"
    timeout_s = 180.0

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
                if not li.state:
                    li.state = "NC"
                if not li.county:
                    li.county = "Buncombe"
                out.append(li)
        return out

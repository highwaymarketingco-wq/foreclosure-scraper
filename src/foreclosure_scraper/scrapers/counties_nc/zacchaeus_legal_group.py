"""Zacchaeus Legal Group — handles tax foreclosures for several NC counties."""
from __future__ import annotations

from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ..law_firms._helpers import parse_blocks

URLS = (
    "https://www.zacchaeuslegalgroup.com/upcoming-sales/",
    "https://www.zacchaeuslegalgroup.com/tax-foreclosure-sales/",
)


class ZacchaeusLegalGroup(BaseScraper):
    slug = "counties_nc.zacchaeus_legal_group"
    name = "Zacchaeus Legal Group (NC tax foreclosures)"
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
                out.append(li)
        return out

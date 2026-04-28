"""Rogers Townsend — major SC + NC substitute trustee."""
from __future__ import annotations

from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._helpers import parse_blocks

START_URLS = (
    "https://www.rogerstownsend.com/foreclosure-sales-sc/",
    "https://www.rogerstownsend.com/foreclosure-sales-nc/",
    "https://www.rogerstownsend.com/foreclosure-listings/",
)


class RogersTownsend(BaseScraper):
    slug = "law_firms.rogers_townsend"
    name = "Rogers Townsend"
    category = "law_firm"
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for url in START_URLS:
            try:
                html = await get_text(url, timeout=45.0)
            except Exception:
                continue
            tree = HTMLParser(html)
            text = tree.body.text(separator="\n") if tree.body else ""
            out.extend(parse_blocks(text, source_slug=self.slug, source_url=url))
        return out

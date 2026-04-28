"""Shapiro & Ingle (a.k.a. logs.com) — single largest substitute trustee in the Carolinas."""
from __future__ import annotations

from typing import Iterable

from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing
from ._helpers import parse_blocks

START_URLS = (
    "https://www.logs.com/sales-info/north-carolina",
    "https://www.logs.com/sales-info/south-carolina",
    "https://www.logs.com/sales-info/north-carolina-foreclosures",
    "https://www.logs.com/sales-info/south-carolina-foreclosures",
)


class ShapiroIngle(BaseScraper):
    slug = "law_firms.shapiro_ingle"
    name = "Shapiro & Ingle (logs.com)"
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

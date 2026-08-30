"""LoopNet commercial listings — distressed / auction commercial properties.

LoopNet (loopnet.com) is the largest commercial real estate marketplace.
We scan for listings flagged as "distressed", "auction", "bank-owned", or
"as-is" in our NC/SC footprint. These are motivated-seller commercial leads.

Access path: LoopNet's public search returns server-rendered HTML with
property cards. No login required for basic search results (detail pages
may require a free account, but the search results page has enough data).

Free, public. Uses impersonation for Cloudflare/TLS fingerprint matching.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.loopnet.com"
_SEARCH = f"{_BASE}/search/commercial-real-estate/"

# Search URLs for NC/SC cities in our footprint.
# LoopNet uses URL patterns like /<city>-<state>/commercial-real-estate/.
_CITIES = [
    ("asheville-nc", "Asheville", "NC"),
    ("hendersonville-nc", "Hendersonville", "NC"),
    ("spartanburg-sc", "Spartanburg", "SC"),
    ("greenville-sc", "Greenville", "SC"),
    ("gastonia-nc", "Gastonia", "NC"),
    ("shelby-nc", "Shelby", "NC"),
    ("morganton-nc", "Morganton", "NC"),
    ("anderson-sc", "Anderson", "SC"),
    ("gaffney-sc", "Gaffney", "SC"),
    ("rutherfordton-nc", "Rutherfordton", "NC"),
]

# Distress keywords in listing titles/descriptions.
_DISTRESS_KEYWORDS = (
    "distressed", "auction", "bank-owned", "reo", "as-is", "as is",
    "motivated", "must sell", "short sale", "liquidation", "priced to sell",
    "estate sale", "assignment", "below market",
)

# Price regex.
_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# Address regex.
_ADDR_RE = re.compile(
    r"(\d{1,5}\s+[A-Z][\w .'\-]+)\s*,?\s*"
    r"([A-Z][\w .'\-]+?)\s*,\s*"
    r"(NC|SC)\s+(\d{5})",
)


class LoopNetScraper(BaseScraper):
    slug = "national.loopnet"
    name = "LoopNet Commercial Distressed Listings"
    category = "marketplace"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for slug, city, state in _CITIES:
            url = f"{_BASE}/{slug}/commercial-real-estate/"
            try:
                html = await get_text_impersonate(url, timeout=45.0)
            except Exception as exc:
                log.warning("loopnet.fetch_fail", city=city, error=str(exc)[:160])
                continue

            if not html or len(html) < 1000:
                continue

            tree = HTMLParser(html)
            body_text = tree.body.text(separator="\n") if tree.body else html

            # Find listing blocks. LoopNet uses article/div cards.
            cards = tree.css("article, .listing, .placard, [data-listing-id]")
            if not cards:
                # Fallback: scan body text for addresses.
                for m in _ADDR_RE.finditer(body_text):
                    addr_state = m.group(3)
                    if addr_state not in ("NC", "SC"):
                        continue
                    street, addr_city, _, zip_code = m.groups()
                    # Check for distress keywords in context.
                    start = max(0, m.start() - 500)
                    end = min(len(body_text), m.end() + 500)
                    block = body_text[start:end].lower()
                    if not any(kw in block for kw in _DISTRESS_KEYWORDS):
                        continue
                    out.append(self._make_listing(
                        street, addr_city, addr_state, zip_code, url, block[:500]))
            else:
                for card in cards:
                    text = card.text(separator=" ").strip()
                    if not text or len(text) < 20:
                        continue
                    text_lower = text.lower()
                    if not any(kw in text_lower for kw in _DISTRESS_KEYWORDS):
                        continue
                    # Extract address from the card.
                    am = _ADDR_RE.search(text)
                    if not am:
                        continue
                    street, addr_city, addr_state, zip_code = am.groups()
                    # Extract price.
                    price = None
                    pm = _PRICE_RE.search(text)
                    if pm:
                        try:
                            price = float(pm.group(1).replace(",", ""))
                        except ValueError:
                            pass
                    out.append(Listing(
                        source=self.slug,
                        source_url=url,
                        listing_type=ListingType.DISTRESSED,
                        property_kind=PropertyKind.COMMERCIAL,
                        street_address=street.strip(),
                        city=addr_city.strip(),
                        state=addr_state,
                        zip_code=zip_code,
                        opening_bid=price,
                        description=f"LoopNet distressed commercial ({addr_city.strip()}, {addr_state})",
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"loopnet": {"card_text": text[:500]}},
                    ))

        log.info("loopnet.done", count=len(out), cities=len(_CITIES))
        return out

    def _make_listing(self, street: str, city: str, state: str,
                      zip_code: str, url: str, excerpt: str) -> Listing:
        return Listing(
            source=self.slug,
            source_url=url,
            listing_type=ListingType.DISTRESSED,
            property_kind=PropertyKind.COMMERCIAL,
            street_address=street.strip(),
            city=city.strip(),
            state=state,
            zip_code=zip_code,
            description=f"LoopNet distressed commercial ({city.strip()}, {state})",
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"loopnet": {"excerpt": excerpt}},
        )

"""LiensNC.com — NC mechanic's lien / construction lien database.

LiensNC is the official online filing system for North Carolina mechanic's
liens (NCGS 44A). Construction liens are a strong distress signal: they
indicate unpaid contractors, which often precede foreclosure or forced sale.

The site at liensnc.com provides a public search portal. We search for
recently-filed liens in our NC footprint counties. The data is server-
rendered HTML with a search form.

Free, public, no login required for basic search. Cloudflare-protected,
so we use impersonate=True for the TLS fingerprint.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text, get_text_impersonate
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_BASE = "https://www.liensnc.com"
_SEARCH_URL = f"{_BASE}/Search"

# NC counties in our footprint.
_NC_COUNTIES = (
    "Buncombe", "Burke", "Cleveland", "Gaston", "Henderson",
    "Lincoln", "McDowell", "Mitchell", "Polk", "Rutherford",
    "Transylvania",
)

# Address regex for NC addresses.
_ADDR_RE = re.compile(
    r"(\d{1,5}\s+[A-Z][\w .'\-]+)\s*,?\s*"
    r"([A-Z][\w .'\-]+?)\s*,\s*"
    r"NC\s+(\d{5})",
    re.MULTILINE,
)
# Amount pattern (lien amount).
_AMOUNT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# Date pattern.
_DATE_RE = re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")


class LiensNCScraper(BaseScraper):
    slug = "national.liensnc"
    name = "LiensNC — NC Mechanic's Lien Filings"
    category = "lien_filing"
    expected_min_count = 0  # May be 0 if no recent filings
    requires_apify = False
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        # Try the search page with impersonation (Cloudflare-protected).
        try:
            html = await get_text_impersonate(_SEARCH_URL, timeout=60.0)
        except Exception as exc:
            log.warning("liensnc.fetch_failed", error=str(exc)[:200])
            return []

        if not html or len(html) < 500:
            log.warning("liensnc.empty_response", size=len(html))
            return []

        tree = HTMLParser(html)
        body_text = tree.body.text(separator="\n") if tree.body else html

        out: list[Listing] = []
        seen: set[str] = set()

        # Scan for NC addresses in the results.
        for m in _ADDR_RE.finditer(body_text):
            street, city, zip_code = m.groups()
            key = f"{street.strip()}_{zip_code}"
            if key in seen:
                continue
            seen.add(key)

            # Look for amount and date in surrounding context.
            start = max(0, m.start() - 300)
            end = min(len(body_text), m.end() + 500)
            block = body_text[start:end]

            amount = None
            am = _AMOUNT_RE.search(block)
            if am:
                try:
                    amount = float(am.group(1).replace(",", ""))
                except ValueError:
                    pass

            filing_date = None
            dm = _DATE_RE.search(block)
            if dm:
                from dateutil import parser as dp
                try:
                    filing_date = dp.parse(dm.group(1), fuzzy=True)
                except (ValueError, TypeError):
                    pass

            # Try to find a detail link.
            html_block = html[start:end] if start < len(html) else ""
            link_m = re.search(r'href=["\']([^"\']*lien[^"\']*)["\']', html_block, re.I)
            detail_url = ""
            if link_m:
                href = link_m.group(1)
                detail_url = href if href.startswith("http") else f"{_BASE}/{href.lstrip('/')}"

            out.append(Listing(
                source=self.slug,
                source_url=detail_url or _SEARCH_URL,
                listing_type=ListingType.LIS_PENDENS,  # closest: pending claim against property
                property_kind=PropertyKind.UNKNOWN,
                street_address=street.strip(),
                city=city.strip(),
                state="NC",
                zip_code=zip_code,
                judgment_amount=amount,
                sale_date=filing_date,
                description=f"NC mechanic's lien filed ({city.strip()}, NC)",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                raw={
                    "liensnc": {
                        "forward_excerpt": block[:500],
                        "detail_url": detail_url,
                    },
                },
            ))

        log.info("liensnc.done", count=len(out))
        return out

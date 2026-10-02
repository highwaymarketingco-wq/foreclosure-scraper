"""VA Acquired Properties — Department of Veterans Affairs REO inventory.

The VA sells acquired properties (foreclosed VA-guaranteed loans) through
its Property Management Service. Listings are available at:

  https://www.va.gov/va-forms/real-property/properties/

Each listing includes: address, city, state, ZIP, price, beds/baths/sqft,
property type, and listing agent contact.

Free, public, no login.
Slug: national.va_acquired
Category: reo
ListingType: REO

DISABLED 2026-10-01 (national/reo per-source audit): confirmed live, BOTH
candidate URLs are dead, and the one the code actually fetches is the more
dangerous kind of dead -- a silent fake-404:
  * VA_URL (the one this docstring names as the real source,
    va.gov/va-forms/real-property/properties/) returns a genuine HTTP 404.
    The code never even fetches it.
  * BANK_REO_URL (the one fetch() actually requests) returns HTTP 200 but
    the body is VA's own generic site-wide 404 template
    (<meta name="dcterms.subject" content="Page Not Found" />,
    dcterms.dateAccepted 2025-04-16) -- a 200-status page that IS a 404,
    exactly the "silent success" shape CLAUDE.md warns about. The regex
    <tr> scanner below "cleanly" finds 0 matching rows on this error page,
    which looks identical to a legitimate empty search in the logs
    (OUTCOME_ZERO either way).
Also redundant: reo.vrm_va_reo (VRM Properties, the VA's current REO
servicing vendor) already covers this exact signal via a live, working
path -- confirmed live the same day, 193 real NC+SC rows with photos and
prices. Disabled rather than chasing a new URL for a signal the board
already has, same reasoning as national.epa_superfund's redundant-source
disable earlier this audit.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

VA_URL = "https://www.va.gov/va-forms/real-property/properties/"
BANK_REO_URL = "https://www.benefits.va.gov/homeloans/property/property.asp"


class VAAcquired(BaseScraper):
    slug = "national.va_acquired"
    name = "VA Acquired Properties"
    category = "reo"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True
    disabled = True
    disabled_reason = (
        "both candidate URLs confirmed dead 2026-10-01 (VA_URL is a genuine "
        "404; BANK_REO_URL returns HTTP 200 but the body is VA's own "
        "site-wide 404 template) and redundant with reo.vrm_va_reo, which "
        "already covers VA REO via a live, working path (193 real NC+SC "
        "rows confirmed the same day)"
    )

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(BANK_REO_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("va_acquired.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 500:
            return out

        # VA property pages typically list properties in HTML tables
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 3:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if not any(re.search(r"\d", c) for c in clean):
                continue
            if any(h in c.lower() for c in clean[:2] for h in ("header", "title", "property #")):
                continue

            addr = None
            city = None
            state = None
            price = None

            for c in clean:
                m = re.search(r"\b(NC|SC)\b", c)
                if m and not state:
                    state = m.group(1)
                m = re.search(r"\$([\d,]+)", c)
                if m and not price:
                    price = float(m.group(1).replace(",", ""))
                if re.search(r"\b\d+\s+\w+", c) and any(
                    s in c.lower() for s in ("st", "ave", "rd", "dr", "ln", "ct", "blvd", "hwy", "way")
                ):
                    if not addr:
                        addr = c

            if not state or state not in ("NC", "SC"):
                continue

            raw = {
                "source_url": BANK_REO_URL,
                "price": price,
            }
            out.append(
                Listing(
                    source=self.slug,
                    source_url=BANK_REO_URL,
                    listing_type=ListingType.REO,
                    street_address=addr,
                    state=state,
                    property_kind=PropertyKind.UNKNOWN,
                    opening_bid=price,
                    raw=raw,
                )
            )

        log.info("va_acquired.fetch_done", count=len(out))
        return out

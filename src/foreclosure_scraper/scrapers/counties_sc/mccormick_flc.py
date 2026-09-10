"""McCormick County SC - Forfeited Land Commission (FLC) properties.

McCormick County's FLC page lists available forfeited land commission
properties - properties the county acquired through tax delinquency
proceedings. These are county-owned properties available for purchase.

Free, public, no login.
Slug: counties_sc.mccormick_flc
Category: county_tax
ListingType: TAX_SALE
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

PAGE_URL = "https://www.mccormickcountysc.org/departments/treasurer.php"

# Street suffixes shared by the address regexes below.
_SUFFIX = r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Boulevard|Blvd|Highway|Hwy|Way|Circle|Cir|Trail|Trl|Parkway|Pkwy|Terrace|Ter)"


def _norm_addr(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _county_own_addresses(html: str) -> set[str]:
    """Addresses belonging to McCormick County ITSELF, which must never be
    emitted as property leads.

    Verified 2026-09-10: the treasurer page contains no FLC list at all - zero
    "forfeited"/"FLC" mentions, zero PDF links - and states the sale list is
    advertised in The McCormick Messenger (print only). So the address regex in
    fetch() only ever matched the page chrome: the Treasurer's office
    ("Location: 133 South Mine Street ... Room 104") and the site-footer contact
    block ("610 South Mine Street"). Those two rows were the source's entire
    output. They are parsed out here (dynamically, so a template reword still
    catches them, with the two observed values as a fallback) because emitting
    them would publish the courthouse as a distressed property the moment this
    slug is added to DATELESS_OK_SOURCES.
    """
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or ""))
    own = {_norm_addr("133 South Mine Street"), _norm_addr("610 South Mine Street")}
    for m in re.finditer(
        rf"(?:Location|Mailing Address|Address)\s*:?\s*(\d+\s+[A-Za-z0-9.\s]{{3,40}}?{_SUFFIX})\b",
        text, re.I,
    ):
        own.add(_norm_addr(m.group(1)))
    # Footer contact block: the address that precedes the county's own email.
    for m in re.finditer(
        rf"(\d+\s+[A-Za-z0-9.\s]{{3,40}}?{_SUFFIX})\b[^@]{{0,160}}@mccormickcountysc\.org",
        text, re.I,
    ):
        own.add(_norm_addr(m.group(1)))
    return own


def _is_county_own(candidate: str, own: set[str]) -> bool:
    norm = _norm_addr(candidate)
    return any(norm == o or norm.startswith(o + " ") for o in own if o)


class McCormickFLC(BaseScraper):
    slug = "counties_sc.mccormick_flc"
    name = "McCormick County SC Forfeited Land Commission"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("mccormick_flc.fetch_fail", error=str(exc)[:160])
            return out

        if not html:
            return out

        # Find PDF links to property lists
        pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)
        # Find TMS/parcel numbers and addresses in the HTML
        parcels = re.findall(r"(?:TMS|PIN|Parcel)\s*:?\s*([\d\-\.]+)", html, re.I)
        addresses = re.findall(
            r"\b(\d+\s+[A-Za-z0-9\s]+(?:St|Ave|Rd|Dr|Ln|Ct|Blvd|Hwy|Way|Cir|Trl|Pkwy|Ter)[A-Za-z\s]*)",
            html,
        )

        own = _county_own_addresses(html)
        addresses = [a for a in addresses if not _is_county_own(a, own)]

        if not parcels and not addresses:
            # Try table parsing
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
            for row in rows:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
                if len(cells) < 2:
                    continue
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                if not any(re.search(r"\d", c) for c in clean):
                    continue
                parcel = None
                for c in clean:
                    m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
                    if m:
                        parcel = m.group(1)
                        break
                addr_cell = None
                for c in clean[1:]:
                    m = re.search(rf"\d+\s+[A-Za-z0-9.\s]{{3,60}}?{_SUFFIX}\b", c, re.I)
                    if m and not _is_county_own(m.group(0), own):
                        addr_cell = m.group(0).strip()
                        break
                if not parcel and not addr_cell:
                    # Revize layout / department-info table, not a property list.
                    # (This page's single <tr> is the Treasurer's contact block.)
                    continue
                out.append(Listing(
                    source="counties_sc.mccormick_flc",
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="McCormick",
                    parcel_id=parcel,
                    defendant=clean[0] if clean else None,
                    street_address=addr_cell,
                    description=" | ".join(clean[:6]),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"mccormick_flc": {"cells": clean[:10], "pdf_links": pdf_links[:3]}},
                ))
        else:
            max_items = max(len(parcels), len(addresses), 1)
            for i in range(max_items):
                parcel = parcels[i] if i < len(parcels) else None
                addr = addresses[i].strip() if i < len(addresses) else None
                out.append(Listing(
                    source="counties_sc.mccormick_flc",
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="McCormick",
                    parcel_id=parcel,
                    street_address=addr,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"mccormick_flc": {"pdf_links": pdf_links[:3]}},
                ))

        log.info("mccormick_flc.done", count=len(out))
        return out

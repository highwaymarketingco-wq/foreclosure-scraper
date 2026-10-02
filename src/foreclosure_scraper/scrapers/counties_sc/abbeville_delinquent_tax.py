"""Abbeville County SC — Delinquent Tax Collector properties.

Abbeville County's delinquent tax page at abbevillecountysc.com lists
properties with delinquent taxes. Tax sale is held the first Monday in
November. The page references an online delinquent tax search (free to view).

Free, public, no login. WordPress/CivicPlus site.

DISABLED 2026-10-01: confirmed live this page carries no delinquent-property
table at all -- it is an office-contact + FAQ page ("Properties classified as
delinquent will be advertised in The Press & Banner for three consecutive
weeks prior to the tax sale") with a link out to the county's "Online Taxes"
search portal, never a bulk list. That portal IS the SAME treasurer system
counties_sc.qpaybill_delinquent_roll.py already sweeps for Abbeville
(QPAYBILL_SUBS["Abbeville"] = "abbevilletreasurer", verified live since
2026-09-10) -- with owner, situs, balance and years-delinquent, which this
page structurally could never produce. Found via the 2026-10-01 counties_sc
per-source extraction audit. Do not re-enable without a different, real
per-parcel source at this URL.

Slug: counties_sc.abbeville_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

PAGE_URL = "https://abbevillecountysc.com/delinquent-tax-collector/"


class AbbevilleDelinquentTax(BaseScraper):
    slug = "counties_sc.abbeville_delinquent_tax"
    name = "Abbeville County SC Delinquent Tax"
    disabled = True
    disabled_reason = ("target page has no delinquent-property list (office/FAQ page only) - "
                       "superseded by counties_sc.qpaybill_delinquent_roll (Abbeville) - confirmed 2026-10-01")
    category = "county_tax"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(PAGE_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("abbeville_tax.fetch_fail", error=str(exc)[:160])
            return out

        if not html or len(html) < 200:
            return out

        # Parse tables and list items for property data
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S)
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.I | re.S)
            if len(cells) < 2:
                continue
            clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
            if any(h in c.lower() for c in clean[:2] for h in ("owner", "name", "tms", "map", "#")):
                continue
            if not any(re.search(r"\d", c) for c in clean):
                continue

            parcel = None
            for c in clean:
                m = re.search(r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]+)\b", c)
                if m:
                    parcel = m.group(1).strip()
                    break
                m = re.search(r"\b(\d{8,})\b", c)
                if m and not parcel:
                    parcel = m.group(1)

            owner = clean[0] if clean else None
            addr = None
            for c in clean[1:]:
                if re.search(r"\b\d+\s+\w+", c) and any(
                    s in c.lower() for s in ("st", "ave", "rd", "dr", "ln", "ct", "blvd", "hwy", "way")
                ):
                    addr = c
                    break

            raw = {
                "owner": owner,
                "parcel": parcel,
                "source_url": PAGE_URL,
            }
            out.append(
                Listing(
                    source=self.slug,
                    source_url=PAGE_URL,
                    listing_type=ListingType.TAX_SALE,
                    street_address=addr,
                    county="Abbeville",
                    state="SC",
                    parcel_id=parcel,
                    owner_name=owner,
                    property_kind=PropertyKind.UNKNOWN,
                    raw=raw,
                )
            )

        log.info("abbeville_tax.fetch_done", count=len(out))
        return out

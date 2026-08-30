"""Lexington County SC — Forfeited Land Commission (FLC) properties.

Lexington County's FLC page at lex-co.sc.gov lists available forfeited land
commission properties — properties the county acquired through tax delinquency
proceedings. The page links to a PDF property list and an offer form.

Also captures surplus property auctions from the Central Stores page.

Free, public, no login. JS-rendered Drupal site — may need impersonate=True.
Slug: counties_sc.lexington_flc
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

FLC_URL = "https://lex-co.sc.gov/treasurer/forfeited-land-commission"
AUCTION_URL = "https://lex-co.sc.gov/central-stores-auction-items"
BASE = "https://lex-co.sc.gov"


class LexingtonFLC(BaseScraper):
    slug = "counties_sc.lexington_flc"
    name = "Lexington County SC Forfeited Land Commission"
    category = "county_tax"
    timeout_s = 90.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        try:
            html = await get_text(FLC_URL, impersonate=True, timeout=30.0)
        except Exception as exc:
            log.warning("lex_flc.fetch_fail", error=str(exc)[:160])
            return out

        if not html:
            return out

        # Find PDF links to property lists
        pdf_links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)
        # Find property entries — Drupal renders as paragraphs or list items
        # with TMS numbers, addresses, owner names
        parcels = re.findall(r"(?:TMS|PIN|Parcel)\s*:?\s*([\d\-\.]+)", html, re.I)
        addresses = re.findall(
            r"\b(\d+\s+[A-Za-z0-9\s]+(?:St|Ave|Rd|Dr|Ln|Ct|Blvd|Hwy|Way|Cir|Trl|Pkwy|Ter)[A-Za-z\s]*)",
            html,
            re.I,
        )

        # If we found TMS parcels, create listings
        for i, parcel in enumerate(parcels):
            addr = addresses[i] if i < len(addresses) else None
            raw = {
                "tms": parcel,
                "source_url": FLC_URL,
                "flc": True,
            }
            out.append(
                Listing(
                    source=self.slug,
                    source_url=FLC_URL,
                    listing_type=ListingType.TAX_SALE,
                    street_address=addr.strip() if addr else None,
                    county="Lexington",
                    state="SC",
                    parcel_id=parcel,
                    property_kind=PropertyKind.UNKNOWN,
                    raw=raw,
                )
            )

        # Also check the Central Stores auction page for surplus property
        try:
            html2 = await get_text(AUCTION_URL, impersonate=True, timeout=30.0)
            if html2:
                auction_parcels = re.findall(
                    r"(?:TMS|PIN|Parcel)\s*:?\s*([\d\-\.]+)", html2, re.I
                )
                for parcel in auction_parcels:
                    if parcel not in parcels:
                        out.append(
                            Listing(
                                source=self.slug,
                                source_url=AUCTION_URL,
                                listing_type=ListingType.AUCTION,
                                county="Lexington",
                                state="SC",
                                parcel_id=parcel,
                                property_kind=PropertyKind.UNKNOWN,
                                raw={"surplus_auction": True, "source_url": AUCTION_URL},
                            )
                        )
        except Exception as exc:
            log.debug("lex_flc.auction_fail", error=str(exc)[:120])

        log.info("lex_flc.fetch_done", count=len(out))
        return out

"""York County SC — Tax Sale Properties via ArcGIS REST API.

York County publishes tax sale properties through an ArcGIS Experience Builder
dashboard backed by a public FeatureServer. This scraper queries the FeatureServer
API directly, getting all 850+ properties with full attribute data (owner,
parcel, address, assessed value, legal description, etc.) in a single request.

Free, public, no login, no CAPTCHA — the ArcGIS REST API is open.

Slug: counties_sc.york_delinquent_tax
Category: county_tax
ListingType: TAX_SALE
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# ArcGIS FeatureServer for York County Tax Sale Properties 2025
# Discovered from the Experience Builder app config:
#   https://experience.arcgis.com/experience/ef9243d9330c4891ba724689f2eb1502
FS_URL = (
    "https://services1.arcgis.com/2AGLxyiJoNiVHKwq"
    "/arcgis/rest/services/Tax_Sale_Properties_2025_View/FeatureServer/0"
)


class YorkDelinquentTax(BaseScraper):
    slug = "counties_sc.york_delinquent_tax"
    name = "York County SC Delinquent Tax Collection"
    category = "county_tax"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True
    active_months = (10, 11, 12, 1)

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        now = datetime.utcnow()

        # Query all records from the FeatureServer
        # maxRecordCount is 2000, total is ~853, so one batch suffices
        all_features: list[dict] = []
        offset = 0
        page_size = 2000

        with httpx.Client(timeout=60.0) as client:
            while True:
                params = {
                    "where": "1=1",
                    "outFields": "*",
                    "returnGeometry": "false",
                    "f": "json",
                    "resultRecordCount": page_size,
                    "resultOffset": offset,
                    "orderByFields": "OBJECTID",
                }
                r = client.get(f"{FS_URL}/query", params=params)
                if r.status_code != 200:
                    log.warning(
                        "york_tax.arcgis_http_fail",
                        status=r.status_code,
                        body=r.text[:200],
                    )
                    return out

                data = r.json()
                features = data.get("features", [])
                if not features:
                    break

                all_features.extend(features)
                log.info(
                    "york_tax.arcgis_page",
                    offset=offset,
                    page_count=len(features),
                    total_so_far=len(all_features),
                )

                # Check if there are more records
                if not data.get("exceededTransferLimit"):
                    break
                offset += len(features)
                if offset >= 10000:  # safety cap
                    break

        log.info("york_tax.arcgis_total", count=len(all_features))

        skipped_no_parcel = 0
        for feat in all_features:
            attrs = feat.get("attributes", {})

            # Build owner name from Owner1/Owner2/Owner3
            owner_parts = [
                attrs.get("Owner1", ""),
                attrs.get("Owner2", ""),
                attrs.get("Owner3", ""),
            ]
            owner = " ".join(p for p in owner_parts if p and p.strip()).strip()
            if not owner:
                owner = attrs.get("NAME", "") or attrs.get("ownernames", "") or None

            parcel_id = attrs.get("ParcelID") or attrs.get("TAXMAPID") or None
            if not parcel_id:
                # A tax-sale row with no parcel/TMS cannot be underwritten, joined to
                # the assessor, or routed to a county -- the same rationale the
                # shared _sc_tax_table.is_usable_row() gate uses for this parser's
                # HTML-table-parsing siblings (darlington/fairfield/saluda/lancaster/
                # newberry). This scraper reads ArcGIS attributes rather than parsed
                # table cells, so there's no row text for is_usable_row to check --
                # but "no parcel" is the one part of that gate that still applies
                # directly, and skipping here keeps an unroutable row from ever
                # becoming a Listing instead of relying on a downstream filter.
                skipped_no_parcel += 1
                continue
            address = attrs.get("PropertyAddress") or attrs.get("fulladdress") or None
            if address:
                address = address.strip()

            # Assessed value
            assessed_val = attrs.get("AprTotVal") or attrs.get("TaxTotVal") or None

            # Sale price (last sale, not tax sale opening bid)
            sale_price = attrs.get("SalePrice") or None

            # Legal description
            legal = attrs.get("LegalDescription") or ""
            land_use = attrs.get("LandUseDesc") or ""

            # Build description
            desc_parts = []
            if legal:
                desc_parts.append(f"Legal: {legal.strip()}")
            if land_use:
                desc_parts.append(f"Land use: {land_use.strip()}")
            if attrs.get("Subdivision"):
                desc_parts.append(f"Subdivision: {attrs['Subdivision']}")
            if attrs.get("deededacres"):
                desc_parts.append(f"Acres: {attrs['deededacres']}")
            if attrs.get("FinishedSQFT"):
                desc_parts.append(f"SqFt: {attrs['FinishedSQFT']}")
            if attrs.get("YearBuilt"):
                desc_parts.append(f"Year built: {attrs['YearBuilt']}")
            description = " | ".join(desc_parts) if desc_parts else None

            # GIS report URL
            gis_url = attrs.get("URL") or None

            # Mail address (for skip tracing)
            mail_addr = None
            mail_parts = [
                attrs.get("MailAddr1", ""),
                attrs.get("MailApt", ""),
                attrs.get("MailCity", ""),
                attrs.get("MailState", ""),
                attrs.get("MailZip", ""),
            ]
            mail_addr = " ".join(str(p) for p in mail_parts if p).strip() or None

            # Previous owner
            prev_owner = attrs.get("PreviousOwner") or None

            # Homestead
            homestead = attrs.get("Homestead") or ""

            raw = {
                "york_delinquent_tax": {
                    "parcel_id": parcel_id,
                    "owner": owner,
                    "property_address": address,
                    "assessed_value": assessed_val,
                    "apr_land_val": attrs.get("AprLandVal"),
                    "apr_bldg_val": attrs.get("AprBldgVal"),
                    "tax_land_val": attrs.get("TaxLandVal"),
                    "tax_bldg_val": attrs.get("TaxBldgVal"),
                    "sale_price": sale_price,
                    "date_sold": attrs.get("DateSold"),
                    "legal_description": legal.strip() if legal else None,
                    "land_use": land_use or None,
                    "subdivision": attrs.get("Subdivision"),
                    "deededacres": attrs.get("deededacres"),
                    "gis_size_ac": attrs.get("GISSizeAC"),
                    "finished_sqft": attrs.get("FinishedSQFT"),
                    "year_built": attrs.get("YearBuilt"),
                    "bldg_type": attrs.get("BldgTypeDesc"),
                    "improved_status": attrs.get("ImprovedStatus"),
                    "neighborhood": attrs.get("NeighborhoodDesc"),
                    "mail_address": mail_addr,
                    "previous_owner": prev_owner,
                    "homestead": homestead or None,
                    "district": attrs.get("DISTRICT"),
                    "tax_year": attrs.get("TAX_YEAR"),
                    "sold": attrs.get("SOLD"),
                    "gis_url": gis_url,
                    "map_number": attrs.get("MAP__"),
                    "transfer_book": attrs.get("TransferBook"),
                    "transfer_page": attrs.get("TransferPage"),
                    "plat_book": attrs.get("PlatBook"),
                    "plat_page": attrs.get("PlatPage"),
                    "fire_tax_dist": attrs.get("FireTaxDist"),
                    "school_tax_dist": attrs.get("SchSpeTaxDist"),
                    "muni_tax_dist": attrs.get("MuniTaxDist"),
                    "total_ag_credit": attrs.get("TotalAgCredit"),
                }
            }

            out.append(
                Listing(
                    source=self.slug,
                    source_url=gis_url or FS_URL,
                    listing_type=ListingType.TAX_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="SC",
                    county="York",
                    parcel_id=parcel_id,
                    defendant=owner,
                    street_address=address,
                    assessed_value=float(assessed_val) if assessed_val else None,
                    opening_bid=float(sale_price) if sale_price else None,
                    description=description,
                    first_seen=now,
                    last_seen=now,
                    raw=raw,
                )
            )

        log.info("york_tax.done", count=len(out), skipped_no_parcel=skipped_no_parcel)
        return out

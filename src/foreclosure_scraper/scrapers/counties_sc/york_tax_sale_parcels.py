"""York County SC delinquent-tax SALE list, read from the county's own ArcGIS layer.

WHY THIS EXISTS
    ``york_delinquent_tax`` reads ``yorkcountysc.gov/216`` and has produced zero rows:
    the county moved its site to ``yorkcountygov.com``, which answers scripts with a
    Cloudflare "Enable JavaScript and cookies to continue" page (HTTP 403, checked
    2026-10-07). That is a wall and it is left alone.

    The same list is published, open, as the hosted layer behind the county's tax-sale
    map: item "Tax Sale Properties 2026 View" (owner ``yorkcountysc_gisonline``). The
    service URL still carries "2025" in its name; the rows say ``TAX_YEAR = '2026'``.
    Live on 2026-10-07: 853 parcels, last edited 2026-09-29, every row ``SOLD = 'N'``,
    521 improved and 330 vacant land, 121 with an out-of-state owner mailing address.
    Each row carries the 10-digit TMS (the same key ``parcel_cache.PARCEL_LAYERS["York"]``
    uses), owner, owner mailing address, situs (791 of 853), appraised and taxable value,
    land use and improvement status.

SALE DATE
    York holds its sale on the second Monday of October. The 2026 sale is Monday
    2026-10-12 (the county's "2026 Tax Sale Information" notice, as indexed by search; the
    notice itself sits behind the Cloudflare wall above). ``sale_date`` is computed from
    the row's ``TAX_YEAR`` with that rule, so next year's layer needs no code change.
    An SC tax sale conveys a certificate and the owner keeps a 12-month redemption right
    (SC Code 12-51-90), which ``enrichment_foreclosure_sold_comps.sc_tax_redemption_open``
    already uses to keep these rows active after sale day. Rows the county flags as sold
    are NOT given a terminal ``auction_status``; the flag is kept in ``raw``.

PRIVACY
    ``outFields`` is an explicit list of property-record columns (never ``*``) and every
    attribute bag goes through ``sensitive_fields.drop_sensitive`` (via ``_layer_kit``)
    before it is read. The owner's mailing address is kept in ``raw["owner_mailing"]``
    (absentee signal), never written into the property's own address fields.

Gate: ``FORECLOSURE_YORK_TAX_SALE=0`` turns it off.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive
from ..counties_generic._layer_kit import clean, fetch_attrs, num, owner_mailing

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_YORK_TAX_SALE"
SOURCE = "counties_sc.york_tax_sale_parcels"

LAYER = ("https://services1.arcgis.com/2AGLxyiJoNiVHKwq/arcgis/rest/services/"
         "Tax_Sale_Properties_2025_View/FeatureServer/0")

#: Human-facing page for source_url. The county's own tax-sale notice is behind a
#: Cloudflare challenge, so the ArcGIS item page (open) is the reachable link.
ITEM_PAGE = "https://www.arcgis.com/home/item.html?id=0bf91b9d18f14702873af5f3ad870429"

FIELDS = (
    "TAXMAPID", "ParcelID", "TAX_YEAR", "SOLD",
    "Owner1", "Owner2",
    "MailAddr1", "MailAddr2", "MailApt", "MailCity", "MailState", "MailZip",
    "PropertyAddress", "AprTotVal", "TaxTotVal",
    "LandUseDesc", "ImprovedStatus", "YearBuilt", "deededacres",
)

_NON_DIGIT = re.compile(r"\D")

#: Columns copied into raw["york_tax_sale"].
_RAW_FACTS = ("TAXMAPID", "TAX_YEAR", "SOLD", "LandUseDesc", "ImprovedStatus",
              "AprTotVal", "TaxTotVal", "YearBuilt", "deededacres")


def second_monday_of_october(year: int) -> datetime:
    d = datetime(year, 10, 1)
    first_monday = d + timedelta(days=(0 - d.weekday()) % 7)
    return first_monday + timedelta(days=7)


def sale_date_for(tax_year: Any) -> Optional[datetime]:
    """The sale day for a row's TAX_YEAR (York: second Monday of October)."""
    try:
        y = int(str(tax_year).strip())
    except (TypeError, ValueError):
        return None
    if not 2000 <= y <= 2100:
        return None
    return second_monday_of_october(y)


def to_listing(attrs: dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Listing]:
    a = drop_sensitive(attrs)
    tms = clean(a.get("TAXMAPID")) or clean(a.get("ParcelID"))
    if tms:
        tms = _NON_DIGIT.sub("", tms) or None
    situs = clean(a.get("PropertyAddress"))
    if not (tms or situs):
        return None
    owners = [o for o in (clean(a.get("Owner1")), clean(a.get("Owner2"))) if o]
    owner = " & ".join(owners) or None
    sale = sale_date_for(a.get("TAX_YEAR"))
    improved = clean(a.get("ImprovedStatus"))
    vacant_land = bool(improved and improved.lower().startswith("vacant"))
    sold = (clean(a.get("SOLD")) or "").upper()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    raw: dict[str, Any] = {
        # Property facts only; owner and mailing live in owner_name / raw["owner_mailing"].
        "york_tax_sale": {k: a.get(k) for k in _RAW_FACTS if a.get(k) not in (None, "")},
        "tax_sale_year": clean(a.get("TAX_YEAR")),
        "sold_flag": sold or None,
    }
    mail = owner_mailing(
        owner,
        (a.get("MailAddr1"), a.get("MailAddr2"), a.get("MailApt"),
         a.get("MailCity"), a.get("MailState"), a.get("MailZip")),
        a.get("MailState"), situs, tms, "SC", "york_tax_sale_parcels")
    if mail:
        raw["owner_mailing"] = mail
    if vacant_land:
        raw["vacant_lot"] = True

    try:
        yb = int(a.get("YearBuilt")) if a.get("YearBuilt") not in (None, "", 0) else None
    except (TypeError, ValueError):
        yb = None
    bits = [b for b in (owner, situs, improved, clean(a.get("LandUseDesc"))) if b]
    return Listing(
        source=SOURCE,
        source_url=ITEM_PAGE,
        listing_type=ListingType.TAX_SALE,
        property_kind=PropertyKind.LAND if vacant_land else PropertyKind.UNKNOWN,
        state="SC", county="York",
        street_address=situs,
        parcel_id=tms,
        owner_name=owner, defendant=owner,
        market_value=num(a.get("AprTotVal")),
        tax_value=num(a.get("TaxTotVal")),
        acreage=num(a.get("deededacres")),
        year_built=yb,
        land_use=clean(a.get("LandUseDesc")),
        sale_date=sale,
        sale_location="York County delinquent tax sale",
        auction_status=("scheduled" if sold == "N" and sale and sale >= now - timedelta(days=1)
                        else None),
        foreclosure_process="tax",
        description=f"York SC tax sale {clean(a.get('TAX_YEAR')) or ''} — {' | '.join(bits)}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class YorkTaxSaleParcels(BaseScraper):
    slug = SOURCE
    name = "York County SC delinquent tax sale list (county ArcGIS layer)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        async with client(timeout=45.0) as c:
            rows = await fetch_attrs(c, LAYER, FIELDS)
        out = [li for li in (to_listing(a) for a in rows) if li]
        log.info("york_tax_sale.done", fetched=len(rows), leads=len(out))
        return out

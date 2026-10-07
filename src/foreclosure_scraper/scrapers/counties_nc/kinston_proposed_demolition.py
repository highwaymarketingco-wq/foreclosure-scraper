"""City of Kinston NC (Lenoir County) 2026 proposed demolition list.

SOURCE
    Public hosted layer "2026 Proposed Demolition Map" (owner ``thomas.vogel_KDPS``, the
    Kinston public-services GIS account; extent centred on Kinston), layer 0 "Proposed
    Demolition Properties". Found 2026-10-07 by an ArcGIS Online search over the NC/SC
    extent. Live that day: 45 parcels, ``TAX_YEAR`` 2026, last edited 2026-06-04.
    Local news describes a much longer condemnation list (about 118 properties) that the
    city has not put online; this layer is the part that is published.

    Each row is a Lenoir County parcel record (NC PIN, owner, taxpayer mailing address,
    situs, values, year built) plus the city's own case columns: ``CONDEMENED`` (date the
    structure was condemned), ``POWER_CUT_OFF`` / ``SEWER_CUTOFF`` / ``GAS_CUT_OFF``
    ("Yes-2018" style) and ``HEIR_PROPERTY``. The utility columns are the only
    utility-disconnect facts found anywhere in NC or SC on 2026-10-07 (utility customer
    records are closed by NCGS 132-1.1(c)); here the city publishes them itself, per
    condemned building, with no account data.

    Layer 1 of the same service ("City Owned Properties", 25 rows) is city-owned land and
    is NOT read: the owner is the city, not a seller.

SIGNALS
    raw["condemned"] = True on every row (a city demolition list is the end state of a
    condemnation). A "Yes" utility cut-off sets raw["utility_cutoff"] and a
    raw["vacancy"] block (``basis`` = "utility_cut_off"). HEIR_PROPERTY "Yes" sets
    raw["heir_property"]. Owner mailing goes to raw["owner_mailing"].

DATELESS: ships under the ``counties_generic.arcgis_distress.`` prefix that
``main.DATELESS_OK_SOURCES`` already admits (see ``_layer_kit``).
PRIVACY: explicit outFields, ``drop_sensitive`` on every attribute bag.
Gate: ``FORECLOSURE_KINSTON_DEMOLITION=0``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ..counties_generic._layer_kit import DATELESS_PREFIX, clean, fetch_attrs, num, owner_mailing

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_KINSTON_DEMOLITION"
SLUG = "counties_nc.kinston_proposed_demolition"
SOURCE = DATELESS_PREFIX + "kinston_proposed_demolition"

LAYER = ("https://services5.arcgis.com/oHyVM17u2FMyV4oB/arcgis/rest/services/"
         "2026_Proposed_Demolition_Map_WFL1/FeatureServer/0")
ITEM_PAGE = "https://www.arcgis.com/home/item.html?id=1f297147be8d4427b867f73961bc4bd1"

#: Property-record and case columns only. Never "*".
FIELDS = (
    "record_num", "nc_pin", "PARCEL_NUM", "TAX_YEAR",
    "NAME_1", "NAME_2",
    "TAYPAYER_A", "TAYPAYER_1", "TAYPAYER_2", "TAXPAYER_C", "STATE", "ZIP_CODE",
    "PHYSICAL_S", "ADDRESS", "TOTAL_FMV_", "TOTAL_FMV1", "YEAR_ACTUA", "DEED_ACR_1",
    "CONDEMENED", "POWER_CUT_OFF", "SEWER_CUTOFF", "GAS_CUT_OFF", "HEIR_PROPERTY",
)

_YES = re.compile(r"^\s*y(es)?\b", re.I)


def _yes(v: Any) -> bool:
    return bool(_YES.match(str(v))) if v not in (None, "") else False


def to_listing(a: dict, *, now: Optional[datetime] = None) -> Optional[Listing]:
    pin = clean(a.get("nc_pin"))
    # PHYSICAL_S (the county's situs) is filled on all 45 live rows; the city's own
    # ADDRESS column only on 7 (2026-10-07), so it is the fallback.
    situs = clean(a.get("PHYSICAL_S")) or clean(a.get("ADDRESS"))
    if not (pin or situs):
        return None
    owners = [o for o in (clean(a.get("NAME_1")), clean(a.get("NAME_2"))) if o]
    owner = " & ".join(owners) or None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    cut = {k: clean(a.get(f)) for k, f in (("power", "POWER_CUT_OFF"), ("sewer", "SEWER_CUTOFF"),
                                           ("gas", "GAS_CUT_OFF"))}
    cut_yes = {k: v for k, v in cut.items() if _yes(v)}
    raw: dict[str, Any] = {
        "condemned": True,
        "kinston_demolition": {
            "list": "2026 proposed demolition",
            "tax_year": a.get("TAX_YEAR"),
            "condemned_date": clean(a.get("CONDEMENED")),
            "record_num": a.get("record_num"),
        },
        "arcgis_distress": {"layer": "kinston_proposed_demolition",
                            **{k: v for k, v in a.items() if v not in (None, "", " ")}},
    }
    if cut_yes:
        raw["utility_cutoff"] = {**cut_yes, "source": "kinston_proposed_demolition"}
        raw["vacancy"] = {"vacant": True, "basis": "utility_cut_off",
                          "source": "kinston_proposed_demolition"}
    if _yes(a.get("HEIR_PROPERTY")):
        raw["heir_property"] = True
    mail = owner_mailing(
        owner, (a.get("TAYPAYER_A"), a.get("TAYPAYER_1"), a.get("TAYPAYER_2"),
                a.get("TAXPAYER_C"), a.get("STATE"), a.get("ZIP_CODE")),
        a.get("STATE"), situs, pin, "NC", "kinston_proposed_demolition")
    if mail:
        raw["owner_mailing"] = mail
    try:
        yb = int(a.get("YEAR_ACTUA")) if a.get("YEAR_ACTUA") not in (None, "", 0) else None
    except (TypeError, ValueError):
        yb = None
    return Listing(
        source=SOURCE,
        source_url=ITEM_PAGE,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Lenoir",
        street_address=situs,
        parcel_id=pin,
        owner_name=owner, defendant=owner,
        tax_value=num(a.get("TOTAL_FMV_")) or num(a.get("TOTAL_FMV1")),
        acreage=num(a.get("DEED_ACR_1")),
        year_built=yb if yb and yb > 1700 else None,
        foreclosure_process="demolition_order",
        description=("Kinston NC 2026 proposed demolition"
                     + (f", utilities cut ({', '.join(cut_yes)})" if cut_yes else "")
                     + f" — {' | '.join(b for b in (owner, situs) if b)}")[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class KinstonProposedDemolition(BaseScraper):
    slug = SLUG
    name = "City of Kinston NC 2026 proposed demolition list (ArcGIS)"
    category = "city_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        async with client(timeout=45.0) as c:
            rows = await fetch_attrs(c, LAYER, FIELDS)
        out = [li for li in (to_listing(a) for a in rows) if li]
        log.info("kinston_demolition.done", fetched=len(rows), leads=len(out))
        return out

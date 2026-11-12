"""Iredell County NC parcels with delinquent taxes owed (the county's own map layer).

SOURCE
    maps.iredellcountync.gov Data/DelinquentTaxes MapServer/0 "Delinquent Taxes": 2,391 parcel
    outlines on 2026-10-07, every row DELINQ = 'Delinquent Taxes Owed', ASOF = 2026-10-06 (the
    county refreshes it; the as-of date rides along). This overturns the earlier note that Iredell
    has no delinquent feed (its PTS tenant answers HTTP 500).

    The layer carries NO parcel number, owner or amount: only the outline. Each outline is turned
    into an interior point and the points are matched, 100 per query, to the NC OneMap statewide
    parcel layer (cntyname='Iredell'), which gives parno (the parcel cache key), owner, situs,
    owner mailing and value. A point that lands in no OneMap parcel is dropped (counted in the log).

THE NOT-YET-LATE RULE
    The layer says only "delinquent", with no levy year. In October 2026 the newest levy that can
    be late is 2025 (tax_calendar.latest_delinquent_levy_year), and the 2026 bill is not late
    until 2027-01-06, so raw['tax_owed'] names 2025 (years_delinquent 1, balance unknown). A
    parcel whose only unpaid bill were the current one would not be on a "delinquent" layer.

DATELESS: slug counties_nc.iredell_delinquent_tax goes in main.DATELESS_OK_SOURCES.
Gate: FORECLOSURE_IREDELL_TAX=0.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...parcel_cache import NC_ONEMAP_URL
from ...tax_calendar import latest_delinquent_levy_year
from ..counties_generic._layer_kit import clean, interior_point, match_points, num, owner_mailing
from ..counties_generic._tax_kit import tax_owed_block

log = structlog.get_logger()

SLUG = "counties_nc.iredell_delinquent_tax"
ENV_OFF = "FORECLOSURE_IREDELL_TAX"
LAYER = "https://maps.iredellcountync.gov/server/rest/services/Data/DelinquentTaxes/MapServer/0"
ONEMAP = NC_ONEMAP_URL.rsplit("/query", 1)[0]
PAGE = "https://www.iredellcountync.gov/170/Tax-Collections"

ONEMAP_FIELDS = ("parno", "altparno", "ownname", "siteadd", "scity", "szip", "parval",
                 "mailadd", "mcity", "mstate", "mzip")


def _ms_date(v) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def outline_points(features: Iterable[dict]) -> list[tuple[tuple[float, float], Optional[str]]]:
    out = []
    for f in features:
        g = f.get("geometry") or {}
        p = interior_point(g.get("rings"))
        if p:
            out.append((p, _ms_date((f.get("attributes") or {}).get("ASOF"))))
    return out


def to_listing(parcel: dict, asof: Optional[str], *, now: Optional[datetime] = None,
               year: Optional[int] = None) -> Optional[Listing]:
    pid = clean(parcel.get("parno")) or clean(parcel.get("altparno"))
    if not pid:
        return None
    year = year or latest_delinquent_levy_year("NC", "Iredell")
    to = tax_owed_block([(year, None)], state="NC", county="Iredell", source=SLUG,
                        basis="county_delinquent_layer")
    if not to:
        return None
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    owner = clean(parcel.get("ownname"))
    situs = clean(parcel.get("siteadd"))
    raw: dict[str, Any] = {
        "iredell_delinquent_tax": {"status": "Delinquent Taxes Owed", "as_of": asof,
                                   "years_unpaid": [year], "year_assumed": True,
                                   "matched_by": "outline interior point in NC OneMap parcel"},
        "tax_owed": to,
    }
    mail = owner_mailing(owner, (parcel.get("mailadd"), parcel.get("mcity"), parcel.get("mstate"),
                                 parcel.get("mzip")), parcel.get("mstate"), situs, pid, "NC",
                         "iredell_delinquent_tax")
    if mail:
        raw["owner_mailing"] = mail
    return Listing(
        source=SLUG, source_url=PAGE,
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Iredell",
        street_address=situs, city=(clean(parcel.get("scity")) or "").title() or None,
        zip_code=clean(parcel.get("szip")), parcel_id=pid,
        owner_name=owner, defendant=owner, market_value=num(parcel.get("parval")),
        foreclosure_process="tax",
        description=f"Iredell NC delinquent taxes owed (as of {asof}) — {owner or ''} {situs or pid}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class IredellDelinquentTax(BaseScraper):
    slug = SLUG
    name = "Iredell County NC delinquent-tax parcels (county layer joined to NC OneMap)"
    category = "county_tax"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        async with client(timeout=90.0) as c:
            feats = await agw.query_features(c, LAYER, out_fields="OBJECTID,DELINQ,ASOF", where="1=1",
                                             return_geometry=True, out_sr=4326, page=1000)
            pts = outline_points(feats)
            parcels = await match_points(c, ONEMAP, [p for p, _a in pts], ONEMAP_FIELDS,
                                         where="cntyname='Iredell'")
        out, seen, miss = [], set(), 0
        for (_p, asof), parcel in zip(pts, parcels):
            if not parcel:
                miss += 1
                continue
            li = to_listing(parcel, asof)
            if li and li.parcel_id not in seen:
                seen.add(li.parcel_id)
                out.append(li)
        log.info("iredell_tax.done", outlines=len(feats), matched=len(pts) - miss, leads=len(out))
        return out

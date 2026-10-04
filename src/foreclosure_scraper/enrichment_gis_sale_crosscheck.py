"""County-recorded sale-price cross-check for HomeHarvest sold comps.

Confirmed bug (2026-10-04, independently verified three ways -- Spatialest
record-card history, a live query of Buncombe's own ArcGIS parcel layer, and
the NC excise-tax-stamp math): HomeHarvest/Realtor.com's own `sold_price`
field can be flatly wrong even though the address/URL/date/year-built all
match. Example: 140 Old Leicester Rd, Asheville NC 28804 -- HomeHarvest says
$140,000; Buncombe County's own ArcGIS parcel layer says $160,000, DeedDate
2026-04-06, `Stamps` = 320 * $500/stamp = $160,000 exactly (NC's excise tax is
$1 per $500 of consideration -- a legally-binding proxy for the real closing
price). HomeHarvest's own `estimated_value` for that listing is $158,987,
consistent with the COUNTY figure, not HomeHarvest's own claimed sold_price.
Likely cause: the listing text says the parcel carries two dwellings (a 1940s
bungalow + a mobile home) -- a multi-structure investment-property closing is
exactly the kind an MLS agent miskeys. This is an external MLS-data-quality
issue, not a pipeline bug (see `enrichment_comps.py`'s read of `sold_price` --
no caching/staleness/field-confusion there).

This module re-queries the SAME free, lightweight (plain httpx, no headless
browser) county ArcGIS layer `enrichment_recorded_sales.py` already uses for
Buncombe, this time keyed by ADDRESS rather than by parcel ring, and prefers
the county's `SalePrice` over HomeHarvest's `sold_price` when:

  (a) the county has a parcel whose house number + street match the comp's
      address (disambiguated by situs city when more than one candidate
      shares that house number + street -- Buncombe has several, e.g. two
      distinct "140 Old Leicester" parcels in different towns), AND
  (b) that parcel's `DeedDate` falls within `DATE_TOLERANCE_DAYS` of the
      comp's claimed `sold_date` -- i.e. it is confidently the SAME closing,
      not an earlier or later one on the same parcel, AND
  (c) the two prices disagree by more than `PRICE_DISAGREEMENT_TOLERANCE`.

Scope -- ONLY counties with an already-wired, confirmed-working GIS layer
(see `enrichment_recorded_sales.SUPPORTED`, which lists the three counties
this repo has a confirmed sales-roll/parcel-snapshot layer for). Checked all
three live on 2026-10-04 specifically for ADDRESS-based lookup (the
requirement here, distinct from the ring-based lookup `enrichment_recorded_
sales.py` does):

  - Buncombe NC: `property_bc_dis/MapServer/1` carries `SalePrice`/`DeedDate`/
    `Stamps` keyed to a clean `Address`/`HouseNumber`/`streetname`/`CityName`
    -- confirmed live, wired here.
  - Anderson SC: its sales-roll layer (`ANDERSON_SALES`,
    `Parcel_Sales/MapServer/0`) has NO usable address field for this purpose
    -- live-queried 2026-10-04 and its `SALOCA` field is a lot/legal
    description ("LTS 11 + 12  S MAIN/WARDLAW ST", "LT 17  S MAIN ST"), not a
    mailing-style address a HomeHarvest comp ("41 Olive St") could ever be
    matched against. Excluded -- confirmed NOT usable, not unconfirmed.
  - Cleveland NC: its sales layers (`CLEVELAND_IMPROVED`/`CLEVELAND_VACANT`)
    carry no address field at all -- the address shown elsewhere is joined in
    from a DIFFERENT statewide layer (NC OneMap) by `Parcel_Number`, and that
    two-hop (address -> OneMap parcel -> Cleveland sale row) join has not been
    independently validated for this address-match use case. Excluded as an
    unconfirmed case, not guessed at -- a real follow-up, not a dead end.
"""
from __future__ import annotations

import re
from datetime import date, datetime

import structlog

log = structlog.get_logger()

# Disagreement beyond this fraction of the COUNTY's own recorded price makes
# the comp's HomeHarvest sold_price untrustworthy enough to override. Named
# per the task: "start with >5-10%" -- 8% splits that range.
PRICE_DISAGREEMENT_TOLERANCE = 0.08

# How many days the county's DeedDate may sit from the comp's claimed
# sold_date and still count as the SAME transaction (not a different, later
# or earlier, sale of the same parcel). Looser than a same-day match because
# HomeHarvest's last_sold_date and the recorded deed date routinely differ by
# a few weeks (closing vs. recording lag) -- tighter than
# enrichment_recorded_sales' MAX_DATE_GAP_DAYS-style windows because here we
# are confirming identity of ONE specific sale, not sampling a basket.
DATE_TOLERANCE_DAYS = 45

NC_STAMP_PER_DOLLARS = 500.0  # NC excise tax: $1 per $500 of consideration

BUNCOMBE_PARCELS = ("https://gis.buncombecounty.org/arcgis/rest/services/"
                    "property_bc_dis/MapServer/1/query")
_BUNCOMBE_FIELDS = "pinnum,Address,HouseNumber,streetname,CityName,SalePrice,DeedDate,Stamps"

# (state, county) pairs this module can cross-check, in the SAME tuple shape
# `enrichment_comps.py` already keys its county pools with (state upper-cased,
# county title-cased via validation.normalize_county). See the module
# docstring above for why Anderson/Cleveland are not (yet) in this set.
SUPPORTED: frozenset[tuple[str, str]] = frozenset({("NC", "Buncombe")})

_STREET_SUFFIX_RE = re.compile(
    r"\b(ST|AVE|RD|DR|LN|CT|BLVD|HWY|WAY|PL|CIR|TER|HTS|LOOP)\b")


def _esc(v: str) -> str:
    return v.replace("'", "''")


def split_house_street(addr: str) -> tuple[str, str] | None:
    """'140 Old Leicester Rd' -> ('140', 'OLD LEICESTER'). Same convention as
    `assessor_cards/buncombe_nc.py`'s address fallback and the validated
    pattern in docs/validation_2026-10-03/scripts/
    crosscheck_comps_arcgis_live_snapshot.py."""
    m = re.match(r"^\s*(\d+)\s+(.*)$", (addr or "").strip())
    if not m:
        return None
    num, rest = m.groups()
    street = _STREET_SUFFIX_RE.split(rest.upper(), maxsplit=1)[0].strip()
    return num, (street or rest.upper())


def _deed_date_iso(v) -> str | None:
    """Buncombe's parcel layer publishes DeedDate as an 8-digit 'YYYYMMDD'
    STRING (confirmed live: '20260406') -- unlike the saledata roll's
    epoch-ms SellDate that enrichment_recorded_sales._epoch_iso parses."""
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) != 8:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def parse_any_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2][: len(s)], fmt).date()
        except ValueError:
            pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


async def _buncombe_lookup(http, house_num: str, street: str, city: str | None) -> list[dict]:
    where = f"HouseNumber='{_esc(house_num)}' AND UPPER(streetname) LIKE '%{_esc(street)}%'"
    try:
        r = await http.get(BUNCOMBE_PARCELS, params={
            "where": where, "outFields": _BUNCOMBE_FIELDS,
            "returnGeometry": "false", "f": "json", "resultRecordCount": "10",
        })
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("gis_crosscheck.buncombe.http_error", error=str(exc)[:120])
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    feats = [f.get("attributes") or {} for f in (data.get("features") or [])]
    if city:
        city_u = city.strip().upper()
        narrowed = [f for f in feats if str(f.get("CityName") or "").strip().upper() == city_u]
        if narrowed:
            feats = narrowed
    return feats


def _disambiguate(feats: list[dict], claimed_date: date | None) -> dict | None:
    """House-number + street alone can match more than one real parcel
    (Buncombe has several, e.g. two distinct "140 Old Leicester" parcels in
    different towns). Refuse to guess among them UNLESS the claimed sold_date
    pins down exactly one candidate's DeedDate within DATE_TOLERANCE_DAYS."""
    if not feats:
        return None
    if len(feats) == 1:
        return feats[0]
    if claimed_date is None:
        return None
    dated: list[tuple[int, dict]] = []
    for f in feats:
        dd = parse_any_date(_deed_date_iso(f.get("DeedDate")))
        if dd is not None:
            dated.append((abs((dd - claimed_date).days), f))
    if not dated:
        return None
    dated.sort(key=lambda t: t[0])
    if len(dated) >= 2 and dated[0][0] == dated[1][0]:
        return None  # genuine tie -- don't guess
    return dated[0][1]


async def crosscheck_sold_price(
    http, *, state: str, county: str, address: str | None, city: str | None,
    claimed_sold_price: float | None, claimed_sold_date: str | None,
) -> dict | None:
    """Cross-check one HomeHarvest comp's claimed sold_price/sold_date
    against the county's own recorded SalePrice/DeedDate for that address.

    Returns None whenever there isn't a confident, date-aligned, price-
    bearing county record for this exact address (never guesses). Otherwise
    returns:
      {"county_sale_price": float, "county_deed_date": "YYYY-MM-DD",
       "county_stamps": float | None, "date_gap_days": int,
       "disagreement_pct": float, "source": str, "preferred": bool}
    `preferred` is True exactly when the two prices disagree by more than
    PRICE_DISAGREEMENT_TOLERANCE -- i.e. when the county price should be
    preferred over HomeHarvest's.
    """
    if (state, county) not in SUPPORTED:
        return None
    split = split_house_street(address or "")
    if not split:
        return None
    house_num, street = split
    claimed_date = parse_any_date(claimed_sold_date)

    feats = await _buncombe_lookup(http, house_num, street, city)
    rec = _disambiguate(feats, claimed_date)
    if not rec:
        return None

    try:
        county_price = float(rec.get("SalePrice")) if rec.get("SalePrice") else None
    except (TypeError, ValueError):
        county_price = None
    if not county_price or county_price <= 0:
        return None

    deed_date = parse_any_date(_deed_date_iso(rec.get("DeedDate")))
    if deed_date is None or claimed_date is None:
        return None
    gap_days = abs((deed_date - claimed_date).days)
    if gap_days > DATE_TOLERANCE_DAYS:
        return None  # not confidently the SAME transaction

    if not claimed_sold_price or claimed_sold_price <= 0:
        return None
    disagreement = abs(county_price - claimed_sold_price) / county_price

    stamps = rec.get("Stamps")
    try:
        stamps = float(stamps) if stamps else None
    except (TypeError, ValueError):
        stamps = None

    return {
        "county_sale_price": county_price,
        "county_deed_date": deed_date.isoformat(),
        "county_stamps": stamps,
        "date_gap_days": gap_days,
        "disagreement_pct": round(disagreement * 100, 1),
        "source": "buncombe_property_bc_dis",
        "preferred": disagreement > PRICE_DISAGREEMENT_TOLERANCE,
    }

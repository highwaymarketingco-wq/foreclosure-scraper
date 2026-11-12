"""County sales rolls — the comps spine, plus building characteristics.

WHY THIS EXISTS
    Measured on the 2026-08-03 board of 25,552 leads:

        comps          0.0% — not one lead has one
        living_sqft   11.3% — 22,663 missing
        bathrooms     16.4% — 21,353 missing
        bedrooms      16.6% — 21,322 missing
        year_built    29.3% — 18,062 missing

    Those are the fields the dashboard detail card is built to show, and they
    are the fields an ARV estimate needs. Every one of them is ordinary county
    assessor data that several counties publish free and unauthenticated — we
    simply were not reading it. The parcel GEOMETRY layer is wired for 17 of 18
    counties and does not carry them; the CAMA/sales tables behind it do.

WHAT THIS IS NOT
    Not a lead source. Nothing here creates a listing. It only fills fields on
    leads we already have, keyed by parcel. A sales roll has six figures of rows
    and would swamp the board if treated as leads.

THE JOIN IS THE HARD PART
    Counties key their sales roll differently from their parcel layer. Henderson
    is the worked example: leads carry a 10-digit PIN, the sales roll is keyed by
    REID, and the two only meet through the parcel layer. Verified end to end on
    real board leads — PIN 9569798277 -> REID 101727 -> $360,000 / 1,932 sqft /
    built 1982. A source whose key we cannot bridge is worthless no matter how
    rich it is, so every entry declares its bridge explicitly.

COMPLIANCE
    All hosts here were robots-checked. gisweb.hendersoncountync.gov returns 404
    on /robots.txt (no directives). Fields are always requested explicitly —
    never outFields=*, which on an assessor layer would sweep up owner mailing
    data we have no reason to hold twice.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable, NamedTuple, Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

_PAGE = 2000
ENABLED = os.environ.get("FORECLOSURE_COUNTY_SALES", "1") != "0"
#: Sales older than this are poor comps and only bloat the payload.
MAX_SALE_AGE_Y = float(os.environ.get("FORECLOSURE_COMPS_MAX_AGE_Y", "6"))


class SalesRoll(NamedTuple):
    """One county's sales roll and how it reaches our leads."""
    county: str
    state: str
    url: str
    #: Explicit field list. Never a wildcard.
    fields: tuple[str, ...]
    key: str                       # the sales roll's own parcel key
    price: str
    sale_date: str                 # epoch millis or yyyymm
    #: Optional bridge: our lead's parcel_id is `bridge_to`, the roll keys on
    #: `key`, and this layer carries both so we can cross them.
    bridge_url: Optional[str] = None
    bridge_from: Optional[str] = None   # column matching our parcel_id
    bridge_to: Optional[str] = None     # column matching the roll's key
    situs: Optional[str] = None
    sqft: Optional[str] = None
    year_built: Optional[str] = None
    acreage: Optional[str] = None
    sale_type: Optional[str] = None
    #: Values of sale_type that indicate an arms-length improved sale.
    arms_length: tuple[str, ...] = ()
    #: Some layers store the parcel key space-padded to a fixed width (Mitchell
    #: pads PIN to 26 chars). An exact IN() match then returns nothing, so for
    #: small layers we pull everything and match on the trimmed value instead.
    padded_key: bool = False


ROLLS: tuple[SalesRoll, ...] = (
    # Henderson publishes a real sales roll: 33,276 rows, price populated on
    # 99.98%, current to within a week. It keys on REID while our leads carry
    # the 10-digit PIN, so the parcel layer bridges them.
    SalesRoll(
        county="Henderson", state="NC",
        url=("https://gisweb.hendersoncountync.gov/arcgis/rest/services/"
             "Tax/Data_for_MapMetrics/MapServer/2/query"),
        fields=("REID", "PRICE", "SALE_DATE", "LOCATION_ADDR", "SALE_TYPE",
                "YEAR_BUILT", "BLDG_SIZE", "ACREAGE"),
        key="REID", price="PRICE", sale_date="SALE_DATE",
        situs="LOCATION_ADDR", sqft="BLDG_SIZE", year_built="YEAR_BUILT",
        acreage="ACREAGE", sale_type="SALE_TYPE",
        arms_length=("LAND & BLDG(S)",),
        bridge_url=("https://gisweb.hendersoncountync.gov/arcgis/rest/services/"
                    "Parcels/FeatureServer/0/query"),
        bridge_from="PIN", bridge_to="REID",
    ),
    # Pickens publishes the whole parcel file with sale price/date, a VACANT
    # flag and the owner mailing state (an absentee proxy). No bridge needed —
    # our Pickens leads already carry the dashed PIN this layer keys on.
    SalesRoll(
        county="Pickens", state="SC",
        url=("https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/"
             "Pickens_Open_data/FeatureServer/6/query"),
        fields=("PIN", "LOCADD", "SALEDT", "SALEP", "ACRES", "BLDGS", "IMPVAC"),
        key="PIN", price="SALEP", sale_date="SALEDT",
        situs="LOCADD", acreage="ACRES",
    ),
    # Laurens: 44,880 rows. Verified our TMS format matches theirs 3/3 on real
    # board leads, so no bridge is needed here either.
    SalesRoll(
        county="Laurens", state="SC",
        url=("https://www.laurenscountygis.org/arcgis/rest/services/"
             "Pebble/LaurensCountyData/MapServer/4/query"),
        fields=("TMS", "Property_Address", "Sale_Price", "Sale_Date"),
        key="TMS", price="Sale_Price", sale_date="Sale_Date",
        situs="Property_Address",
    ),
    # ---------------------------------------------------------------------
    # Added 2026-08-06 from the per-signal parity sweep, which required every
    # one of the 18 counties to be accounted for rather than letting agents
    # chase whichever counties were easiest. comps was 0.0% of the board.
    # Field names were read off each layer's own /?f=json rather than guessed.
    # ---------------------------------------------------------------------
    SalesRoll(county="Buncombe", state="NC",
              url="https://gis.buncombecounty.org/arcgis/rest/services/opendata/MapServer/1/query",
              fields=("PIN", "Address", "SalePrice", "DeedDate", "Stamps",
                      "TotalMarketValue", "DeedBook", "DeedPage"),
              key="PIN", price="SalePrice", sale_date="DeedDate", situs="Address"),
    SalesRoll(county="Rutherford", state="NC",
              url="https://gis.rutherfordcountync.gov/arcgis/rest/services/TaxParcels/MapServer/0/query",
              fields=("Parcel_Number", "PIN", "Sale_Price", "Deed_Date",
                      "Heated_Area", "Physical_Address"),
              key="Parcel_Number", price="Sale_Price", sale_date="Deed_Date",
              sqft="Heated_Area", situs="Physical_Address"),
    SalesRoll(county="Transylvania", state="NC",
              url="https://gis.transylvaniacounty.org/server/rest/services/Parcels/MapServer/2/query",
              fields=("PIN", "SALE_PRICE", "SALE_DATE", "HEATED_SQ_", "AYB",
                      "LEGAL_ADDR", "ACRES"),
              key="PIN", price="SALE_PRICE", sale_date="SALE_DATE",
              sqft="HEATED_SQ_", year_built="AYB", situs="LEGAL_ADDR", acreage="ACRES"),
    SalesRoll(county="Cleveland", state="NC",
              url=("https://gis.clevelandcounty.com/arcgis/rest/services/Tax/"
                   "Vacant_ImprovedLot_Sales/MapServer/1/query"),
              fields=("Parcel_Number", "Sales_Amount", "DateSold_YYYYMMDD",
                      "Deed_Book", "Deed_Page", "Acres"),
              key="Parcel_Number", price="Sales_Amount",
              sale_date="DateSold_YYYYMMDD", acreage="Acres"),
    SalesRoll(county="Gaston", state="NC",
              url=("https://cogserver.gastonianc.gov/serverweb/rest/services/Parcels/"
                   "GastonCountyParcels/MapServer/0/query"),
              fields=("PIN", "SALESAMT", "SALEDATE", "SQFT"),
              key="PIN", price="SALESAMT", sale_date="SALEDATE", sqft="SQFT"),
    # LINCOLN NOT WIRED. Server_Tables/4 has 98,319 priced sale rows, but it
    # keys on AMPAR — a 5-digit internal account number (' 59277'), not the
    # 10-digit PIN our leads carry, and it is blank on many rows. It needs a
    # bridge through MainInfoLive before it is usable; wiring it on the wrong
    # key would silently attach another parcel's sale history.
    SalesRoll(county="Burke", state="NC",
              url="https://gis.burkenc.org/arcgis/rest/services/ProdParcelViewFC/MapServer/0/query",
              fields=("PIN", "REID", "PKG_SALE_PRICE", "PKG_SALE_DATE",
                      "HEATED_AREA", "LOCATION_ADDR", "ACREAGE"),
              key="PIN", price="PKG_SALE_PRICE", sale_date="PKG_SALE_DATE",
              sqft="HEATED_AREA", situs="LOCATION_ADDR", acreage="ACREAGE"),
    # Mitchell's PIN is space-padded to 26 chars in this layer; _fetch_all
    # compares against our trimmed ids, so the roll is matched on the trimmed
    # value the county also stores. Smallest roll in the sweep at 397 rows, but
    # Mitchell had no comps source at all.
    SalesRoll(county="Mitchell", state="NC",
              url="https://mapping.mitchellcountync.gov/arcgis/rest/services/WebMap/MapServer/18/query",
              fields=("PIN", "sale_price", "sale_date"),
              key="PIN", price="sale_price", sale_date="sale_date",
              padded_key=True),
    SalesRoll(county="Spartanburg", state="SC",
              url=("https://maps.spartanburgcounty.org/server/rest/services/GIS/"
                   "Assessed_Land_Use/MapServer/0/query"),
              # Key on TAXPIN, NOT PARCELNUMBER. Despite the name,
              # PARCELNUMBER holds a suffix fragment ('.01', '.126'); TAXPIN is
              # the 12-digit id our Spartanburg leads actually carry.
              fields=("TAXPIN", "PARCELNUMBER", "SaleAmount", "SaleDate", "YearBuilt"),
              key="TAXPIN", price="SaleAmount", sale_date="SaleDate",
              year_built="YearBuilt"),
    # ANDERSON IS DELIBERATELY ABSENT. propertyviewer.andersoncountysc.org has a
    # valid DigiCert certificate but its server omits the intermediate, so curl
    # and openssl recover the chain by AIA fetching while Python's OpenSSL does
    # not and raises CERTIFICATE_VERIFY_FAILED. That is their misconfiguration,
    # and the fix is to supply the missing intermediate — NOT verify=False,
    # which would disable verification for a real host we cannot then trust.
)


def _num(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _int(v) -> Optional[int]:
    f = _num(v)
    return int(f) if f is not None else None


def _sale_date(v) -> Optional[str]:
    """Counties store this as epoch millis or a yyyymm string. Return ISO date."""
    if v in (None, "", 0):
        return None
    s = str(v).strip()
    # Counties disagree on this in every way they can. Observed live:
    #   Henderson  epoch millis (int)      1590695820000
    #   Transylvania  yyyymm (str)         "199607"
    #   Laurens    yyyymmdd (str)          "20260113"
    # so each shape is handled explicitly rather than guessed at.
    if s.isdigit() and len(s) == 8:                 # yyyymmdd
        y, m, d = s[:4], s[4:6], s[6:8]
        if "1700" <= y <= "2100" and "01" <= m <= "12" and "01" <= d <= "31":
            return f"{y}-{m}-{d}"
        return None
    if s.isdigit() and len(s) == 6:                 # yyyymm
        y, m = s[:4], s[4:6]
        if "1700" <= y <= "2100" and "01" <= m <= "12":
            return f"{y}-{m}-01"
        return None
    # MM/DD/YYYY, seen on several county portals
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and all(x.isdigit() for x in parts):
            m, d, y = parts
            if len(y) == 4:
                return f"{y}-{int(m):02d}-{int(d):02d}"
        return None
    try:
        ms = float(s)
    except ValueError:
        return None
    # Guard against a year stored as a bare int being read as epoch millis.
    if ms < 10_000_000_000:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


async def _fetch_all(c, url: str, fields: tuple[str, ...], where: str,
                     order_by: str | None = None) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        # POST, not GET. A WHERE clause listing a few hundred parcel ids makes a
        # query string long enough that the server answers 404 — which reads as
        # "layer gone" and is really "URL too long". ArcGIS accepts the same
        # parameters as a form POST with no length limit.
        params = {
            "where": where, "outFields": ",".join(fields),
            "returnGeometry": "false", "resultOffset": offset,
            "resultRecordCount": _PAGE, "f": "json",
        }
        if order_by:
            # "Pagination request requires either orderBy field or the
            # layer/table must have objectIdField" — none of these layers
            # declare an objectIdField, so paging without this 400s.
            params["orderByFields"] = order_by
        r = await c.post(url, data=params, timeout=90.0)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        d = r.json()
        # ArcGIS answers 200 with an error BODY; treat that as the failure it is.
        if "error" in d:
            raise RuntimeError(str(d["error"])[:140])
        feats = d.get("features") or []
        out.extend(f.get("attributes") or {} for f in feats)
        if len(feats) < _PAGE or not d.get("exceededTransferLimit"):
            break
        offset += _PAGE
    return out


async def _one_county(c, roll: SalesRoll, leads: list[Listing]) -> dict:
    stat = {"county": roll.county, "leads": len(leads), "bridged": 0,
            "sales_rows": 0, "matched": 0, "sqft": 0, "year": 0, "comps": 0}
    if not leads:
        return stat

    # Which of OUR parcel ids are in play.
    ours = {(li.parcel_id or "").strip() for li in leads if (li.parcel_id or "").strip()}
    if not ours:
        return stat

    # Bridge our key to the roll's key, when they differ.
    to_roll: dict[str, str] = {}
    if roll.bridge_url and roll.bridge_from and roll.bridge_to:
        vals = sorted(ours)
        for i in range(0, len(vals), 400):          # keep the WHERE clause sane
            chunk = vals[i:i + 400]
            q = ",".join("'" + v.replace("'", "''") + "'" for v in chunk)
            try:
                rows = await _fetch_all(
                    c, roll.bridge_url, (roll.bridge_from, roll.bridge_to),
                    f"{roll.bridge_from} IN ({q})", order_by=roll.bridge_from)
            except Exception as exc:  # noqa: BLE001
                log.warning("county_sales.bridge_failed", county=roll.county,
                            error=f"{type(exc).__name__}: {str(exc)[:90]}")
                continue
            for a in rows:
                src = str(a.get(roll.bridge_from) or "").strip()
                dst = str(a.get(roll.bridge_to) or "").strip()
                if src and dst:
                    to_roll[src] = dst
        stat["bridged"] = len(to_roll)
        # Try BOTH keys. Our leads do not all speak one dialect: 742 of the 1,019
        # Henderson parcel_ids are ALREADY REIDs (they came from the ptscloud
        # delinquent roll) while 277 are PINs. Bridging everything silently drops
        # the ones that were already in the roll's own key.
        wanted = set(ours) | set(to_roll.values())
    else:
        wanted = set(ours)
    if not wanted:
        return stat

    # Pull only the sales for parcels we actually hold.
    by_key: dict[str, list[dict]] = {}
    if roll.padded_key:
        # An exact IN() match cannot work against a space-padded column, so pull
        # the whole layer (these are small) and key on the trimmed value.
        try:
            rows = await _fetch_all(c, roll.url, roll.fields, "1=1",
                                    order_by=roll.key)
        except Exception as exc:  # noqa: BLE001
            log.warning("county_sales.roll_failed", county=roll.county,
                        error=f"{type(exc).__name__}: {str(exc)[:90]}")
            rows = []
        for a in rows:
            k = str(a.get(roll.key) or "").strip()
            if k:
                by_key.setdefault(k, []).append(a)
        stat["sales_rows"] = sum(len(v) for v in by_key.values())
        return _attach(roll, leads, to_roll, by_key, stat)

    vals = sorted(wanted)
    for i in range(0, len(vals), 400):
        chunk = vals[i:i + 400]
        q = ",".join("'" + v.replace("'", "''") + "'" for v in chunk)
        try:
            rows = await _fetch_all(c, roll.url, roll.fields,
                                    f"{roll.key} IN ({q})", order_by=roll.key)
        except Exception as exc:  # noqa: BLE001
            log.warning("county_sales.roll_failed", county=roll.county,
                        error=f"{type(exc).__name__}: {str(exc)[:90]}")
            continue
        for a in rows:
            k = str(a.get(roll.key) or "").strip()
            if k:
                by_key.setdefault(k, []).append(a)
    stat["sales_rows"] = sum(len(v) for v in by_key.values())

    return _attach(roll, leads, to_roll, by_key, stat)





def _attach(roll: SalesRoll, leads: list[Listing], to_roll: dict,
            by_key: dict, stat: dict) -> dict:
    """Write the matched sale history and backfill sqft/year/acreage."""
    cutoff = datetime.now(timezone.utc).year - MAX_SALE_AGE_Y
    for li in leads:
        pid = (li.parcel_id or "").strip()
        if not pid:
            continue
        k = to_roll.get(pid, pid)
        rows = by_key.get(k)
        if not rows:
            continue
        stat["matched"] += 1

        # Newest first — the most recent sale is the best basis.
        def _key(a):
            return _sale_date(a.get(roll.sale_date)) or ""
        rows = sorted(rows, key=_key, reverse=True)
        newest = rows[0]

        if roll.sqft and li.living_sqft in (None, 0):
            v = _int(newest.get(roll.sqft))
            if v:
                li.living_sqft = v
                li.living_sqft_estimated = False
                stat["sqft"] += 1
        if roll.year_built and li.year_built in (None, 0):
            v = _int(newest.get(roll.year_built))
            if v and 1700 < v <= datetime.now(timezone.utc).year + 1:
                li.year_built = v
                stat["year"] += 1
        if roll.acreage and li.acreage in (None, 0):
            v = _num(newest.get(roll.acreage))
            if v:
                li.acreage = v

        comps = []
        for a in rows:
            iso = _sale_date(a.get(roll.sale_date))
            price = _num(a.get(roll.price))
            if not (iso and price):
                continue
            if int(iso[:4]) < cutoff:
                continue
            st = str(a.get(roll.sale_type) or "").strip() if roll.sale_type else ""
            comps.append({
                "date": iso, "price": price,
                "sqft": _int(a.get(roll.sqft)) if roll.sqft else None,
                "year_built": _int(a.get(roll.year_built)) if roll.year_built else None,
                "address": str(a.get(roll.situs) or "").strip() or None if roll.situs else None,
                "sale_type": st or None,
                "arms_length": (st in roll.arms_length) if roll.arms_length else None,
                "source": f"{roll.county} {roll.state} county sales roll",
            })
        if comps:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw.setdefault("county_sales", {})["sales"] = comps
            li.raw["county_sales"]["source"] = roll.url
            stat["comps"] += 1

    log.info("county_sales.county_done", **stat)
    return stat


async def enrich_county_sales(listings: list[Listing]) -> dict:
    """Fill sqft / year / acreage and attach the parcel's own sale history."""
    if not ENABLED or not listings:
        return {"skipped": "disabled"}
    totals = {"counties": 0, "matched": 0, "sqft": 0, "year": 0, "comps": 0}
    async with client(timeout=90.0) as c:
        for roll in ROLLS:
            leads = [li for li in listings
                     if li.county == roll.county and li.state == roll.state
                     and (li.parcel_id or "").strip()]
            if not leads:
                continue
            try:
                s = await _one_county(c, roll, leads)
            except Exception as exc:  # noqa: BLE001 - one county must not stop the rest
                log.warning("county_sales.failed", county=roll.county,
                            error=f"{type(exc).__name__}: {str(exc)[:110]}")
                continue
            totals["counties"] += 1
            for k in ("matched", "sqft", "year", "comps"):
                totals[k] += s.get(k, 0)
    log.info("county_sales.done", **totals)
    return totals


def sales_rolls() -> Iterable[SalesRoll]:
    return ROLLS

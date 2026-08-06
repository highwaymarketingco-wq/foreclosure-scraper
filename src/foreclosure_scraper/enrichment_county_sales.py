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
    if s.isdigit() and len(s) == 6:                 # yyyymm
        try:
            return f"{s[:4]}-{s[4:6]}-01"
        except Exception:  # noqa: BLE001
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


async def _fetch_all(c, url: str, fields: tuple[str, ...], where: str) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        r = await c.get(url, params={
            "where": where, "outFields": ",".join(fields),
            "returnGeometry": "false", "resultOffset": offset,
            "resultRecordCount": _PAGE, "f": "json",
        }, timeout=90.0)
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
                    f"{roll.bridge_from} IN ({q})")
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
    vals = sorted(wanted)
    for i in range(0, len(vals), 400):
        chunk = vals[i:i + 400]
        q = ",".join("'" + v.replace("'", "''") + "'" for v in chunk)
        try:
            rows = await _fetch_all(c, roll.url, roll.fields,
                                    f"{roll.key} IN ({q})")
        except Exception as exc:  # noqa: BLE001
            log.warning("county_sales.roll_failed", county=roll.county,
                        error=f"{type(exc).__name__}: {str(exc)[:90]}")
            continue
        for a in rows:
            k = str(a.get(roll.key) or "").strip()
            if k:
                by_key.setdefault(k, []).append(a)
    stat["sales_rows"] = sum(len(v) for v in by_key.values())

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

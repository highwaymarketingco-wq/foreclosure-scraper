"""Richland County SC parcel facts and owner mailing from the county's own map viewer API
(richlandmaps.com/apps/dataviewer), for board rows that carry a street address.

WHY
    Richland is the weakest county on the board for contact: 2,229 rows, 95.5% with a street,
    0.2% with a parcel id, 0% owner mailing (docs/new_sources_2026-10-07_contact_and_facts.md).
    The county publishes no bulk parcel layer and its own site is Cloudflare-challenged, but the
    data viewer's JSON API answers plainly. The viewer shows a liability disclaimer with a
    "Got it" button (rc-disclaimer.js); the owner's attorney cleared click-throughs on
    2026-10-07, and the API calls themselves need no acceptance.

HOW (the viewer's own two calls, nothing else)
    1. api/RCGeoSearchData.php?searchTerm=<street>&searchLimit=10&useFuzzyBkp=1
       -> address points with centerWKT; a result is used only when its confidence is "high",
          its house number equals the row's, and its street words overlap the row's.
    2. api/RCGeoGetParcelAtLatLon.php?lat=..&lon=..
       -> the parcel(s) under that point: TMS, owner, owner mailing (Owner_Addr, Owner_Ad_1,
          Owner_City, Owner_Stat, Owner_Zip), Market_Val, Heated_SQF, Bldg1_Beds, Bldg1_Bath,
          Bldg1_YrBu, Acreage, Last_Sale_ (date), Last_Sale1 (price), OptedOut.
       The parcel is taken only when its Address carries the same house number.
    Polite: one request at a time, >= 1.7 s apart (RICHLAND_PARCEL_DELAY_S), at most
    RICHLAND_PARCEL_MAX lookups per run (default 300), and a row is not re-asked for 30 days
    (raw["richland_parcel"]["attempted"]), so the 2,229 rows converge over a few runs.

RULES
    Fill-only. OptedOut = 1 keeps the owner name and mailing off the row (values and facts are
    still property facts). When the row already names an owner and the parcel's owner shares no
    name word with it, the mailing is withheld (owner_agrees False), the same rule the parcel-
    cache join uses. drop_sensitive runs on every parcel record; geometry is never kept.

WIRING: not called by main.py yet (main.py is edited by the coordinator). The call belongs right
after the enrich_gis_attrs block; see docs/new_sources_2026-10-07_contact_and_facts.md.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog

from .models import Listing, ListingType
from .sensitive_fields import drop_sensitive

log = structlog.get_logger()

API = "https://www.richlandmaps.com/apps/api"
SEARCH = API + "/RCGeoSearchData.php"
AT_POINT = API + "/RCGeoGetParcelAtLatLon.php"
RETRY_DAYS = 30

_HOUSE = re.compile(r"^\s*(\d+)[A-Z]?\s+(.+)$", re.I)
_STOP = {"ST", "STREET", "RD", "ROAD", "DR", "DRIVE", "AVE", "AVENUE", "LN", "LANE", "CT", "COURT",
         "CIR", "CIRCLE", "BLVD", "WAY", "PL", "PLACE", "HWY", "PKWY", "TRL", "N", "S", "E", "W",
         "NE", "NW", "SE", "SW", "EXT", "APT", "UNIT"}
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[A-Z0-9]+", (s or "").upper()) if w not in _STOP and not w.isdigit()}


def _num(v) -> Optional[float]:
    m = _NUM.search(str(v or ""))
    if not m:
        return None
    try:
        f = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return f if f > 0 else None


def _date(v) -> Optional[str]:
    s = str(v or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _zip(v) -> str:
    z = re.sub(r"\D", "", str(v or ""))
    if len(z) == 9:
        return z[:5] if z[5:] == "0000" else f"{z[:5]}-{z[5:]}"
    return z[:5]


def _has_mailing(raw: dict) -> bool:
    om = raw.get("owner_mailing")
    if isinstance(om, dict) and om.get("mailing"):
        return True
    if isinstance(om, str) and om.strip():
        return True
    return bool((raw.get("gis") or {}).get("mailing"))


def _priority(li: Listing) -> int:
    raw = li.raw if isinstance(li.raw, dict) else {}
    tier = (raw.get("distress_stack") or {}).get("tier") if isinstance(raw.get("distress_stack"), dict) else None
    return {"HOT": 0, "WARM": 1}.get(tier, 2)


def wants(li: Listing, now: datetime) -> bool:
    """A Richland SC row with a numbered street that still lacks mailing or a parcel id."""
    if (li.state or "").upper() != "SC":
        return False
    if (li.county or "").replace(" County", "").strip().lower() != "richland":
        return False
    if li.listing_type == ListingType.TAX_SALE_OVERAGE:
        return False
    if not _HOUSE.match(li.street_address or ""):
        return False
    raw = li.raw if isinstance(li.raw, dict) else {}
    if _has_mailing(raw) and li.parcel_id:
        return False
    att = (raw.get("richland_parcel") or {}).get("attempted")
    if att:
        try:
            if now - datetime.fromisoformat(att) < timedelta(days=RETRY_DAYS):
                return False
        except ValueError:
            pass
    return True


def choose_point(results: list[dict], street: str) -> Optional[tuple[float, float]]:
    """(lat, lon) of the search result that is this address: high confidence, same house
    number, overlapping street words."""
    m = _HOUSE.match(street or "")
    if not m:
        return None
    num, rest = m.group(1), m.group(2)
    want = _words(rest)
    for r in results or []:
        if str(r.get("confidence") or "").lower() != "high":
            continue
        u = str(r.get("uniqstring") or "")
        um = _HOUSE.match(u.split(",")[0])
        if not um or um.group(1) != num or not (want & _words(um.group(2))):
            continue
        pt = re.findall(r"-?\d+\.\d+", str(r.get("centerWKT") or ""))
        if len(pt) >= 2:
            return float(pt[1]), float(pt[0])      # WKT is POINT(lon lat)
    return None


def choose_parcel(parcels: list[dict], street: str) -> Optional[dict]:
    m = _HOUSE.match(street or "")
    if not m:
        return None
    num = m.group(1)
    for item in parcels or []:
        p = item.get("Parcel") if isinstance(item, dict) else None
        if not isinstance(p, dict):
            continue
        am = _HOUSE.match(str(p.get("Address") or "").replace("-", " "))
        if am and am.group(1) == num:
            return drop_sensitive(p)
    return None


def apply_parcel(li: Listing, p: dict, now: datetime) -> dict:
    """Fill one listing from one parcel record. Returns what was filled (field -> True)."""
    from .enrichment_owner_mailing import _is_absentee

    if not isinstance(li.raw, dict):
        li.raw = {}
    filled: dict[str, bool] = {}
    opted_out = str(p.get("OptedOut") or "0").strip() not in ("", "0", "false", "False")
    tms = str(p.get("TMS") or "").strip()
    owner = re.sub(r"\s+", " ", str(p.get("Owner_Name") or "")).strip()
    if tms and not li.parcel_id:
        li.parcel_id = tms
        filled["parcel_id"] = True
    agrees: Optional[bool] = None
    if owner and li.owner_name:
        agrees = bool(_words(owner) & _words(li.owner_name))
    if owner and not opted_out and not (li.owner_name or "").strip():
        li.owner_name = owner
        filled["owner_name"] = True
    parts = [str(p.get(k) or "").strip() for k in ("Owner_Addr", "Owner_Ad_1", "Owner_City", "Owner_Stat")]
    mailing = re.sub(r"\s+", " ", " ".join(x for x in parts + [_zip(p.get("Owner_Zip"))] if x)).strip()
    if mailing and not opted_out and agrees is not False:
        g = li.raw.setdefault("gis", {})
        if not g.get("mailing"):
            g["mailing"] = mailing
        om = li.raw.get("owner_mailing")
        if om is None or isinstance(om, dict):
            om = li.raw.setdefault("owner_mailing", {})
            if not om.get("mailing"):
                st = str(p.get("Owner_Stat") or "").strip().upper()[:2] or None
                om.update({"mailing": mailing, "source": "richland_parcel",
                           "absentee": _is_absentee(p.get("Address") or li.street_address, mailing),
                           "mail_state": st, "out_of_state": bool(st and st != "SC")})
                filled["mailing"] = True
    for fld, key in (("market_value", "Market_Val"), ("living_sqft", "Heated_SQF"),
                     ("acreage", "Acreage"), ("bedrooms", "Bldg1_Beds"), ("bathrooms", "Bldg1_Bath")):
        v = _num(p.get(key))
        if v and not getattr(li, fld):
            setattr(li, fld, v)
            filled[fld] = True
    yb = _num(p.get("Bldg1_YrBu"))
    if yb and 1700 < yb <= 2100 and not li.year_built:
        li.year_built = int(yb)
        filled["year_built"] = True
    amt, sd = _num(p.get("Last_Sale1")), _date(p.get("Last_Sale_"))
    if amt or sd:
        ls = li.raw.setdefault("gis", {}).setdefault("last_sale", {})
        if amt and not ls.get("amount"):
            ls["amount"] = amt
            filled["last_sale"] = True
        if sd and not ls.get("date"):
            ls["date"] = sd
    li.raw["richland_parcel"] = {"attempted": now.isoformat(timespec="seconds"), "matched": True,
                                 "tms": tms or None, "opted_out": opted_out,
                                 "owner_agrees": agrees, "source": "richlandmaps.com"}
    return filled


async def _get_json(c, url: str, params: dict) -> Any:
    r = await c.get(url, params=params, timeout=30.0)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.json()


async def enrich_richland_parcel(listings: list[Listing], *, max_lookups: Optional[int] = None,
                                 delay_s: Optional[float] = None, http=None) -> dict:
    """Look up Richland rows on the county viewer API. Returns counts only."""
    if os.environ.get("FORECLOSURE_RICHLAND_PARCEL") == "0":
        return {"skipped": "env"}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cap = int(max_lookups if max_lookups is not None else os.environ.get("RICHLAND_PARCEL_MAX", "300"))
    delay = float(delay_s if delay_s is not None else os.environ.get("RICHLAND_PARCEL_DELAY_S", "1.7"))
    # HOT and WARM rows first (the tier the previous run gave them), then the rest in board order:
    # the per-run cap (about 4 s a row on one host) leaves the remainder for later runs, and on the
    # 10/8 run 1,775 Richland rows were still waiting after the first 300 (audit 2026-10-09).
    todo = sorted((li for li in listings if wants(li, now)), key=_priority)[:cap]
    stats = {"candidates": len(todo), "asked": 0, "matched": 0, "no_point": 0, "no_parcel": 0,
             "errors": 0}
    if not todo:
        return stats

    async def run(c):
        first = True
        for li in todo:
            street = (li.street_address or "").split(",")[0].strip()
            try:
                if not first:
                    await asyncio.sleep(delay)
                first = False
                stats["asked"] += 1
                s = await _get_json(c, SEARCH, {"searchTerm": street, "searchLimit": "10",
                                                "useFuzzyBkp": "1"})
                pt = choose_point((s or {}).get("d") or [], street)
                if not pt:
                    stats["no_point"] += 1
                    li.raw = li.raw if isinstance(li.raw, dict) else {}
                    li.raw["richland_parcel"] = {"attempted": now.isoformat(timespec="seconds"),
                                                 "matched": False, "reason": "no_point"}
                    continue
                await asyncio.sleep(delay)
                d = await _get_json(c, AT_POINT, {"lat": f"{pt[0]:.8f}", "lon": f"{pt[1]:.8f}"})
                p = choose_parcel((d or {}).get("d") or [], street)
                if not p:
                    stats["no_parcel"] += 1
                    li.raw = li.raw if isinstance(li.raw, dict) else {}
                    li.raw["richland_parcel"] = {"attempted": now.isoformat(timespec="seconds"),
                                                 "matched": False, "reason": "no_parcel"}
                    continue
                stats["matched"] += 1
                for k in apply_parcel(li, p, now):
                    stats[f"filled_{k}"] = stats.get(f"filled_{k}", 0) + 1
            except Exception as e:  # noqa: BLE001 - one bad answer must not stop the batch
                stats["errors"] += 1
                log.warning("richland_parcel.error", error=str(e)[:120])

    if http is not None:
        await run(http)
    else:
        from .http_client import client
        async with client(timeout=30.0) as c:
            await run(c)
    log.info("richland_parcel.done", **stats)
    return stats

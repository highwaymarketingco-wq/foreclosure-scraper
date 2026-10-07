"""Charleston County SC building code cases and demolition permits, from the county's own
EnerGov history map layer.

SOURCE
    gisccapps.charlestoncounty.org ENERGOV/energov_history MapServer/0 ("ENERGOV HISTORY POINTS"):
    386,391 rows on 2026-10-07, every module of the county's permitting system, updated daily.
    Two slices are distress:
      * CodeManagement, CASETYPE 'Building Services': building-code cases (1,871 since 2010;
        727 cases of every type in 2025). Planning and Zoning, Environmental Management (yard and
        trash), Stormwater and Short Term Rental cases are NOT read.
      * PermitManagement, WORKCLASS 'Demolition' / 'Demolition - Commercial' (3,222 since 2010,
        about 525 a year; CASETYPE Building (R), Zoning Permit, Manufactured Home, Building (C)).
    Default window: the last 730 days (FORECLOSURE_CHARLESTON_ENERGOV_DAYS).

THE JOIN
    The layer has no address and no parcel: SPATIALID is an address-point GUID that matches no
    published key. Each point sits on the county's address point (verified 2026-10-07: 20 of 20
    sampled demolition points had an address point within 3 m), so the points are matched in
    batches of 100 to "County Address Points" (ENERGOV/energov_css MapServer/0, the layer the
    Charleston parcel cache already uses for situs) within 3 m, which gives PID (the parcel
    cache's key) and WHOLE_ADDRESS. Owner and mailing then come from the parcel cache join.

WHAT A ROW MEANS
    One lead per parcel (or address when the point has no PID): its building-code cases and
    demolition permits in the window. The layer carries no case status, so a code case is
    treated as open for 365 days from its date (raw code_enforcement block, stale_after) and
    then ages out; a demolition permit is an owner's or buyer's application, not a
    condemnation, so it carries no condemned flag (New Hanover demolition-permit precedent).

DATELESS: no sale date; slug counties_sc.charleston_energov_history goes in
main.DATELESS_OK_SOURCES. Gate: FORECLOSURE_CHARLESTON_ENERGOV=0.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import structlog

from ... import arcgis_webmap as agw
from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...sensitive_fields import drop_sensitive
from ..counties_generic._layer_kit import clean, match_points

log = structlog.get_logger()

SLUG = "counties_sc.charleston_energov_history"
ENV_OFF = "FORECLOSURE_CHARLESTON_ENERGOV"
ENV_DAYS = "FORECLOSURE_CHARLESTON_ENERGOV_DAYS"

HISTORY = ("https://gisccapps.charlestoncounty.org/arcgis/rest/services/ENERGOV/"
           "energov_history/MapServer/0")
ADDRESSES = ("https://gisccapps.charlestoncounty.org/arcgis/rest/services/ENERGOV/"
             "energov_css/MapServer/0")
PAGE_URL = "https://www.charlestoncounty.org/departments/building-inspection-services/"

HIST_FIELDS = ("OBJECTID", "MODULENAME", "CASENUMBER", "CASETYPE", "WORKCLASS", "APPLICATIONDATE")
ADDR_FIELDS = ("PID", "WHOLE_ADDRESS", "UNIT", "POSTAL_TOWN", "POSTAL_CODE")
CODE_TYPES = ("Building Services",)
OPEN_DAYS = 365


def where_clauses(since: datetime) -> dict[str, str]:
    d = f"APPLICATIONDATE >= DATE '{since:%Y-%m-%d}'"
    types = ",".join(f"'{t}'" for t in CODE_TYPES)
    return {
        "code": f"MODULENAME='CodeManagement' AND CASETYPE IN ({types}) AND {d}",
        "demolition": f"MODULENAME='PermitManagement' AND WORKCLASS LIKE 'Demolition%' AND {d}",
    }


def _ms(v) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def unique_cases(features: Iterable[dict], kind: str) -> list[dict]:
    """One record per CASENUMBER (the history repeats a case per queue event), newest date,
    with its point."""
    by: dict[str, dict] = {}
    for f in features:
        a = drop_sensitive(f.get("attributes") or {})
        g = f.get("geometry") or {}
        num = clean(a.get("CASENUMBER"))
        if not num or "x" not in g:
            continue
        d = _ms(a.get("APPLICATIONDATE"))
        cur = by.get(num)
        if cur is None or (d and (cur["date"] is None or d > cur["date"])):
            by[num] = {"kind": kind, "case": num, "type": clean(a.get("CASETYPE")),
                       "workclass": clean(a.get("WORKCLASS")), "date": d,
                       "pt": (float(g["x"]), float(g["y"]))}
    return list(by.values())


def group_by_property(cases: list[dict], addrs: list[Optional[dict]]) -> list[dict]:
    groups: dict[str, dict] = {}
    unmatched = 0
    for c, a in zip(cases, addrs):
        if not a:
            unmatched += 1
            continue
        pid = clean(a.get("PID"))
        addr = clean(a.get("WHOLE_ADDRESS"))
        key = f"p:{pid}" if pid else (f"a:{addr.lower()}" if addr else None)
        if not key:
            unmatched += 1
            continue
        g = groups.setdefault(key, {"pid": pid, "address": addr, "town": clean(a.get("POSTAL_TOWN")),
                                    "zip": clean(a.get("POSTAL_CODE")), "code": [], "demolition": []})
        g[c["kind"]].append(c)
    for g in groups.values():
        for k in ("code", "demolition"):
            g[k].sort(key=lambda c: c["date"] or datetime.min, reverse=True)
    out = list(groups.values())
    if out:
        out[0]["_unmatched"] = unmatched
    return out


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.date().isoformat() if d else None


def to_listing(g: dict, *, now: Optional[datetime] = None) -> Listing:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    code, demo = g["code"], g["demolition"]
    raw: dict[str, Any] = {"charleston_energov": {
        "code_cases": [{"case": c["case"], "type": c["type"], "date": _iso(c["date"])} for c in code[:10]],
        "demolition_permits": [{"permit": c["case"], "workclass": c["workclass"], "type": c["type"],
                                "date": _iso(c["date"])} for c in demo[:10]],
        "source": "energov_history",
    }}
    if code:
        newest = code[0]["date"]
        raw["code_enforcement"] = {
            "county": "Charleston",
            "open_violations": len(code),
            "total_violations": len(code),
            "prior_cases": 0,
            "repeat_offender": len(code) > 1,
            "violation_types": sorted({c["type"] for c in code if c["type"]}),
            "severe": True,
            "violations": [{"violation": c["type"] or "Building Services", "status": "filed",
                            "date": _iso(c["date"]), "case_id": c["case"]} for c in code[:10]],
            "status_known": False,
            "stamped_at": now.date().isoformat(),
            "stale_after": ((newest or now) + timedelta(days=OPEN_DAYS)).date().isoformat(),
            "source": SLUG,
        }
    if demo:
        raw["demolition_permit"] = {
            "count": len(demo), "latest_date": _iso(demo[0]["date"]),
            "manufactured_home": any((c["type"] or "").lower().startswith("manufactured") for c in demo),
            "source": SLUG,
        }
    bits = []
    if code:
        bits.append(f"{len(code)} building code case{'s' if len(code) > 1 else ''} (latest {_iso(code[0]['date'])})")
    if demo:
        bits.append(f"{len(demo)} demolition permit{'s' if len(demo) > 1 else ''} (latest {_iso(demo[0]['date'])})")
    return Listing(
        source=SLUG,
        source_url=PAGE_URL,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county="Charleston",
        street_address=g["address"],
        city=(g["town"] or "").title() or None,
        zip_code=g["zip"],
        parcel_id=g["pid"],
        foreclosure_process="code_enforcement" if code else "demolition_permit",
        description=f"Charleston County SC: {'; '.join(bits)} — {g['address'] or g['pid']}"[:300],
        first_seen=now, last_seen=now,
        raw=raw,
    )


class CharlestonEnergovHistory(BaseScraper):
    slug = SLUG
    name = "Charleston County SC building code cases + demolition permits (EnerGov history)"
    category = "county_distress"
    expected_min_count = 0

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF) == "0":
            return []
        try:
            days = int(os.environ.get(ENV_DAYS) or 730)
        except ValueError:
            days = 730
        since = datetime.now(timezone.utc) - timedelta(days=days)
        cases: list[dict] = []
        async with client(timeout=90.0) as c:
            for kind, where in where_clauses(since).items():
                feats = await agw.query_features(c, HISTORY, out_fields=",".join(HIST_FIELDS),
                                                 where=where, return_geometry=True, out_sr=4326,
                                                 page=1000)
                cases.extend(unique_cases(feats, kind))
            addrs = await match_points(c, ADDRESSES, [x["pt"] for x in cases], ADDR_FIELDS,
                                       distance_m=3.0)
        groups = group_by_property(cases, addrs)
        out = [to_listing(g) for g in groups]
        log.info("charleston_energov.done", cases=len(cases), leads=len(out),
                 unmatched=(groups[0].get("_unmatched") if groups else 0))
        return out

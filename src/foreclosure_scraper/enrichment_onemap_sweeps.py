"""NC OneMap statewide sweeps: two county-wide screens that were "built" for a few hundred leads and
never screened the county (top-80 build list 2026-10-09: heir_estate, rollback_exposure).

WHY. Two cube columns were read off the statewide parcel layer (NC1Map_Parcels, free ArcGIS REST, no
login) only as a capped lead list:

  heir_estate        scrapers/counties_nc/nc_heir_estate_parcels reads at most 400 matching parcels per
                     county (highest value first) and emits each as a lead. 49 of the 99 NC counties that
                     have any match hold more than 400 (measured 2026-10-09: Forsyth 3,062, Catawba 2,208,
                     Halifax 2,153, ... 65,037 matching parcels statewide), so for those the county is
                     sampled, not screened, and a board row from ANY other source whose parcel is titled
                     "<name> HEIRS" / "ESTATE OF <name>" never got the flag.
  rollback_exposure  the present-use (farm / forest) deferral comes due in full on a sale. Dedicated county
                     layers exist for six counties (enrichment_tax_relief, enrichment_rollback_deferral);
                     the statewide layer carries a per-parcel present-use flag, `presentval`, a Y/N string.

WHAT THIS DOES (no row is added; existing board rows are flagged, and each county is screened in full):
  1. One paged statewide pass for each column (ArcGIS resultOffset, ordered by objectid, one request at a
     time, PACE_S apart): heir/estate titled parcels, and present-use parcels (`presentval = 'Y'`).
  2. The present-use flag is trusted only where it behaves like a flag. Measured 2026-10-09: 51 counties
     carry any Y; in seven the flag is on nearly every parcel (Johnston 99%, Rowan 99%, Wayne 97%,
     Wilson 97%, Yadkin 100%, Caswell 99%, Carteret 49%: a different meaning) and in 49 it is N on every
     parcel (the county does not populate it). Only counties with a Y share of at most 25% and at least
     one Y are used (44 on the day); the rest are not screened and are left to their county layers.
  3. Every NC board row whose parcel is in an index gets the flag, never overwriting a richer stamp:
       raw.heir_estate        {owner_of_record, match, heir_names, source: nc_onemap_sweep, ...}
       raw.rollback_exposure  {basis: present_use_flag, deferred_value: None, ...}: the flag says a
                              deferral exists, not its size (no dollar figure is invented)
  4. A county is SCREENED for a column only when its sweep finished without a failed page. The run stats
     carry `screened`: {column: ["NC|County", ...]}; screen_ledger turns them into the cube's "screened,
     none found" (a county with no parcel flagged is a clean negative, not a gap).

The sweep result is cached under data/onemap_sweeps (CACHE_TTL_DAYS); a tail run reuses it. Kill switch:
FORECLOSURE_ONEMAP_SWEEPS_OFF=1. Counts and parcel ids only; no private data is read (owner names are the
public roll's and are not stored in the cache beyond the match kind).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx
import structlog

from . import parcel_cache
from .http_client import client
from .models import Listing, _normalize_parcel
from .validation import NC_COUNTIES

log = structlog.get_logger()

ENV_OFF = "FORECLOSURE_ONEMAP_SWEEPS_OFF"
URL = parcel_cache.NC_ONEMAP_URL
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "onemap_sweeps"
CACHE_TTL_DAYS = int(os.environ.get("ONEMAP_SWEEPS_TTL_DAYS", "7"))
PACE_S = float(os.environ.get("ONEMAP_SWEEPS_PACE_S", "2.0"))
PAGE = 2000
MAX_PAGES = 400                     # a stall guard: the heir sweep is about 33 pages, present-use about 80
#: a county's present-use flag is trusted at or below this share of its parcels (see the docstring)
MAX_FLAG_SHARE = 0.25
RECORD_STATE = "NC"
SOURCE_HEIR = "nc_onemap_sweep"
SOURCE_PUV = "nc_onemap_presentval"
ROLLBACK_YEARS_NC = 4              # G.S. 105-277.4(c): the year of disqualification plus three before

_HEIR_FIELDS = "parno,altparno,cntyname,ownname,ownname2"
_PUV_FIELDS = "parno,altparno,cntyname"


class SweepError(RuntimeError):
    """A page failed: the sweep is incomplete and must not be claimed as a screen."""


# ---------------------------------------------------------------------------------------------
# paging
# ---------------------------------------------------------------------------------------------

RETRIES = 3


async def _get(http: httpx.AsyncClient, params: dict) -> dict:
    """One /query call; a slow or failed answer is retried (RETRIES, growing pause) before the sweep
    is declared incomplete. The statewide layer is large: a grouped statistics call takes about 40 s."""
    last = "no attempt"
    for attempt in range(RETRIES):
        if attempt:
            await _pause(attempt)
        try:
            r = await http.get(URL, params={**params, "f": "json", "returnGeometry": "false"}, timeout=120.0)
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {str(exc)[:100]}"
            continue
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            continue
        try:
            d = r.json()
        except ValueError:
            last = "not JSON"
            continue
        if not isinstance(d, dict) or d.get("error"):
            last = f"layer error {str((d or {}).get('error'))[:100]}"
            continue
        return d
    raise SweepError(last)


async def _sweep(http: httpx.AsyncClient, where: str, fields: str) -> list[dict]:
    """Every row matching `where`, paged by objectid with a keyset (`objectid > last`), not an
    offset: deep offsets on this layer take 10+ s a page, keyset pages stay under 2 s. Raises
    SweepError on any failed page, so a sweep is complete or it is an error."""
    rows: list[dict] = []
    last = -1
    flds = fields if "objectid" in fields.split(",") else fields + ",objectid"
    for page_no in range(MAX_PAGES):
        d = await _get(http, {"where": f"({where}) AND objectid > {last}", "outFields": flds,
                              "orderByFields": "objectid", "resultRecordCount": str(PAGE)})
        page = [f.get("attributes") or {} for f in d.get("features") or []]
        rows.extend(page)
        log.info("onemap_sweeps.page", page=page_no + 1, rows=len(rows))
        if not page or not d.get("exceededTransferLimit"):
            return rows
        ids = [a.get("objectid") for a in page if isinstance(a.get("objectid"), (int, float))]
        if not ids or max(ids) <= last:
            raise SweepError("objectid did not advance")
        last = int(max(ids))
        await _pause()
    raise SweepError(f"more than {MAX_PAGES} pages")


async def _stats(http: httpx.AsyncClient, where: str) -> dict[str, int]:
    """{county: count} for `where` (one grouped statistics request)."""
    d = await _get(http, {"where": where, "groupByFieldsForStatistics": "cntyname",
                          "outStatistics": json.dumps([{"statisticType": "count",
                                                        "onStatisticField": "objectid",
                                                        "outStatisticFieldName": "n"}])})
    return {str(f["attributes"]["cntyname"]): int(f["attributes"]["n"]) for f in d.get("features") or []
            if f.get("attributes", {}).get("cntyname")}


async def _pause(times: int = 1) -> None:
    import asyncio
    await asyncio.sleep(PACE_S * max(times, 1))


# ---------------------------------------------------------------------------------------------
# the two sweeps (pure parts are tested without the network)
# ---------------------------------------------------------------------------------------------

def reliable_flag_counties(flag_counts: dict[str, int], totals: dict[str, int],
                           max_share: float = MAX_FLAG_SHARE) -> list[str]:
    """Counties whose present-use flag behaves like a flag: at least one Y, Y on at most `max_share`
    of the county's parcels."""
    out = []
    for county, n in sorted(flag_counts.items()):
        tot = totals.get(county) or 0
        if n > 0 and tot > 0 and n / tot <= max_share:
            out.append(county)
    return out


def _owner_fields(attrs: dict) -> list[str]:
    return [str(attrs[k]).strip() for k in ("ownname", "ownname2") if attrs.get(k) and str(attrs[k]).strip()]


def classify_heir_row(attrs: dict) -> Optional[dict]:
    """{owner, match, heir_names} for a decedent-titled parcel, else None. Same rule as
    nc_heir_estate_parcels (HEIR / ESTATE tokens; LIFE ESTATE, REAL ESTATE and 'ESTATES' excluded)."""
    from .scrapers.counties_nc import nc_heir_estate_parcels as H
    fields = _owner_fields(attrs)
    if not fields or not H._is_decedent(fields) or H._excluded_row(fields):  # noqa: SLF001
        return None
    owner = H._owner_display(fields)  # noqa: SLF001
    if not owner:
        return None
    return {"owner": owner[:80], "match": "heirs" if H._HEIR_TOKEN.search(owner) else "estate",  # noqa: SLF001
            "heir_names": H._heir_names(fields)}  # noqa: SLF001


def _keys(attrs: dict) -> list[str]:
    ks = []
    for f in ("parno", "altparno"):
        k = _normalize_parcel(str(attrs.get(f) or ""))
        if k and k not in ks:
            ks.append(k)
    return ks


def build_heir_index(rows: Iterable[dict]) -> dict[str, dict[str, dict]]:
    """{county: {normalized parcel key: {o, m, h}}} from the swept rows."""
    idx: dict[str, dict[str, dict]] = {}
    for a in rows:
        hit = classify_heir_row(a)
        county = str(a.get("cntyname") or "").strip()
        if not hit or not county:
            continue
        rec = {"o": hit["owner"], "m": hit["match"], "h": hit["heir_names"]}
        for k in _keys(a):
            idx.setdefault(county, {})[k] = rec
    return idx


def build_flag_index(rows: Iterable[dict]) -> dict[str, dict[str, int]]:
    idx: dict[str, dict[str, int]] = {}
    for a in rows:
        county = str(a.get("cntyname") or "").strip()
        if not county:
            continue
        for k in _keys(a):
            idx.setdefault(county, {})[k] = 1
    return idx


# ---------------------------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------------------------

def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.json"


def load_cache(name: str, today: Optional[date] = None) -> Optional[dict]:
    today = today or date.today()
    try:
        d = json.loads(_cache_path(name).read_text())
        done = date.fromisoformat(str(d.get("swept_on")))
    except Exception:  # noqa: BLE001
        return None
    return d if (today - done).days <= CACHE_TTL_DAYS and d.get("complete") else None


def save_cache(name: str, doc: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")))
        tmp.replace(_cache_path(name))
    except Exception as exc:  # noqa: BLE001 - a cache that cannot be written costs one re-sweep
        log.warning("onemap_sweeps.cache_write_failed", name=name, error=str(exc)[:100])


_HEIR_WHERE = ("(UPPER(ownname) LIKE '%HEIR%' OR UPPER(ownname) LIKE '%ESTATE%' "
               "OR UPPER(ownname2) LIKE '%HEIR%' OR UPPER(ownname2) LIKE '%ESTATE%')")


async def sweep_heir(http: httpx.AsyncClient, today: Optional[date] = None) -> dict:
    """{swept_on, complete, counties_swept, index} for heir/estate titled parcels, all 100 counties."""
    cached = load_cache("heir_estate", today)
    if cached:
        return cached
    rows = await _sweep(http, _HEIR_WHERE, _HEIR_FIELDS)
    idx = build_heir_index(rows)
    # a finished statewide pass (no failed page) screened every county of the layer
    doc = {"swept_on": (today or date.today()).isoformat(), "complete": True, "rows_read": len(rows),
           "counties_swept": sorted(NC_COUNTIES), "matches": {c: len(v) for c, v in sorted(idx.items())},
           "index": idx}
    save_cache("heir_estate", doc)
    return doc


async def sweep_present_use(http: httpx.AsyncClient, today: Optional[date] = None) -> dict:
    """{swept_on, complete, counties_swept, counties_skipped, index} for present-use flagged parcels."""
    cached = load_cache("present_use", today)
    if cached:
        return cached
    totals = await _stats(http, "1=1")
    await _pause()
    flagged = await _stats(http, "presentval = 'Y'")
    await _pause()
    use = reliable_flag_counties(flagged, totals)
    skipped = {c: ("flag on most parcels" if flagged[c] / max(totals.get(c) or 1, 1) > MAX_FLAG_SHARE
                   else "no flag") for c in sorted(flagged) if c not in use}
    quoted = ",".join("'" + c.replace("'", "''") + "'" for c in use)
    rows = await _sweep(http, f"presentval = 'Y' AND cntyname IN ({quoted})", _PUV_FIELDS) if use else []
    idx = build_flag_index(rows)
    doc = {"swept_on": (today or date.today()).isoformat(), "complete": True, "rows_read": len(rows),
           "counties_swept": use, "counties_skipped": skipped,
           "matches": {c: len(v) for c, v in sorted(idx.items())}, "index": idx}
    save_cache("present_use", doc)
    return doc


# ---------------------------------------------------------------------------------------------
# stamping
# ---------------------------------------------------------------------------------------------

def _county_of(li: Any) -> str:
    name = str(getattr(li, "county", "") or "").replace(" County", "").strip()
    return parcel_cache._nc_name_ci(name) or name.title()  # noqa: SLF001 - "Mcdowell" -> "McDowell"


def _is_nc(li: Any) -> bool:
    return str(getattr(li, "state", "") or "").strip().upper() == RECORD_STATE


def stamp_heir(li: Any, hit: dict, swept_on: str) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    if raw.get("heir_estate"):
        return False
    raw["heir_estate"] = {"owner_of_record": hit["o"], "heir_names": hit.get("h") or [], "mailing": None,
                          "care_of": None, "match": hit["m"], "source": SOURCE_HEIR, "swept_on": swept_on}
    li.raw = raw
    return True


def stamp_rollback(li: Any, county: str, swept_on: str) -> bool:
    raw = li.raw if isinstance(li.raw, dict) else {}
    if raw.get("rollback_exposure"):
        return False             # a county layer's richer stamp (dollar figures) is never overwritten
    raw["rollback_exposure"] = {
        "deferred_value": None, "rollback_years": ROLLBACK_YEARS_NC, "annual_deferred_tax": None,
        "estimated_rollback": None, "estimate_is_floor": None,
        "tax_rate_source": "unavailable_flag_only", "basis": "present_use_flag",
        "county": county, "state": RECORD_STATE,
        "source": "NC OneMap statewide parcel layer (presentval = Y)", "source_key": SOURCE_PUV,
        "match_method": "parcel", "swept_on": swept_on}
    li.raw = raw
    return True


def apply_indexes(listings: Iterable[Any], heir: Optional[dict], puv: Optional[dict]) -> dict:
    """Stamp the board rows from the two swept indexes. Pure (no network)."""
    stats = {"nc_rows_with_parcel": 0, "heir_estate_stamped": 0, "heir_estate_already": 0,
             "rollback_stamped": 0, "rollback_already": 0}
    h_idx = (heir or {}).get("index") or {}
    p_idx = (puv or {}).get("index") or {}
    h_on = (heir or {}).get("swept_on") or ""
    p_on = (puv or {}).get("swept_on") or ""
    p_ok = set((puv or {}).get("counties_swept") or [])
    for li in listings:
        if not _is_nc(li):
            continue
        pid = _normalize_parcel(getattr(li, "parcel_id", None))
        county = _county_of(li)
        if not pid or not county:
            continue
        stats["nc_rows_with_parcel"] += 1
        hit = (h_idx.get(county) or {}).get(pid)
        if hit:
            if stamp_heir(li, hit, h_on):
                stats["heir_estate_stamped"] += 1
            else:
                stats["heir_estate_already"] += 1
        if county in p_ok and pid in (p_idx.get(county) or {}):
            if stamp_rollback(li, county, p_on):
                stats["rollback_stamped"] += 1
            else:
                stats["rollback_already"] += 1
    return stats


def screened_counties(heir: Optional[dict], puv: Optional[dict]) -> dict[str, list[str]]:
    """{cube column: ['NC|County', ...]} the complete sweeps screened."""
    out: dict[str, list[str]] = {}
    if heir and heir.get("complete"):
        out["heir_estate"] = [f"{RECORD_STATE}|{c}" for c in sorted(heir.get("counties_swept") or [])]
    if puv and puv.get("complete"):
        out["rollback_exposure"] = [f"{RECORD_STATE}|{c}" for c in sorted(puv.get("counties_swept") or [])]
    return out


async def enrich_onemap_sweeps(listings: list[Listing]) -> dict:
    """Run both sweeps (cached for CACHE_TTL_DAYS) and flag the board's NC rows. Never raises."""
    if os.environ.get(ENV_OFF) == "1":
        return {"skipped": f"{ENV_OFF}=1"}
    t0 = time.monotonic()
    heir = puv = None
    errors: dict[str, str] = {}
    async with client(timeout=60.0) as http:
        for name, fn in (("heir_estate", sweep_heir), ("present_use", sweep_present_use)):
            try:
                doc = await fn(http)
                if name == "heir_estate":
                    heir = doc
                else:
                    puv = doc
            except SweepError as exc:
                errors[name] = str(exc)[:120]
                log.warning("onemap_sweeps.failed", sweep=name, error=str(exc)[:120])
            except Exception as exc:  # noqa: BLE001
                errors[name] = f"{type(exc).__name__}: {str(exc)[:100]}"
                log.warning("onemap_sweeps.failed", sweep=name, error=errors[name])
    stats = apply_indexes(listings, heir, puv)
    stats.update(
        screened=screened_counties(heir, puv), errors=errors, seconds=round(time.monotonic() - t0, 1),
        heir_swept_on=(heir or {}).get("swept_on"), puv_swept_on=(puv or {}).get("swept_on"),
        heir_matches=sum((heir or {}).get("matches", {}).values()),
        puv_matches=sum((puv or {}).get("matches", {}).values()),
        puv_counties=len((puv or {}).get("counties_swept") or []),
        puv_skipped=(puv or {}).get("counties_skipped") or {})
    log.info("onemap_sweeps.done", **{k: v for k, v in stats.items() if not isinstance(v, (dict, list))})
    return stats

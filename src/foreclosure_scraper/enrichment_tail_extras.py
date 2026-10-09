"""Enrichers that were built but only scripts ran, wired into main.run_enrich_tail (audit 2026-10-09,
unwired_enrichers; docs/audit_2026-10-09/unwired_enrichers.md has the per-module decisions).

Four steps, each idempotent (a second pass with the same inputs changes nothing), budgeted (no step
can hold the tail past its budget) and incremental (a network step only touches rows that lack its
key or whose check is older than its refresh age). The two LOCAL steps never open a connection, so
scripts/reconcile_board.py runs them; the two NETWORK steps are stubbed there.

  enrich_local_pre_gate(listings)       LOCAL, just before the call-ready gate
      flood_zone   mirrored from raw['flood'], which enrichment_flood (the run's FEMA NFHL reader)
                   writes; enrichment_flood_zone read the same FEMA layer a second time and is
                   retired as a fetcher. 18,428 rows of the 10/7 board carried a stored failure
                   (zone None) beside a real raw['flood'] zone, 16,043 had raw['flood'] only.
      hud_fmr      HUD Fair Market Rent from the cached county/metro table
                   (data/fmr_cache/fmr_by_county.json; refreshed on a schedule by
                   scripts/refresh_fmr_cache.py, which needs the HUD token): no network here. Every
                   row the table covers gets the block for its county and bedroom count, so a
                   new FMR year or a corrected bedroom count reaches every row on the next run.
                   It no longer writes raw['census_rent'] (that blocked the ACS rent enricher).
      septic       Buncombe septic permits, applied from the cached county layer
                   (data/cache/septic_buncombe.json.gz, refreshed weekly by the network step):
                   every Buncombe row with a parcel gets its parcel's current summary, a row whose
                   parcel no longer has a case loses the block and the land_distress it set.
  enrich_local_after_qa(listings)        LOCAL, right after enrich_board_qa
      source_consistency   enrich_board_qa ASSIGNS raw['qa_flags'] every run, which deleted these
                           four self-contradiction flags (115 rows still carried one on 10/7)
      property_category    the dashboard's category filter and badge: 56% of a 14,000-row sample
                           of the 10/7 board had no category, 1.7% a stale one
  enrich_network_pre_value(listings)     NETWORK, before the valuation loop (it fills sqft/value)
      bt_appraisal_card    the assessor's appraisal card in the 14 BT portal counties for rows
                           with no heated sqft: never checked or checked over 30 days ago, HOT and
                           WARM first, BT_CARD_MAX (300) a run, inside TAIL_BT_CARD_BUDGET_S (600)
  enrich_network_geo(listings)           NETWORK, in the post-board geographic group
      septic layer refresh  at most once in SEPTIC_REFRESH_DAYS (7), then applied
      wetlands              National Wetlands Inventory (USFWS, the public service on
                            fwspublicservices.wim.usgs.gov; the fws.gov address the module used
                            answers 403 'excessive crawling'), polygons within WETLANDS_RADIUS_M of
                            the row's point, for HOT/WARM and land rows never checked or checked
                            over 365 days ago; WETLANDS_MAX points a run inside the budget

The DNC scrub is its own tail step (enrichment_dnc.enrich_dnc_scrub, local, before the gate).
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import structlog

log = structlog.get_logger()

_REPO = Path(__file__).resolve().parent.parent.parent
SEPTIC_CACHE = Path(os.environ.get("SEPTIC_CACHE", str(_REPO / "data" / "cache" / "septic_buncombe.json.gz")))
SEPTIC_REFRESH_DAYS = float(os.environ.get("SEPTIC_REFRESH_DAYS", "7") or 7)
BT_RECHECK_DAYS = 30
WETLANDS_RECHECK_DAYS = 365
WETLANDS_RADIUS_M = int(os.environ.get("WETLANDS_RADIUS_M", "60") or 60)
WETLANDS_MAX = int(os.environ.get("WETLANDS_MAX", "5000") or 5000)
WETLANDS_CONCURRENCY = int(os.environ.get("WETLANDS_CONCURRENCY", "4") or 4)
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _env_s(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _raw(li) -> dict:
    if not isinstance(getattr(li, "raw", None), dict):
        li.raw = {}
    return li.raw


def _tier(li) -> str:
    ds = _raw(li).get("distress_stack")
    return str(ds.get("tier") or "") if isinstance(ds, dict) else ""


def _age_days(iso: Any, now: datetime) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 86400.0


def _due(block: Any, days: float, now: datetime) -> bool:
    """True when `block` (a dict carrying checked_at) is missing, undated or older than `days`."""
    if not isinstance(block, dict):
        return True
    age = _age_days(block.get("checked_at"), now)
    return age is None or age > days


def _step(stats: dict, name: str, fn, *a, **k):
    t0 = time.monotonic()
    try:
        out = fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 - one step never costs the others
        log.error(f"tail_extras.{name}.failed", error=f"{type(exc).__name__}: {exc}"[:300])
        out = {"failed": f"{type(exc).__name__}: {exc}"[:200]}
    if isinstance(out, dict):
        out.setdefault("seconds", round(time.monotonic() - t0, 1))
    stats[name] = out
    return out


# ----------------------------------------------------------------------------------- flood_zone
def mirror_flood_zone(listings: Iterable) -> dict:
    from .enrichment_flood_zone import flood_zone_from_flood
    st = {"mirrored": 0, "changed": 0, "flood_zone_only": 0}
    for li in listings:
        raw = _raw(li)
        want = flood_zone_from_flood(raw.get("flood"))
        if want is None:
            if raw.get("flood_zone"):
                st["flood_zone_only"] += 1          # an older reading with no raw['flood']: kept
            continue
        st["mirrored"] += 1
        if raw.get("flood_zone") != want:
            raw["flood_zone"] = want
            st["changed"] += 1
    return st


# ----------------------------------------------------------------------------------- hud_fmr
def load_fmr_table(path: Optional[Path] = None) -> Optional[dict]:
    from . import enrichment_hud_fmr as H
    p = Path(path) if path else H._CACHE_FILE
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if not (d.get("county_rent") or d.get("metro_rent")):
        return None
    return d


def fmr_for(state: str, county: str, table: dict) -> Optional[dict]:
    """enrichment_hud_fmr._match_listing_to_fmr on a loaded table (no module state)."""
    county_rent, metro_rent = table.get("county_rent") or {}, table.get("metro_rent") or {}
    cfips = table.get("county_fips") or {}
    if not county:
        return None
    key = county.lower().replace(" county", "").strip()
    code = (cfips.get(state) or {}).get(key) if state else None
    if code:
        if code in metro_rent:
            return metro_rent[code]
        if code in county_rent:
            return county_rent[code]
    for rent in metro_rent.values():
        if key and key in str(rent.get("area_name", "")).lower():
            return rent
    return None


def apply_hud_fmr(listings: Iterable, table: Optional[dict] = None) -> dict:
    from .enrichment_hud_fmr import _pick_fmr
    table = table if table is not None else load_fmr_table()
    if not table:
        return {"skipped": "no FMR table (data/fmr_cache/fmr_by_county.json): run scripts/refresh_fmr_cache.py"}
    st = {"matched": 0, "changed": 0, "no_match": 0, "table_cached_at": table.get("cached_at")}
    for li in listings:
        raw = _raw(li)
        rent = fmr_for(str(getattr(li, "state", "") or ""), str(getattr(li, "county", "") or ""), table)
        if not rent:
            st["no_match"] += 1
            continue
        try:
            beds = int(li.bedrooms) if getattr(li, "bedrooms", None) else None
        except (TypeError, ValueError):
            beds = None
        info = _pick_fmr(rent, beds)
        if not info:
            st["no_match"] += 1
            continue
        st["matched"] += 1
        if raw.get("hud_fmr") != info:
            raw["hud_fmr"] = info
            st["changed"] += 1
    return st


# ----------------------------------------------------------------------------------- septic
def _is_buncombe_row(li) -> bool:
    from .enrichment_septic_status import _is_buncombe
    return _is_buncombe(li) and bool((getattr(li, "parcel_id", None) or "").strip())


def read_septic_cache(path: Optional[Path] = None) -> tuple[Optional[list], Optional[str]]:
    p = Path(path) if path else SEPTIC_CACHE
    if not p.is_file():
        return None, None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        d = json.load(f)
    feats = d.get("features")
    return (feats if isinstance(feats, list) and feats else None), d.get("fetched_at")


def write_septic_cache(features: list, fetched_at: str, path: Optional[Path] = None) -> None:
    p = Path(path) if path else SEPTIC_CACHE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({"fetched_at": fetched_at, "features": features}, f)
    os.replace(tmp, p)


def apply_septic(listings: Iterable, features: Optional[list], fetched_at: Optional[str],
                 now: Optional[datetime] = None) -> dict:
    """Every Buncombe row with a parcel gets its parcel's septic summary from `features` (the
    county layer); a row whose parcel has no case loses the block and the land_distress it set."""
    from .enrichment_septic_status import _normalize_parcel, index_by_parcel, summarize_parcel
    if not features:
        return {"skipped": "no septic layer cache (the network step fetches it)"}
    now = now or datetime.now(timezone.utc)
    by_parcel = index_by_parcel(features)
    st = {"targets": 0, "matched": 0, "changed": 0, "cleared": 0, "adverse": 0, "layer_fetched_at": fetched_at}
    for li in listings:
        if not _is_buncombe_row(li):
            continue
        st["targets"] += 1
        raw = _raw(li)
        pid = _normalize_parcel(li.parcel_id)
        recs = by_parcel.get(pid) if pid else None
        summary = summarize_parcel(recs, now=now) if recs else None
        if not summary:
            if "septic" in raw or "land_distress" in raw:
                raw.pop("septic", None)
                raw.pop("land_distress", None)     # enrichment_septic_status is its only writer
                st["cleared"] += 1
            continue
        st["matched"] += 1
        want = {**summary, "checked_at": fetched_at}
        if raw.get("septic") != want:
            raw["septic"] = want
            st["changed"] += 1
        if summary.get("land_distress"):
            raw["land_distress"] = True
            st["adverse"] += 1
        else:
            raw.pop("land_distress", None)
    return st


async def refresh_septic_cache(budget_s: float, now: Optional[datetime] = None) -> dict:
    from .enrichment_septic_status import ENV_OFF, fetch_septic_records
    from .http_client import client
    if os.environ.get(ENV_OFF) == "1":
        return {"skipped": f"{ENV_OFF}=1"}
    now = now or datetime.now(timezone.utc)
    _, fetched_at = read_septic_cache()
    age = _age_days(fetched_at, now) if fetched_at else None
    if age is not None and age <= SEPTIC_REFRESH_DAYS:
        return {"fresh": True, "age_days": round(age, 1)}

    async def _fetch():
        async with client(timeout=90.0) as http:
            return await fetch_septic_records(http)
    feats = await asyncio.wait_for(_fetch(), timeout=budget_s)
    if not feats:
        return {"fetched": 0, "kept_old_cache": fetched_at}
    stamp = now.isoformat()
    write_septic_cache(feats, stamp)
    return {"fetched": len(feats), "fetched_at": stamp}


# ----------------------------------------------------------------------------------- bt cards
def bt_targets(listings: Iterable, now: datetime) -> list:
    from .enrichment_bt_appraisal_card import card_url
    out = []
    for li in listings:
        if (getattr(li, "state", "") or "").upper() != "NC" or getattr(li, "living_sqft", None):
            continue
        pid = getattr(li, "parcel_id", None)
        if not pid or not card_url(getattr(li, "county", "") or "", pid):
            continue
        if not _due(_raw(li).get("bt_appraisal_card"), BT_RECHECK_DAYS, now):
            continue
        out.append(li)
    order = {"HOT": 0, "WARM": 1}
    out.sort(key=lambda li: order.get(_tier(li), 2))
    return out


async def run_bt_cards(listings: Iterable, budget_s: float, now: Optional[datetime] = None) -> dict:
    from . import enrichment_bt_appraisal_card as BT
    now = now or datetime.now(timezone.utc)
    targets = bt_targets(listings, now)[:BT.MAX_CARDS]
    if not targets:
        return {"eligible": 0}
    stamp = now.isoformat()
    try:
        stats = await asyncio.wait_for(BT.enrich_bt_appraisal_card(targets), timeout=budget_s)
    except asyncio.TimeoutError:
        stats = {"time_capped": budget_s}
    for li in targets:
        blk = _raw(li).get("bt_appraisal_card")
        if isinstance(blk, dict) and not blk.get("checked_at"):
            blk["checked_at"] = stamp           # a card read this run, or a 'no_card' answer
    stats["selected"] = len(targets)
    return stats


# ----------------------------------------------------------------------------------- wetlands
def wetlands_targets(listings: Iterable, now: datetime) -> list:
    out = []
    for li in listings:
        if not (getattr(li, "latitude", None) and getattr(li, "longitude", None)):
            continue
        tier = _tier(li)
        kind = str(getattr(getattr(li, "property_kind", None), "value", getattr(li, "property_kind", "")) or "").lower()
        if tier not in ("HOT", "WARM") and kind != "land":
            continue
        if not _due(_raw(li).get("wetlands"), WETLANDS_RECHECK_DAYS, now):
            continue
        out.append(li)
    order = {"HOT": 0, "WARM": 1}
    out.sort(key=lambda li: order.get(_tier(li), 2))
    return out


async def run_wetlands(listings: Iterable, budget_s: float, now: Optional[datetime] = None,
                       query=None) -> dict:
    import httpx
    from .enrichment_usfws_wetlands import query_point
    now = now or datetime.now(timezone.utc)
    targets = wetlands_targets(listings, now)
    stats = {"eligible": len(targets), "points": 0, "answered": 0, "with_wetlands": 0,
             "rows_set": 0, "unanswered": 0}
    if not targets:
        return stats
    by_point: dict[tuple, list] = {}
    for li in targets:
        by_point.setdefault((round(float(li.latitude), 4), round(float(li.longitude), 4)), []).append(li)
    points = list(by_point)[:WETLANDS_MAX]
    stamp = now.isoformat()
    deadline = time.monotonic() + budget_s
    sem = asyncio.Semaphore(max(1, WETLANDS_CONCURRENCY))
    walled: list[str] = []

    async def one(c, pt):
        if walled or time.monotonic() > deadline:
            return
        async with sem:
            if walled or time.monotonic() > deadline:
                return
            stats["points"] += 1
            try:
                got = await (query or query_point)(c, pt[0], pt[1], WETLANDS_RADIUS_M)
            except PermissionError as exc:
                walled.append(str(exc))
                return
            except Exception:  # noqa: BLE001 - a miss is retried next run (no stamp)
                got = None
        if got is None:
            stats["unanswered"] += 1
            return
        stats["answered"] += 1
        stats["with_wetlands"] += bool(got)
        blk = {"has_wetlands": bool(got), "features": got[:10], "within_m": WETLANDS_RADIUS_M,
               "source": "usfws_nwi", "checked_at": stamp}
        for li in by_point[pt]:
            _raw(li)["wetlands"] = blk
            stats["rows_set"] += 1

    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": _UA, "Accept": "application/json"}) as c:
        await asyncio.gather(*(one(c, pt) for pt in points))
    if walled:
        stats["stopped"] = walled[0]
        log.warning("tail_extras.wetlands.stopped", reason=walled[0])
    if time.monotonic() > deadline:
        stats["time_capped"] = budget_s
    return stats


# ----------------------------------------------------------------------------------- the steps
def enrich_local_pre_gate(listings, *, now: Optional[datetime] = None) -> dict:
    """LOCAL tail step before the call-ready gate: flood_zone mirror, HUD FMR, septic. No network."""
    listings = list(listings)
    now = now or datetime.now(timezone.utc)
    stats: dict = {}
    _step(stats, "flood_zone", mirror_flood_zone, listings)
    _step(stats, "hud_fmr", apply_hud_fmr, listings)

    def _septic():
        feats, at = read_septic_cache()
        return apply_septic(listings, feats, at, now=now)
    _step(stats, "septic", _septic)
    log.info("tail_extras.local_pre_gate", **{k: v for k, v in stats.items() if isinstance(v, dict)})
    return stats


def enrich_local_after_qa(listings) -> dict:
    """LOCAL tail step right after enrich_board_qa: source-consistency flags, property category."""
    from .enrichment_property_category import enrich_property_category
    from .enrichment_source_consistency import enrich_source_consistency
    listings = list(listings)
    stats: dict = {}
    _step(stats, "source_consistency", enrich_source_consistency, listings)
    _step(stats, "property_category", enrich_property_category, listings)
    log.info("tail_extras.local_after_qa", **{k: v for k, v in stats.items() if isinstance(v, dict)})
    return stats


async def enrich_network_pre_value(listings, *, budget_s: Optional[float] = None) -> dict:
    """NETWORK tail step before the valuation loop: BT appraisal cards (sqft, value, last sale)."""
    budget = budget_s if budget_s is not None else _env_s("TAIL_BT_CARD_BUDGET_S", 600)
    t0 = time.monotonic()
    try:
        out = await run_bt_cards(listings, budget)
    except Exception as exc:  # noqa: BLE001
        log.error("tail_extras.bt_appraisal_card.failed", error=f"{type(exc).__name__}: {exc}"[:300])
        out = {"failed": f"{type(exc).__name__}: {exc}"[:200]}
    out["seconds"] = round(time.monotonic() - t0, 1)
    log.info("tail_extras.network_pre_value", **{k: v for k, v in out.items() if not isinstance(v, dict)})
    return {"bt_appraisal_card": out}


async def enrich_network_geo(listings, *, budget_s: Optional[float] = None) -> dict:
    """NETWORK tail step in the post-board geographic group: septic layer refresh (weekly, then
    applied), NWI wetlands. The whole step stays inside `budget_s` (TAIL_GEO_EXTRAS_BUDGET_S, 600)."""
    listings = list(listings)
    budget = budget_s if budget_s is not None else _env_s("TAIL_GEO_EXTRAS_BUDGET_S", 600)
    t0 = time.monotonic()
    stats: dict = {}
    try:
        stats["septic_refresh"] = await refresh_septic_cache(min(300.0, budget / 2))
        if stats["septic_refresh"].get("fetched"):
            feats, at = read_septic_cache()
            stats["septic"] = apply_septic(listings, feats, at)
    except Exception as exc:  # noqa: BLE001
        log.error("tail_extras.septic_refresh.failed", error=f"{type(exc).__name__}: {exc}"[:300])
        stats["septic_refresh"] = {"failed": f"{type(exc).__name__}: {exc}"[:200]}
    left = max(0.0, budget - (time.monotonic() - t0))
    try:
        stats["wetlands"] = await run_wetlands(listings, left)
    except Exception as exc:  # noqa: BLE001
        log.error("tail_extras.wetlands.failed", error=f"{type(exc).__name__}: {exc}"[:300])
        stats["wetlands"] = {"failed": f"{type(exc).__name__}: {exc}"[:200]}
    stats["seconds"] = round(time.monotonic() - t0, 1)
    log.info("tail_extras.network_geo", seconds=stats["seconds"])
    return stats

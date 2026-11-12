"""raw['county_deed_ref'] (the atty_deed_ref cube column) for Florence and Colleton County SC,
from the register-of-deeds NAME index these two counties actually publish --
search.florencedeeds.com / search.colletondeeds.com (the SC "Online Record System" platform
rod/sc_online_record_system.py already reads and parses).

WHY THIS EXISTS (gap_matrix "sourced-not-built": Florence atty_deed_ref ~3,883 est rows, Colleton
atty_deed_ref ~3,680 est rows). gis_fill.py's own LAYER_LACKS entry for these two counties says it
plainly: "the county's open parcel layer carries no deed or legal field ...; the register index is
the OTHER route" (gis_fill.py line ~197). That other route was never built as a FILL: the register
reader exists and chain()s successfully for both counties today (live-checked 2026-11-05 -- see the
module docstring below for two real hits), and enrichment_rod_chain.py already calls it for rows
that have an owner_name AND is already wired to copy the chain's last deed into
raw['county_deed_ref'] -- but ONLY when county_deed_ref._needs_deed_ref() says the row is NC, or an
SC county in county_deed_ref.SC_LAYERS (Greenville/Greenwood/Spartanburg/Horry/Oconee/Pickens).
Florence and Colleton are in NEITHER list, so a chain's own last_deed book/page -- a real citation
from the register, already paid for in the HTTP round trip -- is computed and then thrown away for
these two counties specifically. Separately, Florence's tax-sale-list rows
(counties_sc.florence_delinquent_tax) carry no owner_name at all (only `defendant`), so
enrichment_rod_chain.py's own owner_name gate (`if ... not (li.owner_name or "").strip(): continue`)
skips every one of them before chain() is ever tried.

THIS MODULE closes both gaps, for Florence and Colleton only, two ways:
  1. FREE FILL (no network): a row that already carries raw['rod_chain'] with status "ok" and a
     last_deed book/page (enrichment_rod_chain.py already ran for it, and either it predates this
     module or the row is in one of these two counties) gets county_deed_ref copied straight from
     that chain -- zero extra requests.
  2. LIVE FILL: a row with no usable rod_chain yet -- most often because it has no owner_name, only
     a defendant (the Florence tax roll's taxpayer-of-record name) -- gets its OWN chain() call,
     using defendant as the search name when owner_name is blank.

MECHANISM (not reinvented here -- reused as-is). rod/sc_online_record_system.chain() already
implements and the project's own rod/sc_polite.py already paces/walls/caps it:
  GET  <base>/NameSearch.php?Accept=Accept   clears the disclaimer, opens the session
  POST <base>/NamePick.php                   tor_last_name=<surname> -> one entityID checkbox per
                                              indexed party name (the picker)
  POST <base>/NameDisplay.php                the ticked entityID boxes -> the actual document rows
                                              (Date | Code-Book-Page | Type | ... )
rod/sc_polite.PoliteSession already enforces >=1.6s between two requests to one host, one request
at a time per host, wall detection (RodWalled, cached per county for the rest of the run) and a
per-county-per-run lookup cap (SC_ROD_MAX_LOOKUPS_PER_COUNTY, default 30) -- this module adds no
pacing of its own and does not touch that shared state beyond calling chain().

LIVE-CHECKED 2026-11-05 (this audit, real board owners, see scratchpad test script -- not fixtures):
  Colleton, "WINGO TAMMY TERESA THOMAS" -> status ok, last_deed Book 1432 Page 223, recorded
    2006-10-30, plus a prior 1988 deed into the grantor.
  Colleton, "LANE TIMOTHY J" -> status ok, last_deed Book 3170 Page 59, recorded 2023-01-04, plus
    three open mortgages.
  Colleton, "POTTS EDWARD ROBERT" -> status not_found (clean negative: the disclaimer/pick/display
    flow completes, zero matching parties).
  Florence, 5 real florence_delinquent_tax `defendant` names (BARTELL BARRY, BAZEN WILLIAM EARL x2,
    BRAILEY KEVIN LEVERN, BRUNSON KENYETTA, WILLARD JULIUS SHANNON) -> all status not_found. A raw
    surname-only probe (e.g. plain POST tor_last_name=BARTELL) against the live site returns 133
    distinct indexed parties named Bartell, so the index itself is alive and NOT walled/broken for
    Florence; these five simply have no deed recorded under that exact name in the online index.
    BARTELL BARRY in particular (TMS 30000-44-787) is a mobile home on a billing address lot
    (confirmed live against web.florenceco.org the same day -- see enrichment_florence_tax_inquiry.py)
    -- consistent with no recorded real-estate deed rather than a broken fetch. Expect a real but
    lower hit rate against Florence's tax-roll "taxpayer of record" cohort than against Colleton's
    general lead mix: stale/decades-old taxpayer names and mobile-home-only parcels are exactly the
    rows least likely to have a name-indexed deed. DO NOT re-chase a Florence-specific "it must be
    broken" theory from a run of not_found results alone -- confirm the raw NamePick count for the
    surname first, the way this audit did.

WHAT IT WRITES (missing-only -- deed_ref_on_row() from gis_fill.py is the exact same gate gis_fill
and county_deed_ref.py already use, so a value this module writes and a value either of those
writes are mutually exclusive, never double-fetched):
  raw['county_deed_ref'] = {source: '<county>_register_index', parno: None, book, page, date,
                            fetched_at}
  (book/page as the register prints them, no re-padding; date ISO when the register's Date column
  parsed; parno is None -- this route matches by NAME, not by a county parcel id, so there is no
  parcel-system id to echo, unlike the GIS-layer fetchers' parno.)
A not_found or error result is NOT left silent: raw['county_deed_ref_check'] = {checked_at, county,
  name_searched, status} records the screen so the SAME name is not re-queried every run forever
  (RECHECK_DAYS below), mirroring gis_fill.py's own raw['gis_fill'] "screened, none found" pattern
  for the register-index route specifically.

FLAG: FORECLOSURE_FL_CO_DEED_REF (default off -- this is a new, previously-untested-at-scale fetcher
  against a live two-county portal; opt in explicitly, same convention as enrichment_qpaybill_tax.py's
  QPAYBILL_TAX). FORECLOSURE_FL_CO_DEED_REF_BUDGET_S bounds the wall clock (default 1200); the shared
  SC_ROD_MAX_LOOKUPS_PER_COUNTY (already read by every rod/sc_* adapter) bounds live lookups per
  county per run regardless of this module's own budget.

NOT WIRED INTO main.py by this change -- see the caller's own report for the one import+call line.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog

from .gis_fill import deed_ref_on_row
from .models import Listing
from .rod import sc_online_record_system as ors

log = structlog.get_logger()

_ENV_FLAG = "FORECLOSURE_FL_CO_DEED_REF"
_ENV_BUDGET = "FORECLOSURE_FL_CO_DEED_REF_BUDGET_S"
#: a name this module already screened (found nothing, or errored) is not re-queried for this long
RECHECK_DAYS = 30.0
#: counties this module ever touches -- Florence and Colleton only, per the task's gap_matrix lines
COUNTIES = ("florence", "colleton")
#: a chain is trusted for the free, no-network fill only at this confidence
_TRUSTED_CHAIN_STATUS = ("ok",)
#: chain() statuses that mean "stop asking this county for the rest of this run"
_STOP_COUNTY = ("walled", "capped")


def enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "0").strip() == "1"


def _raw(li: Any) -> dict:
    r = getattr(li, "raw", None)
    return r if isinstance(r, dict) else {}


def _county_key(li: Any) -> Optional[str]:
    if str(getattr(li, "state", "") or "").upper() != "SC":
        return None
    c = str(getattr(li, "county", "") or "").strip().lower().replace(" county", "")
    return c if c in COUNTIES else None


def _search_name(li: Any) -> str:
    return str(getattr(li, "owner_name", "") or getattr(li, "defendant", "") or "").strip()


def _recently_checked(raw: dict, now: datetime) -> bool:
    chk = raw.get("county_deed_ref_check")
    if not isinstance(chk, dict) or not chk.get("checked_at"):
        return False
    try:
        t = datetime.fromisoformat(str(chk["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() < RECHECK_DAYS * 86400.0


def needs(li: Any, now: datetime) -> bool:
    """An eligible row: Florence or Colleton SC, a usable name, a parcel id, no county_deed_ref yet,
    not screened recently."""
    if _county_key(li) is None or not str(getattr(li, "parcel_id", "") or "").strip():
        return False
    if not _search_name(li):
        return False
    raw = _raw(li)
    if deed_ref_on_row(raw):
        return False
    return not _recently_checked(raw, now)


def free_fill_from_cached_chain(li: Any, now_iso: str) -> bool:
    """The zero-network fill: a row's own raw['rod_chain'] already names a trustworthy last deed
    (enrichment_rod_chain.py ran, status ok). True when county_deed_ref was written."""
    raw = _raw(li)
    if deed_ref_on_row(raw):
        return False
    rc = raw.get("rod_chain")
    if not isinstance(rc, dict) or rc.get("status") not in _TRUSTED_CHAIN_STATUS:
        return False
    ld = rc.get("last_deed")
    if not isinstance(ld, dict) or not (ld.get("book") and ld.get("page")):
        return False
    county = _county_key(li)
    if county is None:
        return False
    raw["county_deed_ref"] = {"source": f"{county}_register_index", "parno": None,
                              "book": ld["book"], "page": ld["page"], "date": ld.get("recorded"),
                              "fetched_at": now_iso}
    li.raw = raw
    return True


def apply_chain_result(li: Any, res: dict, county: str, now_iso: str) -> str:
    """Write county_deed_ref (when res has a usable last_deed) or a county_deed_ref_check negative
    screen otherwise. Returns res['status'] for the caller's counters."""
    raw = _raw(li)
    status = str(res.get("status") or "error")
    ld = res.get("last_deed") if isinstance(res.get("last_deed"), dict) else None
    if status in ("ok", "partial") and ld and ld.get("book") and ld.get("page") and not deed_ref_on_row(raw):
        raw["county_deed_ref"] = {"source": f"{county}_register_index", "parno": None,
                                  "book": ld["book"], "page": ld["page"], "date": ld.get("recorded"),
                                  "fetched_at": now_iso}
    else:
        raw["county_deed_ref_check"] = {"checked_at": now_iso, "county": county,
                                        "name_searched": res.get("owner_searched"), "status": status}
    li.raw = raw
    return status


async def enrich_florence_colleton_deed_ref(listings: Iterable[Listing]) -> dict:
    stats = {"eligible": 0, "free_filled": 0, "looked_up": 0, "filled": 0, "not_found": 0,
             "walled_counties": [], "capped": 0, "errors": 0, "budget_exhausted": False}
    if not enabled():
        return {**stats, "skipped": f"{_ENV_FLAG}=0"}
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    try:
        budget_s = float(os.environ.get(_ENV_BUDGET, "1200"))
    except ValueError:
        budget_s = 1200.0
    t0 = time.monotonic()

    cache: dict[tuple[str, str], dict] = {}
    targets: list[Listing] = []
    for li in listings:
        if not needs(li, now):
            continue
        stats["eligible"] += 1
        if free_fill_from_cached_chain(li, now_iso):
            stats["free_filled"] += 1
            continue
        targets.append(li)

    stopped: set[str] = set()
    for li in targets:
        if time.monotonic() - t0 > budget_s:
            stats["budget_exhausted"] = True
            break
        county = _county_key(li)
        if county is None or county in stopped:
            continue
        name = _search_name(li)
        key = (county, name.upper())
        if key not in cache:
            try:
                res = await asyncio.to_thread(ors.chain, county, name, state="SC", depth=1)
            except Exception as exc:  # noqa: BLE001 - one lead never kills the pass
                log.warning("fl_co_deed_ref.failed", county=county, error=f"{type(exc).__name__}: {str(exc)[:120]}")
                res = {"status": "error", "owner_searched": name}
            cache[key] = res
            stats["looked_up"] += 1
        res = cache[key]
        status = apply_chain_result(li, res, county, now_iso)
        if status in _STOP_COUNTY:
            stopped.add(county)
            stats["walled_counties" if status == "walled" else "capped"] = (
                stats["walled_counties"] + [county] if status == "walled" else stats["capped"] + 1)
            continue
        if status == "error":
            stats["errors"] += 1
        elif status == "not_found":
            stats["not_found"] += 1
        else:
            stats["filled"] += 1

    log.info("fl_co_deed_ref.done", **{k: v for k, v in stats.items() if k != "walled_counties"},
             walled_counties=stats["walled_counties"])
    return stats

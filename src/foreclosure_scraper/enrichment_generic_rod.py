"""Generic ROD lien-existence enricher for COTT + Kofile + Acclaim platforms.

These rod modules all expose a ``search_by_name(state, county, name)`` function
that returns ``list[RodDoc]`` — same interface as CCHS. This enricher wraps all
three into one pass, attaches ``raw['rod']`` in the same shape as CCHS/Gaston,
and is default-ON. Disable per-platform via env vars.

Coverage added:
  - Polk NC        → COTT       (228 listings, 0% ROD)
  - Pickens SC     → Acclaim    (2,824 listings, 7% ROD)
  - Oconee SC      → Kofile     (1,675 listings, 0% ROD)
  - Union SC       → COTT RecordRoom (501 listings, 0% ROD)  [if search_by_name added]

Note: Logan ROD (McDowell/Mitchell/Transylvania NC, Laurens SC) only has
discover_recent_nods(), not search_by_name — covered by rod_name_index enricher.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Optional

import structlog

from .models import Listing
from .rod.classify import classify_rod_docs, is_stale, refresh_windows

log = structlog.get_logger()

# (state, county) -> (module_name, env_flag)
# Acclaim (Pickens SC) and cott_recordroom (Union SC) only have discover_recent_nods,
# not search_by_name — they're covered by rod_name_index enricher instead.
ROD_CONFIG = {
    ("NC", "Polk"):          ("cott",  "FORECLOSURE_COTT_ROD"),
    ("SC", "Oconee"):        ("kofile", "FORECLOSURE_KOFILE_ROD"),
}

_MORTGAGE_N = {"DT", "DOT", "DOFTR", "MORT", "MTG", "MORTGAGE", "DEEDOFTRUST"}
_ADVERSE_N = {"LIEN", "TAXLIEN", "TAX", "JUDG", "JUDGMENT", "LP", "LISP",
              "EXECUTION", "FCL", "NOS", "CLAIM", "STLIEN", "FEDTAXLIEN"}

_EMPTY = {
    "instrument_count": 0, "kinds": {}, "has_mortgage": False,
    "has_adverse_lien": False, "adverse_types": [],
    "mortgage_count": 0, "satisfaction_count": 0,
    "open_mortgages_est": 0, "instruments": [], "source": "generic_rod",
}

_CONCURRENCY = int(os.environ.get("GENERIC_ROD_CONCURRENCY", "3"))
_MAX_PER_COUNTY = int(os.environ.get("GENERIC_ROD_MAX_PER_COUNTY", "150"))


def _name_parts(owner: str):
    o = re.sub(r"[^A-Za-z, ]", " ", owner or "").upper()
    o = re.sub(r"\s+", " ", o).strip()
    if not o:
        return "", ""
    if "," in o:
        a, b = o.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    toks = o.split(" ")
    return toks[0], (toks[1] if len(toks) > 1 else "")


def _owner_doc(doc, last: str, first: str) -> bool:
    blob = f"{getattr(doc, 'grantor', '') or ''} {getattr(doc, 'grantee', '') or ''}".upper()
    return bool(last) and last in blob and (not first or first in blob)


def _get_module(module_name: str):
    """Lazily import the ROD module."""
    try:
        import importlib
        mod = importlib.import_module(f"foreclosure_scraper.rod.{module_name}")
        return mod
    except ImportError:
        return None


async def enrich_generic_rod(listings: list[Listing]) -> dict:
    """Search ROD by owner name for COTT/Kofile/Acclaim counties.

    Attaches raw['rod'] in the same shape as CCHS enricher so the dashboard
    and equity engine read it uniformly.
    """
    now = datetime.now(timezone.utc)
    hot_days, base_days = refresh_windows("FORECLOSURE_GENERIC_ROD", 7, 2)

    # Group targets by (state, county) -> module
    targets_by_county: dict[tuple[str, str], list[Listing]] = {}
    for li in listings:
        key = (li.state or "", (li.county or "").strip())
        if key not in ROD_CONFIG:
            continue
        if not li.owner_name:
            continue
        if not is_stale(li, now, hot_days, base_days):
            continue
        targets_by_county.setdefault(key, []).append(li)

    stats = {"counties": 0, "targets": 0, "searched": 0,
             "with_instruments": 0, "with_mortgage": 0, "with_adverse": 0}

    for (state, county), targets in targets_by_county.items():
        module_name, env_flag = ROD_CONFIG[(state, county)]
        if os.environ.get(env_flag, "1") == "0":
            log.info("generic_rod.skipped", county=county, reason=f"disabled ({env_flag}=0)")
            continue

        mod = _get_module(module_name)
        if mod is None:
            log.warning("generic_rod.no_module", county=county, module=module_name)
            continue

        if not hasattr(mod, "search_by_name"):
            log.warning("generic_rod.no_search_by_name", county=county, module=module_name)
            continue
        search_fn = mod.search_by_name

        # Cap per county
        if len(targets) > _MAX_PER_COUNTY:
            targets = targets[:_MAX_PER_COUNTY]

        stats["counties"] += 1
        stats["targets"] += len(targets)
        log.info("generic_rod.county_start", county=county, module=module_name,
                 targets=len(targets))

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def one(li: Listing) -> None:
            owner = li.owner_name or ""
            last, first = _name_parts(owner)
            if not last:
                return
            async with sem:
                try:
                    docs = await search_fn(state, county, owner, max_docs=80)
                except Exception as exc:
                    log.debug("generic_rod.search_fail", county=county,
                              owner=li.owner_name[:40], error=str(exc)[:80])
                    docs = []
                stats["searched"] += 1

            if not docs:
                return  # fetch failed -> leave unstamped, retry next run

            mine = [d for d in docs if _owner_doc(d, last, first)]
            if not mine:
                return

            summ = classify_rod_docs(mine, "generic_rod") if mine else dict(_EMPTY)
            summ["fetched_at"] = now.isoformat()
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["rod"] = summ

            stats["with_instruments"] += 1
            if summ.get("has_mortgage"):
                stats["with_mortgage"] += 1
            if summ.get("has_adverse_lien"):
                stats["with_adverse"] += 1

            await asyncio.sleep(0.3)

        await asyncio.gather(*(one(li) for li in targets))

    log.info("generic_rod.done", **stats)
    return stats

"""Burke/Cleveland/Madison/Henderson/Lincoln NC ROD lien-existence by owner name (CCHS
SearchService.asp). Burke and Cleveland were the original two; Madison/Henderson/Lincoln were
added later (_COUNTIES is the current list).

These core Western-NC counties run the OLDER CourthouseComputerSystems interface (classic-ASP
SearchService.asp), already wired in rod/cchs.py (search_by_name) but never called by any enricher
— so their lien data never reached the board. This thin enricher calls it for each owner and
attaches raw['rod'] in the SAME shape as the Gaston ROD enricher (so the dashboard filter + CSV
read rod_mortgage / rod_adverse uniformly). Default-ON; FORECLOSURE_CCHS_ROD=0 to disable.

ROUND-ROBIN BY COUNTY (2026-10-16): _await_capped's 900s budget rarely covers every eligible
lead across all 5 counties in one run, and `targets` used to scan in whatever order `listings`
itself arrived in -- which always favors the same counties. Live-measured the day this was
found: Henderson 28.8% checked, Burke 8.1%, Cleveland 7.5%, Lincoln 0.04% (8 of 18,436 -- Lincoln
alone outnumbers the other 4 counties combined), Madison a flat 0%. Same fix as gis_fill.py's:
rotate which county's group goes first by today's ordinal day, so a budget-capped run still
starves someone, but a different county each day.

cchs returns normalized RodDoc.doc_type (DEED/MORT/DT/LIEN/TAX_LIEN/SAT/LP/NOS/ASSIGN/CANC). We
filter the returned docs to those whose grantor/grantee actually contains the owner's name (the
search is last-name-only, so this trims namesakes), then classify mortgage + adverse-lien existence.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

from .rod import cchs
from .rod.classify import classify_rod_docs, is_stale, refresh_windows
from .name_normalize import first_last_parts

_COUNTIES = {"Burke", "Cleveland", "Madison", "Henderson", "Lincoln"}
# Match on the alpha-only normalized code (D/T -> DT, D OF TR -> DOFTR, TAX_LIEN -> TAXLIEN).
_MORTGAGE_N = {"DT", "DOT", "DOFTR", "MORT", "MTG", "MORTGAGE", "DEEDOFTRUST"}
_ADVERSE_N = {"LIEN", "TAXLIEN", "TAX", "JUDG", "JUDGMENT", "LP", "LISP", "EXECUTION",
              "FCL", "NOS", "CLAIM", "STLIEN", "FEDTAXLIEN"}


def _name_parts(owner: str):
    fl = first_last_parts(owner)   # Title Case FIRST-LAST court/probate names
    if fl is not None:
        return fl
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
    blob = f"{doc.grantor or ''} {doc.grantee or ''}".upper()
    return bool(last) and last in blob and (not first or first in blob)


def _classify(docs) -> dict:
    kinds: dict[str, int] = {}
    has_m = has_a = False
    adv: set[str] = set()
    for d in docs:
        k = (d.doc_type or "").upper().strip()
        if k:
            kinds[k] = kinds.get(k, 0) + 1
        kn = re.sub(r"[^A-Z]", "", k)
        if kn in _MORTGAGE_N:
            has_m = True
        if kn in _ADVERSE_N:
            has_a = True
            adv.add(k)
    return {
        "instrument_count": len(docs), "kinds": kinds,
        "has_mortgage": has_m, "has_adverse_lien": has_a,
        "adverse_types": sorted(adv), "source": "cchs_rod",
    }


_EMPTY = {"instrument_count": 0, "kinds": {}, "has_mortgage": False, "has_adverse_lien": False,
          "adverse_types": [], "mortgage_count": 0, "satisfaction_count": 0,
          "open_mortgages_est": 0, "instruments": [], "source": "cchs_rod"}


async def enrich_cchs_rod(listings, max_lookups: int | None = None) -> dict:
    if os.environ.get("FORECLOSURE_CCHS_ROD", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_CCHS_ROD=0)"}
    now = datetime.now(timezone.utc)
    hot_days, base_days = refresh_windows("FORECLOSURE_CCHS_ROD", 7, 2)
    # Fast httpx -> cover ALL leads, re-fetch any whose ROD is stale (deal-aware) so new liens land.
    eligible = [li for li in listings
                if li.state == "NC" and (li.county or "").strip() in _COUNTIES
                and li.owner_name and is_stale(li, now, hot_days, base_days)]
    # Round-robin by county, same fix as gis_fill.py's (2026-10-16): _await_capped's 900s
    # budget rarely covers every eligible lead across all 5 counties in one run, and a flat
    # `listings`-order scan always hits the SAME counties first -- live-measured the day this
    # was found: Henderson 28.8% checked, Burke 8.1%, Cleveland 7.5%, Lincoln 0.04% (8 of
    # 18,436 -- Lincoln alone outnumbers the other 4 counties combined), Madison a flat 0%.
    # Rotating which county's group goes first each day (not reordering individual leads
    # within a county, which `is_stale`'s own urgency already favors) means a budget-capped
    # run still starves someone, but a DIFFERENT county each day instead of Lincoln/Madison
    # forever.
    by_county: dict[str, list] = {}
    for li in eligible:
        by_county.setdefault((li.county or "").strip(), []).append(li)
    county_order = sorted(by_county)
    if county_order:
        spin = now.toordinal() % len(county_order)
        county_order = county_order[spin:] + county_order[:spin]
    targets = [li for c in county_order for li in by_county[c]]
    if max_lookups:
        targets = targets[:max_lookups]
    stats = {"targets": len(targets), "searched": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0}
    for li in targets:
        last, first = _name_parts(li.owner_name)
        try:
            docs = await cchs.search_by_name("NC", li.county, li.owner_name, max_docs=80)
        except Exception:  # noqa: BLE001
            docs = []
        stats["searched"] += 1
        if not docs:
            continue  # fetch failed -> leave unstamped, retry next run
        mine = [d for d in docs if _owner_doc(d, last, first)]
        summ = classify_rod_docs(mine, "cchs_rod") if mine else dict(_EMPTY)
        summ["fetched_at"] = now.isoformat()
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rod"] = summ
        if mine:
            stats["with_instruments"] += 1
            if summ["has_mortgage"]:
                stats["with_mortgage"] += 1
            if summ["has_adverse_lien"]:
                stats["with_adverse"] += 1
        await asyncio.sleep(0.3)
    return stats

"""Burke + Cleveland NC ROD lien-existence by owner name (CCHS SearchService.asp).

These two core Western-NC counties run the OLDER CourthouseComputerSystems interface (classic-ASP
SearchService.asp), already wired in rod/cchs.py (search_by_name) but never called by any enricher
— so their lien data never reached the board. This thin enricher calls it for each Burke/Cleveland
owner and attaches raw['rod'] in the SAME shape as the Gaston ROD enricher (so the dashboard filter
+ CSV read rod_mortgage / rod_adverse uniformly). Default-ON; FORECLOSURE_CCHS_ROD=0 to disable.

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

_COUNTIES = {"Burke", "Cleveland", "Madison", "Henderson"}
# Match on the alpha-only normalized code (D/T -> DT, D OF TR -> DOFTR, TAX_LIEN -> TAXLIEN).
_MORTGAGE_N = {"DT", "DOT", "DOFTR", "MORT", "MTG", "MORTGAGE", "DEEDOFTRUST"}
_ADVERSE_N = {"LIEN", "TAXLIEN", "TAX", "JUDG", "JUDGMENT", "LP", "LISP", "EXECUTION",
              "FCL", "NOS", "CLAIM", "STLIEN", "FEDTAXLIEN"}


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
    targets = [li for li in listings
               if li.state == "NC" and (li.county or "").strip() in _COUNTIES
               and li.owner_name and is_stale(li, now, hot_days, base_days)]
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

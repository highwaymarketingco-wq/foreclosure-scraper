"""Buncombe NC ROD lien-existence by owner name (Cott/Aumentum v4 SrchName).

Buncombe is the flagship core county (265 leads) and had ROD at 0% because rod/aumentum.py's
search_by_name posted wrong field names + bailed on the (intentionally empty) __VIEWSTATE. That's
now fixed + live-verified (4,468 rows for SMITH/JOHN). This enricher calls it per Buncombe owner,
filters to docs whose grantor matches the owner (the search is surname-broad), classifies D/T
mortgage + adverse liens, and attaches raw['rod'] in the SAME shape as the Gaston/CCHS enrichers.
Default-ON; FORECLOSURE_AUMENTUM_ROD=0 to disable. (Gaston is already covered by enrichment_gaston_rod
via the LRSearch path, so it's not re-searched here.)
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

from .rod import aumentum
from .rod.classify import classify_rod_docs, is_stale, refresh_windows

_COUNTIES = {"Buncombe"}
_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|SECURITY (DEED|AGREEMENT)|\bD\s*/?\s*T\b", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|CLAIM OF|MECHANIC", re.I)


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
        if _MORTGAGE.search(k):
            has_m = True
        if _ADVERSE.search(k):
            has_a = True
            adv.add(k)
    return {
        "instrument_count": len(docs), "kinds": kinds,
        "has_mortgage": has_m, "has_adverse_lien": has_a,
        "adverse_types": sorted(adv), "source": "aumentum_rod",
    }


async def enrich_aumentum_rod(listings, max_lookups: int | None = None) -> dict:
    if os.environ.get("FORECLOSURE_AUMENTUM_ROD", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_AUMENTUM_ROD=0)"}
    now = datetime.now(timezone.utc)
    hot_days, base_days = refresh_windows("FORECLOSURE_AUMENTUM_ROD", 7, 2)
    targets = [li for li in listings
               if li.state == "NC" and (li.county or "").strip() in _COUNTIES
               and li.owner_name and is_stale(li, now, hot_days, base_days)]
    if max_lookups:
        targets = targets[:max_lookups]
    stats = {"targets": len(targets), "searched": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0}
    empty = {"instrument_count": 0, "kinds": {}, "has_mortgage": False, "has_adverse_lien": False,
             "adverse_types": [], "mortgage_count": 0, "satisfaction_count": 0,
             "open_mortgages_est": 0, "instruments": [], "source": "aumentum_rod"}
    for li in targets:
        last, first = _name_parts(li.owner_name)
        try:
            docs = await aumentum.search_by_name("NC", li.county, li.owner_name, max_docs=400)
        except Exception:  # noqa: BLE001
            docs = []
        stats["searched"] += 1
        if not docs:
            continue  # fetch failed -> leave unstamped, retry next run
        mine = [d for d in docs if _owner_doc(d, last, first)]
        summ = classify_rod_docs(mine, "aumentum_rod") if mine else dict(empty)
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

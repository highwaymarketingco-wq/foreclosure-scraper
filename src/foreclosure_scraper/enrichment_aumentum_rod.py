"""Buncombe NC ROD lien-existence by owner name (Cott/Aumentum v4 SrchName).

Buncombe is the flagship core county (265 leads) and had ROD at 0% because rod/aumentum.py's
search_by_name posted wrong field names + bailed on the (intentionally empty) __VIEWSTATE. That's
now fixed + live-verified (4,468 rows for SMITH/JOHN). This enricher calls it per Buncombe owner,
filters to docs whose grantor matches the owner (the search is surname-broad), classifies D/T
mortgage + adverse liens, and attaches raw['rod'] in the SAME shape as the Gaston/CCHS enrichers.
Default-ON; FORECLOSURE_AUMENTUM_ROD=0 to disable. (Gaston is already covered by enrichment_gaston_rod
via the LRSearch path, so it's not re-searched here.)

MARRIAGE (2026-10-16, gap-sweep wave 3): Buncombe's Aumentum grid carries marriage records as a
plain doc_type ("MARRIED") right alongside deeds and liens in the SAME name-search this module
already runs -- enrichment_marriage_license.py (retired 2026-10-09, kept for its pure helpers)
documented this and reused the same adapter before it was retired; its only other live lane
(enrichment_register_checks.py's Cott counties) never touches Buncombe (a different vendor). This
module's own fetch already pulls marriage rows and silently dropped them. Filtering `mine` for one
now costs nothing extra: same request, same owner-match filter, just also checking doc_type.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone

from .enrichment_marriage_license import _is_marriage_doc, _spouse_from_doc
from .rod import aumentum
from .rod.classify import classify_rod_docs, is_stale, refresh_windows
from .name_normalize import first_last_parts

_COUNTIES = {"Buncombe"}
_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|SECURITY (DEED|AGREEMENT)|\bD\s*/?\s*T\b", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|CLAIM OF|MECHANIC", re.I)


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
        if not li.raw.get("marriage_license"):
            # `docs` is already confirmed non-empty (the fetch-failed case above continues
            # before this point), so the search itself worked for this name: no marriage
            # record among this owner's own rows is a confirmed no-match, the same terminal
            # shape enrichment_marriage_license.py used to write, so later runs don't re-ask
            # forever -- never a guessed negative from an empty/failed fetch.
            marriage_doc = next((d for d in mine if _is_marriage_doc(d.doc_type)), None)
            match = _spouse_from_doc(marriage_doc, last, first) if marriage_doc else None
            if match:
                li.raw["marriage_license"] = match
                stats["with_marriage"] = stats.get("with_marriage", 0) + 1
            else:
                li.raw["marriage_license"] = {"status": "no_match", "checked_at": now.isoformat()}
        await asyncio.sleep(0.3)
    return stats

"""Spartanburg SC ROD lien-existence by owner name (render-based Logan/DataTables).

Spartanburg (386 leads, biggest SC county) had ROD at 0% because its Logan site renders via jQuery
DataTables AJAX — the fast httpx path the other 6 ROD counties use returns empty tables here. This
drives the flow with a headless browser (rod/logan_render.search_by_name_render) — free, guest
session, no login/CAPTCHA defeated. Because render costs ~25s/owner, this is HOT/WARM-first + capped
per run (env FORECLOSURE_SPARTANBURG_ROD_MAX, default 30) and idempotent (skips leads that already
have raw['rod']), so coverage grows across runs without blowing up any single run. Disable with
FORECLOSURE_SPARTANBURG_ROD=0.
"""
from __future__ import annotations

import os
import re

from .rod.logan_render import search_by_name_render

_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|\bMTG\b|SECURITY (DEED|AGREEMENT)|\bD\s*/?\s*T\b", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|MECHANIC|HOA", re.I)
_SATISFY = re.compile(r"SATISF|CANCEL|RELEASE|\bSAT\b|\bREL\b", re.I)
# Keep the title/lien-relevant instruments in full detail; drop pure noise (plats, UCC, charters).
_KEEP = re.compile(r"MORTGAGE|DEED|TRUST|\bMTG\b|\bD/?T\b|LIEN|JUDG|\bTAX\b|FORECLOS|SATISF|CANCEL|RELEASE|ASSIGN|SECURITY|LIS PEND", re.I)


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
    instruments: list[dict] = []
    mtg = sat = 0
    # newest first so the kept (capped) detail favors current liens
    docs = sorted(docs, key=lambda d: (d.recorded_date or __import__("datetime").datetime.min), reverse=True)
    for d in docs:
        k = (d.doc_type or "").upper().strip()
        if k:
            kinds[k] = kinds.get(k, 0) + 1
        if _MORTGAGE.search(k):
            has_m = True
            mtg += 1
        if _ADVERSE.search(k):
            has_a = True
            adv.add(k)
        if _SATISFY.search(k):
            sat += 1
        if _KEEP.search(k) and len(instruments) < 40:
            instruments.append({
                "date": d.recorded_date.date().isoformat() if d.recorded_date else None,
                "type": d.doc_type, "grantor": d.grantor, "grantee": d.grantee,
                "book": d.book, "page": d.page,
            })
    return {
        "instrument_count": len(docs), "kinds": kinds,
        "has_mortgage": has_m, "has_adverse_lien": has_a, "adverse_types": sorted(adv),
        # Full per-instrument lien stack (type/date/parties/book-page). No $ amount — that's on the
        # paid document image. open_mortgages = mortgages minus satisfactions/cancellations (rough).
        "mortgage_count": mtg, "satisfaction_count": sat,
        "open_mortgages_est": max(0, mtg - sat),
        "instruments": instruments,
        "source": "spartanburg_rod_render",
    }


def _tier(li) -> str:
    return ((li.raw or {}).get("distress_stack") or {}).get("tier") or "COLD"


async def enrich_spartanburg_rod(listings, max_lookups: int | None = None) -> dict:
    if os.environ.get("FORECLOSURE_SPARTANBURG_ROD", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_SPARTANBURG_ROD=0)"}
    cap = max_lookups if max_lookups is not None else int(os.environ.get("FORECLOSURE_SPARTANBURG_ROD_MAX", "30"))
    targets = [li for li in listings
               if li.state == "SC" and (li.county or "").strip() == "Spartanburg"
               and li.owner_name and not (isinstance(li.raw, dict) and "rod" in li.raw)]
    # HOT/WARM first (render budget goes to the highest-value leads).
    order = {"HOT": 0, "WARM": 1, "COLD": 2}
    targets.sort(key=lambda li: order.get(_tier(li), 3))
    targets = targets[:cap]
    stats = {"targets": len(targets), "searched": 0, "with_instruments": 0,
             "with_mortgage": 0, "with_adverse": 0}
    for li in targets:
        last, first = _name_parts(li.owner_name)
        try:
            docs = await search_by_name_render("SC", "Spartanburg", li.owner_name)
        except Exception:  # noqa: BLE001
            docs = []
        stats["searched"] += 1
        mine = [d for d in docs if _owner_doc(d, last, first)]
        if not mine:
            continue
        summ = _classify(mine)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rod"] = summ
        stats["with_instruments"] += 1
        if summ["has_mortgage"]:
            stats["with_mortgage"] += 1
        if summ["has_adverse_lien"]:
            stats["with_adverse"] += 1
    return stats

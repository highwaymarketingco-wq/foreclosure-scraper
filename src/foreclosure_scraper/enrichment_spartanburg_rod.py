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
from datetime import datetime, timezone

from .rod.logan_render import search_by_name_render

_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|\bMTG\b|SECURITY (DEED|AGREEMENT)|\bD\s*/?\s*T\b", re.I)
# Documents that REFERENCE a mortgage but are NOT a new mortgage recording.
_NOT_NEW_MORTGAGE = re.compile(
    r"ASSIGN|MODIF|SATISF|CANCEL|RELEASE|CORRECT|SUBSTITUT|AMEND|EXTEN|CONSOLEN"
    r"|CONSOLI|RESCISSION|RATIFICATION|RECORDING|SUBORDINAT", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|MECHANIC|HOA", re.I)
# Liens that are NOT real-estate distress (don't flag these as adverse).
_NOT_REALTY_LIEN = re.compile(r"AIRPLANE|AIRCRAFT|\bUCC\b|VESSEL|\bBOAT\b", re.I)
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
        if _MORTGAGE.search(k) and not _NOT_NEW_MORTGAGE.search(k):
            has_m = True
            mtg += 1
        if _ADVERSE.search(k) and not _NOT_REALTY_LIEN.search(k):
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


def _rod_age_days(li, now: datetime) -> float | None:
    """Days since this lead's ROD was last fetched (None if never)."""
    rod = (li.raw or {}).get("rod") if isinstance(li.raw, dict) else None
    fa = (rod or {}).get("fetched_at")
    if not fa:
        return None
    try:
        dt = datetime.fromisoformat(fa)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds() / 86400.0
    except Exception:  # noqa: BLE001
        return None


async def enrich_spartanburg_rod(listings, max_lookups: int | None = None) -> dict:
    if os.environ.get("FORECLOSURE_SPARTANBURG_ROD", "1") == "0":
        return {"skipped": "disabled (FORECLOSURE_SPARTANBURG_ROD=0)"}
    # ALL Spartanburg leads, every full scrape — no per-run count cap (set MAX only to bound a quick
    # test). Refresh defaults to 3 days so a twice-weekly full scrape always re-pulls everyone (no
    # gaps). Bounded only by a wall-clock BUDGET_S safety so a pathological render can't hang the run;
    # any leads not reached stay unstamped and get pulled next run.
    cap = max_lookups if max_lookups is not None else int(os.environ.get("FORECLOSURE_SPARTANBURG_ROD_MAX", "100000"))
    base_days = float(os.environ.get("FORECLOSURE_SPARTANBURG_ROD_REFRESH_DAYS", "3"))
    hot_days = float(os.environ.get("FORECLOSURE_SPARTANBURG_ROD_REFRESH_HOT_DAYS", "1"))
    budget_s = float(os.environ.get("FORECLOSURE_SPARTANBURG_ROD_BUDGET_S", "14400"))  # 4h safety
    now = datetime.now(timezone.utc)
    import time as _time
    _t0 = _time.monotonic()

    def _imminent(li) -> bool:
        tier = ((li.raw or {}).get("distress_stack") or {}).get("tier")
        if tier == "HOT":
            return True
        sd = getattr(li, "sale_date", None)
        if sd:
            try:
                d = datetime.fromisoformat(str(sd)[:10]).replace(tzinfo=timezone.utc)
                return 0 <= (d - now).days <= 30   # auction within 30 days
            except Exception:  # noqa: BLE001
                return False
        return False

    def stale(li) -> bool:
        age = _rod_age_days(li, now)
        return age is None or age >= (hot_days if _imminent(li) else base_days)

    # EVERY Spartanburg lead that's due a refresh (all of them on a twice-weekly full scrape).
    targets = [li for li in listings
               if li.state == "SC" and (li.county or "").strip() == "Spartanburg"
               and li.owner_name and stale(li)]
    # Order: never-fetched first, then stalest first, so a budget-trimmed run still makes progress.
    targets.sort(key=lambda li: (_rod_age_days(li, now) is not None, -(_rod_age_days(li, now) or 1e9)))
    total_pending = len(targets)
    targets = targets[:cap]
    stats = {"pending": total_pending, "targets": len(targets), "searched": 0,
             "with_instruments": 0, "with_mortgage": 0, "with_adverse": 0, "budget_exhausted": False}
    for li in targets:
        if _time.monotonic() - _t0 > budget_s:
            stats["budget_exhausted"] = True
            break
        last, first = _name_parts(li.owner_name)
        try:
            docs = await search_by_name_render("SC", "Spartanburg", li.owner_name)
        except Exception:  # noqa: BLE001
            docs = []
        stats["searched"] += 1
        if not docs:
            continue  # render failed / no page returned -> leave unstamped so it retries next run
        mine = [d for d in docs if _owner_doc(d, last, first)]
        # Stamp fetched_at even on a clean no-match so the revolving window doesn't re-poll it
        # until the refresh interval; only genuine render failures (above) retry immediately.
        summ = _classify(mine) if mine else {
            "instrument_count": 0, "kinds": {}, "has_mortgage": False, "has_adverse_lien": False,
            "adverse_types": [], "mortgage_count": 0, "satisfaction_count": 0,
            "open_mortgages_est": 0, "instruments": [], "source": "spartanburg_rod_render"}
        summ["fetched_at"] = now.isoformat()
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["rod"] = summ
        if not mine:
            continue
        stats["with_instruments"] += 1
        if summ["has_mortgage"]:
            stats["with_mortgage"] += 1
        if summ["has_adverse_lien"]:
            stats["with_adverse"] += 1
    return stats

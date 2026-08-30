"""Shared ROD lien classifier + revolving-refresh helper.

Turns a list of RodDoc into the raw['rod'] dict used board-wide: the summary flags PLUS the full
per-instrument lien stack (date / type / grantor / grantee-lender / book-page), mortgage vs
satisfaction counts, and an open-mortgage estimate. One source of truth so every ROD county
(Gaston/cchs/aumentum/spartanburg) emits identical shape + the same airplane-lien exclusion.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

_MORTGAGE = re.compile(r"DEED OF TRUST|MORTGAGE|\bMTG\b|SECURITY (DEED|AGREEMENT)|\bD\s*/?\s*T\b|\bD OF TR\b|DOFTR", re.I)
# Documents that REFERENCE a mortgage but are NOT a new mortgage recording.
# Assignments, modifications, satisfactions, releases, corrections, substitutions,
# and amendments all contain "MORTGAGE" in the doc type but should NOT increment
# the mortgage counter — only original mortgage/deed-of-trust recordings should.
_NOT_NEW_MORTGAGE = re.compile(
    r"ASSIGN|MODIF|SATISF|CANCEL|RELEASE|CORRECT|SUBSTITUT|AMEND|EXTEN|CONSOLEN"
    r"|CONSOLI|RESCISSION|RATIFICATION|RECORDING|SUBORDINAT", re.I)
_ADVERSE = re.compile(r"JUDG|\bLIEN\b|\bTAX\b|EXECUTION|FORECLOS|LIS PEND|MECHANIC|HOA", re.I)
_MECHANIC_LIEN = re.compile(r"\bMECHANIC\b|\bM&L\b|\bML\b|\bMATERIAL(?:MAN|SMEN)?\b|\bCONTRACTOR\b", re.I)
# HOA / POA lien detection — homeowners-association liens, assessments, and
# HOA foreclosure filings. Catches "HOA LIEN", "HOA FORECLOSURE",
# "ASSESSMENT LIEN" (when paired with HOA context), "POA" (property owners assn).
_HOA_LIEN = re.compile(
    r"\bHOA\b|\bH\.?O\.?A\.?\b|HOMEOWNER.?S?\s*ASSOC|PROPERTY\s*OWNER.?S?\s*ASSOC|\bPOA\b"
    r"|ASSESSMENT\s*LIEN|COVENANT.*LIEN|\bCOMMUNITY\s*ASSOC", re.I)
# Liens that are NOT real-estate distress — do not flag these as adverse.
_NOT_REALTY_LIEN = re.compile(r"AIRPLANE|AIRCRAFT|\bUCC\b|VESSEL|\bBOAT\b", re.I)
_SATISFY = re.compile(r"SATISF|CANCEL|RELEASE|\bSAT\b|\bREL\b", re.I)
_KEEP = re.compile(r"MORTGAGE|DEED|TRUST|\bMTG\b|\bD/?T\b|LIEN|JUDG|\bTAX\b|FORECLOS|SATISF|CANCEL|RELEASE|ASSIGN|SECURITY|LIS PEND", re.I)


def classify_rod_docs(docs, source: str, detail_cap: int = 40) -> dict:
    """Build the raw['rod'] dict from RodDoc objects (newest-first detail, capped)."""
    kinds: dict[str, int] = {}
    has_m = has_a = has_ml = has_hoa = False
    adv: set[str] = set()
    instruments: list[dict] = []
    mtg = sat = ml_count = hoa_count = 0
    docs = sorted(docs, key=lambda d: (getattr(d, "recorded_date", None) or datetime.min), reverse=True)
    for d in docs:
        k = (getattr(d, "doc_type", "") or "").upper().strip()
        if k:
            kinds[k] = kinds.get(k, 0) + 1
        if _MORTGAGE.search(k) and not _NOT_NEW_MORTGAGE.search(k):
            has_m = True
            mtg += 1
        if _ADVERSE.search(k) and not _NOT_REALTY_LIEN.search(k):
            has_a = True
            adv.add(k)
        if _MECHANIC_LIEN.search(k) and not _NOT_REALTY_LIEN.search(k):
            has_ml = True
            ml_count += 1
        if _HOA_LIEN.search(k) and not _NOT_REALTY_LIEN.search(k):
            has_hoa = True
            hoa_count += 1
        if _SATISFY.search(k):
            sat += 1
        if _KEEP.search(k) and len(instruments) < detail_cap:
            rd = getattr(d, "recorded_date", None)
            instruments.append({
                "date": rd.date().isoformat() if rd else None,
                "type": getattr(d, "doc_type", None),
                "grantor": getattr(d, "grantor", None),
                "grantee": getattr(d, "grantee", None),
                "book": getattr(d, "book", None),
                "page": getattr(d, "page", None),
            })
    return {
        "instrument_count": len(docs), "kinds": kinds,
        "has_mortgage": has_m, "has_adverse_lien": has_a, "adverse_types": sorted(adv),
        "has_mechanic_lien": has_ml, "mechanic_lien_count": ml_count,
        "has_hoa_lien": has_hoa, "hoa_lien_count": hoa_count,
        "mortgage_count": mtg, "satisfaction_count": sat, "open_mortgages_est": max(0, mtg - sat),
        "instruments": instruments, "source": source,
    }


def rod_age_days(li, now: datetime) -> float | None:
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


def imminent(li, now: datetime) -> bool:
    """HOT tier or auction within 30 days — fresh liens matter most here."""
    tier = ((li.raw or {}).get("distress_stack") or {}).get("tier")
    if tier == "HOT":
        return True
    sd = getattr(li, "sale_date", None)
    if sd:
        try:
            d = datetime.fromisoformat(str(sd)[:10]).replace(tzinfo=timezone.utc)
            return 0 <= (d - now).days <= 30
        except Exception:  # noqa: BLE001
            return False
    return False


def is_stale(li, now: datetime, hot_days: float, base_days: float) -> bool:
    age = rod_age_days(li, now)
    return age is None or age >= (hot_days if imminent(li, now) else base_days)


def refresh_windows(prefix: str, default_base: float, default_hot: float) -> tuple[float, float]:
    base = float(os.environ.get(f"{prefix}_REFRESH_DAYS", str(default_base)))
    hot = float(os.environ.get(f"{prefix}_REFRESH_HOT_DAYS", str(default_hot)))
    return hot, base

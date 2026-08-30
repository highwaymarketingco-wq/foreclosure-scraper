"""Bankruptcy STAY cross-reference — the "don't discard a stayed foreclosure" layer.

`enrichment_bankruptcy.py` already matches a foreclosure lead's defendant to a recent NC/SC
bankruptcy debtor and tags `raw.bankruptcy` ({chapter, date_filed, case_name, docket, court}).
What it does NOT do — and the gap the 2026-08-17 audit flagged — is interpret that match as a
STAY: a bankruptcy filing triggers an automatic stay (11 U.S.C. §362) that halts the scheduled
foreclosure sale. So a matched foreclosure lead is NOT imminently buyable, but it is also NOT
gone — it's a high-motivation seller whose sale is paused and will very likely resume.

This enricher derives that status onto `raw.bankruptcy_stay` so the operator board treats it
correctly:
  - Chapter 13 = debtor trying to CURE arrears over a 3-5yr plan. Sale stayed. But Ch13 plans
    fail often — a plan that ages without discharge is at elevated risk of dismissal, at which
    point the foreclosure resumes. `resume_risk` rises with the case's age.
  - Chapter 7 = liquidation. Sale stayed only briefly; the lender files a Motion for Relief and
    the property proceeds to sale. Short-fuse, high resume likelihood.

Pure-local (reads the tag `enrichment_bankruptcy` already set — no network), idempotent.
Full relief-from-stay / dismissal DOCKET tracking is a follow-on (needs per-case CourtListener
re-checks); this ships the status + an age-based resume-risk heuristic now.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger(__name__)

# listing types that represent an actual/pending foreclosure a bankruptcy would STAY
_FORECLOSURE_TYPES = {"foreclosure_sale", "lis_pendens", "sheriff_sale", "tax_sale", "distressed"}


def _months_since(date_filed) -> float | None:
    try:
        d = datetime.fromisoformat(str(date_filed)[:10]).replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days / 30.44
    except (ValueError, TypeError):
        return None


def enrich_bankruptcy_stay(listings: Iterable[Listing]) -> dict:
    stats = {"stayed": 0, "ch13": 0, "ch7": 0, "elevated_resume_risk": 0}
    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else {}
        bk = raw.get("bankruptcy")
        if not isinstance(bk, dict):
            continue
        # only a FORECLOSURE-class lead gets stayed; a standalone BK lead isn't "stayed"
        if (li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type)) \
                not in _FORECLOSURE_TYPES:
            continue
        chapter = str(bk.get("chapter") or "").strip()
        age = _months_since(bk.get("date_filed"))
        if chapter == "13":
            # Ch13 plans run 36-60 months; dismissal risk climbs the longer it drags unresolved.
            risk = "elevated" if (age is not None and age >= 9) else "moderate"
            note = ("Chapter 13 automatic stay — debtor curing arrears over a 3-5yr plan; "
                    "foreclosure paused. Ch13 plans fail often — watch for plan default / "
                    "dismissal, at which point the sale resumes.")
            stats["ch13"] += 1
        elif chapter == "7":
            risk = "high"   # liquidation: lender files Motion for Relief, sale proceeds fast
            note = ("Chapter 7 automatic stay — liquidation. Stay is short-lived; lender files "
                    "a Motion for Relief and the property proceeds to sale. Near-term re-emergence.")
            stats["ch7"] += 1
        else:
            risk = "unknown"
            note = "Bankruptcy automatic stay in effect; foreclosure sale paused."
        if risk == "elevated" or risk == "high":
            stats["elevated_resume_risk"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["bankruptcy_stay"] = {
            "status": "stayed",
            "chapter": chapter or None,
            "date_filed": bk.get("date_filed"),
            "months_since_filing": round(age, 1) if age is not None else None,
            "resume_risk": risk,
            "case": bk.get("case_name"),
            "docket": bk.get("docket_number"),
            "court": bk.get("court"),
            "note": note,
        }
        stats["stayed"] += 1
    if stats["stayed"]:
        log.info("bankruptcy_stay.done", **stats)
    return stats

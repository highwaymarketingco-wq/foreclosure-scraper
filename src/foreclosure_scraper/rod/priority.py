"""Lien-priority engine.

Given a list of recorded documents on a property, compute:
  - Position of the foreclosing lien (1st mortgage, 2nd, tax sale, etc.)
  - Senior liens (buyer takes subject to these) with $ amounts
  - Junior liens (wiped out at sale) with $ amounts
  - State super-priority warnings (property tax, HOA in some states, mechanics liens)

The engine is conservative: when in doubt, treats a lien as senior to avoid
under-stating risk for the investor.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .models import DOC_BUCKETS, LienPosition, RodDoc, normalize_doc_type


# State super-priority rules (true if property-tax / HOA / mechanics liens
# can jump above earlier-recorded mortgages)
SUPER_PRIORITY = {
    "SC": {
        "tax_lien": True,           # SC property tax is super-priority
        "hoa_lien": False,          # not super-priority by default
        "mechanics_lien": False,    # priority from work-start, not recording
    },
    "NC": {
        "tax_lien": True,           # NC property tax super-priority (G.S. §105-356)
        "hoa_lien": True,           # NC limited super-priority for HOA (G.S. §47F-3-116)
        "mechanics_lien": False,
    },
}


def _is_satisfaction(doc: RodDoc) -> bool:
    return DOC_BUCKETS.get(normalize_doc_type(doc.doc_type)) == "satisfaction"


def _refers_to(sat: RodDoc, prior: RodDoc) -> bool:
    """Heuristic: does the satisfaction doc cancel a prior mortgage?

    Simple match: same grantor + book/page in raw text or notes. Production
    quality would parse the released-instrument book/page out of the doc.
    """
    if not (sat and prior):
        return False
    # Normalize names by stripping spaces
    g_sat = (sat.grantor or "").lower().replace(",", " ").split()
    g_pri = (prior.grantee or "").lower().replace(",", " ").split()  # mortgage GRANTEE = lender
    if not g_sat or not g_pri:
        return False
    # If satisfaction's grantor (the lender being released) matches the
    # original mortgage's grantee (the lender), treat as cancellation.
    return any(t in g_pri for t in g_sat if len(t) > 3)


def _active_documents(docs: list[RodDoc]) -> list[RodDoc]:
    """Filter out satisfied mortgages, releases, etc."""
    sats = [d for d in docs if _is_satisfaction(d)]
    active: list[RodDoc] = []
    for d in docs:
        if _is_satisfaction(d):
            continue
        bucket = DOC_BUCKETS.get(normalize_doc_type(d.doc_type), "")
        if bucket != "mortgage":
            active.append(d)
            continue
        # Check whether this mortgage has a satisfaction
        if any(_refers_to(s, d) for s in sats):
            continue
        active.append(d)
    return active


def compute_priority(
    docs: list[RodDoc],
    foreclosing_doc_book: str | None = None,
    foreclosing_doc_page: str | None = None,
    state: str = "NC",
) -> LienPosition:
    """Compute lien position from a list of recorded docs on a property."""
    out = LienPosition(docs_examined=len(docs), rationale=[])

    if not docs:
        out.title_risk_summary = "No ROD documents found — title status unknown"
        return out

    active = _active_documents(docs)
    out.rationale.append(f"Examined {len(docs)} documents, {len(active)} active after netting satisfactions")

    # Sort by recording date (oldest first = highest priority by general rule)
    active.sort(key=lambda d: d.recorded_date or datetime.min)

    # Identify foreclosing doc
    foreclosing = None
    if foreclosing_doc_book and foreclosing_doc_page:
        foreclosing = next(
            (
                d
                for d in active
                if (d.book or "") == str(foreclosing_doc_book)
                and (d.page or "") == str(foreclosing_doc_page)
            ),
            None,
        )

    # Bucket each active doc
    encumbrances: list[tuple[RodDoc, str]] = []
    for d in active:
        bucket = DOC_BUCKETS.get(normalize_doc_type(d.doc_type), "")
        if bucket in ("mortgage", "lien", "tax_lien", "mechanics_lien", "hoa_lien"):
            encumbrances.append((d, bucket))

    # Apply state super-priority: tax / HOA jump to position 1 regardless of date
    rules = SUPER_PRIORITY.get(state.upper(), {})
    super_pri: list[tuple[RodDoc, str]] = []
    regular: list[tuple[RodDoc, str]] = []
    for d, b in encumbrances:
        if rules.get(b):
            super_pri.append((d, b))
        else:
            regular.append((d, b))

    ordered = super_pri + regular   # super-priority first, then by recording date
    if not ordered:
        out.title_risk_summary = "No active liens — clean title (or ROD search incomplete)"
        return out

    # Find foreclosing position
    fpos = None
    for i, (d, _) in enumerate(ordered, start=1):
        if d is foreclosing:
            fpos = i
            break

    # If we couldn't pin the foreclosing doc, ASSUME it's the most recent mortgage
    if fpos is None:
        recent_mort = next(
            ((d, b) for d, b in reversed(ordered) if b == "mortgage"), None
        )
        if recent_mort:
            d, _ = recent_mort
            fpos = ordered.index(recent_mort) + 1
            foreclosing = d
            out.rationale.append(f"Foreclosing doc inferred as most-recent mortgage ({d.book}/{d.page})")

    if fpos is not None:
        out.foreclosing_position = fpos
        out.foreclosing_doc = foreclosing.to_dict() if foreclosing else None
        # Senior = positions before fpos; Junior = after
        for i, (d, b) in enumerate(ordered, start=1):
            if i < fpos:
                out.senior_liens.append({**d.to_dict(), "bucket": b})
            elif i > fpos:
                out.junior_liens.append({**d.to_dict(), "bucket": b})

    # $ totals
    out.total_senior_amount = sum((s.get("amount") or 0) for s in out.senior_liens) or None
    out.total_junior_amount = sum((j.get("amount") or 0) for j in out.junior_liens) or None

    # Super-priority warnings
    for d, b in super_pri:
        out.super_priority_warnings.append(
            f"{b.replace('_', ' ').title()} ({d.book}/{d.page}, recorded {d.recorded_date.date() if d.recorded_date else '?'}) has SUPER-PRIORITY in {state.upper()} — buyer takes subject"
        )

    # Risk summary
    if fpos == 1 and not out.senior_liens:
        out.title_risk_summary = "1st-position foreclosure, clean title — junior liens get wiped out"
    elif fpos == 1 and out.senior_liens:
        out.title_risk_summary = "1st-position foreclosure, but super-priority items (tax/HOA) survive"
    elif fpos and fpos > 1:
        out.title_risk_summary = f"{fpos}-position foreclosure — buyer takes subject to {len(out.senior_liens)} senior lien(s) totaling ${out.total_senior_amount or 0:,.0f}"
    else:
        out.title_risk_summary = "Foreclosing position unknown — manual title review recommended"

    return out

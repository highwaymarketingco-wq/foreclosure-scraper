"""A-F grades across investment dimensions, plus an overall grade.

Grades are computed from data we already have (or that the calc produces).
Each dimension is a 0-100 score, then mapped:
  90+: A   80-89: B   65-79: C   50-64: D   <50: F
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

from ..models import Listing, PropertyKind
from . import calc as _calc


@dataclass
class Grade:
    overall: str
    overall_score: int
    financial: str
    financial_score: int
    property: str
    property_score: int
    location: str
    location_score: int
    risk: str
    risk_score: int
    rationale: list[str]


def _letter(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def _financial_score(li: Listing, c: _calc.Calc) -> tuple[int, str]:
    """Bid relative to (max_bid_70, ARV, rehab). 70% rule sits at score 80."""
    if not (li.opening_bid and c.arv_expected):
        return 50, "no bid or ARV — neutral"
    bid = li.opening_bid
    bid_to_arv = bid / c.arv_expected
    rehab = c.rehab_expected or 0
    fees = c.arv_expected * 0.07
    spread = c.arv_expected - bid - rehab - fees   # rough profit if bought at bid
    spread_pct = spread / c.arv_expected if c.arv_expected else 0

    if bid_to_arv <= 0.30:
        s, why = 98, f"Bid is {bid_to_arv*100:.0f}% of ARV — exceptional"
    elif bid_to_arv <= 0.40:
        s, why = 92, f"Bid {bid_to_arv*100:.0f}% of ARV — strong upside"
    elif bid_to_arv <= 0.55:
        s, why = 85, f"Bid {bid_to_arv*100:.0f}% of ARV — within 70% rule"
    elif bid_to_arv <= 0.70:
        s, why = 70, f"Bid {bid_to_arv*100:.0f}% of ARV — at 70% rule"
    elif bid_to_arv <= 0.85:
        s, why = 55, f"Bid {bid_to_arv*100:.0f}% of ARV — thin margin"
    elif bid_to_arv <= 1.0:
        s, why = 35, f"Bid {bid_to_arv*100:.0f}% of ARV — almost retail"
    else:
        s, why = 15, f"Bid {bid_to_arv*100:.0f}% of ARV — overpriced"

    # ROI bonus / penalty
    if c.roi_pct is not None:
        if c.roi_pct >= 30:
            s += 3
        elif c.roi_pct < 10:
            s -= 5
    return max(0, min(100, s)), why


def _property_score(li: Listing) -> tuple[int, str]:
    """Year built + sqft data + flags."""
    score = 70  # neutral baseline
    notes = []

    if li.year_built:
        age = datetime.utcnow().year - li.year_built
        if age <= 15:
            score += 12
            notes.append(f"newer construction ({li.year_built})")
        elif age <= 35:
            score += 6
        elif age <= 60:
            pass
        elif age <= 100:
            score -= 8
            notes.append(f"older home ({age} yrs)")
        else:
            score -= 18
            notes.append(f"very old ({age} yrs)")

    if li.bedrooms and li.bathrooms and li.living_sqft:
        score += 8
    elif li.living_sqft:
        score += 3

    flags = (li.raw or {}).get("flags", []) if isinstance(li.raw, dict) else []
    fb = " ".join(flags).lower()
    bad = ["fire damage", "tear down", "uninhabitable", "condemned", "foundation", "gutted",
           "structural", "termite", "no power", "no water", "boarded", "hoarder", "vacant"]
    good = ["renovated", "remodeled", "updated", "move-in", "turnkey", "new roof", "new hvac"]
    bad_hits = sum(1 for k in bad if k in fb)
    good_hits = sum(1 for k in good if k in fb)
    score -= bad_hits * 6
    score += good_hits * 4
    if bad_hits:
        notes.append(f"{bad_hits} negative condition flag(s)")
    if good_hits:
        notes.append(f"{good_hits} positive condition flag(s)")

    if li.property_kind == PropertyKind.LAND:
        score = max(score, 60)
        notes.append("vacant land — minimal physical condition risk")

    return max(0, min(100, score)), "; ".join(notes) or "limited property data"


def _location_score(li: Listing) -> tuple[int, str]:
    """Rough location score from county tier + ZIP + state economy.

    Tier-1 counties have stronger demand (Mecklenburg, Buncombe, Greenville).
    Tier-2 are smaller but still active. Tier-3 are rural / slow.
    A future enhancement is Census API integration for true median income +
    population trend per ZIP.
    """
    if not li.county or not li.state:
        return 60, "location data missing"

    county = li.county.lower().strip()
    state = li.state.upper()

    tier_1 = {"mecklenburg", "buncombe", "greenville"}
    tier_2 = {"spartanburg", "anderson", "henderson", "gaston", "rutherford"}
    tier_3 = {"cleveland", "polk", "transylvania", "mcdowell", "lincoln",
              "pickens", "oconee", "cherokee", "union", "laurens", "abbeville",
              "greenwood", "newberry", "madison", "yancey", "mitchell", "burke"}

    if county in tier_1:
        s = 88
        why = f"{county.title()} County, {state} — high-demand metro"
    elif county in tier_2:
        s = 78
        why = f"{county.title()} County, {state} — established market"
    elif county in tier_3:
        s = 65
        why = f"{county.title()} County, {state} — smaller market"
    else:
        s = 60
        why = f"{county.title()} County, {state}"

    # Pull location enrichment from raw if present (Census API filled later)
    loc = (li.raw or {}).get("location") if isinstance(li.raw, dict) else None
    if isinstance(loc, dict):
        income = loc.get("median_household_income")
        if income:
            if income > 80000:
                s += 6
                why += f" · median HH income ${income:,.0f}"
            elif income < 40000:
                s -= 8
                why += f" · low median HH income ${income:,.0f}"
            else:
                why += f" · median HH income ${income:,.0f}"
    return max(0, min(100, s)), why


def _risk_score(li: Listing) -> tuple[int, str]:
    """Risk grade from auction status + flag count + listing type."""
    score = 75
    notes = []
    flags = (li.raw or {}).get("flags", []) if isinstance(li.raw, dict) else []
    fb = " ".join(flags).lower()

    if any(k in fb for k in ("fire damage", "tear down", "condemned", "uninhabitable")):
        score -= 30
        notes.append("severe condition risk")
    elif "foundation" in fb or "structural" in fb:
        score -= 18
        notes.append("structural risk")
    elif "vacant" in fb:
        score -= 5
        notes.append("vacant (vandalism risk)")

    # Listing type risk
    lt = (li.listing_type.value if hasattr(li.listing_type, "value") else str(li.listing_type)).lower()
    if "tax_sale" in lt or "tax_lien" in lt:
        score -= 10
        notes.append("tax sale — buyer takes subject to other liens")
    elif "auction" in lt:
        score -= 5
        notes.append("auction — non-refundable deposit risk")
    elif "reo" in lt:
        score += 8
        notes.append("REO — clean title typical")

    # Equity flag from county GIS or zillow
    flag_set = set(flags)
    if "high_equity" in flag_set:
        score += 6
        notes.append("high equity (likely 1st-mortgage foreclosure)")
    if "negative_equity" in flag_set:
        score -= 12
        notes.append("negative equity (short-sale territory)")

    return max(0, min(100, score)), "; ".join(notes) or "no major flags"


def grade(li: Listing, c: _calc.Calc | None = None) -> Grade:
    if c is None:
        c = _calc.compute(li)

    fs, fn = _financial_score(li, c)
    ps, pn = _property_score(li)
    ls, ln = _location_score(li)
    rs, rn = _risk_score(li)

    # Weighted overall: financial 40 / property 25 / location 20 / risk 15
    overall = round(fs * 0.40 + ps * 0.25 + ls * 0.20 + rs * 0.15)
    return Grade(
        overall=_letter(overall),
        overall_score=overall,
        financial=_letter(fs), financial_score=fs,
        property=_letter(ps), property_score=ps,
        location=_letter(ls), location_score=ls,
        risk=_letter(rs), risk_score=rs,
        rationale=[fn, pn, ln, rn],
    )


def to_dict(g: Grade) -> dict:
    return asdict(g)

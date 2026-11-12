"""Property assessment: condition guess, rehab cost estimate, ARV estimate, max-bid suggestion.

Inputs are best-effort. None of this replaces a real inspection or BPO.
We expose three numbers per listing where possible:

  * ARV (After Repair Value) — from Zillow zestimate or comparable sold avg in same ZIP
  * Estimated rehab cost — from age + sqft + condition keywords
  * Suggested max bid — 70% rule: 0.70 * ARV - rehab - closing/holding fees

Plus a condition score (0-100) and a flag list (foundation, fire, vacant, etc).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()


# Keyword tags that adjust condition score / rehab tier
NEGATIVE_KEYWORDS = {
    "fire damage": -40,
    "fire-damaged": -40,
    "burned": -40,
    "smoke damage": -25,
    "water damage": -25,
    "flood": -25,
    "mold": -20,
    "foundation": -20,
    "structural": -25,
    "tear down": -50,
    "tear-down": -50,
    "vacant": -10,
    "abandoned": -15,
    "boarded": -15,
    "hoarder": -25,
    "as-is": -10,
    "as is": -10,
    "needs work": -15,
    "fixer": -20,
    "fixer-upper": -20,
    "tlc": -10,
    "investor special": -15,
    "rehab": -10,
    "gutted": -30,
    "no power": -10,
    "no water": -10,
    "termite": -15,
    "uninhabitable": -35,
    "condemned": -45,
}
POSITIVE_KEYWORDS = {
    "renovated": 15,
    "remodeled": 15,
    "updated": 10,
    "move-in ready": 20,
    "turnkey": 20,
    "new roof": 8,
    "new hvac": 5,
    "new kitchen": 8,
    "granite": 3,
    "hardwood": 3,
    "well maintained": 10,
    "pristine": 12,
}


def _tag_keywords(text: str) -> tuple[int, list[str]]:
    """Return (delta, hit_keywords) by scanning text for quality signals."""
    if not text:
        return 0, []
    delta = 0
    hits: list[str] = []
    low = text.lower()
    for kw, val in NEGATIVE_KEYWORDS.items():
        if kw in low:
            delta += val
            hits.append(kw)
    for kw, val in POSITIVE_KEYWORDS.items():
        if kw in low:
            delta += val
            hits.append(kw)
    return delta, hits


def condition_score(li: Listing) -> tuple[int, list[str]]:
    """Score 0-100. Higher = better. None inputs default to ~70 (assume average)."""
    base = 70
    text = " ".join(filter(None, (li.description, li.legal_description, " ".join(str(v) for v in li.raw.values() if isinstance(v, str)))))
    delta, hits = _tag_keywords(text)
    # Age penalty
    if li.year_built:
        age = max(0, datetime.utcnow().year - li.year_built)
        if age > 80:
            base -= 15
            hits.append(f"old({age}yr)")
        elif age > 50:
            base -= 8
        elif age < 15:
            base += 5
    score = max(0, min(100, base + delta))
    return score, hits


def rehab_estimate(li: Listing, score: int) -> float | None:
    """Per-square-foot rehab estimate based on condition tier.

    Tiers (rough industry rules of thumb for the Carolinas, 2026 dollars):
      score 80-100 -> $5-15/sqft  cosmetic refresh
      score 60-79  -> $20-40/sqft light rehab (paint, floors, fixtures)
      score 40-59  -> $40-70/sqft moderate rehab (kitchens, baths, HVAC)
      score 20-39  -> $70-120/sqft heavy rehab (roof, systems, structural minor)
      score  0-19  -> $120-200/sqft gut rehab or near tear-down
    """
    if li.property_kind == PropertyKind.LAND:
        return None  # land doesn't rehab
    sqft = li.living_sqft
    if not sqft:
        # fall back on a typical 1,500 sqft assumption for SFH
        sqft = 1500 if li.property_kind in (PropertyKind.SINGLE_FAMILY, PropertyKind.UNKNOWN) else 1000
    if score >= 80:
        per = 10
    elif score >= 60:
        per = 30
    elif score >= 40:
        per = 55
    elif score >= 20:
        per = 95
    else:
        per = 160
    return round(per * sqft, -2)


def arv_estimate(li: Listing, score: int) -> float | None:
    """Best-available ARV. Order of preference:
       1) zillow zestimate from raw payload
       2) tax assessed value × 1.25 (rough adjustment to market)
       3) opening_bid × 2.5 (very rough; foreclosure floors tend to run 30-50% of ARV)
    """
    z = li.raw.get("zillow") if isinstance(li.raw, dict) else None
    if z and isinstance(z, dict):
        for k in ("zestimate", "rentZestimate", "homeValue"):
            v = z.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    if li.market_value and li.market_value > 0:
        return float(li.market_value)
    if li.tax_value and li.tax_value > 0:
        return round(float(li.tax_value) * 1.25, -2)
    if li.assessed_value and li.assessed_value > 0:
        return round(float(li.assessed_value) * 1.25, -2)
    if li.opening_bid and li.opening_bid > 0:
        # Rough: distressed properties often go for 35-50% of ARV at open bid.
        return round(li.opening_bid * 2.4, -2)
    return None


def max_bid_70(arv: float | None, rehab: float | None, fees_pct: float = 0.05) -> float | None:
    """Classic 70% rule: max_bid = 0.70 * ARV - rehab - closing/holding fees.

    fees_pct defaults to 5% of ARV — combination of closing, holding, and selling.
    """
    if arv is None:
        return None
    rehab = rehab or 0
    fees = arv * fees_pct
    bid = 0.70 * arv - rehab - fees
    return max(0.0, round(bid, -2))


def assess(li: Listing) -> dict[str, Any]:
    """Compute and attach assessment fields. Returns the assessment dict for logging."""
    score, flags = condition_score(li)
    rehab = rehab_estimate(li, score)
    arv = arv_estimate(li, score)
    max_bid = max_bid_70(arv, rehab)

    summary_bits = []
    if score is not None:
        summary_bits.append(f"Condition {score}/100")
    if rehab:
        summary_bits.append(f"Est. rehab ${int(rehab):,}")
    if arv:
        summary_bits.append(f"Est. ARV ${int(arv):,}")
    if max_bid:
        summary_bits.append(f"Suggested max bid ${int(max_bid):,}")
    if flags:
        summary_bits.append("Flags: " + ", ".join(flags[:6]))

    summary = " | ".join(summary_bits)
    if li.description:
        li.description = (li.description + " || " + summary)[:500]
    else:
        li.description = summary[:500]

    li.market_value = arv if arv else li.market_value
    return {
        "condition_score": score,
        "rehab_estimate": rehab,
        "arv_estimate": arv,
        "max_bid_70": max_bid,
        "flags": flags,
    }


def assess_all(listings: list[Listing]) -> list[dict[str, Any]]:
    """Run assessment on every listing in place. Returns list of assessment dicts (parallel to listings)."""
    return [assess(li) for li in listings]

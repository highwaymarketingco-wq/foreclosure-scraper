"""Investor financial calculator.

Outputs (per listing):
  arv_low / arv_expected / arv_high       — After-repair value range
  rehab_low / rehab_expected / rehab_high — Rehab cost range
  max_bid_70                              — 70% rule (real-estate-investor standard)
  total_investment                        — bid + rehab + closing + holding + selling
  estimated_profit                        — arv - total_investment
  roi_pct                                 — profit / total_investment * 100
  cash_on_cash_pct                        — profit / cash_down (if 25% down + 75% loan)
  confidence                              — HIGH / MEDIUM / LOW based on data quality
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

from ..models import Listing, PropertyKind


# Per-square-foot rehab cost tiers (Carolina market, 2026 dollars)
# tier letter -> (low $/sqft, expected $/sqft, high $/sqft)
REHAB_TIERS = {
    "cosmetic":  (5,  10,  20),   # paint, fixtures, maybe carpet
    "light":     (15, 30,  45),   # paint, floors, kitchen counters, baths
    "moderate":  (35, 55,  80),   # kitchens, baths, HVAC, some plumbing
    "heavy":     (65, 95,  130),  # roof, systems, structural minor
    "gut":       (110, 160, 220), # near-tear-down
}

CLOSING_PCT = 0.04        # buyer-side closing (title, recording, attorney)
SELLING_PCT = 0.07        # 6% commission + 1% misc
HOLDING_RATE_MONTH = 0.005  # ~6% APR / 12 mo of bid value
HOLDING_MONTHS = 6
DOWN_PCT = 0.25           # cash down for cash-on-cash
LOAN_RATE_MONTH = 0.008   # 9.5% APR (hard money) / 12


@dataclass
class Calc:
    arv_low: float | None = None
    arv_expected: float | None = None
    arv_high: float | None = None
    rehab_low: float | None = None
    rehab_expected: float | None = None
    rehab_high: float | None = None
    rehab_tier: str | None = None
    max_bid_70: float | None = None
    total_investment: float | None = None
    estimated_profit: float | None = None
    roi_pct: float | None = None
    cash_on_cash_pct: float | None = None
    bid_to_arv_pct: float | None = None
    confidence: str = "LOW"
    notes: list[str] | None = None


def _condition_to_tier(li: Listing) -> str:
    """Pick rehab tier from year built + flags."""
    flags = (li.raw or {}).get("flags", []) if isinstance(li.raw, dict) else []
    flag_blob = " ".join(flags).lower()

    # Hard signals
    if any(k in flag_blob for k in ("tear down", "fire damage", "uninhabitable", "condemned", "gutted")):
        return "gut"
    if any(k in flag_blob for k in ("foundation", "structural", "termite", "no power", "no water")):
        return "heavy"
    if any(k in flag_blob for k in ("vacant", "abandoned", "boarded", "hoarder", "as-is", "as is", "investor special")):
        return "moderate"
    if any(k in flag_blob for k in ("fixer", "rehab", "needs work", "tlc", "water damage", "mold")):
        return "moderate"
    if any(k in flag_blob for k in ("renovated", "remodeled", "move-in", "turnkey", "new roof", "new hvac")):
        return "cosmetic"

    # Age-based default
    yb = li.year_built
    if yb:
        age = datetime.utcnow().year - yb
        if age >= 80:
            return "heavy"
        if age >= 50:
            return "moderate"
        if age >= 25:
            return "light"
        return "cosmetic"
    # Unknown age, unknown flags → assume moderate
    return "moderate"


def _arv_signals(li: Listing) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Return (low, expected, high, confidence, notes) for ARV.

    Best signal: Zillow zestimate (real Zestimate per address).
    Fallback: tax_value × 1.25 (assessed values lag market).
    Worst:    opening_bid × 2.4 (foreclosures often run ~40% of ARV at the floor).

    Range = expected ± 15%.
    """
    notes: list[str] = []
    z = (li.raw or {}).get("zillow", {}) if isinstance(li.raw, dict) else {}
    zest = z.get("zestimate") or li.market_value

    if zest and zest > 0:
        expected = float(zest)
        notes.append(f"ARV from Zillow Zestimate ({zest:,.0f})")
        confidence = "MEDIUM"  # zestimates are ±5-20% off real comps
    elif li.tax_value and li.tax_value > 0:
        expected = float(li.tax_value) * 1.25
        notes.append(f"ARV from tax-assessed × 1.25 ({li.tax_value:,.0f} × 1.25)")
        confidence = "LOW"
    elif li.opening_bid and li.opening_bid > 0:
        expected = float(li.opening_bid) * 2.4
        notes.append(f"ARV proxy from opening bid × 2.4 ({li.opening_bid:,.0f} × 2.4) — rough")
        confidence = "LOW"
    else:
        return None, None, None, "LOW", ["Insufficient data for ARV"]

    low = round(expected * 0.85, -2)
    high = round(expected * 1.15, -2)
    return round(expected, -2), low, high, confidence, notes


def compute(li: Listing) -> Calc:
    """Compute investor financials for a listing. Mutates nothing."""
    out = Calc(notes=[])

    # ---- ARV range ------------------------------------------------------
    expected, low, high, arv_conf, arv_notes = _arv_signals(li)
    out.arv_low, out.arv_expected, out.arv_high = low, expected, high
    out.notes.extend(arv_notes)

    # ---- Rehab range ----------------------------------------------------
    if li.property_kind == PropertyKind.LAND:
        out.rehab_tier = "land"
        out.rehab_low = out.rehab_expected = out.rehab_high = 0.0
    else:
        tier = _condition_to_tier(li)
        out.rehab_tier = tier
        sqft = li.living_sqft
        if not sqft:
            sqft = 1500 if li.property_kind in (PropertyKind.SINGLE_FAMILY, PropertyKind.UNKNOWN) else 1000
        lo_psf, mid_psf, hi_psf = REHAB_TIERS[tier]
        out.rehab_low = round(lo_psf * sqft, -2)
        out.rehab_expected = round(mid_psf * sqft, -2)
        out.rehab_high = round(hi_psf * sqft, -2)
        out.notes.append(
            f"Rehab tier '{tier}' on {sqft:,.0f} sqft = {lo_psf}-{hi_psf}/sqft"
        )

    # ---- Max bid (70% rule, expected case) ------------------------------
    if out.arv_expected:
        fees = out.arv_expected * SELLING_PCT
        out.max_bid_70 = max(
            0.0,
            round(0.70 * out.arv_expected - (out.rehab_expected or 0) - fees, -2),
        )

    # ---- Total investment if bidding at opening bid ---------------------
    bid = li.opening_bid
    if bid and out.arv_expected:
        closing = bid * CLOSING_PCT
        holding = bid * HOLDING_RATE_MONTH * HOLDING_MONTHS
        selling = out.arv_expected * SELLING_PCT
        total = bid + (out.rehab_expected or 0) + closing + holding + selling
        out.total_investment = round(total, -2)
        out.estimated_profit = round(out.arv_expected - total, -2)
        if total > 0:
            out.roi_pct = round((out.estimated_profit / total) * 100, 1)
        # Cash on cash: 25% down + 75% loan
        cash_down = bid * DOWN_PCT + (out.rehab_expected or 0)  # rehab usually cash
        loan_amt = bid * (1 - DOWN_PCT)
        loan_interest = loan_amt * LOAN_RATE_MONTH * HOLDING_MONTHS
        cash_total = cash_down + loan_interest + closing + holding + selling
        cash_profit = out.arv_expected - bid - (out.rehab_expected or 0) - closing - holding - selling - loan_interest
        if cash_down > 0:
            out.cash_on_cash_pct = round((cash_profit / cash_down) * 100, 1)
        out.bid_to_arv_pct = round((bid / out.arv_expected) * 100, 1)

    # ---- Confidence -----------------------------------------------------
    score = 0
    if arv_conf == "MEDIUM":
        score += 2
    elif arv_conf == "LOW":
        score += 0
    if li.living_sqft:
        score += 1
    if li.year_built:
        score += 1
    if li.bedrooms is not None and li.bathrooms is not None:
        score += 1
    if li.tax_value:
        score += 1
    out.confidence = "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW"
    return out


def to_dict(c: Calc) -> dict:
    return {k: v for k, v in asdict(c).items() if v is not None}

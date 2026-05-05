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

# Manufactured / mobile homes are far cheaper to rehab per sqft than stick-built:
# vinyl skirting, single-pane windows, cosmetic-grade fixtures throughout.
MOBILE_REHAB_TIERS = {
    "cosmetic": (3,   8,   15),
    "light":    (10,  20,  30),
    "moderate": (20,  35,  55),
    "heavy":    (40,  60,  80),
    "gut":      (70,  100, 140),
}

CLOSING_PCT = 0.04        # buyer-side closing (title, recording, attorney)
SELLING_PCT = 0.07        # 6% commission + 1% misc
HOLDING_RATE_MONTH = 0.005  # ~6% APR / 12 mo of bid value
HOLDING_MONTHS = 6
DOWN_PCT = 0.25           # cash down for cash-on-cash
LOAN_RATE_MONTH = 0.008   # 9.5% APR (hard money) / 12

# Sources where opening_bid is a retail asking price (and therefore a useful
# ARV sanity-check). For everything else (auctions, lis pendens, REO floors,
# law-firm foreclosure sales) the bid is a discount-to-ARV floor — clamping
# ARV to bid would silently kill the entire flip thesis.
RETAIL_PRICE_SOURCES = {
    "national.homeharvest",
    "national.realtor_foreclosures",
}


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
    # Investor framing — what's the deal status at the listed/asking price?
    deal_status: str | None = None         # GREAT / OK / NEGOTIATE / PASS
    deal_message: str | None = None        # human-readable explanation
    haircut_needed: float | None = None    # $ user needs to negotiate down to flip


def _condition_to_tier(li: Listing) -> str:
    """Pick rehab tier from condition_tier (set by enrichment_comps), flags, year built.

    Maps the four-tier condition (move_in_ready / cosmetic / major / gut)
    to the five-tier rehab cost table (cosmetic / light / moderate / heavy / gut).
    Reads condition_tier from raw.vision.condition_tier first (Vision-grounded,
    most accurate), then raw.condition_tier (legacy enrichment_comps mirror).
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    cond = (raw.get("vision") or {}).get("condition_tier") or raw.get("condition_tier")
    cond_map = {
        "move_in_ready": "cosmetic",
        "cosmetic": "light",
        "major": "moderate",
        "gut": "gut",
    }
    if cond and cond in cond_map:
        return cond_map[cond]

    # Fallback: legacy flags-based detection
    flags = raw.get("flags", []) if isinstance(raw, dict) else []
    flag_blob = " ".join(flags).lower() if isinstance(flags, list) else ""

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
    return "moderate"


def _acreage_for(li: Listing) -> float | None:
    """Best-available acreage value for a listing, in acres."""
    if li.acreage and li.acreage > 0:
        return float(li.acreage)
    if li.lot_size_sqft and li.lot_size_sqft > 0:
        return float(li.lot_size_sqft) / 43560.0
    return None


def _land_arv(li: Listing) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Land-specific ARV path. Comps come pre-filtered by lot acreage band
    (±50% in enrichment_comps), so use sold_price ÷ acreage to get $/acre,
    then apply to the subject's acreage. No living_sqft involvement.
    """
    notes: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    comps = raw.get("comps") or []
    subj_ac = _acreage_for(li)

    # Tier 1: $/acre from land comps × subject acreage
    if comps and subj_ac:
        ppa_list = []
        for c in comps:
            sp = c.get("sold_price")
            lot = c.get("lot_sqft")
            if sp and lot and lot > 0:
                ppa = float(sp) / (float(lot) / 43560.0)
                ppa_list.append(ppa)
        ppa_list.sort()
        if len(ppa_list) >= 2:
            mid = ppa_list[len(ppa_list) // 2]
            low_ppa = ppa_list[0]
            high_ppa = ppa_list[-1]
            expected = round(mid * subj_ac, -2)
            low = round(low_ppa * subj_ac, -2)
            high = round(high_ppa * subj_ac, -2)
            notes.append(
                f"ARV from {len(ppa_list)} land comps × {subj_ac:.2f} ac "
                f"(${mid:,.0f}/ac median; range ${low_ppa:,.0f}-${high_ppa:,.0f}/ac)"
            )
            return expected, low, high, "HIGH", notes

    # Tier 2: tax-assessed × 1.10 (land is assessed closer to market than improved)
    if li.tax_value and li.tax_value > 0:
        expected = round(float(li.tax_value) * 1.10, -2)
        notes.append(f"Land ARV from tax-assessed × 1.10 ({li.tax_value:,.0f})")
        return expected, round(expected * 0.85, -2), round(expected * 1.15, -2), "LOW", notes

    # Tier 3: bid × 1.5 (land foreclosures discount less than improved)
    if li.opening_bid and li.opening_bid > 0:
        expected = round(float(li.opening_bid) * 1.5, -2)
        notes.append(f"Land ARV proxy from bid × 1.5 ({li.opening_bid:,.0f})")
        return expected, round(expected * 0.7, -2), round(expected * 1.3, -2), "LOW", notes

    return None, None, None, "LOW", ["Insufficient land data for ARV"]


def _arv_signals(li: Listing) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """Return (low, expected, high, confidence, notes) for ARV.

    Best signal: 3 zip-matched comps × subject sqft (TRUE comp-based ARV).
    Next:        Zillow zestimate (per-address Zestimate).
    Fallback:    tax_value × 1.25 (assessed values lag market).
    Worst:       opening_bid × 2.4 (foreclosures often run ~40% of ARV at the floor).

    Range = expected ± 15%. Land takes a separate $/acre path (_land_arv).
    """
    if li.property_kind == PropertyKind.LAND:
        return _land_arv(li)

    notes: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    comps = raw.get("comps") or []
    comp_ppsf = raw.get("comp_median_ppsf")

    # Tier 1: comp-based ARV (HIGHEST confidence)
    if comps and comp_ppsf and li.living_sqft:
        expected = float(comp_ppsf) * float(li.living_sqft)
        notes.append(
            f"ARV from {len(comps)} zip-matched sold comps × subject sqft "
            f"(${comp_ppsf:,.0f}/sqft × {li.living_sqft:,.0f} sqft)"
        )
        # Range: low = 25th percentile $/sqft, high = 75th percentile
        ppsfs = sorted(c["price_per_sqft"] for c in comps if c.get("price_per_sqft"))
        if len(ppsfs) >= 3:
            low_ppsf = ppsfs[0]
            high_ppsf = ppsfs[-1]
            low = round(low_ppsf * li.living_sqft, -2)
            high = round(high_ppsf * li.living_sqft, -2)
        else:
            low = round(expected * 0.90, -2)
            high = round(expected * 1.10, -2)
        return round(expected, -2), low, high, "HIGH", notes

    # Tier 2: Zillow zestimate
    z = raw.get("zillow", {}) if isinstance(raw, dict) else {}
    zest = z.get("zestimate") or li.market_value
    if zest and zest > 0:
        expected = float(zest)
        notes.append(f"ARV from Zillow Zestimate ({zest:,.0f})")
        confidence = "MEDIUM"
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

    # ---- Vision-based ARV adjustment ------------------------------------
    # Subject's photo-derived condition tier is what the rehab will need to
    # *overcome*. Comps are average retail-sold properties — typically already
    # at "cosmetic-or-better" finish. If subject is gut/major, even after
    # full rehab the result is "renovated SFR" not "premium tear-out-and-
    # rebuild," so it sells at average comp pricing, not above. If subject
    # is move_in_ready, post-rehab is barely-touched-premium and tends to
    # sell *above* comp median.
    raw = li.raw if isinstance(li.raw, dict) else {}
    vision_tier = raw.get("condition_tier")
    vision_conf = (raw.get("condition_source") or "").lower()
    if (out.arv_expected and vision_tier
            and vision_conf.startswith("vision-")
            and arv_conf == "HIGH"):
        # Multipliers calibrated to flipper-Carolina market behavior.
        # Only apply when ARV is comp-grounded (HIGH confidence) AND vision
        # confidence is HIGH/MEDIUM. We don't want to compound noise.
        adj_map = {
            "move_in_ready": 1.05,   # post-rehab premium
            "cosmetic":      1.00,   # neutral, matches comp median
            "major":         0.95,   # slight haircut, full rehab won't equal premium
            "gut":           0.88,   # bigger haircut, structural risks remain
        }
        adj = adj_map.get(vision_tier)
        if adj and adj != 1.0:
            old_expected = out.arv_expected
            out.arv_expected = round(out.arv_expected * adj, -2)
            out.arv_low = round((out.arv_low or 0) * adj, -2) or None
            out.arv_high = round((out.arv_high or 0) * adj, -2) or None
            pct = (adj - 1.0) * 100
            out.notes.append(
                f"Vision-adjusted ARV by {pct:+.0f}% (subject tier='{vision_tier}', "
                f"comp median assumes cosmetic-tier finish): "
                f"${old_expected:,.0f} → ${out.arv_expected:,.0f}"
            )

    # ---- ARV sanity check vs listing price ------------------------------
    # If the listing has an opening_bid AND it's a clean for-sale listing
    # (HomeHarvest / Realtor sources), the bid IS the asking price and ARV
    # should not be wildly different. Flag suspect ARVs.
    if (out.arv_expected and li.opening_bid and li.opening_bid > 0
            and li.source in ("national.homeharvest", "national.distressed",
                              "national.realtor_foreclosures")):
        ratio = out.arv_expected / li.opening_bid
        if ratio < 0.6 or ratio > 1.6:
            # ARV implausibly off from listing price — fall back to listing price
            out.notes.append(
                f"ARV (${out.arv_expected:,.0f}) was {ratio:.1f}× listing price "
                f"(${li.opening_bid:,.0f}); using listing price as ARV anchor"
            )
            out.arv_expected = float(li.opening_bid)
            out.arv_low = round(li.opening_bid * 0.90, -2)
            out.arv_high = round(li.opening_bid * 1.10, -2)
            arv_conf = "MEDIUM"

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

        # Photo-grounded rehab $/sqft from Vision wins over generic tier ranges
        # when both Vision tier and Vision rehab_psf range are HIGH-confidence.
        # Vision's psf reflects what the photos actually show — boarded windows,
        # missing roof shingles, peeling exterior — which the generic tier
        # buckets can't capture.
        vision = (raw.get("vision") or {}) if isinstance(raw, dict) else {}
        v_psf_low = vision.get("rehab_psf_low")
        v_psf_high = vision.get("rehab_psf_high")
        v_conf = (vision.get("confidence") or "").upper()
        if (v_psf_low and v_psf_high and v_conf in ("HIGH", "MEDIUM")
                and 1 <= v_psf_low <= v_psf_high <= 300):
            v_psf_mid = (v_psf_low + v_psf_high) / 2
            out.rehab_low = round(v_psf_low * sqft, -2)
            out.rehab_expected = round(v_psf_mid * sqft, -2)
            out.rehab_high = round(v_psf_high * sqft, -2)
            out.notes.append(
                f"Rehab from Vision photos: ${v_psf_low}-${v_psf_high}/sqft "
                f"× {sqft:,.0f} sqft (Vision conf={v_conf}, tier='{tier}')"
            )
        else:
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

    # ---- Deal status: investor's actionable verdict ----------------------
    # Frames the listing in terms a flipper actually decides on:
    #   GREAT       — listing price is below the 70% rule max bid (rare, snap-up)
    #   OK          — listing price right at max bid (margin OK, do diligence)
    #   NEGOTIATE   — listing price above max bid; specifies haircut needed
    #   PASS        — math doesn't work even at $0 acquisition
    if out.max_bid_70 is not None and bid is not None and bid > 0:
        if out.max_bid_70 <= 0:
            out.deal_status = "PASS"
            out.deal_message = (
                f"Math doesn't work — ARV ${out.arv_expected or 0:,.0f} minus "
                f"rehab ${out.rehab_expected or 0:,.0f} leaves no margin even at $0 acquisition."
            )
        elif bid <= out.max_bid_70 * 0.95:
            out.deal_status = "GREAT"
            out.deal_message = (
                f"List ${bid:,.0f} is below max viable bid ${out.max_bid_70:,.0f}. "
                f"Solid margin if specs are accurate — verify."
            )
        elif bid <= out.max_bid_70 * 1.05:
            out.deal_status = "OK"
            out.deal_message = (
                f"List ${bid:,.0f} is right at max viable bid ${out.max_bid_70:,.0f}. "
                f"Tight but workable — do diligence."
            )
        else:
            out.haircut_needed = round(bid - out.max_bid_70, -2)
            out.deal_status = "NEGOTIATE"
            out.deal_message = (
                f"List ${bid:,.0f} is ${out.haircut_needed:,.0f} above max viable "
                f"bid ${out.max_bid_70:,.0f}. Negotiate down or pass."
            )

    return out


def to_dict(c: Calc) -> dict:
    return {k: v for k, v in asdict(c).items() if v is not None}

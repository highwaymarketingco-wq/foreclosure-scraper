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
REHAB_CONTINGENCY_PCT = 0.125  # every pro pads the repair estimate 10-15% for surprises
ASSIGNMENT_FEE = 10000    # typical residential wholesale assignment fee

# Living-sqft plausibility band for $/sqft ARV. A handful of real records
# legitimately sit in [8000,10000) (large estates), so only HARD-reject clearly
# bad values: below this floor is a data-entry/parse error (sqft-as-acres, a lot
# dimension, a zero), above the ceiling is almost always garbage. Outside the
# band, living_sqft is treated as missing FOR ARV PURPOSES (the $/sqft tiers are
# skipped) rather than producing a nonsense headline ARV.
LIVING_SQFT_MIN = 300
LIVING_SQFT_MAX = 10000

# Rural land sanity ceiling: a land-comp $/acre median above this is almost
# always a parse error (a per-sqft figure leaking through, or a 0.01-ac lot
# dividing a full sale price) and would emit a multi-million phantom land ARV.
MAX_LAND_PPA = 2_000_000  # $/acre

# Proxy-ARV ceiling. The bid×2.4 / bid×1.5 / tax×1.25 fallbacks fire on rows
# with no comps, and on those rows opening_bid is often a money-JUDGMENT or
# total-debt figure (not a property bid), which multiplied out emits a multi-
# million phantom ARV. Above this ceiling the proxy is not trustworthy, so we
# return ARV-unavailable (honest) instead of a fabricated number.
MAX_PROXY_ARV = 2_000_000


def _plausible_living_sqft(li: Listing) -> float | None:
    """Subject living_sqft usable for a $/sqft ARV, or None if implausible.

    Defensive: anything outside [LIVING_SQFT_MIN, LIVING_SQFT_MAX] is treated as
    missing so a bad parse can't fabricate an ARV. Non-positive / non-numeric
    values also return None.
    """
    sqft = li.living_sqft
    try:
        sqft = float(sqft) if sqft is not None else None
    except (TypeError, ValueError):
        return None
    if not sqft or sqft <= 0:
        return None
    if sqft < LIVING_SQFT_MIN or sqft > LIVING_SQFT_MAX:
        return None
    return sqft

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
    rehab_with_contingency: float | None = None   # rehab_expected + 12.5% surprise buffer
    max_bid_70: float | None = None
    wholesale_mao: float | None = None            # max_bid − assignment fee (wholesale lens)
    wholesale_spread: float | None = None         # max_bid − opening_bid (assignable margin)
    total_investment: float | None = None
    estimated_profit: float | None = None
    roi_pct: float | None = None
    cash_on_cash_pct: float | None = None
    bid_to_arv_pct: float | None = None
    confidence: str = "LOW"
    # ARV-METHOD confidence (distinct from `confidence`, which scores overall
    # data completeness): HIGH = sold-comp grounded, MEDIUM = zestimate or
    # county tax/appraised value, LOW = opening-bid guess. grading.py reads this
    # to decide whether a listing is assessable enough to rate.
    arv_confidence: str | None = None
    arv_vs_assessed: float | None = None   # comp-ARV / county appraised value (accuracy anchor)
    notes: list[str] | None = None
    # Flip framing — what's the deal status at the listed/asking price?
    deal_status: str | None = None         # GREAT / OK / NEGOTIATE / PASS
    deal_message: str | None = None        # human-readable explanation
    haircut_needed: float | None = None    # $ user needs to negotiate down to flip
    # Buy-and-hold framing — for investors who'd rent rather than flip.
    # Computed when rent comp data is available (raw.rent_median_ppsf).
    monthly_rent_est: float | None = None
    annual_gross_rent: float | None = None
    noi_annual: float | None = None        # NOI = 50% of gross (industry rule)
    cap_rate_pct: float | None = None      # NOI / acquisition cost
    monthly_cashflow_est: float | None = None  # after PITI debt service
    hold_status: str | None = None         # GREAT / OK / NEGOTIATE / PASS
    hold_message: str | None = None
    one_pct_rule: bool | None = None       # rent ≥ 1% of total acq cost


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
                # Reject above the rural ceiling — a $/acre this high is almost
                # always a parse error (per-sqft figure or a near-zero lot) and
                # would emit a multi-million phantom land ARV. Skip the bad comp.
                if ppa > MAX_LAND_PPA:
                    continue
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
            # 2026-06-19: a >=3x low/high spread means the comps disagree wildly
            # ($/acre varies hugely by location) — don't present that as HIGH.
            conf = "LOW" if (low and high and low > 0 and high / low >= 3) else "HIGH"
            return expected, low, high, conf, notes

    # Tier 2: tax-assessed × 1.10 (land is assessed closer to market than improved)
    if li.tax_value and li.tax_value > 0:
        expected = round(float(li.tax_value) * 1.10, -2)
        if expected <= MAX_PROXY_ARV:
            notes.append(f"Land ARV from tax-assessed × 1.10 ({li.tax_value:,.0f})")
            return expected, round(expected * 0.85, -2), round(expected * 1.15, -2), "LOW", notes

    # Tier 3: bid × 1.5 (land foreclosures discount less than improved)
    if li.opening_bid and li.opening_bid > 0:
        expected = round(float(li.opening_bid) * 1.5, -2)
        # Reject runaway proxies: opening_bid on a comps-empty land row may be a
        # judgment/debt figure, not a property bid — don't emit a phantom ARV.
        if expected <= MAX_PROXY_ARV:
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
    # 2026-06-19: a listing with living_sqft is an IMPROVED property even if
    # mis-classified as LAND — never value a house off $/acre land comps (that
    # produced nonsense like a 1,808-sqft house at $12,500). Route it to the
    # sqft-comp path below; if no sqft comps exist it returns ARV-unavailable
    # (honest) rather than a fabricated land value.
    if li.property_kind == PropertyKind.LAND and not (li.living_sqft and li.living_sqft > 0):
        return _land_arv(li)

    notes: list[str] = []
    raw = li.raw if isinstance(li.raw, dict) else {}
    comps = raw.get("comps") or []
    comp_ppsf = raw.get("comp_median_ppsf")

    # Tier 0: RECORDED arms-length sales comps (county GIS, distance-matched).
    # Real recorded transactions beat scraped listings — no list-vs-sold gap,
    # tighter geography. This is the comp-accuracy fix (enrichment_recorded_comps).
    # An ESTIMATED sqft (footprint × stories) is not bankable as TRUE GLA, so any
    # ARV built on it is capped to MEDIUM and labelled, never HIGH (Pass: footprint
    # sqft proxy). enrichment_footprint_sqft sets this flag.
    sqft_est = bool(getattr(li, "living_sqft_estimated", False))
    sqft_lbl = f"{li.living_sqft:,.0f} sqft{' (ESTIMATED: footprint×stories ~2019)' if sqft_est else ''}" if li.living_sqft else ""

    # Plausibility guard: an implausible living_sqft (parse error, lot dimension,
    # zero) is treated as missing FOR ARV — skip the $/sqft paths rather than emit
    # a nonsense headline ARV. A footprint-estimated sqft is allowed but grades
    # down (LOW for scraped comps, capped MEDIUM for recorded comps).
    arv_sqft = _plausible_living_sqft(li)

    rec = raw.get("recorded_comps") or {}
    rec_ppsf = raw.get("comp_median_ppsf_recorded")
    if rec_ppsf and arv_sqft:
        expected = float(rec_ppsf) * arv_sqft
        notes.append(
            f"ARV from {rec.get('count', '?')} RECORDED arms-length sales within "
            f"{rec.get('radius_mi', '?')}mi (${rec_ppsf:,.0f}/sqft × {sqft_lbl})"
        )
        low = round((rec.get("p25_ppsf") or rec_ppsf * 0.9) * arv_sqft, -2)
        high = round((rec.get("p75_ppsf") or rec_ppsf * 1.1) * arv_sqft, -2)
        conf = "HIGH" if rec.get("confidence") == "HIGH" else "MEDIUM"
        if sqft_est:
            conf = "MEDIUM"
            notes.append("ARV confidence capped at MEDIUM: living sqft is a footprint-based ESTIMATE")
        return round(expected, -2), low, high, conf, notes

    # Tier 1: comp-based ARV (HIGHEST confidence)
    if comps and comp_ppsf and arv_sqft:
        # Build the adjusted $/sqft series ONCE and derive both `expected` (median)
        # and low/high (min/max) from it, so the headline ARV can never fall
        # outside its own band (Pass-2 fix: expected used the comp_median_ppsf
        # scalar while the band used this adjusted series — a different base).
        ppsfs = sorted((c.get("adjusted_ppsf") or c["price_per_sqft"])
                       for c in comps if (c.get("adjusted_ppsf") or c.get("price_per_sqft")))
        if ppsfs:
            median_ppsf = ppsfs[len(ppsfs) // 2]
        else:
            # No usable per-comp $/sqft — fall back to the supplied median scalar.
            median_ppsf = float(comp_ppsf)
        expected = median_ppsf * arv_sqft
        notes.append(
            f"ARV from {len(comps)} zip-matched sold comps × subject sqft "
            f"(${median_ppsf:,.0f}/sqft × {sqft_lbl})"
        )
        if len(ppsfs) >= 3:
            low = round(ppsfs[0] * arv_sqft, -2)
            high = round(ppsfs[-1] * arv_sqft, -2)
        else:
            low = round(expected * 0.90, -2)
            high = round(expected * 1.10, -2)
        # Clamp the rounded headline into [low,high] so it always sits inside its
        # own band even if rounding or a fallback base nudges it out.
        expected = min(max(round(expected, -2), low), high)
        # Comp-QUALITY gate: scraped comps are only HIGH-confidence when there
        # are enough of them, they're geographically anchored (not county-wide),
        # and they actually agree. A single far/stale comp is not bankable.
        conf = "HIGH"
        reasons = []
        # A footprint-estimated sqft CAPS ARV at MEDIUM (never HIGH) — a bounded
        # estimate, not bankable GLA. The >8000 footprint reject + plausibility
        # band already drop garbage, so MEDIUM (not LOW) is the right confidence.
        if sqft_est:
            conf, reasons = "MEDIUM", reasons + ["living sqft is a footprint-based ESTIMATE"]
        if len(ppsfs) < 3:
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + [f"only {len(ppsfs)} comp(s)"]
        if comps and not comps[0].get("geo_anchored", True):
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + ["county-wide comps (no local anchor)"]
        if len(ppsfs) >= 2 and ppsfs[0] > 0 and ppsfs[-1] / ppsfs[0] >= 1.6:
            conf, reasons = ("LOW" if conf == "LOW" else "MEDIUM"), reasons + ["comps disagree (wide $/sqft spread)"]
        if reasons:
            notes.append(f"ARV confidence lowered to {conf}: " + "; ".join(reasons))
        return round(expected, -2), low, high, conf, notes

    # Tier 2: Zillow zestimate
    z = raw.get("zillow", {}) if isinstance(raw, dict) else {}
    zest = z.get("zestimate") or li.market_value
    _fh = (raw.get("fhfa_value") or {}) if isinstance(raw, dict) else {}
    if zest and zest > 0:
        expected = float(zest)
        notes.append(f"ARV from Zillow Zestimate ({zest:,.0f})")
        confidence = "MEDIUM"
    elif _fh.get("est_value") and float(_fh["est_value"]) > 0:
        # Free FHFA-HPI rescale of the property's last recorded sale to today's
        # market (MSA, else statewide). Coarse trend estimate (not comp-grounded)
        # so it ranks below zestimate/tax and is LOW confidence — but it gives the
        # equity engine an ARV basis for comp-thin rural/SC leads that had none.
        expected = float(_fh["est_value"])
        notes.append(f"ARV from FHFA-HPI rescale of last recorded sale "
                     f"({_fh.get('msa_or_state', 'MSA/state')}) — coarse fallback")
        confidence = "LOW"
    elif li.tax_value and li.tax_value > 0:
        expected = float(li.tax_value) * 1.25
        notes.append(f"ARV from tax-assessed × 1.25 ({li.tax_value:,.0f} × 1.25)")
        # 2026-06-21: MEDIUM, not LOW. A county tax-assessed / appraised value
        # is an official, authoritative valuation (just conservative/stale),
        # not a guess like opening_bid × 2.4. Treating it as MEDIUM lets the
        # grade engine actually rate the listing instead of withholding; the
        # anomaly guard in grading.py still backstops implausible ARVs.
        confidence = "MEDIUM"
    elif li.opening_bid and li.opening_bid > 0:
        expected = float(li.opening_bid) * 2.4
        # Reject runaway proxies: on a comps-empty row opening_bid is often a
        # money judgment / total debt, not a property bid. Above the ceiling
        # the ×2.4 proxy emits a phantom multi-million ARV — return unavailable.
        if expected > MAX_PROXY_ARV:
            return None, None, None, "LOW", [
                f"Opening bid (${li.opening_bid:,.0f}) too large for a ×2.4 ARV proxy "
                f"(>${MAX_PROXY_ARV:,.0f}) — likely a judgment/debt figure, not a "
                f"property bid; ARV withheld."
            ]
        notes.append(f"ARV proxy from opening bid × 2.4 ({li.opening_bid:,.0f} × 2.4) — rough")
        confidence = "LOW"
    else:
        return None, None, None, "LOW", ["Insufficient data for ARV"]

    # Final backstop: the tax×1.25 path can also overshoot on a stale/wrong
    # assessment. Any proxy ARV above the ceiling is not trustworthy.
    if expected > MAX_PROXY_ARV:
        return None, None, None, "LOW", [
            f"Proxy ARV (${expected:,.0f}) exceeds the ${MAX_PROXY_ARV:,.0f} "
            f"plausibility ceiling — input likely a judgment/debt figure; ARV withheld."
        ]

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
    # Two failure modes the guard exists to catch:
    #
    #  (a) ratio < 0.6  → comp-implied ARV is *less* than the asking price.
    #      Almost always a bad-comp problem (wrong zip cluster, wrong
    #      property type, bid is the actual market). Anchor to listing.
    #
    #  (b) ratio > 1.6  → comp-implied ARV is way more than the asking
    #      price. For distressed/foreclosure inventory this is exactly
    #      the flip thesis we WANT to see. We do NOT anchor in this
    #      direction — that would silently kill every real deal.
    #
    # Therefore the guard only fires on (a), and only for retail-priced
    # sources where the listing is genuinely an asking price (HomeHarvest
    # active for-sale, Realtor foreclosure REO list price).
    if (out.arv_expected and li.opening_bid and li.opening_bid > 0
            and li.source in RETAIL_PRICE_SOURCES):
        ratio = out.arv_expected / li.opening_bid
        if ratio < 0.6:
            out.notes.append(
                f"ARV (${out.arv_expected:,.0f}) was {ratio:.1f}× listing price "
                f"(${li.opening_bid:,.0f}) — comps appear too low; anchoring ARV "
                f"to listing price as a floor."
            )
            out.arv_expected = float(li.opening_bid)
            out.arv_low = round(li.opening_bid * 0.90, -2)
            out.arv_high = round(li.opening_bid * 1.10, -2)
            arv_conf = "MEDIUM"
        elif ratio > 1.6:
            # Don't rewrite ARV — but record the wide gap so the dashboard /
            # investor can see it's a high-discount listing (potential flip).
            out.notes.append(
                f"Listing price (${li.opening_bid:,.0f}) is {1/ratio*100:.0f}% of "
                f"comp-grounded ARV (${out.arv_expected:,.0f}) — high-discount "
                f"signal; preserved for investor review."
            )

    # ---- Assessed-value anchor (comp accuracy cross-check) --------------
    # A comp-grounded ARV should exceed a distressed property's county
    # appraisal (after-repair > as-is), but a comp ARV that's WILDLY off the
    # assessor (>2.5x or <0.6x) almost always means bad comps (wrong submarket
    # or property type — the zip-match failure). We don't rewrite the ARV
    # (the assessor isn't ARV), but we flag it and lower confidence so a
    # bad-comp number can't masquerade as HIGH. Only meaningful when ARV is
    # comp-grounded (HIGH) — the tax-value fallback would be circular.
    assessed = li.market_value or li.assessed_value or li.tax_value
    if out.arv_expected and assessed and float(assessed) > 0:
        out.arv_vs_assessed = round(out.arv_expected / float(assessed), 2)
        if arv_conf == "HIGH" and (out.arv_vs_assessed > 2.5 or out.arv_vs_assessed < 0.6):
            arv_conf = "MEDIUM"
            out.notes.append(
                f"Comp ARV (${out.arv_expected:,.0f}) is {out.arv_vs_assessed:.1f}× the "
                f"county appraisal (${float(assessed):,.0f}) — comps may be off-market; "
                f"confidence lowered to MEDIUM, verify before bidding."
            )

    # ---- ARV FLOOR at county market value / recent recorded sale --------
    # A comp-grounded ARV BELOW what the county appraises the home at (or below a
    # recent arms-length sale) is almost always a thin/weak-comp artifact — the
    # home's own market appraisal and last sale are stronger signals than 3 stray
    # comps. After-repair value should never sit under the as-is county value.
    # So when comps are NOT high-confidence, FLOOR (raise) the ARV to it.
    mv = float(li.market_value) if (li.market_value and float(li.market_value) > 10000) else None
    sale_amt = None
    _ls = (raw.get("gis") or {}).get("last_sale") if isinstance(raw, dict) else None
    if isinstance(_ls, dict) and _ls.get("amount"):
        try:
            sale_amt = float(_ls["amount"]) if float(_ls["amount"]) > 10000 else None
        except (TypeError, ValueError):
            sale_amt = None
    floor_val = max([v for v in (mv, sale_amt) if v], default=None)
    if out.arv_expected and floor_val and out.arv_expected < floor_val:
        old_arv = out.arv_expected
        out.arv_expected = round(floor_val, -2)
        out.arv_low = round(min(out.arv_low or floor_val, floor_val * 0.95), -2)
        out.arv_high = round(max(out.arv_high or floor_val, floor_val * 1.10), -2)
        # A comp ARV that disagreed with the county/sale value is, by definition, not a
        # clean comp read — cap confidence at MEDIUM so a floored number reads as "verify".
        if arv_conf == "HIGH":
            arv_conf = "MEDIUM"
        out.notes.append(
            f"ARV floored to county market value/recent sale (${floor_val:,.0f}); "
            f"comp ARV (${old_arv:,.0f}) sat below the as-is value (after-repair can't be lower)."
        )

    # ---- Rehab range ----------------------------------------------------
    if li.property_kind == PropertyKind.LAND:
        out.rehab_tier = "land"
        out.rehab_low = out.rehab_expected = out.rehab_high = 0.0
    elif not li.living_sqft and li.property_kind != PropertyKind.MULTI_FAMILY:
        # Refuse to invent a sqft. Without sqft we cannot compute a rehab
        # range that's meaningful, so we don't compute one. The grade
        # pipeline downstream sees rehab_expected == None and treats it as
        # "data missing" rather than as a confident estimate. Multi-family
        # is exempt because their valuation runs per-unit, not per-sqft.
        out.rehab_tier = "unknown"
        out.notes.append(
            "Rehab not estimated: living_sqft missing. Confidence cannot "
            "be assigned without a building size."
        )
    else:
        tier = _condition_to_tier(li)
        out.rehab_tier = tier
        sqft = li.living_sqft or 1000  # multi-family fallback (per-unit avg)

        # Mobile / manufactured homes use a much cheaper rehab tier table
        # (vinyl skirting, single-pane windows, cosmetic-grade fixtures).
        # Generic SFR rehab cost overstates by 30-50% on these.
        is_mobile = li.property_kind == PropertyKind.MOBILE
        tier_table = MOBILE_REHAB_TIERS if is_mobile else REHAB_TIERS

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
            lo_psf, mid_psf, hi_psf = tier_table[tier]
            out.rehab_low = round(lo_psf * sqft, -2)
            out.rehab_expected = round(mid_psf * sqft, -2)
            out.rehab_high = round(hi_psf * sqft, -2)
            kind_tag = "mobile" if is_mobile else "standard"
            out.notes.append(
                f"Rehab tier '{tier}' ({kind_tag}) on {sqft:,.0f} sqft "
                f"= ${lo_psf}-${hi_psf}/sqft"
            )

    # Senior liens reduce what a buyer can pay:
    #  (a) at a JUNIOR-position foreclosure the winner takes title SUBJECT TO all
    #      senior debt (rod/priority.py total_senior_amount), and
    #  (b) SUPER-PRIORITY liens (state tax liens) survive ANY foreclosure, so
    #      they always come off the bid (enrichment_lien_stack -> raw['liens']).
    # Either way the cost must come out of both max bid and total investment,
    # else the deal looks falsely cheap.
    lp = raw.get("lien_priority") or {}
    senior = float(lp.get("total_senior_amount") or 0)
    fpos = lp.get("foreclosure_position")
    junior_senior = senior if (senior > 0 and (fpos is None or fpos > 1)) else 0.0
    superpri = sum(float(x.get("amount") or 0) for x in (raw.get("liens") or [])
                   if isinstance(x, dict) and x.get("super_priority"))
    senior_cost = round(junior_senior + superpri, 2)
    senior_applies = senior_cost > 0

    # Pad the repair estimate with a contingency buffer for the buy math — every
    # seasoned flipper bids on rehab + 10-15% for hidden conditions, never the
    # optimistic mid. (The headline rehab_expected stays un-padded for display.)
    rehab_buy = round((out.rehab_expected or 0) * (1 + REHAB_CONTINGENCY_PCT), -2)
    if out.rehab_expected:
        out.rehab_with_contingency = rehab_buy

    # ---- Max bid (70% rule, expected case) ------------------------------
    if out.arv_expected:
        fees = out.arv_expected * SELLING_PCT
        out.max_bid_70 = max(
            0.0,
            round(0.70 * out.arv_expected - rehab_buy - fees, -2),
        )
        if senior_applies and out.max_bid_70 is not None:
            out.max_bid_70 = max(0.0, round(out.max_bid_70 - senior_cost, -2))
            bits = []
            if junior_senior:
                bits.append(f"${junior_senior:,.0f} junior-position senior lien(s)")
            if superpri:
                bits.append(f"${superpri:,.0f} super-priority lien(s) (e.g. tax)")
            out.notes.append(
                "Subtracted " + " + ".join(bits) + " from max bid (buyer takes "
                "title subject to this debt)."
            )
        # Wholesale lens: what an end-investor MAO leaves for an assignment fee.
        if out.max_bid_70 is not None:
            out.wholesale_mao = max(0.0, round(out.max_bid_70 - ASSIGNMENT_FEE, -2))
            if li.opening_bid:
                out.wholesale_spread = round(out.max_bid_70 - float(li.opening_bid), -2)

    # ---- Total investment if bidding at opening bid ---------------------
    # Holding period scales with local market velocity (months-of-inventory from
    # enrichment_comps): fast market -> shorter carry, slow market -> longer.
    holding_months = (raw.get("market_velocity") or {}).get("holding_months_est") or HOLDING_MONTHS
    bid = li.opening_bid
    if bid and out.arv_expected:
        closing = bid * CLOSING_PCT
        holding = bid * HOLDING_RATE_MONTH * holding_months
        selling = out.arv_expected * SELLING_PCT
        # senior_cost (junior-position + super-priority liens) computed above;
        # rehab_buy includes the contingency buffer (same number used for max bid).
        total = bid + senior_cost + rehab_buy + closing + holding + selling
        out.total_investment = round(total, -2)
        out.estimated_profit = round(out.arv_expected - total, -2)
        if total > 0:
            out.roi_pct = round((out.estimated_profit / total) * 100, 1)
        # Cash on cash: 25% down + 75% loan. Use rehab_buy (contingency-padded)
        # and the market-velocity holding_months EVERYWHERE so the cash math is
        # the same deal as the flip math (Pass-2 fix: was using un-padded rehab
        # + the fixed 6-month constant, making CoC optimistic vs ROI).
        cash_down = bid * DOWN_PCT + rehab_buy  # rehab usually cash
        loan_amt = bid * (1 - DOWN_PCT)
        loan_interest = loan_amt * LOAN_RATE_MONTH * holding_months
        cash_profit = out.arv_expected - bid - senior_cost - rehab_buy - closing - holding - selling - loan_interest
        if cash_down > 0:
            out.cash_on_cash_pct = round((cash_profit / cash_down) * 100, 1)
        out.bid_to_arv_pct = round((bid / out.arv_expected) * 100, 1)

    # ---- Confidence -----------------------------------------------------
    score = 0
    if arv_conf == "HIGH":
        score += 3      # comp-grounded ARV — was previously unscored (bug)
    elif arv_conf == "MEDIUM":
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
    # Persist the ARV-method confidence so grading.py can read it (it was
    # computed locally but never stored — grade-withhold silently degraded to
    # bid-only). arv_conf is final by here (set in _arv_signals + any MEDIUM
    # upgrade above).
    out.arv_confidence = arv_conf

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

    # ---- Buy-and-hold (rental) verdict ----------------------------------
    # An investor not interested in flipping wants to know: at this bid,
    # what's the cap rate and monthly cashflow if I held it as a rental?
    # Standard 50% rule: NOI = 50% of gross rent (covers vacancy, property
    # mgmt, insurance, taxes, maintenance, capex reserve).
    rent_psf = raw.get("rent_median_ppsf") if isinstance(raw, dict) else None
    if (rent_psf and li.living_sqft and bid and bid > 0
            and li.property_kind not in (PropertyKind.LAND,)):
        monthly_rent = float(rent_psf) * float(li.living_sqft)
        out.monthly_rent_est = round(monthly_rent, 0)
        out.annual_gross_rent = round(monthly_rent * 12, 0)
        out.noi_annual = round(out.annual_gross_rent * 0.50, 0)
        # Total acquisition for cap rate: bid + rehab + closing fees.
        # Holding/selling fees don't apply to a hold strategy.
        rehab = out.rehab_expected or 0
        acq_total = bid + rehab + bid * CLOSING_PCT
        if acq_total > 0:
            out.cap_rate_pct = round((out.noi_annual / acq_total) * 100, 1)
        # Monthly cashflow vs. PITI on a 25%-down 30-yr mortgage @ 7.5%.
        # (Hard-money holding cost in the flip path is too short-term to
        # use for hold; this is permanent-financing economics.)
        loan_amt = bid * (1 - DOWN_PCT)
        # 30-yr fixed at 7.5% APR → monthly P&I ≈ loan × 0.006992
        piti_monthly = loan_amt * 0.006992
        # Add taxes + insurance estimate: 1.5% of bid annually
        piti_monthly += (bid * 0.015) / 12
        cashflow = (out.noi_annual / 12) - piti_monthly
        out.monthly_cashflow_est = round(cashflow, 0)
        # 1% rule: monthly rent ≥ 1% of PURCHASE PRICE (conventional usage —
        # investors apply this against the offer/bid, not all-in cost).
        out.one_pct_rule = monthly_rent >= bid * 0.01

        # Verdict: cap-rate-driven (NOI / acq).
        # 10%+ cap = exceptional; 8% = good; 6% = market; <5% = thin
        cr = out.cap_rate_pct or 0
        if cr >= 10 and out.monthly_cashflow_est > 0:
            out.hold_status = "GREAT"
            out.hold_message = (
                f"Cap rate {cr:.1f}% with ${out.monthly_cashflow_est:.0f}/mo cashflow. "
                f"Strong rental in this market."
            )
        elif cr >= 7 and out.monthly_cashflow_est > 0:
            out.hold_status = "OK"
            out.hold_message = (
                f"Cap rate {cr:.1f}% — market-rate rental. Cashflow ${out.monthly_cashflow_est:.0f}/mo."
            )
        elif cr >= 5:
            out.hold_status = "NEGOTIATE"
            out.hold_message = (
                f"Cap rate {cr:.1f}% is thin. Monthly cashflow "
                f"${out.monthly_cashflow_est:.0f}/mo at this bid; "
                f"would need a price cut to clear hurdle."
            )
        else:
            out.hold_status = "PASS"
            out.hold_message = (
                f"Cap rate {cr:.1f}% — won't pencil as a rental at this bid."
            )

    return out


def to_dict(c: Calc) -> dict:
    return {k: v for k, v in asdict(c).items() if v is not None}

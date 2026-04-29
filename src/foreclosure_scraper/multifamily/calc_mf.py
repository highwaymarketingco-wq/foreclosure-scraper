"""Multifamily-specific calc + grading.

Foreclosure flips care about ARV - rehab. Multifamily buyers care about
cash flow: cap rate, GRM, price-per-unit, price-per-sqft, neighborhood
trajectory. This module computes those metrics + an A-F grade.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..models import Listing


# Market benchmarks for upstate SC + nearby NC (refresh annually from CoStar reports)
BENCHMARKS = {
    "cap_rate_target_pct": 7.0,         # current upstate market median for B/C class
    "grm_target": 8.5,                  # gross rent multiplier
    "price_per_unit_avg": 110_000,      # 5-20 unit B/C class
    "price_per_sqft_avg": 95.0,
    "expense_ratio_default": 0.45,      # NOI = GPR x (1 - 0.45)
    "vacancy_default_pct": 7.0,
}


@dataclass
class MultifamilyCalc:
    units: int | None = None
    asking_price: float | None = None
    price_per_unit: float | None = None
    price_per_sqft: float | None = None
    estimated_gpr: float | None = None      # gross potential rent (annual)
    estimated_noi: float | None = None      # net operating income
    cap_rate_pct: float | None = None
    grm: float | None = None                # gross rent multiplier
    cash_on_cash_pct: float | None = None
    rationale: list[str] = field(default_factory=list)


def _estimate_unit_rent(li: Listing) -> float | None:
    """Pull avg unit rent from RentCast if present, else use Census ACS median * 1.0."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    rc = raw.get("rentcast") or {}
    if rc.get("rent_value"):
        return float(rc["rent_value"])
    loc = raw.get("location") or {}
    median_rent = loc.get("median_gross_rent")
    if median_rent:
        return float(median_rent)
    return None


def compute_multifamily(li: Listing) -> MultifamilyCalc:
    out = MultifamilyCalc()
    raw = li.raw if isinstance(li.raw, dict) else {}

    units = raw.get("units")
    if units:
        try:
            out.units = int(units)
        except (TypeError, ValueError):
            pass
    out.asking_price = li.market_value or None

    if out.asking_price and out.units:
        out.price_per_unit = round(out.asking_price / out.units, 2)
        out.rationale.append(f"Price/unit = ${out.price_per_unit:,.0f}")

    if out.asking_price and li.living_sqft:
        out.price_per_sqft = round(out.asking_price / li.living_sqft, 2)

    # Cap rate
    listed_cap = raw.get("cap_rate")
    if listed_cap:
        try:
            out.cap_rate_pct = float(listed_cap) * (100 if float(listed_cap) < 1 else 1)
            out.rationale.append(f"Cap rate (listed) = {out.cap_rate_pct:.2f}%")
        except (TypeError, ValueError):
            pass

    # Estimate GPR / NOI / cap rate when not listed
    unit_rent = _estimate_unit_rent(li)
    if unit_rent and out.units:
        out.estimated_gpr = round(unit_rent * out.units * 12, 0)
        vac = BENCHMARKS["vacancy_default_pct"] / 100.0
        gross_collected = out.estimated_gpr * (1 - vac)
        out.estimated_noi = round(gross_collected * (1 - BENCHMARKS["expense_ratio_default"]), 0)
        if out.asking_price:
            if out.cap_rate_pct is None:
                out.cap_rate_pct = round((out.estimated_noi / out.asking_price) * 100, 2)
                out.rationale.append(
                    f"Cap rate (estimated, {BENCHMARKS['vacancy_default_pct']}% vac, "
                    f"{BENCHMARKS['expense_ratio_default']*100:.0f}% expenses) = {out.cap_rate_pct:.2f}%"
                )
            out.grm = round(out.asking_price / out.estimated_gpr, 2)
            out.rationale.append(f"GRM = {out.grm:.2f}")
            # Cash-on-cash assuming 25% down @ 7.5% interest 30-yr
            if out.estimated_noi:
                down = out.asking_price * 0.25
                loan = out.asking_price * 0.75
                annual_debt = loan * 0.0852  # rough P+I factor for 30-yr @ 7.5%
                pre_tax = out.estimated_noi - annual_debt
                if down > 0:
                    out.cash_on_cash_pct = round((pre_tax / down) * 100, 2)
                    out.rationale.append(
                        f"Cash-on-cash (25% down, 7.5% / 30y) = {out.cash_on_cash_pct:.2f}%"
                    )

    return out


def grade_multifamily(li: Listing, calc: MultifamilyCalc) -> dict:
    """Return {overall_grade, overall_score, dimensions:{...}, rationale:[...]}.

    Simple weighted scoring across cap-rate / cash-on-cash / price-per-unit /
    location quality.
    """
    rationale: list[str] = []
    scores: dict[str, float] = {}

    # Cap rate: 35% weight. >= 8% = 100, 7-8 = 85, 6-7 = 70, 5-6 = 55, <5 = 30
    cap = calc.cap_rate_pct or 0
    if cap >= 8:
        scores["cap_rate"] = 100
    elif cap >= 7:
        scores["cap_rate"] = 85
    elif cap >= 6:
        scores["cap_rate"] = 70
    elif cap >= 5:
        scores["cap_rate"] = 55
    elif cap > 0:
        scores["cap_rate"] = 30
    else:
        scores["cap_rate"] = 50  # unknown - middling
    rationale.append(f"Cap rate {cap:.2f}% -> {scores['cap_rate']}")

    # Cash-on-cash: 25% weight
    coc = calc.cash_on_cash_pct or 0
    if coc >= 10:
        scores["coc"] = 100
    elif coc >= 7:
        scores["coc"] = 85
    elif coc >= 4:
        scores["coc"] = 70
    elif coc > 0:
        scores["coc"] = 50
    else:
        scores["coc"] = 50
    rationale.append(f"Cash-on-cash {coc:.2f}% -> {scores['coc']}")

    # Price-per-unit vs market: 20% weight (lower is better)
    ppu = calc.price_per_unit or 0
    bench = BENCHMARKS["price_per_unit_avg"]
    if ppu and ppu < bench * 0.7:
        scores["ppu"] = 100
    elif ppu and ppu < bench * 0.85:
        scores["ppu"] = 85
    elif ppu and ppu < bench * 1.0:
        scores["ppu"] = 70
    elif ppu and ppu < bench * 1.2:
        scores["ppu"] = 55
    elif ppu:
        scores["ppu"] = 35
    else:
        scores["ppu"] = 50
    rationale.append(f"Price/unit ${ppu:,.0f} vs benchmark ${bench:,} -> {scores['ppu']}")

    # Location: 20% weight (Census ACS signals)
    raw = li.raw if isinstance(li.raw, dict) else {}
    loc = raw.get("location") or {}
    income = loc.get("median_household_income") or 0
    owner_pct = loc.get("owner_occupied_pct") or 0
    home_val = loc.get("median_home_value") or 0
    loc_score = 50.0
    if income > 75_000:
        loc_score += 15
    elif income > 55_000:
        loc_score += 5
    if home_val > 250_000:
        loc_score += 15
    elif home_val > 180_000:
        loc_score += 5
    if owner_pct > 60:
        loc_score += 10
    scores["location"] = min(100, loc_score)
    rationale.append(f"Location: income ${income:,.0f}, home_val ${home_val:,.0f}, "
                     f"owner {owner_pct:.0f}% -> {scores['location']:.0f}")

    weights = {"cap_rate": 0.35, "coc": 0.25, "ppu": 0.20, "location": 0.20}
    overall = sum(scores[k] * w for k, w in weights.items())
    if overall >= 90:
        letter = "A"
    elif overall >= 80:
        letter = "B"
    elif overall >= 65:
        letter = "C"
    elif overall >= 50:
        letter = "D"
    else:
        letter = "F"

    return {
        "overall_grade": letter,
        "overall_score": round(overall, 1),
        "dimensions": scores,
        "rationale": rationale,
    }


def to_dict_mf(c: MultifamilyCalc) -> dict:
    return asdict(c)

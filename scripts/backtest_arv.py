#!/usr/bin/env python3
"""Standing ARV / max-bid accuracy backtest harness.

Reads docs/listings.json READ-ONLY and prints an accuracy report. Writes nothing.

Method:
  We treat each lead's last RECORDED SALE (an actual arm's-length transaction)
  as ground truth for resale value, index-adjust it to current dollars with a
  coarse Carolina FHFA-HPI multiplier, then compare the engine's computed
  calc.arv_expected against that adjusted resale. The error is reported as a
  MEDIAN (never a mean) because the distribution is heavy-tailed and a single
  rural mis-comp would wreck a mean.

Eligibility (every condition must hold):
  - raw.last_sale.basis == 'recorded_sale'
  - raw.last_sale.amount  > $20,000
  - recorded sale year in [2000, 2026]
  - raw.calc.arv_expected is present (not None)

Exclusions (their error would be circular or non-retail):
  - FLOOR-ANCHORED rows: calc.notes contain 'floored', OR arv_expected equals
    last_sale.amount. The ARV was pinned to the sale/market value, so comparing
    it back to that same number is tautological.
  - source in the non-retail set (foreclosure_d / foreclosure.com, any HUD feed)
    whose dollar amounts are auction/subsidy figures, not open-market resale.

Index adjustment (Carolina FHFA-HPI approximation, multiply historical $ ->
current $):
  2024 -> 1.13, 2022 -> 1.30, 2020 -> 1.62, 2015 -> 2.16, 2010 -> 2.52,
  current -> 1.00. Years between anchors snap to the nearest defined anchor.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LISTINGS = Path(__file__).resolve().parent.parent / "docs" / "listings.json"

# FHFA-HPI-style multipliers: historical sale $ * factor = current $.
# Keyed by anchor year; intervening years snap to the nearest anchor.
HPI_ANCHORS = {
    2026: 1.00,
    2025: 1.00,
    2024: 1.13,
    2022: 1.30,
    2020: 1.62,
    2015: 2.16,
    2010: 2.52,
}

NON_RETAIL_SOURCES = {
    "national.foreclosure_d",
    "national.foreclosure_dot_com",
}


def hpi_factor(year: int) -> float:
    """Nearest-anchor HPI multiplier for a given sale year."""
    anchors = sorted(HPI_ANCHORS)
    best = min(anchors, key=lambda a: abs(a - year))
    return HPI_ANCHORS[best]


def sale_year(date_str: str) -> int | None:
    m = re.match(r"(\d{4})", str(date_str or ""))
    if not m:
        return None
    return int(m.group(1))


def is_non_retail(source: str) -> bool:
    if source in NON_RETAIL_SOURCES:
        return True
    return "hud" in (source or "").lower()


def pct(vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0..1) over a non-empty list."""
    s = sorted(vals)
    if not s:
        return float("nan")
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def median(vals: list[float]) -> float:
    return pct(vals, 0.5)


def collect() -> list[dict]:
    rows = json.loads(LISTINGS.read_text())
    out = []
    for r in rows:
        raw = r.get("raw") or {}
        ls = raw.get("last_sale") or {}
        calc = raw.get("calc") or {}

        if ls.get("basis") != "recorded_sale":
            continue
        amt = ls.get("amount")
        if not isinstance(amt, (int, float)) or amt <= 20000:
            continue
        yr = sale_year(ls.get("date"))
        if yr is None or yr < 2000 or yr > 2026:
            continue
        arv = calc.get("arv_expected")
        if not isinstance(arv, (int, float)):
            continue

        # Exclude floor-anchored (circular) rows.
        notes = " ".join(calc.get("notes") or []).lower()
        if "floored" in notes or abs(arv - amt) < 1e-6:
            continue

        # Exclude non-retail dollar sources.
        if is_non_retail(r.get("source") or ""):
            continue

        factor = hpi_factor(yr)
        adj_sale = amt * factor
        if adj_sale <= 0:
            continue

        out.append(
            {
                "county": r.get("county") or "(unknown)",
                "arv_confidence": calc.get("arv_confidence") or "(none)",
                "arv": float(arv),
                "adj_sale": float(adj_sale),
                "arv_err": (arv - adj_sale) / adj_sale,
                "max_bid_70": calc.get("max_bid_70"),
                "year": yr,
            }
        )
    return out


def build_calibration(items: list[dict], min_n: int = 8) -> dict[str, float]:
    """Per-county ARV calibration factor = 1 / (1 + median_bias).

    Corrects the measured systematic per-county ARV bias. Only counties with
    >= min_n eligible backtest rows earn a factor (else no evidence). Clamped
    to [0.4, 2.5] so one noisy county can't swing ARV wildly. Consumed by
    valuation/calc.py:_arv_calibration_factor.
    """
    by_cty: dict[str, list[float]] = {}
    for i in items:
        by_cty.setdefault(str(i["county"]).strip().lower(), []).append(i["arv_err"])
    factors: dict[str, float] = {}
    for cty, errs in by_cty.items():
        if not cty or cty == "(unknown)" or len(errs) < min_n:
            continue
        bias = median(errs)
        factors[cty] = round(max(0.4, min(2.5, 1.0 / (1.0 + bias))), 4)
    return factors


def fmt_block(label: str, items: list[dict]) -> str:
    n = len(items)
    if n == 0:
        return f"  {label:<24} n=0"
    errs = [i["arv_err"] for i in items]
    med = median(errs)
    p25 = pct(errs, 0.25)
    p75 = pct(errs, 0.75)
    within20 = sum(1 for e in errs if abs(e) <= 0.20) / n
    return (
        f"  {label:<24} n={n:<4} "
        f"med={med:+.1%}  p25={p25:+.1%}  p75={p75:+.1%}  "
        f"within20%={within20:.0%}"
    )


def main() -> None:
    items = collect()
    n = len(items)

    print("=" * 78)
    print("ARV / MAX-BID ACCURACY BACKTEST")
    print(f"source: {LISTINGS}")
    print("=" * 78)
    print(f"\nEligible leads (recorded-sale, non-floored, retail): {n}\n")

    if n == 0:
        print("No eligible leads. Nothing to report.")
        return

    # --- ARV error overall ---
    errs = [i["arv_err"] for i in items]
    aerr = [abs(e) for e in errs]
    print("ARV ERROR = (arv_expected - HPI_adjusted_recorded_sale) / adj_sale")
    print(f"  OVERALL  median={median(errs):+.1%}  "
          f"p25={pct(errs,0.25):+.1%}  p75={pct(errs,0.75):+.1%}  "
          f"within20%={sum(1 for e in errs if abs(e)<=0.20)/n:.0%}")
    print(f"  MdAPE={median(aerr):.1%}  "
          f"PPE10={sum(1 for e in aerr if e<=0.10)/n:.0%}  "
          f"PPE20={sum(1 for e in aerr if e<=0.20)/n:.0%}  "
          f"bias(signed median)={median(errs):+.1%}   "
          f"(targets: MdAPE<10%, PPE10>60%, |bias|<3%)")

    # --- by confidence ---
    print("\nBY ARV_CONFIDENCE")
    confs = sorted({i["arv_confidence"] for i in items})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for c in sorted(confs, key=lambda x: order.get(x, 9)):
        print(fmt_block(c, [i for i in items if i["arv_confidence"] == c]))

    # --- by county ---
    print("\nBY COUNTY (>=5 leads)")
    counties = {}
    for i in items:
        counties.setdefault(i["county"], []).append(i)
    for cty in sorted(counties, key=lambda k: -len(counties[k])):
        grp = counties[cty]
        if len(grp) < 5:
            continue
        print(fmt_block(cty, grp))

    # --- max_bid_70 as fraction of adjusted resale ---
    mb = [
        i["max_bid_70"] / i["adj_sale"]
        for i in items
        if isinstance(i["max_bid_70"], (int, float)) and i["adj_sale"] > 0
    ]
    print("\nMAX_BID_70 as fraction of HPI-adjusted recorded sale")
    if mb:
        sub55 = sum(1 for x in mb if x < 0.55) / len(mb)
        print(f"  n={len(mb)}  median={median(mb):.1%}  "
              f"p25={pct(mb,0.25):.1%}  p75={pct(mb,0.75):.1%}  "
              f"sub-55%rate={sub55:.0%}")
        print("  (a disciplined 70%-rule max bid should sit well under 55% of "
              "true resale once rehab+margin are carved out)")
    else:
        print("  n=0 (no max_bid_70 values present)")

    print("\n" + "=" * 78)


def emit_calibration() -> None:
    items = collect()
    factors = build_calibration(items)
    out = {
        "generated_by": "scripts/backtest_arv.py --emit-calibration",
        "method": "factor = 1/(1+median_bias); counties with >=8 recorded-sale "
                  "backtest rows; clamped [0.4, 2.5]",
        "n_eligible_rows": len(items),
        "n_counties": len(factors),
        "factors": factors,
    }
    dest = Path(__file__).resolve().parent.parent / "data" / "arv_calibration.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"wrote {dest}  ({len(factors)} county factors from {len(items)} rows)")
    for c, f in sorted(factors.items()):
        arrow = "over-values → shrink" if f < 1 else "under-values → lift"
        print(f"  {c:<16} ×{f}   ({arrow})")


if __name__ == "__main__":
    import sys
    if "--emit-calibration" in sys.argv:
        emit_calibration()
    else:
        main()

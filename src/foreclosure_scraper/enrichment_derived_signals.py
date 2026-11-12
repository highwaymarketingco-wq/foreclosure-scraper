"""Net-new DERIVED signals — zero new scrape, pure computation over fields we
already collect. These were identified as cheap lifts the pipeline was leaving
on the table (TRACK: downstream recompute).

Two signals, both gated to avoid the known garbage-in failure modes:

  1. discount_to_arv  — bid as a fraction of a TRUSTWORTHY (HIGH/MEDIUM) ARV, on
     sources where the bid is a real acquisition floor (NOT a retail REO/asking
     price). A deeply-discounted price on a distress listing is a motivated-
     seller signal the distress stack currently ignores (it only reads roi_pct).

  2. lien_to_value (LTV) — (payoff_estimate + senior_liens) / arv_used, taken
     straight from the equity engine's own output. The equity engine emits the
     dollar pieces but never the ratio; LTV is the bankable "how levered is this
     seller" number that lenders/wholesalers actually screen on. Pure derive —
     it costs nothing and is available for EVERY row equity already computed.

Designed to run AFTER calc + equity, alongside / just before distress_score, so
the bands can feed the operator board. No I/O. Mirrors calc.py's RETAIL gate so
the two never disagree about when a bid is an asking price.
"""
from __future__ import annotations

from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# Sources where opening_bid is a RETAIL asking price, not a foreclosure floor.
# Mirrors valuation/calc.RETAIL_PRICE_SOURCES plus the bank-REO list portals,
# so a discount band is never computed off an asking price (which would fake a
# huge "discount" vs its own ARV).
_RETAIL_SOURCES = {
    "national.homeharvest",
    "national.realtor_foreclosures",
    "national.fannie_homepath",
    "national.hudhomestore",
}


def _discount_to_arv(li: Listing) -> Optional[dict]:
    """bid / arv on a non-retail listing with a trustworthy ARV."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    bid = li.opening_bid
    arv = calc.get("arv_expected")
    conf = (calc.get("arv_confidence") or "").upper()
    if not (bid and arv and arv > 0):
        return None
    # Never bank a discount band on a proxy (opening-bid×2.4) ARV — it's circular.
    if conf not in ("HIGH", "MEDIUM"):
        return None
    lt = (li.listing_type.value if hasattr(li.listing_type, "value")
          else str(li.listing_type or "")).lower()
    if li.source in _RETAIL_SOURCES or lt == "reo":
        return None
    ratio = float(bid) / float(arv)
    if ratio <= 0.50:
        band = "deep_discount"
    elif ratio <= 0.70:
        band = "moderate_discount"
    else:
        band = "near_retail"
    return {"ratio": round(ratio, 3), "band": band, "arv_confidence": conf}


def _lien_to_value(li: Listing) -> Optional[dict]:
    """(payoff + senior_liens) / arv, straight from the equity engine output."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    eq = raw.get("equity")
    if not isinstance(eq, dict):
        return None
    arv = eq.get("arv_used")
    payoff = eq.get("payoff_estimate")
    seniors = eq.get("senior_liens") or 0
    if not (arv and arv > 0 and payoff is not None):
        return None
    ltv = (float(payoff) + float(seniors)) / float(arv)
    if ltv >= 0.85:
        band = "thin_equity"      # highly levered — short-sale / underwater risk
    elif ltv >= 0.60:
        band = "moderate_equity"
    else:
        band = "deep_equity"      # lots of room — best buy-below-market candidate
    return {"ltv": round(ltv, 3), "band": band, "confidence": eq.get("confidence")}


def enrich_derived_signals(listings: list[Listing]) -> dict:
    """Attach raw['derived_signals'] = {discount_to_arv?, lien_to_value?}.

    Pure compute over calc + equity output. Returns a coverage histogram.
    """
    n_disc = n_ltv = n_any = 0
    for li in listings:
        out: dict = {}
        d = _discount_to_arv(li)
        if d:
            out["discount_to_arv"] = d
            n_disc += 1
        l = _lien_to_value(li)
        if l:
            out["lien_to_value"] = l
            n_ltv += 1
        if out:
            raw = li.raw if isinstance(li.raw, dict) else {}
            raw["derived_signals"] = out
            li.raw = raw
            n_any += 1
    log.info("derived_signals.done", discount=n_disc, ltv=n_ltv,
             any=n_any, total=len(listings))
    return {"discount_to_arv": n_disc, "lien_to_value": n_ltv, "rows": n_any}

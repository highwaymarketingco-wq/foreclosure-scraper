"""Owner-equity engine — the #1 thing a fix-and-flipper needs: how much equity
the seller has, i.e. ARV − mortgage payoff − junior liens.

This is what tells you whether a deal even exists. A pre-foreclosure with deep
equity is a motivated seller you can buy below market; one that's underwater
needs a short sale or is a dead lead. The old flags.py 'equity' treated the
PURCHASE PRICE as the balance owed (ignores years of paydown) — wrong. Here we
estimate the CURRENT payoff:

  1. recorded Deed of Trust amount + date  -> amortized current balance  (best)
  2. amount_owed when it's an ACTUAL debt   (foreclosure judgment / indebtedness)
  3. last arms-length sale price            -> assume ~90% financed, amortized
  4. none                                   -> equity unknown (we say so)

equity = ARV − payoff − senior_liens ; equity_pct = equity / ARV.
Runs AFTER calc (needs arv_expected) and amount_owed, BEFORE distress scoring
(which now gates HOT on real equity). Pure-Python, no I/O, no cost.
"""
from __future__ import annotations

from typing import Optional

import structlog

from .models import Listing
from .valuation.amortize import amortized_balance

log = structlog.get_logger()

_LTV_PROXY = 0.90   # if we only know the sale price, assume ~90% was financed


def _arv(li: Listing) -> Optional[float]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    arv = calc.get("arv_expected")
    if arv:
        return float(arv)
    if li.market_value:
        return float(li.market_value)
    if li.tax_value:
        return float(li.tax_value) * 1.25
    return None


def _recorded_dt(raw: dict) -> tuple[Optional[float], object]:
    """Best recorded Deed-of-Trust (mortgage) original amount + date, if captured."""
    docs = raw.get("rod_docs") or []
    best_amt, best_date = None, None
    for d in docs if isinstance(docs, list) else []:
        dt = (d.get("doc_type") or "").upper()
        if "DEED OF TRUST" in dt or dt in ("DT", "MTG", "MORTGAGE"):
            amt = d.get("amount")
            if amt and (best_amt is None or (d.get("recorded_date") or "") > (best_date or "")):
                best_amt, best_date = float(amt), d.get("recorded_date")
    return best_amt, best_date


def _senior_liens(raw: dict) -> float:
    lp = raw.get("lien_priority") or {}
    total = lp.get("total_senior_amount")
    if total:
        return float(total)
    liens = raw.get("liens") or []
    return float(sum((x.get("amount") or 0) for x in liens if isinstance(x, dict)))


def _payoff(li: Listing) -> tuple[Optional[float], str, str]:
    """(estimated_payoff, source, confidence)."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    # 1) recorded Deed of Trust -> amortized current balance
    amt, dt = _recorded_dt(raw)
    if amt and dt:
        bal = amortized_balance(amt, dt)
        if bal is not None:
            return bal, "recorded_deed_of_trust", "high"
    # 2) amount_owed when it's an actual debt (judgment / indebtedness)
    ao = raw.get("amount_owed") or {}
    if ao.get("is_actual_debt") and ao.get("value"):
        return float(ao["value"]), f"amount_owed:{ao.get('source', '?')}", ao.get("confidence", "medium")
    # 3) last arms-length sale -> assume ~90% financed, amortize from sale date
    gis = raw.get("gis") or {}
    ls = gis.get("last_sale") or {}
    sale_amt = ls.get("amount") or gis.get("last_sale_amount")
    sale_date = ls.get("date") or gis.get("last_sale_date")
    if sale_amt and sale_date:
        bal = amortized_balance(float(sale_amt) * _LTV_PROXY, sale_date)
        if bal is not None:
            return bal, "last_sale_amortized", "low"
    return None, "unknown", "none"


def enrich_equity(listings: list[Listing]) -> dict:
    """Attach raw['equity'] = {value, pct, arv_used, payoff, payoff_source, ...}."""
    n = 0
    for li in listings:
        arv = _arv(li)
        if not arv or arv <= 0:
            continue
        payoff, src, conf = _payoff(li)
        if payoff is None:
            continue
        seniors = _senior_liens(li.raw if isinstance(li.raw, dict) else {})
        equity = round(arv - payoff - seniors, -2)
        raw = li.raw if isinstance(li.raw, dict) else {}
        raw["equity"] = {
            "value": equity,
            "pct": round(equity / arv, 3),
            "arv_used": round(arv, -2),
            "payoff_estimate": round(payoff, -2),
            "payoff_source": src,
            "senior_liens": round(seniors, -2),
            "confidence": conf,
            "is_underwater": equity < 0,
        }
        li.raw = raw
        n += 1
    log.info("equity.done", computed=n, total=len(listings))
    return {"computed": n}

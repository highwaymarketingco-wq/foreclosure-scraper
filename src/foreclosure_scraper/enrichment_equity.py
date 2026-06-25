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

from datetime import date

from .models import Listing
from .valuation.amortize import _as_date, amortized_balance

log = structlog.get_logger()

_LTV_PROXY = 0.90   # if we only know the sale price, assume ~90% was financed

# NC counties whose parcel layer publishes a sale AMOUNT but no sale DATE.
# For these we attach a conservative assumed note date so the last-sale path
# can still produce a (low-confidence) payoff instead of yielding 0 equity.
_NC_AMOUNT_ONLY = {"Buncombe", "Lincoln", "Transylvania"}
_ASSUMED_NOTE_AGE_YEARS = 3   # recent -> conservative (high payoff, low equity)


def _assumed_note_date() -> date:
    """A deliberately recent assumed origination date for amount-only counties.
    Recent = less paydown = higher estimated balance = we never overstate equity."""
    today = date.today()
    try:
        return today.replace(year=today.year - _ASSUMED_NOTE_AGE_YEARS)
    except ValueError:  # Feb 29 on a non-leap target year
        return today.replace(year=today.year - _ASSUMED_NOTE_AGE_YEARS, day=28)


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
    """Best (most-recent) recorded Deed-of-Trust original amount + date."""
    docs = raw.get("rod_docs") or []
    best_amt, best_date, best_key = None, None, None
    for d in docs if isinstance(docs, list) else []:
        dt = (d.get("doc_type") or "").upper()
        if "DEED OF TRUST" in dt or dt in ("DT", "MTG", "MORTGAGE"):
            amt = d.get("amount")
            if not amt:
                continue
            # Compare PARSED dates, not raw strings — ROD feeds mix ISO and
            # US formats, so a string compare picks the wrong (older) note.
            key = _as_date(d.get("recorded_date")) or date.min
            if best_key is None or key > best_key:
                best_amt, best_date, best_key = float(amt), d.get("recorded_date"), key
    return best_amt, best_date


def _senior_liens(raw: dict) -> float:
    """Senior debt the buyer takes subject to — MIRRORS calc.py exactly so the
    two never disagree: junior-position senior total (gated on fpos>1) PLUS any
    super-priority liens from raw['liens'] (state tax liens survive any sale)."""
    lp = raw.get("lien_priority") or {}
    total = float(lp.get("total_senior_amount") or 0)
    fpos = lp.get("foreclosure_position")
    junior = total if (total > 0 and (fpos is None or fpos > 1)) else 0.0
    superpri = sum(float(x.get("amount") or 0) for x in (raw.get("liens") or [])
                   if isinstance(x, dict) and x.get("super_priority"))
    return junior + superpri


def _payoff(li: Listing, arv: float) -> tuple[Optional[float], str, str]:
    """(estimated_payoff, source, confidence). arv is the value reference used to
    arms-length-gate the last-sale proxy."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    # 1) recorded Deed of Trust -> amortized current balance
    amt, dt = _recorded_dt(raw)
    if amt and dt:
        bal = amortized_balance(amt, dt)
        if bal is not None:
            return bal, "recorded_deed_of_trust", "high"
    # 2) amount_owed when it's an actual debt (judgment / indebtedness).
    #    A foreclosure judgment OR the auction opening bid both represent the
    #    debt being foreclosed (the lender opens at ~the payoff), so treat them
    #    as actual debt here even when amount_owed flagged the bid a proxy —
    #    otherwise NC leads (which carry an opening_bid, not a parsed judgment)
    #    never reach a payoff and the engine yields 0 equity for the whole state.
    ao = raw.get("amount_owed") or {}
    _FORECLOSURE_DEBT_SRC = {"judgment", "opening_bid"}
    if ao.get("value") and (ao.get("is_actual_debt") or ao.get("source") in _FORECLOSURE_DEBT_SRC):
        try:
            return float(ao["value"]), f"amount_owed:{ao.get('source', '?')}", ao.get("confidence", "medium")
        except (ValueError, TypeError):
            pass
    # 3) last sale -> ~90% financed, amortized. ARMS-LENGTH GATE: a $1/$10
    #    intra-family quitclaim or estate deed amortizes to ~0 and fakes ~100%
    #    equity (the exact failure mode this whole engine prevents). Require the
    #    sale price to clear a real-transaction floor before trusting it.
    gis = raw.get("gis") or {}
    ls = gis.get("last_sale") or {}
    sale_amt = ls.get("amount") or gis.get("last_sale_amount")
    sale_date = ls.get("date") or gis.get("last_sale_date")
    # Some NC counties (Buncombe/Lincoln/Transylvania) expose a sale AMOUNT but
    # no sale DATE on their parcel layer, so path 3 never fired and these leads
    # produced 0 equity. When the amount clears the arms-length floor, attach a
    # conservative ASSUMED note date so amortization can run. "Conservative"
    # means recent: a fresher note amortizes less -> higher payoff -> we never
    # overstate equity. Never fabricate when the amount itself is missing.
    src, conf = "last_sale_amortized", "low"
    if sale_amt and not sale_date:
        county = (li.county or "").strip().title()
        if (li.state or "").strip().upper() == "NC" and county in _NC_AMOUNT_ONLY:
            sale_date = _assumed_note_date()
            src, conf = "last_sale_amortized:assumed_date", "low"
    if sale_amt and sale_date:
        floor = max(10000.0, 0.30 * arv)
        if float(sale_amt) >= floor:
            bal = amortized_balance(float(sale_amt) * _LTV_PROXY, sale_date)
            if bal is not None:
                return bal, src, conf
    return None, "unknown", "none"


def enrich_equity(listings: list[Listing]) -> dict:
    """Attach raw['equity'] = {value, pct, arv_used, payoff, payoff_source, ...}."""
    n = 0
    for li in listings:
        arv = _arv(li)
        if not arv or arv <= 0:
            continue
        payoff, src, conf = _payoff(li, arv)
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

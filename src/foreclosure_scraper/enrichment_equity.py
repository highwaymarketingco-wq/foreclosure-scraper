"""Owner-equity engine — the #1 thing a fix-and-flipper needs: how much equity
the seller has, i.e. ARV − mortgage payoff − junior liens.

This is what tells you whether a deal even exists. A pre-foreclosure with deep
equity is a motivated seller you can buy below market; one that's underwater
needs a short sale or is a dead lead. The old flags.py 'equity' treated the
PURCHASE PRICE as the balance owed (ignores years of paydown) — wrong. Here we
estimate the CURRENT payoff:

  1. recorded Deed of Trust amount + date  -> amortized current balance  (best)
  2. amount_owed when it's an ACTUAL debt   (foreclosure judgment / indebtedness)
  2b. raw judgment_amount / opening_bid     -> foreclosure-debt proxy (LOW conf;
                                               fires when amount_owed is missing)
  3. last arms-length sale price            -> assume ~90% financed, amortized
  4. none                                   -> equity unknown (we say so)

equity = ARV − payoff − senior_liens ; equity_pct = equity / ARV.
Runs AFTER calc (needs arv_expected) and amount_owed, BEFORE distress scoring
(which now gates HOT on real equity). Pure-Python, no I/O, no cost.

Because the first term IS the ARV, this module is also the third call site of
the ARV trust gate: a valuation the board refuses to bid off is a valuation it
refuses to publish equity off. See the block above `_EQUITY_TRUST_BLOCKED`.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog

from datetime import date

from .models import Listing
from .valuation.amortize import _as_date, estimate_current_balance
from .valuation.grading import ARV_TRUST_BLOCKS_DERIVED, arv_trust

log = structlog.get_logger()

_LTV_PROXY = 0.90   # if we only know the sale price, assume ~90% was financed

# ===========================================================================
# THE ARV TRUST GATE, AT THE WRITER
#
# THE DEFECT. `equity = ARV - payoff - senior_liens` (`enrich_equity` below), so
# equity is an ARV-derived money figure in exactly the sense
# grading.ARV_DERIVED_MONEY_FIELDS means. It was the only one that was never
# gated. Measured by replaying the shipping code over the live board (38,500
# leads, 9,146 equity rows): 1,252 published an equity figure on a CONTRADICTED
# ARV and 113 more on a WITHHELD one — leads whose max bid, ROI, profit, deal
# verdict AND letter grade were all withheld by the gate, still rendering
# "Equity $1,920,000 (97%)" in green on the same card, because
# docs/dashboard.js:2454 tests `eq.value != null` and nothing else.
#
# WHY IT COULD NOT BE FIXED IN grading.py. valuation runs at main.py:2287 and
# writes raw['calc']; enrich_equity runs at main.py:2329 and writes
# raw['equity'] itself. At grade() time raw['equity'] does not exist yet, so
# there is nothing there to blank — the gate has to live at the writer. The same
# is true of distress_score._equity_band (main.py:2369), which reads the equity
# it must not rank on. Same rule, same function (grading.arv_trust), three call
# sites; see the "GATED ELSEWHERE" block in grading.py.
#
# THE RULE. Identical to the one the money fields already follow, deliberately,
# so there is one definition and not two:
#
#   CONTRADICTED or WITHHELD -> no equity figure. WEAK -> publish.
#
# Why WEAK still publishes. The weak tier is ~16,300 leads, most of them ARVs
# that simply ARE the county's own appraisal times a constant
# (anchor_not_independent). max_bid_70 and roi_pct are published there for that
# reason and equity is no different: unverified is not the same as contradicted,
# and blanking the equity on two thirds of the board would delete the signal the
# HOT/WARM tier is built on. (Weak equity inherits the same caption gap the weak
# max bid has — the card marks the ARV "unverified" but not each figure derived
# from it. That is the dashboard's E6, not this file's.)
#
# Why WITHHELD is blocked even though calc published no ARV at all. `_arv()`
# falls back to `market_value`, then `tax_value x 1.25`, so a withheld lead
# still produced an equity number — off a value reference that appears NOWHERE
# on the card, because calc refused to print an ARV. That is the worst shape a
# number can have here: a large green figure whose denominator the reader cannot
# see, on a card whose headline claim is "this property could not be valued".
# 113 leads; blocking them is not a normal-case cost.
#
# WHAT IS PUBLISHED INSTEAD. Not nothing — a marker. `raw['equity']` keeps its
# block with NO `value` and NO `pct`, plus `withheld` / `withheld_reason` /
# `arv_trust` / `arv_flags`. Every existing reader is already written
# `if eq.value != null` (dashboard card :2454, detail panel :3112) or
# `eq.get("pct")` (grading._risk_score, distress_score._equity_band,
# enrichment_strategy_fit._equity_pct), so all of them fall through to their
# no-equity branch with no change. The reason survives into the detail shard
# (web_artifact keeps raw['equity'] whole there); the slim board projects only
# ("value", "pct", "is_underwater") and so ships `"equity": {}` — renders
# nothing, which is the correct board behaviour.
#
# FLAG STRINGS INTRODUCED BY THIS BLOCK (interface — a reader/writer mismatch
# has caused three silent failures in this project already):
#   raw['equity']['withheld']         bool, always True when present
#   raw['equity']['withheld_reason']  prose, safe to render verbatim
#   raw['equity']['arv_trust']        "contradicted" | "withheld"
#   raw['equity']['arv_flags']        sorted list of the calc flags responsible
#
# ---------------------------------------------------------------------------
# THE HALF THE GATE ABOVE STILL MISSED: A VALUATION THAT PUBLISHED NOTHING AND
# SAID NOTHING.
#
# `arv_trust` reads three fields, and its no-ARV branch is
# `_TRUST_WITHHELD if (arv_withheld is not None or flags) else _TRUST_OK`. A
# calc block that has `arv_expected` absent AND `arv_withheld` absent AND an
# empty `arv_flags` therefore classifies **ok** — the gate waves it through —
# and `_arv()` below then quietly substitutes `market_value`, or
# `tax_value x 1.25`, as equity's own first term. That is this module inventing
# an ARV the valuation declined to publish.
#
# Measured on the live board (38,500 leads, 7,677 equity figures): 26 leads
# publish equity with NO `calc.arv_expected` at all, totalling $40,199,500 —
# 19 off `market_value`, 7 off `tax_value x 1.25`. Every one of the 26 HAS a
# real calc block (rehab_low/expected/high, rehab_tier, confidence,
# arv_confidence, notes); calc ran, priced the rehab, and produced no ARV
# without naming a reason. 200 Miracle Mile Dr, Anderson renders
# "Equity $7,934,600" against an `arv_used` of $12,480,200 that appears nowhere
# on the card, because there is no ARV on the card. None of them trips
# `derived_without_arv` either — that tripwire watches `raw['calc']`, and calc
# is innocent here: it published no money, this module did.
#
# THE RULE, and why it is not simply "no calc -> no equity". The distinction
# that matters is whether a VALUATION RAN. A lead with no `raw['calc']` at all
# is a source that never reached the valuation (a bare court record, say);
# nothing has been decided about its value, the county's own figure is the best
# available reference, and blanking those would delete equity on leads where
# nothing is wrong. A lead WITH a calc block that carries no `arv_expected` is
# the opposite: the valuation ran and came back empty. Substituting a number it
# did not choose is not a fallback, it is an override.
#
#   calc block present AND no arv_expected  -> withhold (level "withheld").
#   no calc block at all                    -> unchanged, fallback still allowed.
#
# It reuses the existing "withheld" level and its existing prose rather than
# minting a third value for `raw['equity']['arv_trust']` — the interface stays
# {"contradicted", "withheld"} for every reader, and the prose written for that
# level ("the valuation engine refused to publish an ARV for this property at
# all ... the county or market value this engine would otherwise fall back on
# is not shown anywhere on this card") already describes this case exactly.
# The run summary counts it separately as `withheld_no_arv` so the two paths
# stay distinguishable in the logs.
# ===========================================================================
# Imported, not re-spelled — grading.ARV_TRUST_BLOCKS_DERIVED is the one
# definition of "which trust levels forbid an ARV-derived figure", shared with
# the in-Calc gate and with distress_score.
_EQUITY_TRUST_BLOCKED = ARV_TRUST_BLOCKS_DERIVED

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


def valuation_ran_without_arv(li: Listing) -> bool:
    """True when a calc block exists and carries no ``arv_expected``.

    The one test that separates "nothing has been valued yet" from "the
    valuation ran and came back empty" — see the block above `_arv`. Public
    because `distress_score._equity_band` has to reach the same verdict from
    the same evidence: a board carried over from a run that predates this
    change still holds the invented figure, and the ranking must not use it.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc")
    return isinstance(calc, dict) and bool(calc) and not calc.get("arv_expected")


def _arv(li: Listing) -> Optional[float]:
    """The value reference equity subtracts the payoff from.

    The fallbacks below fire ONLY when no valuation ran at all — `enrich_equity`
    withholds outright when a calc block exists without an `arv_expected`, so
    this function is never asked to second-guess a valuation that already
    declined. Keeping the fallbacks here (rather than deleting them) preserves
    equity on the leads that never reached calc, which is the normal case this
    engine was built for.
    """
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


def equity_arv_trust(li: Listing) -> tuple[str, list[str]]:
    """(trust level, responsible flags) for this lead's published valuation.

    Reads the SERIALIZED raw['calc'] rather than re-running compute(), because
    that is what exists by the time this enricher runs and it is the same block
    the dashboard reads — so the gate here and the warning on the card can never
    be computed off different data. `grading.arv_trust` is a pure function over
    those three fields precisely so this call site exists.

    A lead with no raw['calc'] at all (a source that never reached valuation)
    classifies "ok" and is left exactly as it was: this gate withholds equity
    that a BAD valuation produced, it does not require a valuation.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    calc = raw.get("calc") or {}
    if not isinstance(calc, dict):
        return "ok", []
    flags = sorted(calc.get("arv_flags") or [])
    return arv_trust(flags, calc.get("arv_expected"),
                     calc.get("arv_withheld")), flags


def _withheld_block(level: str, flags: list[str]) -> dict:
    """The marker that replaces a figure we will not stand behind.

    Deliberately carries no `value` and no `pct` — every reader in the repo
    branches on one of those two — and states WHY in prose that is safe to
    render verbatim next to the empty cell.
    """
    named = ", ".join(flags) or "an unnamed sanity flag"
    if level == "withheld":
        why = (
            "No owner-equity figure published: the valuation engine refused to "
            "publish an ARV for this property at all, so equity (ARV minus "
            "payoff minus senior liens) has no first term. The county or market "
            "value this engine would otherwise fall back on is not shown "
            "anywhere on this card, so an equity percentage computed from it "
            "could not be checked against anything you can see."
        )
    else:
        why = (
            f"No owner-equity figure published: this ARV is flagged {named}, "
            f"which means another record (or the arithmetic itself) contradicts "
            f"it. Equity is the ARV minus the estimated payoff, so it is the "
            f"same disputed number with a subtraction on it — and it is the "
            f"largest figure on the card. The max bid, ROI, profit and deal "
            f"verdict are withheld here for exactly this reason; equity is not "
            f"an exception to that. Verify the parcel, then subtract the payoff "
            f"yourself."
        )
    return {
        "withheld": True,
        "withheld_reason": why,
        "arv_trust": level,
        "arv_flags": flags,
    }


def withhold_equity(li: Listing, level: str = "contradicted",
                    flags: list[str] | None = None) -> bool:
    """Replace this lead's equity figure with the withheld marker. Idempotent.

    Public because the ARV can be contradicted by evidence that does not exist
    until AFTER this enricher has run. `enrichment_board_qa` detects a county
    appraisal stamped across hundreds of parcels — a CROSS-ROW fact, knowable
    only once every lead is in memory, which is exactly why board QA runs last —
    and has to retract what the pre-detection valuation already published.
    Retraction is safe to do late: it only ever deletes, and the sole pass
    after board QA is the writer.

    Writes the marker ONLY where a figure actually existed. On a lead that had
    no equity anyway, "withheld because the ARV is contradicted" is not an
    explanation, it is a guess at someone else's reason — the equity is far more
    likely absent because no payoff could be estimated. 389 leads on the live
    board are in that position inside the stamped clusters. Same judgement as
    `_would_have_published` above: retract loudly, stay silent otherwise.

    Returns True when a figure was actually removed, so the caller can count
    the retractions rather than guess at them.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    if not isinstance(li.raw, dict):
        li.raw = raw = {}
    prior = raw.get("equity")
    if not isinstance(prior, dict) or prior.get("value") is None:
        return False          # nothing published (or already withheld) — say nothing
    raw["equity"] = _withheld_block(level, sorted(flags or []))
    raw.pop("_equity_amortization", None)
    return True


def _is_deed_of_trust(doc_type: object) -> bool:
    """True if a rod_doc's doc_type denotes a Deed-of-Trust / mortgage note.

    Normalizes separators so every emitted form matches: feeds (and the
    ROD enricher contract) variously label these 'deed_of_trust', 'DEED OF
    TRUST', 'Deed of Trust', 'DT', 'MTG', 'MORTGAGE'. The old check only
    matched the space-separated phrase or the exact short codes, so the
    underscore form 'deed_of_trust' (the form the equity engine's own
    payoff contract emits) silently fell through and produced 0 equity.

    'D/T' is the SLASHED short code both Logan and CCHS emit natively, and it
    normalizes to 'D T' — which was not in the accepted set, so a recorded
    principal harvested straight off an NC county index was silently ignored
    and the lead fell through to the far weaker opening-bid proxy. Caught on a
    live Burke run 2026-08-04 (10 recorded principals, 0 of them used).
    'TR/D' -> 'TR D' stays out on purpose: that is the TRUSTEE'S deed."""
    s = re.sub(r"[\s_\-/]+", " ", str(doc_type or "").upper()).strip()
    if "DEED OF TRUST" in s:
        return True
    return s in ("DT", "D T", "MTG", "M T G", "MORT", "MORTGAGE")


def _recorded_dt(raw: dict) -> tuple[Optional[float], object]:
    """Best (most-recent) recorded Deed-of-Trust original amount + date."""
    docs = raw.get("rod_docs") or []
    best_amt, best_date, best_key = None, None, None
    for d in docs if isinstance(docs, list) else []:
        if _is_deed_of_trust(d.get("doc_type")):
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
    arms-length-gate the last-sale proxy.

    NOTE: every value this returns is an ESTIMATE. Path 1 amortizes a recorded
    original principal, paths 2/2b read a court/auction debt figure, path 3
    models a note off the last sale price. A true payoff is borrower-only under
    TILA/RESPA. `enrich_equity` therefore stamps `payoff_is_estimate` and an
    `amortization` detail block so nothing downstream can mistake it for one.
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    # 1) recorded Deed of Trust -> amortized ESTIMATED current balance
    amt, dt = _recorded_dt(raw)
    if amt and dt:
        est = estimate_current_balance(amt, dt, basis="recorded_principal")
        if est is not None:
            # Stash the labelled detail for enrich_equity to publish verbatim.
            raw["_equity_amortization"] = est
            return est["estimated_balance"], "recorded_deed_of_trust", "high"
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
    # 2b) FALLBACK when amount_owed never populated. The amount_owed waterfall
    #     only runs for foreclosure/lis-pendens types AND only fires opening_bid
    #     for foreclosures, so most leads reach here with raw.amount_owed missing
    #     even though the Listing itself carries a judgment_amount or opening_bid.
    #     A foreclosure judgment / auction opening bid IS the debt being
    #     foreclosed (lenders open at ~the payoff), so it's a reasonable payoff
    #     proxy — taken at LOW confidence since we never amortize or verify it.
    #     This is what lifts equity coverage from ~500 to ~1k+ leads. We reuse
    #     the SAME upper-bound sanity as the last-sale path: a concatenated
    #     book+page or parcel id leaking into the bid field yields a
    #     billion-dollar "payoff", so reject anything implying >3x ARV (a real
    #     foreclosure debt is well under ARV — that's the whole point of equity).
    try:
        proxy = li.judgment_amount or li.opening_bid
    except AttributeError:
        proxy = None
    if proxy:
        try:
            proxy = float(proxy)
        except (ValueError, TypeError):
            proxy = None
        if proxy and 0 < proxy <= 3.0 * arv:
            psrc = "judgment_amount" if li.judgment_amount else "opening_bid"
            return proxy, f"foreclosure_proxy:{psrc}", "low"
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
        try:
            sale_amt = float(sale_amt)
        except (ValueError, TypeError):
            sale_amt = None
        if sale_amt:
            floor = max(10000.0, 0.30 * arv)
            # UPPER-BOUND sanity gate. Some county GIS layers leak a concatenated
            # book+page, a cents-denominated amount, or a parcel id into the
            # sale-amount field — yielding billion-dollar "sales" that amortize to
            # billion-dollar payoffs (was 228/544 equity rows, e.g. a $234,900-ARV
            # house with a $934M payoff; 194 were >100x ARV). The 0.30*arv floor
            # only screened the LOW end. A real arms-length sale is within a few x
            # ARV, and because this last-sale proxy is LOW confidence we also
            # discard any result that still implies an absurd >2x-ARV payoff
            # rather than trust it. (arv is always > 0 here — _payoff's callers gate
            # on it — so a pure ARV-relative ceiling is safe, no absolute floor.)
            if floor <= sale_amt <= 3.0 * arv:
                est = estimate_current_balance(sale_amt * _LTV_PROXY, sale_date,
                                               basis="last_sale_ltv_proxy")
                bal = est["estimated_balance"] if est else None
                if bal is not None and bal <= 2.0 * arv:
                    raw["_equity_amortization"] = est
                    return bal, src, conf
    return None, "unknown", "none"


def _would_have_published(li: Listing) -> bool:
    """True when the market_value / tax_value fallback WOULD have yielded equity.

    Decides whether the retraction above is worth explaining. Two ways to know:
    a figure is already sitting on the lead (a board written before this
    change), or the fallback reference plus a payoff would produce one now.
    `_payoff` is pure Python and no more expensive here than it is on the main
    path; its `_equity_amortization` side-effect is cleared by the caller.
    """
    prior = li.raw.get("equity") if isinstance(li.raw, dict) else None
    if isinstance(prior, dict) and prior.get("value") is not None:
        return True
    arv = _arv(li)
    if not arv or arv <= 0:
        return False
    payoff, _src, _conf = _payoff(li, arv)
    return payoff is not None


def enrich_equity(listings: list[Listing]) -> dict:
    """Attach raw['equity'] = {value, pct, arv_used, payoff, payoff_source, ...}."""
    n = 0
    amortized = 0
    withheld = 0
    withheld_no_arv = 0
    for li in listings:
        raw0 = li.raw if isinstance(li.raw, dict) else {}
        raw0.pop("_equity_amortization", None)  # never carry a stale detail block
        # ARV TRUST GATE (see the block at the top of this module). Runs FIRST,
        # before `_arv` — on a withheld valuation `_arv` silently substitutes
        # market_value / tax_value x 1.25, so testing the trust level after the
        # fallback would ask "is the number we did not use trustworthy". It also
        # runs before `_payoff`, which is the expensive half of this enricher.
        _level, _flags = equity_arv_trust(li)
        if _level in _EQUITY_TRUST_BLOCKED:
            if not isinstance(li.raw, dict):
                li.raw = {}
                raw0 = li.raw
            raw0["equity"] = _withheld_block(_level, _flags)
            withheld += 1
            continue
        # THE SILENT NO-ARV CASE. `arv_trust` cannot see it: with no
        # arv_expected, no arv_withheld and no flags it returns "ok", and
        # `_arv` below would substitute market_value / tax_value x 1.25 —
        # equity inventing the first term the valuation declined to publish.
        # See the second block at the top of this module. Reported separately
        # from `withheld` so the two paths never blur in the run log.
        if valuation_ran_without_arv(li):
            if not isinstance(li.raw, dict):
                li.raw = {}
                raw0 = li.raw
            # A withheld marker is an EXPLANATION for a number that is missing
            # from where the reader expected one. On a lead that was never going
            # to carry an equity figure it explains nothing and just adds a
            # paragraph of alarming prose to the detail panel: 13,526 leads on
            # the live board have no ARV, and only 26 of them published equity.
            # So retract loudly where there is something to retract, and quietly
            # everywhere else.
            if _would_have_published(li):
                raw0["equity"] = _withheld_block("withheld", _flags)
                withheld_no_arv += 1
            else:
                raw0.pop("equity", None)
            raw0.pop("_equity_amortization", None)
            continue
        arv = _arv(li)
        if not arv or arv <= 0:
            raw0.pop("equity", None)  # never leave a stale equity we can't recompute
            continue
        payoff, src, conf = _payoff(li, arv)
        if payoff is None:
            # e.g. a corrupt last-sale amount the upper-bound gate now rejects —
            # clear any prior (possibly billion-dollar) value rather than keep it.
            raw0.pop("equity", None)
            raw0.pop("_equity_amortization", None)
            continue
        seniors = _senior_liens(li.raw if isinstance(li.raw, dict) else {})
        equity = round(arv - payoff - seniors, -2)
        raw = li.raw if isinstance(li.raw, dict) else {}
        amort = raw.pop("_equity_amortization", None)
        raw["equity"] = {
            "value": equity,
            "pct": round(equity / arv, 3),
            "arv_used": round(arv, -2),
            "payoff_estimate": round(payoff, -2),
            "payoff_source": src,
            "senior_liens": round(seniors, -2),
            "confidence": conf,
            "is_underwater": equity < 0,
            # --- explicit estimate labelling (never present this as a payoff) --
            "payoff_is_estimate": True,
            "payoff_label": "estimated balance",
            "payoff_method": (amort or {}).get("method") or f"reported_debt:{src}",
            "payoff_disclaimer": (
                "ESTIMATE ONLY — a true payoff is borrower-only under TILA/RESPA "
                "and includes escrow, arrears and fees we cannot see"),
            "amortization": amort,
        }
        if amort:
            amortized += 1
        li.raw = raw
        n += 1
    log.info("equity.done", computed=n, amortized=amortized,
             withheld_bad_arv=withheld, withheld_no_arv=withheld_no_arv,
             total=len(listings))
    return {"computed": n, "amortized": amortized, "withheld_bad_arv": withheld,
            "withheld_no_arv": withheld_no_arv}

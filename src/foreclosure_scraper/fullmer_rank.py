"""Fullmer deal-economics rank — ORDERS the board, never trims it.

Companion to `distress_score`, which asks "how many distinct distress signals
does this property carry?". This module asks the different question Fullmer's
book and podcast actually answer: **given the mess, do the economics of the deal
work?**

WHY THIS IS A RANK AND NOT A FILTER
-----------------------------------
The book states hard numbers -- CAD value >= $200k, won't touch below $40-50k,
margin floor $50k -- and it is tempting to wire them in as gates. That would be
wrong here for two reasons.

1. Those numbers are Bexar County arithmetic, not principles. Bexar's property
   tax rate is ~2.7%; NC and SC counties run ~0.6-0.9%. His worked example
   ("$20,000 in back taxes on a $300k house") takes roughly three times as long
   to accrue in this footprint, so the same margin appears at a much lower
   property value. A flat $200k floor would delete most of Rutherford, Polk,
   McDowell, Cherokee, Union and Abbeville outright.

2. He does not delete leads, he ORDERS them. "There are hundreds of other people
   in my CRM right now." "It takes thirty leads to get a deal." His filter is
   call order. Ajay, who runs his acquisitions: "the leads aren't usually bad."

So every threshold below contributes POINTS. Nothing is dropped, nothing is
hidden, and the operator moves their own bar in the dashboard without a re-run.

WHAT IS ACTUALLY TRANSFERABLE
-----------------------------
The invariant is not a dollar value, it is this (ep 021): *"You will do the same
work for 20 grand as you will for 200. It's literally the same signatures, the
same work, the same sales."* Curative cost is roughly FIXED per deal -- he
budgets $10-30k legal, PIs at $80-350/hr with a 4-hour minimum, ~10% to sell. His
$50k margin floor against a $10-30k legal budget is a 2-5x coverage ratio. THAT
is the rule that travels: margin must cover the fixed curative spend several
times over. A Spartanburg deal needing $6k of curative earns its place at a much
smaller margin than a 40-owner Texas parcel needing $30k.

SCOPE NOTE
----------
This applies to the DISTRESSED lane (buy cheap, clear title, resell as-is).
It deliberately does not judge the foreclosure / fix-and-flip lane, which has
different economics -- Fullmer does no rehab at all ("we don't paint, we don't
replace the carpet, we don't even patch holes in the drywall").
"""
from __future__ import annotations

from typing import Optional

from .models import Listing

# ---------------------------------------------------------------- thresholds
# Every constant below is a quote, kept as a named POINT weight rather than a
# gate. Changing a weight re-orders the board; it can never empty it.

# "choose properties that are worth 200 grand or above -- but on the CAD value"
CAD_STRONG = 200_000.0
# "fair market value of 30, 40,000 ... even if you give it to me for free, it's
# not worth it" -- the work does not shrink with the property.
CAD_WEAK = 50_000.0

# "I want them to be two to three years behind" -- one year is explicitly early:
# "at first you lie to yourself. You say you'll catch up next month."
DELINQ_RIPE_YEARS = 2

# Fixed per-deal curative spend, LOCAL estimate -- not his Texas number. Kept
# conservative; the ratio matters more than the absolute.
CURATIVE_COST_BASE = 8_000.0
# "margins need to be no lower than 50 grand" against a $10-30k legal budget is
# 2-5x coverage. We score the RATIO so a cheap-to-cure deal is not punished for
# being small.
MARGIN_COVERAGE_GOOD = 4.0
MARGIN_COVERAGE_MIN = 2.0

# "I don't like to deal in itsy bitsy tiny crummy markets in the middle of
# nowhere ... you got no liquidity" (ep 019). Scored, because a thin market is a
# slower exit, not an impossible one -- he still says "just lower the price".
LIQUIDITY_POINTS = {"major": 12, "mid": 8, "thin": 3, "unknown": 4}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _raw(li: Listing) -> dict:
    return li.raw if isinstance(li.raw, dict) else {}


def cad_value(li: Listing) -> tuple[Optional[float], Optional[str]]:
    """County 100%-basis appraisal -- Fullmer's primary underwriting number.

    "I go to the CAD to see what the county thinks it's worth ... more often than
    not it gives me a baseline." Excludes `assessed_value` on purpose: SC assesses
    at a 4%/6% statutory ratio, so using it is a unit error, not a valuation.
    """
    raw = _raw(li)
    cama = raw.get("cama") if isinstance(raw.get("cama"), dict) else {}
    for val, label in (
        (li.market_value, "market_value"),
        (cama.get("appraised_value"), "cama.appraised_value"),
        (cama.get("total_value"), "cama.total_value"),
        (li.tax_value, "tax_value"),
    ):
        n = _num(val)
        if n is not None:
            return n, label
    return None, None


def tax_arrears(li: Listing) -> tuple[Optional[float], bool]:
    """(dollars, is_county_stated).

    `raw.amount_owed` conflates three different kinds of money -- measured on the
    live board its `source` is `judgment` (6,172 rows), `tax_owed` (2,202) or
    `opening_bid` (2,027). Only `tax_owed` is the delinquent-tax arrears figure
    ep 022 cherry-picks on ("leads that have a pretty high delinquent tax base to
    them ... this one only had 8K"). A judgment or an opening bid is a real debt
    but a different lever, so it must not be ranked as arrears.
    """
    ao = _raw(li).get("amount_owed")
    if not isinstance(ao, dict):
        return None, False
    val = _num(ao.get("value"))
    if val is None:
        return None, False
    src = str(ao.get("source") or "")
    stated = bool(ao.get("is_actual_debt")) and src == "tax_owed"
    return val, stated


def years_delinquent(li: Listing) -> tuple[Optional[float], bool]:
    """(years, is_two_year_plus). Paths verified against the live board.

    `tax_aging_surfaced.years_delinquent` is present on 33,147 rows but carries
    source `default` on 30,750 of them -- a placeholder, not a measurement. Only
    `nc_ptscloud` / `tax_owed` sourced values are real, which is why the ripeness
    signal is answerable for ~2,400 leads and not 33,000.
    """
    raw = _raw(li)
    surf = raw.get("tax_aging_surfaced") if isinstance(raw.get("tax_aging_surfaced"), dict) else {}
    tad = raw.get("two_year_delinquent") if isinstance(raw.get("two_year_delinquent"), dict) else {}
    yrs = _num(surf.get("years_delinquent"))
    if str(surf.get("source") or "") == "default":
        yrs = None          # placeholder, not a measurement
    two_plus = bool(tad.get("is_two_year_plus")) or bool(yrs and yrs >= DELINQ_RIPE_YEARS)
    return yrs, two_plus


def _owner_count(li: Listing) -> int:
    """How many people we must get to yes.

    Ep 019 makes this the FIRST underwriting question and gives the reason: each
    owner is roughly a coin flip, so three owners is ~12.5% not ~50%. It cuts both
    ways -- more owners means more risk AND a cheaper entry per share, because a
    disengaged co-heir sells an interest for $500-$2,000.
    """
    parts = []
    for f in (li.owner_name, li.defendant):
        s = (f or "").strip()
        if s:
            parts.append(s)
    blob = " ; ".join(parts)
    if not blob:
        return 0
    low = blob.lower()
    if "et al" in low or "heirs" in low or "unknown heirs" in low:
        return 4          # "a whole soccer team of folks shared title with you"
    n = 1
    for sep in (" and ", " & ", ";"):
        n += low.count(sep)
    return n


def liquidity_tier(li: Listing, msa_tier: dict) -> str:
    key = ((li.county or "").replace(" County", "").strip().lower(), (li.state or "").strip().upper())
    return msa_tier.get(key, "unknown")


def score(li: Listing, msa_tier: dict | None = None) -> dict:
    """Return the rank breakdown for one lead. Pure; mutates nothing."""
    msa_tier = msa_tier or {}
    pts = 0
    flags: list[str] = []
    why: dict[str, int] = {}

    def add(name: str, n: int, flag: str | None = None):
        nonlocal pts
        if n:
            pts += n
            why[name] = why.get(name, 0) + n
        if flag:
            flags.append(flag)

    # --- value tier -------------------------------------------------------
    cad, cad_src = cad_value(li)
    if cad is None:
        add("cad_unknown", 0, "no_county_value")   # honest zero, not a penalty
    elif cad >= CAD_STRONG:
        add("cad_strong", 25, "cad_200k_plus")
    elif cad >= CAD_WEAK:
        # Linear between the two quoted numbers rather than a cliff.
        add("cad_mid", int(25 * (cad - CAD_WEAK) / (CAD_STRONG - CAD_WEAK)))
    else:
        add("cad_thin", 2, "cad_under_50k")

    # --- ripeness ---------------------------------------------------------
    yrs, two_plus = years_delinquent(li)
    if two_plus:
        add("delinq_ripe", 22, "delinquent_2yr_plus")
    elif yrs is not None and yrs >= 1:
        add("delinq_early", 6, "delinquent_1yr_early")

    # --- arrears size (ep 022's cherry-pick column) -----------------------
    arrears, stated = tax_arrears(li)
    if stated and arrears:
        add("arrears_stated", 8 if arrears >= 5_000 else 4, "tax_arrears_known")
    elif arrears:
        flags.append("arrears_estimated_only")

    # --- named in a tax lawsuit: the single sharpest trigger --------------
    # "we just went ahead and focused on owners that were in a tax lawsuit at some
    # level" -- being SERVED is what makes a seller problem-aware. "they get so
    # scared when they get the tax lawsuit, when they get served with the notice."
    lt = (li.listing_type or "")
    lt = getattr(lt, "value", lt)
    src = (li.source or "").lower()
    if "tax_foreclos" in src or "tax_suit" in src or (li.case_number and "tax" in src):
        add("tax_lawsuit", 20, "named_in_tax_lawsuit")

    # --- the mess: "the margin lives in the mess" ------------------------
    oc = _owner_count(li)
    if oc >= 4:
        add("many_owners", 14, f"multi_owner_~{oc}")
    elif oc >= 2:
        add("some_owners", 8, f"multi_owner_{oc}")

    raw = _raw(li)
    blob_probate = any(
        t in (str(li.owner_name or "") + str(li.defendant or "")).lower()
        for t in ("estate of", "heirs", "deceased")
    ) or bool(raw.get("probate")) or "probate" in src
    if blob_probate:
        # "Heirship ... this is where 70% of our deals live."
        add("probate_heirs", 16, "probate_or_heirs")

    dc = raw.get("deed_chain") if isinstance(raw.get("deed_chain"), dict) else {}
    summ = dc.get("summary") if isinstance(dc.get("summary"), dict) else {}
    if _num(summ.get("chain_breaks")):
        add("chain_break", 12, "title_chain_break")
    if _num(li.judgment_amount):
        add("judgment", 6, "judgment_on_record")

    # --- contactability: a hot lead you can't reach isn't one -------------
    ds = raw.get("distress_stack") if isinstance(raw.get("distress_stack"), dict) else {}
    if ds.get("absentee") or raw.get("absentee"):
        # "Look for older owners, long-term ownership, high dollar amounts
        # delinquent, or folks who live out of state."
        add("absentee", 8, "absentee_owner")

    # --- exit liquidity ---------------------------------------------------
    tier = liquidity_tier(li, msa_tier)
    add(f"liquidity_{tier}", LIQUIDITY_POINTS.get(tier, 4))

    # --- does the margin cover the fixed curative spend? ------------------
    calc = raw.get("calc") if isinstance(raw.get("calc"), dict) else {}
    margin = _num(calc.get("est_gross_margin")) or _num(raw.get("est_gross_margin"))
    coverage = None
    if margin:
        # More owners and a broken chain both cost more to cure.
        cost = CURATIVE_COST_BASE
        if oc >= 4:
            cost += 6_000
        elif oc >= 2:
            cost += 2_000
        if _num(summ.get("chain_breaks")):
            cost += 4_000
        coverage = margin / cost
        if coverage >= MARGIN_COVERAGE_GOOD:
            add("margin_strong", 15, "margin_covers_curative_4x")
        elif coverage >= MARGIN_COVERAGE_MIN:
            add("margin_ok", 8, "margin_covers_curative_2x")
        else:
            flags.append("margin_thin_vs_curative")

    return {
        "rank": min(100, pts),
        "why": why,
        "flags": flags,
        "cad_value": cad,
        "cad_source": cad_src,
        "years_delinquent": yrs,
        "two_year_plus": two_plus,
        "tax_arrears": arrears if stated else None,
        "tax_arrears_estimated": None if stated else arrears,
        "owner_count": oc or None,
        "liquidity": tier,
        "margin_coverage": round(coverage, 2) if coverage else None,
    }


def rank_board(listings: list[Listing], msa_tier: dict | None = None) -> dict:
    """Stamp `raw['fullmer']` on every lead. Returns distribution stats.

    Removes nothing. The count of listings in must equal the count out -- that is
    asserted, because a "ranking" pass that silently trims is the exact failure
    this project keeps hitting.
    """
    before = len(listings)
    buckets = {"A (70+)": 0, "B (50-69)": 0, "C (30-49)": 0, "D (<30)": 0}
    for li in listings:
        r = score(li, msa_tier)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["fullmer"] = r
        v = r["rank"]
        if v >= 70:
            buckets["A (70+)"] += 1
        elif v >= 50:
            buckets["B (50-69)"] += 1
        elif v >= 30:
            buckets["C (30-49)"] += 1
        else:
            buckets["D (<30)"] += 1
    assert len(listings) == before, "fullmer_rank must never drop a lead"
    return {"ranked": before, "buckets": buckets}

"""Stacked-distress score — the HOT/WARM operator board.

Turns the signals we already collect into a ranked motivated-seller score, the
way the paid lead desks do. Core idea (roadmap §6): a property hit by MULTIPLE
*distinct distress categories* is a far hotter lead than one with a single
signal. We:

  1. Group listings by parcel (so the same property in foreclosure AND tax sale
     stacks; cross-listing).
  2. Collect distress signals across the group, bucketed into 5 CATEGORIES.
     STACKED-2+ counts distinct *categories* (two liens = one FINANCIAL, not
     two) so a single default event can't fake a stack.
  3. Score = weighted signals (recency-aware) + equity band + contactability.
  4. Tier: HOT = stacked 2+ AND equity>=med AND contactable; WARM = stacked 2+
     OR a single high-weight signal with equity OR absentee+distress; else COLD.

Contactability (a mailable owner) is a HARD GATE for HOT — a hot lead you can't
reach isn't actionable. Already-sold properties (sold_confirmed) are excluded.
Pure computation over the board; no scraping.
"""
from __future__ import annotations

from typing import Optional

from .models import Listing

# signal -> (category, weight). Categories: FINANCIAL / SALES / LEGAL /
# LIFE_EVENT / PROPERTY. Weight ~ motivation strength.
_LISTING_TYPE_SIGNAL = {
    "foreclosure_sale": ("FINANCIAL", 30),
    "lis_pendens": ("FINANCIAL", 28),
    "sheriff_sale": ("SALES", 25),
    "tax_sale": ("FINANCIAL", 30),
    "tax_lien": ("FINANCIAL", 20),
    "auction": ("SALES", 18),
    "reo": ("SALES", 15),
    "distressed": ("PROPERTY", 10),
    "probate_notice": ("LIFE_EVENT", 20),
}


def _signals_for(li: Listing) -> list[tuple[str, str, int]]:
    """Return (signal_name, category, weight) for one listing's distress signals."""
    r = li.raw if isinstance(li.raw, dict) else {}
    sig: list[tuple[str, str, int]] = []
    lt = (li.listing_type.value if li.listing_type else "") if hasattr(li.listing_type, "value") else str(li.listing_type or "")
    if lt in _LISTING_TYPE_SIGNAL:
        cat, w = _LISTING_TYPE_SIGNAL[lt]
        sig.append((lt, cat, w))
    # court / sale status
    if r.get("court_sale_status") in ("sale_noticed", "sold_unconfirmed"):
        sig.append(("court_sale", "FINANCIAL", 25))
    if r.get("upset_bid"):
        sig.append(("upset_bid", "FINANCIAL", 22))
    if (r.get("amount_owed") or {}).get("value"):
        sig.append(("recorded_debt", "FINANCIAL", 12))
    # legal
    if r.get("bankruptcy"):
        sig.append(("bankruptcy", "LEGAL", 18))
    if r.get("incarceration"):
        sig.append(("incarceration", "LEGAL", 8))  # low-conf name-only signal
    # life event
    if r.get("probate") or r.get("estate"):
        sig.append(("probate", "LIFE_EVENT", 20))
    # relationship-deed signals (probate / divorce / partition) tagged by
    # enrichment_relationship_deeds. Without this, in-place-tagged active
    # listings and ALL divorce signals never reached the score.
    rs = r.get("relationship_signal")
    if isinstance(rs, dict):
        kind = rs.get("kind")
        if kind == "probate":
            sig.append(("probate_deed", "LIFE_EVENT", 20))
        elif kind == "divorce":
            # zero-consideration quitclaim could be a gift, not a split — weaker
            kw = rs.get("keyword")
            w = 8 if kw == "zero_consideration_quitclaim" else 15
            sig.append(("divorce", "LIFE_EVENT", w))
        elif kind == "partition":
            # forced/judicial sale (usually already sold) — modest SALES signal
            sig.append(("partition", "SALES", 12))
    # property
    if r.get("code_enforcement") or r.get("condemned"):
        sig.append(("code_enforcement", "PROPERTY", 14))
    if r.get("distressed"):
        sig.append(("distressed_condition", "PROPERTY", 8))
    return sig


def _equity_band(li: Listing) -> Optional[str]:
    calc = (li.raw or {}).get("calc") or {}
    roi = calc.get("roi_pct")
    if roi is None:
        return None
    if roi >= 50:
        return "high"
    if roi >= 20:
        return "med"
    return "low"


def _parcel_key(li: Listing) -> str:
    import re
    if li.parcel_id and li.parcel_id.strip():
        return f"p:{li.state}:{re.sub(r'[^A-Za-z0-9]', '', li.parcel_id).lower()}"
    return f"id:{id(li)}"  # ungrouped


def score_board(listings: list[Listing]) -> dict:
    """Compute and attach raw['distress_stack'] to each listing. Returns a
    tier histogram."""
    # group by parcel
    groups: dict[str, list[Listing]] = {}
    for li in listings:
        groups.setdefault(_parcel_key(li), []).append(li)

    hist = {"HOT": 0, "WARM": 0, "COLD": 0}
    for key, group in groups.items():
        # exclude sold/closed properties from active scoring
        active = [li for li in group if not (li.raw or {}).get("sold_confirmed")]
        if not active:
            for li in group:
                if isinstance(li.raw, dict):
                    li.raw.pop("distress_stack", None)
            continue
        # union signals across the parcel group
        by_cat: dict[str, list[tuple[str, int]]] = {}
        for li in active:
            for name, cat, w in _signals_for(li):
                by_cat.setdefault(cat, []).append((name, w))
        categories = sorted(by_cat)
        stack = len(categories)  # distinct categories = the STACKED-N number
        # score: best weight per category (don't let 3 liens triple-count financial)
        score = sum(max(w for _, w in by_cat[c]) for c in by_cat)
        signals = sorted({name for c in by_cat for name, _ in by_cat[c]})

        # equity + contactability (best across the group)
        eq = next((b for li in active for b in [_equity_band(li)] if b in ("high", "med")), None) \
            or next((b for li in active for b in [_equity_band(li)] if b), None)
        absentee = any((li.raw or {}).get("owner_mailing", {}).get("absentee") for li in active)
        oos = any((li.raw or {}).get("owner_mailing", {}).get("out_of_state") for li in active)
        mailable = any((li.raw or {}).get("owner_mailing", {}).get("mailing") for li in active)
        if absentee:
            score += 8
        if oos:
            score += 4

        eq_ok = eq in ("high", "med")
        if stack >= 2 and eq_ok and mailable:
            tier = "HOT"
        elif stack >= 2 or (score >= 28 and eq_ok) or (absentee and stack >= 1 and score >= 20):
            tier = "WARM"
        else:
            tier = "COLD"

        ds = {"tier": tier, "stack": stack, "categories": categories,
              "signals": signals, "score": round(score),
              "equity_band": eq, "absentee": absentee, "out_of_state": oos,
              "contactable": mailable}
        for li in active:
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["distress_stack"] = ds
        hist[tier] += 1
    return hist

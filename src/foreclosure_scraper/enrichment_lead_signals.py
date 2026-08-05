"""Lead-signals enricher — Goliath-parity list-stacking + intent score.

Zero new scrape. Pure computation over signals the pipeline already collected,
so it is 100% compliant (no network, no I/O). Runs AFTER distress_score /
derived_signals so it can read their output.

Two board fields, both mirroring how the paid motivated-seller desks (Goliath /
BatchLeads / PropStream) rank a list:

  1. raw['signal_stack'] = {"count": N, "signals": [...]}
     LIST-STACKING. How many DISTINCT distress signals/sources hit this
     property. distress_score already unions weighted distress signals across
     the parcel group into raw['distress_stack']['signals']; we start from that
     and FOLD IN cross-cutting distress facets that live on other raw keys and
     are not always represented as a scored signal (tax delinquency, code
     enforcement / condemned, vacancy, incarceration, recorded liens, bankruptcy,
     storm damage, absentee / out-of-state ownership). The dashboard shows a
     "🔥 N signals" chip and a "min signals" filter to rank the most-distressed
     owners — a property hit by 4 lists is a far hotter lead than one hit by 1.

  2. raw['intent_score'] = 0-100 int  (+ raw['intent_band'])
     INTENT SCORE. A single normalized headline number (Goliath's headline
     feature) folding the three things that actually predict a deal: how many
     distinct distress categories stacked, the weighted distress score, and our
     own investment grade. Normalized to 0-100 so the dashboard can hang a
     single slider filter off it. Sold/closed leads score 0.

Both are per-property. signal_stack is deliberately a SUPERSET of the distress
stack's signal list (never fewer), so the chip can only ever read >= the tier
badge's signal count. Idempotent; safe to re-run.
"""
from __future__ import annotations

import os
from typing import Iterable

import structlog

from .models import Listing
from .enrichment_owner_mailing import mailing_dict

log = structlog.get_logger()

_ENABLED = os.environ.get("LEAD_SIGNALS") != "0"


def _truthy(v) -> bool:
    """A raw facet 'is present' if it's a non-empty value. Guards against the
    common empty-container / zero / blank-string false positives."""
    if v is None or v is False:
        return False
    if isinstance(v, (list, tuple, set, dict, str)):
        return len(v) > 0
    if isinstance(v, (int, float)):
        return v != 0
    return True


def _dollar(v) -> bool:
    """A dollar-amount facet (balance/amount) counts only when > 0."""
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


# Cross-cutting distress facets that live on their own raw keys. Each maps a
# stable signal NAME (what the chip/filter shows) to a predicate over the
# listing's raw dict. These are folded on TOP of distress_stack['signals'] so a
# property hit by, say, tax-delinquency AND code-enforcement AND foreclosure
# reads as a 3-way stack even when the base score only weighted the foreclosure.
def _facet_signals(li: Listing) -> set[str]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    out: set[str] = set()

    # --- FINANCIAL ---
    if _dollar((raw.get("tax_owed") or {}).get("balance")) or _truthy(raw.get("sc_tax_delinquent")):
        out.add("tax_delinquent")
    liens = raw.get("liens")
    if isinstance(liens, list) and liens:
        out.add("lien")
    lp = raw.get("lien_priority")
    if isinstance(lp, list) and lp:
        out.add("lien")
    if _dollar((raw.get("amount_owed") or {}).get("value")):
        out.add("recorded_debt")
    if _truthy(raw.get("upset_bid")):
        out.add("upset_bid")

    # --- LEGAL ---
    if _truthy(raw.get("bankruptcy")):
        out.add("bankruptcy")
    if _truthy(raw.get("incarceration")):
        out.add("incarcerated_owner")

    # --- LIFE_EVENT ---
    if _truthy(raw.get("probate")) or _truthy(raw.get("estate")) or _truthy(raw.get("life_events")):
        out.add("probate_estate")
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict) and rs.get("kind"):
        out.add(str(rs["kind"]))  # probate / divorce / partition

    # --- PROPERTY ---
    if _truthy(raw.get("code_enforcement")):
        out.add("code_enforcement")
    if _truthy(raw.get("condemned")):
        out.add("condemned")
    if _truthy(raw.get("vacant")) or _truthy(raw.get("vacancy")):
        out.add("vacant")
    hel = raw.get("helene")
    if isinstance(hel, dict) and hel.get("worst_placard"):
        out.add("storm_damage")
    elif li.source == "counties_nc.asheville_helene":
        out.add("storm_damage")

    # --- OWNERSHIP context (a distinct list a desk would stack on) ---
    om = mailing_dict(raw)
    if _truthy(om.get("absentee")):
        out.add("absentee_owner")
    if _truthy(om.get("out_of_state")):
        out.add("out_of_state_owner")

    return out


def _signal_stack(li: Listing) -> dict:
    """Union of the distress-stack signals + cross-cutting facet signals."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    ds = raw.get("distress_stack") or {}
    base = ds.get("signals") if isinstance(ds.get("signals"), list) else []
    signals: set[str] = {str(s) for s in base if s}
    signals |= _facet_signals(li)
    ordered = sorted(signals)
    return {"count": len(ordered), "signals": ordered}


def _intent_score(li: Listing) -> int:
    """Fold distinct-category stack + weighted distress score + investment grade
    into a single 0-100 intent number.

    Components (max 100):
      - stack   (0-30): distinct distress CATEGORIES, 10 pts each capped at 3.
      - distress(0-45): distress_stack['score'] scaled (score ~90 = full).
      - grade   (0-25): grade.overall_score (0-100) scaled to 25.

    A lead with no distress signal and no grade scores 0. Sold/closed leads are
    zeroed by the caller (excluded from the active board).
    """
    raw = li.raw if isinstance(li.raw, dict) else {}
    ds = raw.get("distress_stack") or {}

    stack = ds.get("stack") or 0
    try:
        stack = int(stack)
    except (TypeError, ValueError):
        stack = 0
    stack_pts = min(stack, 3) * 10.0  # 0..30

    score = ds.get("score") or 0
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    # distress_score weights: a strong single event ~30, a rich HOT stack ~90+.
    # Clamp negative (title-trap penalty) up to 0 so intent never goes negative.
    distress_pts = max(0.0, min(score, 90.0)) / 90.0 * 45.0  # 0..45

    grade = raw.get("grade") or {}
    gscore = grade.get("overall_score")
    try:
        gscore = float(gscore) if gscore is not None else None
    except (TypeError, ValueError):
        gscore = None
    if gscore is None:
        grade_pts = 0.0
    else:
        grade_pts = max(0.0, min(gscore, 100.0)) / 100.0 * 25.0  # 0..25

    return int(round(stack_pts + distress_pts + grade_pts))


def _band(score: int) -> str:
    if score >= 70:
        return "hot"
    if score >= 45:
        return "warm"
    if score >= 20:
        return "cool"
    return "cold"


def enrich_lead_signals(listings: Iterable[Listing]) -> dict:
    """Attach raw['signal_stack'], raw['intent_score'], raw['intent_band'] to
    each active listing. Sold/closed leads get intent 0 + no stack. Returns
    stats. Mutates in place; idempotent. Gate LEAD_SIGNALS=0."""
    stats = {
        "scored": 0,
        "with_multi_stack": 0,   # >=2 distinct signals
        "hot": 0, "warm": 0, "cool": 0, "cold": 0,
        "max_stack": 0,
        "max_intent": 0,
    }
    if not _ENABLED:
        return stats

    for li in listings:
        try:
            if not isinstance(li.raw, dict):
                li.raw = {}
            raw = li.raw

            if raw.get("sold_confirmed"):
                # closed — not an active lead. Zero it out so a stale score
                # can't linger on a re-run over a previously-scored board.
                raw["signal_stack"] = {"count": 0, "signals": []}
                raw["intent_score"] = 0
                raw["intent_band"] = "cold"
                continue

            ss = _signal_stack(li)
            score = _intent_score(li)
            band = _band(score)

            raw["signal_stack"] = ss
            raw["intent_score"] = score
            raw["intent_band"] = band

            stats["scored"] += 1
            if ss["count"] >= 2:
                stats["with_multi_stack"] += 1
            stats[band] += 1
            stats["max_stack"] = max(stats["max_stack"], ss["count"])
            stats["max_intent"] = max(stats["max_intent"], score)
        except Exception as exc:  # noqa: BLE001
            log.warning("lead_signals.per_listing_failed",
                        source=getattr(li, "source", None), error=str(exc))

    log.info("lead_signals.done", **stats)
    return stats

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

AUDIT 2026-09-21, F13. The chip counted SYNONYMS: one Helene placard read 2 signals
(`helene_unsafe`, `storm_damage`), one tax delinquency read 3 (`tax_lien`, `tax_delinquent`,
`recorded_debt`), one probate notice read 4, so every tax-delinquent lead advertised a stack.
Now facet names are the scorer's own signal names (a real tax balance is `recorded_debt`, an
open code case is `code_enforcement`, and so on), `count` is the number of distinct CATEGORIES
the signals fall in, and the intent score is capped when the lead is stale or its foreclosure is
stayed. `TRUST` and a bare `ESTATE` in an owner name are no longer probate (an LLC named "... REAL
ESTATE HOLDINGS" is not an estate).
"""
from __future__ import annotations

import os
from datetime import date
from typing import Iterable, Optional

import structlog

from .models import Listing
from .mailing_shape import mailing_of
from .distress_score import SIGNAL_CATEGORY, _storm_signal, _upset_open, _vacant_structure
from .enrichment_equity import is_countable_debt
from .signal_freshness import (
    bankruptcy_lapsed, code_enforcement_open, custody_ended, owner_names_a_death,
)

log = structlog.get_logger()

#: Ownership context is listed as a signal (a desk filters on it) but is not a distress
#: category, exactly as the scorer treats it (a bonus, not a category).
_OWNERSHIP = "OWNERSHIP"
# (owner_names_a_death: enrichment_life_events also tags `TRUST` and a bare `ESTATE`, which makes
# "ACME REAL ESTATE HOLDINGS LLC" a probate lead and every living trust an estate. A death shows
# in the name as HEIRS or ESTATE OF / EST OF.)

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


# Cross-cutting distress facets that live on their own raw keys. Each maps to a stable signal
# NAME that is the scorer's own name for the same fact, so a fact reads once however many
# fields carry it. These are folded on TOP of distress_stack['signals'] so a property hit by,
# say, tax delinquency AND code enforcement AND foreclosure reads as a 3-way stack even when the
# base score only weighted the foreclosure.
def _facet_signals(li: Listing, today: Optional[date] = None) -> set[str]:
    raw = li.raw if isinstance(li.raw, dict) else {}
    out: set[str] = set()

    # --- FINANCIAL ---
    if _dollar((raw.get("tax_owed") or {}).get("balance")):
        out.add("recorded_debt")
    if _truthy(raw.get("sc_tax_delinquent")):
        out.add("tax_lien")
    liens = raw.get("liens")
    if isinstance(liens, list) and liens:
        out.add("lien")
    lp = raw.get("lien_priority")
    if isinstance(lp, list) and lp:
        out.add("lien")
    # the same predicate the scorer and the equity engine use: an assessed-value placeholder in
    # amount_owed is not a debt
    if is_countable_debt(raw.get("amount_owed")):
        out.add("recorded_debt")
    if _upset_open(raw.get("upset_bid"), today or date.today()):
        out.add("upset_bid")

    # --- LEGAL ---
    if _truthy(raw.get("bankruptcy")) and not bankruptcy_lapsed(raw.get("bankruptcy"), today):
        out.add("bankruptcy")
    st = raw.get("bankruptcy_stay")
    if isinstance(st, dict) and st.get("status") == "stayed":
        out.add("bankruptcy_stay")   # foreclosure paused by an automatic stay; will likely resume
    if _truthy(raw.get("incarceration")) and not custody_ended(raw.get("jail_booking"), today):
        out.add("incarceration")

    # --- LIFE_EVENT ---
    if _truthy(raw.get("probate")) or _truthy(raw.get("estate")):
        out.add("probate")
    tags = raw.get("life_events")
    if isinstance(tags, (list, tuple, set)):
        for t in tags:
            t = str(t)
            if t == "estate_probate":
                if owner_names_a_death(getattr(li, "owner_name", None)):
                    out.add("probate")
            elif t == "life_estate":
                out.add("life_estate")
            elif t in ("multiple_heirs", "trust"):
                continue          # ownership form, not a life event (F13)
            elif t:
                out.add("senior_exemption")   # a statutory age / disability exemption tag
    elif _truthy(tags):
        out.add("probate")        # legacy int-count shape: the reader cannot tell which tag it was
    rs = raw.get("relationship_signal")
    if isinstance(rs, dict) and rs.get("kind"):
        out.add({"probate": "probate_deed"}.get(str(rs["kind"]), str(rs["kind"])))  # divorce / partition as-is

    # --- PROPERTY ---
    ce = raw.get("code_enforcement")
    if ce:
        if code_enforcement_open(ce, today):
            out.add("code_enforcement")
    elif _truthy(raw.get("condemned")):
        out.add("code_enforcement")
    if _vacant_structure(raw):
        out.add("vacant_structure")
    if _truthy(raw.get("vacant_lot")):
        out.add("vacant_lot")
    if _truthy(raw.get("builder_distress")):
        out.add("builder_distress")   # LiensNC cluster: over-leveraged flipper / stalled build
    if _storm_signal(raw.get("storm_damage")):
        out.add("storm_damage")
    hel = raw.get("helene")
    if (isinstance(hel, dict) and hel.get("worst_placard")) or li.source == "counties_nc.asheville_helene":
        out.add("storm_damage")

    # --- OWNERSHIP context (a distinct list a desk would stack on) ---
    # mailing_of reads only raw['owner_mailing'] (a bare-string address becomes {"mailing": ...}).
    # The old call handed mailing_dict the whole raw dict, which returns that dict itself when
    # 'owner_mailing' is absent, so raw['absentee'] was read as the mailing block.
    om = mailing_of(raw)
    if _truthy(om.get("absentee")):
        out.add("absentee_owner")
    if _truthy(om.get("out_of_state")):
        out.add("out_of_state_owner")

    return out


def _category_of(name: str) -> Optional[str]:
    if name in SIGNAL_CATEGORY:
        return SIGNAL_CATEGORY[name]
    if name in ("absentee_owner", "out_of_state_owner"):
        return _OWNERSHIP
    return None


def _signal_stack(li: Listing, today: Optional[date] = None) -> dict:
    """Union of the distress-stack signals + cross-cutting facet signals.

    `count` is the number of distinct distress CATEGORIES among them (ownership context is
    listed but not counted), so it can never exceed what the tier's own stack could reach and a
    single delinquency cannot read as three. It is still never LOWER than the tier badge's
    category count, because the base categories are included."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    ds = raw.get("distress_stack") or {}
    base = ds.get("signals") if isinstance(ds.get("signals"), list) else []
    signals: set[str] = {str(s) for s in base if s}
    # a Helene placard lead already reads as its graded helene_* signal; storm_damage would be
    # the same fact under a second name (F13)
    facets = _facet_signals(li, today)
    if any(n.startswith("helene_") for n in signals):
        facets.discard("storm_damage")
    signals |= facets
    # Categories the tier itself did not count (a name-based match with no second record-linked
    # category beside it, or a bankruptcy whose foreclosure is stayed) do not count here either:
    # the chip must not advertise a stack the badge refused (F6, F3). Their names stay listed.
    excluded = {str(c) for c in (ds.get("uncounted_categories") or [])}
    if ds.get("stay"):
        excluded.add("LEGAL")
    cats: set[str] = {str(c) for c in (ds.get("categories") or []) if c and str(c) not in excluded}
    for n in signals:
        c = _category_of(n)
        if c and c != _OWNERSHIP and c not in excluded:
            cats.add(c)
    cats.discard(_OWNERSHIP)
    ordered = sorted(signals)
    return {"count": len(cats), "signals": ordered, "categories": sorted(cats)}


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

    total = int(round(stack_pts + distress_pts + grade_pts))
    # An ended sale is not an intent to buy, and a stayed foreclosure will not be sold on
    # schedule. `intent_score` is computed before board quality and QA run, so it reads the
    # facts the scorer itself stamped on the stack (F13).
    if ds.get("stale_reason") or ds.get("scope_capped"):
        return min(total, 19)                  # band: cold (an ended event, or a flip outside the footprint)
    if ds.get("stay") or ds.get("downranked_stale") or raw.get("stale_case"):
        return min(total, 69)                  # never "hot"
    return total


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
        "failed": 0,             # listings that could not be scored (F17); none is a healthy run
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
            # F17: the warning used to be all that happened, and the PREVIOUS run's intent_score
            # stayed on the row as if current. Clear it, count the failure, log at error level.
            stats["failed"] += 1
            log.error("lead_signals.per_listing_failed",
                      source=getattr(li, "source", None), error=str(exc))
            try:
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["signal_stack"] = {"count": 0, "signals": [], "categories": [], "error": True}
                li.raw["intent_score"] = 0
                li.raw["intent_band"] = "cold"
            except Exception:  # noqa: BLE001
                pass

    log.info("lead_signals.done", **stats)
    return stats

"""Lead-signals enricher — list-stacking (signal_stack) + intent score.

Pure computation over already-collected signals, so these tests seed raw the
way the upstream enrichers (distress_score, grade, tax_owed, etc.) leave it.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.enrichment_lead_signals import (
    _band,
    _facet_signals,
    _intent_score,
    _signal_stack,
    enrich_lead_signals,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, raw: dict | None = None, source: str = "test",
        listing_type: ListingType = ListingType.FORECLOSURE_SALE, **kw) -> Listing:
    base = dict(
        source=source,
        source_url="https://example.com/x",
        listing_type=listing_type,
        property_kind=PropertyKind.SINGLE_FAMILY,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw if raw is not None else {},
    )
    base.update(kw)
    return Listing(**base)


# ---- _facet_signals: cross-cutting distress folded in from other raw keys ----

def test_facet_tax_delinquent_from_balance():
    li = _li(raw={"tax_owed": {"balance": 4200}})
    assert "tax_delinquent" in _facet_signals(li)


def test_facet_tax_delinquent_ignores_zero_balance():
    li = _li(raw={"tax_owed": {"balance": 0}})
    assert "tax_delinquent" not in _facet_signals(li)


def test_facet_code_enforcement_condemned_vacant():
    li = _li(raw={"code_enforcement": True, "condemned": True, "vacant": True})
    f = _facet_signals(li)
    assert {"code_enforcement", "condemned", "vacant"} <= f


def test_facet_liens_and_recorded_debt():
    li = _li(raw={
        "liens": [{"type": "state_tax", "amount": 900}],
        "amount_owed": {"value": 150000},
    })
    f = _facet_signals(li)
    assert "lien" in f and "recorded_debt" in f


def test_facet_absentee_and_out_of_state():
    li = _li(raw={"owner_mailing": {"absentee": True, "out_of_state": True}})
    f = _facet_signals(li)
    assert {"absentee_owner", "out_of_state_owner"} <= f


def test_facet_storm_damage_from_helene_source():
    li = _li(source="counties_nc.asheville_helene", raw={})
    assert "storm_damage" in _facet_signals(li)


def test_facet_relationship_divorce():
    li = _li(raw={"relationship_signal": {"kind": "divorce"}})
    assert "divorce" in _facet_signals(li)


# ---- _signal_stack: superset of the distress-stack signal list ----

def test_signal_stack_is_superset_of_distress_signals():
    li = _li(raw={
        "distress_stack": {"tier": "WARM", "stack": 1, "score": 30,
                           "signals": ["foreclosure_sale"]},
        "tax_owed": {"balance": 3000},
        "code_enforcement": True,
    })
    ss = _signal_stack(li)
    # base foreclosure signal + 2 folded facets
    assert "foreclosure_sale" in ss["signals"]
    assert "tax_delinquent" in ss["signals"]
    assert "code_enforcement" in ss["signals"]
    assert ss["count"] == 3


def test_signal_stack_dedupes_overlap():
    """A facet whose name already appears in the distress signals must not
    double-count (recorded_debt is in both)."""
    li = _li(raw={
        "distress_stack": {"stack": 1, "score": 20, "signals": ["recorded_debt"]},
        "amount_owed": {"value": 99000},
    })
    ss = _signal_stack(li)
    assert ss["signals"].count("recorded_debt") == 1
    assert ss["count"] == 1


def test_signal_stack_empty_when_no_signals():
    ss = _signal_stack(_li(raw={}))
    assert ss == {"count": 0, "signals": []}


# ---- _intent_score: 0-100 normalized ----

def test_intent_zero_with_nothing():
    assert _intent_score(_li(raw={})) == 0


def test_intent_scales_with_stack_score_grade():
    # stack 3 -> 30, score 90 -> 45, grade 100 -> 25  == 100
    li = _li(raw={
        "distress_stack": {"stack": 3, "score": 90, "signals": ["a", "b", "c"]},
        "grade": {"overall": "A", "overall_score": 100},
    })
    assert _intent_score(li) == 100


def test_intent_is_bounded_0_100():
    # Over-max inputs still clamp to 100.
    li = _li(raw={
        "distress_stack": {"stack": 9, "score": 500, "signals": []},
        "grade": {"overall_score": 999},
    })
    assert _intent_score(li) == 100
    # Title-trap negative score never drags intent below the grade/stack floor.
    li2 = _li(raw={
        "distress_stack": {"stack": 1, "score": -20, "signals": ["x"]},
        "grade": {"overall_score": 0},
    })
    assert _intent_score(li2) == 10  # stack 1 -> 10, distress clamped to 0, grade 0


def test_intent_partial_components():
    # stack 2 -> 20, score 45 -> 22.5, grade 60 -> 15  == 57.5 -> 58
    li = _li(raw={
        "distress_stack": {"stack": 2, "score": 45, "signals": ["a", "b"]},
        "grade": {"overall_score": 60},
    })
    assert _intent_score(li) == 58


# ---- _band ----

def test_band_thresholds():
    assert _band(75) == "hot"
    assert _band(70) == "hot"
    assert _band(69) == "warm"
    assert _band(45) == "warm"
    assert _band(44) == "cool"
    assert _band(20) == "cool"
    assert _band(19) == "cold"
    assert _band(0) == "cold"


# ---- enrich_lead_signals: end to end ----

def test_enrich_attaches_fields_and_stats():
    hot = _li(raw={
        "distress_stack": {"tier": "HOT", "stack": 3, "score": 88,
                           "signals": ["foreclosure_sale", "probate", "code_enforcement"]},
        "grade": {"overall": "A", "overall_score": 92},
        "tax_owed": {"balance": 5000},
    })
    cold = _li(raw={"distress_stack": {"stack": 0, "score": 0, "signals": []},
                    "grade": {"overall_score": 10}})
    stats = enrich_lead_signals([hot, cold])

    assert hot.raw["signal_stack"]["count"] >= 3
    assert "tax_delinquent" in hot.raw["signal_stack"]["signals"]
    assert hot.raw["intent_score"] >= 70
    assert hot.raw["intent_band"] == "hot"

    assert cold.raw["intent_score"] < 20
    assert cold.raw["intent_band"] == "cold"

    assert stats["scored"] == 2
    assert stats["with_multi_stack"] >= 1
    assert stats["hot"] >= 1
    assert stats["max_stack"] >= 3


def test_sold_confirmed_zeroed():
    li = _li(raw={
        "sold_confirmed": True,
        "distress_stack": {"stack": 3, "score": 88, "signals": ["a", "b", "c"]},
        "grade": {"overall_score": 95},
        # a stale score from a prior run must be overwritten, not kept:
        "intent_score": 99, "signal_stack": {"count": 3, "signals": ["a", "b", "c"]},
    })
    stats = enrich_lead_signals([li])
    assert li.raw["intent_score"] == 0
    assert li.raw["signal_stack"] == {"count": 0, "signals": []}
    assert li.raw["intent_band"] == "cold"
    assert stats["scored"] == 0  # sold leads are not counted as scored


def test_idempotent():
    li = _li(raw={
        "distress_stack": {"stack": 2, "score": 40, "signals": ["foreclosure_sale", "tax_sale"]},
        "grade": {"overall_score": 70},
    })
    enrich_lead_signals([li])
    first = dict(li.raw["signal_stack"]), li.raw["intent_score"]
    enrich_lead_signals([li])
    second = dict(li.raw["signal_stack"]), li.raw["intent_score"]
    assert first == second


def test_gate_disables(monkeypatch):
    import foreclosure_scraper.enrichment_lead_signals as mod
    monkeypatch.setattr(mod, "_ENABLED", False)
    li = _li(raw={"distress_stack": {"stack": 3, "score": 88, "signals": ["a", "b", "c"]}})
    stats = mod.enrich_lead_signals([li])
    assert stats["scored"] == 0
    assert "signal_stack" not in li.raw  # untouched when gated off

"""vacant_lot and life_estate must reach the score.

Audit 2026-10-02 (commit dd19fa6a): SIGNAL_CATEGORY declared both "vacant_lot" -> PROPERTY
and "life_estate" -> LIFE_EVENT, but no code path in _collect()/_score_group() ever read
either raw key, even though both already carry real, already-scraped data:

  * raw['vacant_lot'] (enrichment_vacant_landuse.py) -- a parcel-cache land_use field saying
    a lot is VACANT/UNDEVELOPED. Live-verified 2026-10-02: 5,641 board rows carry it, 0 of
    them credited before this fix.
  * raw['life_events'] containing the token "life_estate" (enrichment_life_events.py) -- a
    regex read of 'LIFE EST...' off the owner-of-record name. Live-verified 2026-10-02: 458
    board rows carry it, 0 of them credited before this fix.

raw['owner_name_signal'] (enrichment_owner_name_signal.py) detects the identical life-estate
token too, but that enricher runs AFTER score_board in main.py's pipeline order, so it was
never a viable wiring point -- life_events is the only one of the two that is live at scoring
time (see the comment in distress_score._collect for the exact line numbers).
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.distress_score import _signals_for, evidence_of, score_board
from foreclosure_scraper.models import Listing, ListingType

NOPE = Path("/nonexistent/listings.json")   # score_board must never read the real board


def _lead(raw, lt=ListingType.DISTRESSED, source="counties_generic.test", owner_name=None):
    return Listing(source=source, source_url="u", listing_type=lt, state="NC", county="Gaston",
                   owner_name=owner_name, raw=raw)


def _names(li):
    return [n for n, _c, _w in _signals_for(li)]


def _cats(li):
    return {c for _n, c, _w in _signals_for(li)}


# ---------------------------------------------------------------------------
# vacant_lot
# ---------------------------------------------------------------------------
def test_vacant_lot_scores_as_a_property_signal():
    li = _lead({"vacant_lot": {"land_use": "VACANT RESIDENTIAL", "source": "parcel_cache_landuse"}})
    assert ("vacant_lot", "PROPERTY", 10) in _signals_for(li)


def test_vacant_lot_evidence_is_record_not_name_based():
    li = _lead({"vacant_lot": {"land_use": "UNDEVELOPED", "source": "parcel_cache_landuse"}},
               owner_name="SOME OWNER")
    [li2] = [li]
    score_board([li2], previous_path=NOPE)
    ds = li2.raw["distress_stack"]
    assert "vacant_lot" in ds["signals"]
    assert evidence_of(ds, "vacant_lot") == "record"          # REC is the default: never listed in evidence{}
    assert "vacant_lot" not in (ds.get("evidence") or {})


def test_missing_or_falsy_vacant_lot_scores_nothing():
    assert "vacant_lot" not in _names(_lead({}))
    assert "vacant_lot" not in _names(_lead({"vacant_lot": None}))
    assert "vacant_lot" not in _names(_lead({"vacant_lot": {}}))
    assert "vacant_lot" not in _names(_lead({"vacant_lot": False}))


def test_vacant_lot_is_distinct_from_vacant_structure():
    """A vacant LOT (undeveloped land) and a vacant HOUSE (vacancy/vacant) are different
    facts on different raw keys; one must never credit the other's signal name."""
    lot = _lead({"vacant_lot": {"land_use": "VACANT LOT"}})
    assert "vacant_structure" not in _names(lot)
    house = _lead({"vacancy": {"vacant": True}})
    assert "vacant_lot" not in _names(house)
    assert "vacant_structure" in _names(house)


def test_vacant_lot_alone_is_too_weak_for_the_absentee_warm_route():
    """Weight 10 (< the non_attribute floor of 12, F16's rule) -- a vacant lot plus absentee
    ownership and nothing else must not reach WARM the way a real event would."""
    li = _lead({"vacant_lot": {"land_use": "VACANT"}, "owner_mailing": {"mailing": "1 Elsewhere Rd",
                                                                        "absentee": True}})
    score_board([li], previous_path=NOPE)
    ds = li.raw["distress_stack"]
    assert ds["stack"] == 1
    assert ds["non_attribute"] is False
    assert ds["tier"] == "COLD"


def test_vacant_lot_stacks_with_a_financial_signal_to_form_stack_two():
    """vacant_lot (PROPERTY) beside a real tax lien (FINANCIAL) is two distinct categories --
    the exact stacking behaviour the SIGNAL_CATEGORY entry was supposed to feed all along."""
    li = _lead({"vacant_lot": {"land_use": "VACANT"},
                "amount_owed": {"value": 9000, "source": "judgment", "is_actual_debt": True}},
               lt=ListingType.TAX_LIEN)
    score_board([li], previous_path=NOPE)
    ds = li.raw["distress_stack"]
    assert ds["stack"] == 2
    assert {"PROPERTY", "FINANCIAL"} <= set(ds["categories"])
    assert "vacant_lot" in ds["signals"] and "recorded_debt" in ds["signals"]


# ---------------------------------------------------------------------------
# life_estate
# ---------------------------------------------------------------------------
def test_life_estate_scores_as_a_life_event_signal():
    li = _lead({"life_events": ["life_estate"]})
    assert ("life_estate", "LIFE_EVENT", 8) in _signals_for(li)


def test_life_estate_evidence_is_inferred_not_record():
    li = _lead({"life_events": ["life_estate"]})
    score_board([li], previous_path=NOPE)
    ds = li.raw["distress_stack"]
    assert "life_estate" in ds["signals"]
    assert evidence_of(ds, "life_estate") == "inferred"
    assert ds.get("evidence", {}).get("life_estate") == "inferred"


def test_other_life_events_tokens_do_not_score_life_estate():
    assert "life_estate" not in _names(_lead({"life_events": ["trust"]}))
    assert "life_estate" not in _names(_lead({"life_events": ["multiple_heirs"]}))
    assert "life_estate" not in _names(_lead({"life_events": []}))
    assert "life_estate" not in _names(_lead({}))


def test_legacy_int_shape_life_events_does_not_crash_or_score():
    """enrichment_lead_signals.py documents a legacy int-count shape for raw['life_events']
    from before the current list-of-tags enricher. The scorer must not crash on it, and
    (unlike the lead-signals chip's own legacy fallback) must not fabricate a life_estate
    credit it cannot actually verify from a bare count."""
    li = _lead({"life_events": 3})
    assert "life_estate" not in _names(li)


def test_life_estate_alone_is_too_weak_for_the_absentee_warm_route():
    """Weight 8, the same bucket as senior_exemption -- an attribute, not an event; F16's
    non_attribute gate must block the absentee WARM route on this signal alone."""
    li = _lead({"life_events": ["life_estate"],
                "owner_mailing": {"mailing": "1 Elsewhere Rd", "absentee": True}})
    score_board([li], previous_path=NOPE)
    ds = li.raw["distress_stack"]
    assert ds["stack"] == 1
    assert ds["non_attribute"] is False
    assert ds["tier"] == "COLD"


def test_life_estate_stacks_with_a_financial_signal_to_form_stack_two():
    li = _lead({"life_events": ["life_estate"],
                "amount_owed": {"value": 9000, "source": "judgment", "is_actual_debt": True}},
               lt=ListingType.TAX_LIEN)
    score_board([li], previous_path=NOPE)
    ds = li.raw["distress_stack"]
    assert ds["stack"] == 2
    assert {"LIFE_EVENT", "FINANCIAL"} <= set(ds["categories"])
    # the group's strong (record-linked) category is FINANCIAL (recorded_debt); life_estate's
    # own evidence is 'inferred', which is NOT in _WEAK_EVIDENCE, so it still counts toward the
    # stack directly -- unlike a name_joined/name_only signal, which would need 2 strong
    # categories already present before it could lengthen the stack.
    assert ds.get("record_linked", True) is True

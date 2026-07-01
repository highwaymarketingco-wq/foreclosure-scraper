"""Helene placard severity -> honest distress weight.

Calibrated against the existing scale (generic distressed=10, code_enf=14,
bankruptcy=18): Restricted just above generic, Unsafe above code enforcement,
scaled by damage % and multi-building count. Helene leads stay single-category
so they never fake-promote to HOT on this signal alone.
"""
from __future__ import annotations

from foreclosure_scraper.distress_score import _helene_signal, _signals_for
from foreclosure_scraper.models import Listing, ListingType


def _hel(desc, meta=None):
    raw = {"helene": meta} if meta else {}
    return Listing(source="counties_nc.asheville_helene", source_url="u",
                   listing_type=ListingType.DISTRESSED, state="NC", county="Buncombe",
                   description=desc, raw=raw)


def test_placard_grading_from_description():
    assert _helene_signal(_hel("Helene damage: Restricted placard - 20%"))[2] == 12
    assert _helene_signal(_hel("Helene damage: Restricted placard - 60%"))[2] == 14  # +2 high %
    assert _helene_signal(_hel("Helene damage: Unsafe placard - 30%"))[2] == 16
    assert _helene_signal(_hel("Helene damage: Unsafe placard - 90%"))[2] == 19      # +3 high %


def test_multi_building_bump_and_meta_precedence():
    # raw['helene'] meta (from the dedup) wins over the description
    sig = _helene_signal(_hel("Helene damage: Restricted placard - 10%",
                              {"worst_placard": "Unsafe", "worst_damage_pct": 90, "damaged_buildings": 5}))
    assert sig == ("helene_unsafe", "PROPERTY", 19 + 2)  # unsafe 16 +3 (>=75%) +2 (>=3 bldgs)


def test_unsafe_outweighs_generic_distressed_in_signals():
    # _signals_for replaces the flat ('distressed', 10) with the graded signal
    sigs = _signals_for(_hel("Helene damage: Unsafe placard - 80%"))
    names = {n for n, _, _ in sigs}
    assert "helene_unsafe" in names
    assert "distressed" not in names  # generic flat-10 is replaced, not stacked
    assert next(w for n, _, w in sigs if n == "helene_unsafe") == 19


def test_non_helene_untouched():
    other = Listing(source="counties_nc.other", source_url="u",
                    listing_type=ListingType.DISTRESSED, state="NC", county="Buncombe",
                    description="Vacant distressed property")
    assert _helene_signal(other) is None
    names = {n for n, _, _ in _signals_for(other)}
    assert "distressed" in names  # generic distressed signal unchanged for non-Helene

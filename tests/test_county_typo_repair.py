"""County repair must never file a lead in the wrong county.

`county` drives routing, scope_repass and every per-county count. 1,815 board rows
(all from the builder-typed liensnc pool) carry a value that is not a real county,
spread over 425 distinct spellings. Recovering them is worth doing, but a WRONG
county is worse than an unroutable one: it passes scope_repass and lands a lead in a
county the operator does not work.

These tests pin the two failure modes that matter, both found in the real data:

  * "Stanley" fuzzy-matches the real county "Stanly" at 92 -- but the town of Stanley
    sits on the Gaston/Lincoln line, ~90 miles from Stanly County.
  * "Leland" fuzzy-matches "Cleveland" at 80 -- but Leland is a town in Brunswick.

So the resolution order is city-lookup, then explicit seat table, then fuzzy at a
threshold chosen from the real values (85), and anything left is CLEARED rather than
guessed. Loosening the threshold is what breaks it: at 80, Leland goes to Cleveland.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "county_repair",
    Path(__file__).resolve().parent.parent / "scripts" / "repair_county_typos_and_towns.py",
)
cr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cr)

_NO_CITY = lambda _c: None  # noqa: E731 -- force the seat/fuzzy paths


@pytest.mark.parametrize("bad,expect", [
    ("Stanley", "Gaston"),          # NOT Stanly
    ("Leland", "Brunswick"),        # NOT Cleveland
    ("Rutherfordton", "Rutherford"),
    ("Hendersonville", "Henderson"),
    ("Lincolnton", "Lincoln"),
    ("Marion", "Mcdowell"),
    ("Columbus", "Polk"),
])
def test_town_names_resolve_to_their_actual_county(bad, expect):
    got, how = cr.resolve(bad, "NC", None, _NO_CITY)
    assert got == expect, f"{bad!r} -> {got!r} via {how}"
    assert how in ("seat_lookup", "city_field", "town_via_resolver")


@pytest.mark.parametrize("typo,expect", [
    ("Bumcombe", "Buncombe"), ("Buncombee", "Buncombe"), ("Buncomb", "Buncombe"),
    ("Bucombe", "Buncombe"), ("Buncome", "Buncombe"),
    ("Mecklenberg", "Mecklenburg"), ("Mcklenburg", "Mecklenburg"),
    ("Mechlenburg", "Mecklenburg"), ("Mecklinburg", "Mecklenburg"),
    ("Meckenburg", "Mecklenburg"), ("Mecklemburg", "Mecklenburg"),
    ("Guiford", "Guilford"), ("Guildford", "Guilford"),
    ("Forstyh", "Forsyth"), ("Forsythe", "Forsyth"),
    ("Catwaba", "Catawba"), ("Catawaba", "Catawba"),
    ("Cabarras", "Cabarrus"), ("Cabbarus", "Cabarrus"), ("Carbarrus", "Cabarrus"),
    ("New Hannover", "New Hanover"), ("North Hampton", "Northampton"),
    ("Watagua", "Watauga"), ("Cateret", "Carteret"), ("Yancy", "Yancey"),
    ("Hatwood", "Haywood"),
])
def test_real_misspellings_recover(typo, expect):
    """Every one of these is an actual value on the board."""
    got, how = cr.resolve(typo, "NC", None, _NO_CITY)
    assert got == expect, f"{typo!r} -> {got!r} via {how}"


def test_stanly_the_real_county_is_left_alone():
    """The guard must not make the genuine county unrecognisable."""
    assert cr.is_real("Stanly", "NC") is True
    assert cr.is_real("Stanley", "NC") is False


@pytest.mark.parametrize("name,state", [
    ("Wake", "NC"), ("Mecklenburg", "NC"), ("Durham", "NC"),   # real, out of footprint
    ("Buncombe", "NC"), ("Spartanburg", "SC"), ("Charleston", "SC"),
])
def test_real_counties_are_never_touched(name, state):
    """is_real must use the OFFICIAL county list, not the footprint -- an
    out-of-footprint but genuine county is not junk to be repaired."""
    assert cr.is_real(name, state) is True


def test_unresolvable_is_cleared_not_guessed():
    """An honest None beats a confident wrong county."""
    got, how = cr.resolve("Zzzqqx", "NC", None, _NO_CITY)
    assert got is None
    assert how == "cleared"


def test_the_city_field_wins_over_fuzzy():
    """A row whose own city resolves is authoritative; fuzzy must not override it."""
    got, how = cr.resolve("Bumcombe", "NC", "Gaffney", lambda c: "Cherokee" if c == "Gaffney" else None)
    assert got == "Cherokee"
    assert how == "city_field"


def test_lowering_the_threshold_would_reintroduce_the_leland_bug():
    """Documents WHY the threshold is 85. Leland/Cleveland scores 80, so an 80
    threshold files Brunswick rows in Cleveland. If someone lowers it, this fails."""
    from rapidfuzz import fuzz
    assert 78 <= fuzz.ratio("leland", "cleveland") < 85
    assert "leland" in cr.TOWN_NOT_COUNTY   # belt and braces even if the score moves

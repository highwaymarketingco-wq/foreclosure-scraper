"""One canonical spelling per county. `.title()` is not it.

MEASURED ON THE LIVE BOARD 2026-09-13, 115,942 rows:
    NC McDowell   1,771 rows SPLIT: 'McDowell' 1,627 / 'Mcdowell' 144
    SC McCormick  311 rows written 'Mccormick' -- wrong EVERYWHERE, so it never even
                  looked split, which is why nobody noticed

`.title()` lowercases every letter after the first of each word, and it is applied to
county names in a dozen modules (address_owner_v2, assessor_photo, aggressive_address,
buyer_match, county_phone, fhfa_value, equity, foreclosure_sold_comps, ...). McDowell NC
and McCormick SC are the only NC/SC counties with an internal capital, so they are the
only two it damages -- and it damages them everywhere.

A split county name fragments every per-county count, fails the footprint check when
config.ALL_COUNTIES says "McDowell", and breaks the parcel-cache lookup for whichever
rows land on the wrong side.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.config import ALL_COUNTIES
from foreclosure_scraper.county_name import canonical_county, same_county


@pytest.mark.parametrize("raw,want", [
    ("mcdowell", "McDowell"), ("MCDOWELL", "McDowell"), ("Mcdowell", "McDowell"),
    ("McDowell", "McDowell"), ("  McDowell County  ", "McDowell"),
    ("mccormick", "McCormick"), ("MCCORMICK COUNTY", "McCormick"),
    ("Mccormick", "McCormick"),
])
def test_the_two_counties_title_case_breaks(raw, want):
    assert canonical_county(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("macon", "Macon"), ("Macon County", "Macon"), ("MACON", "Macon"),
])
def test_macon_is_not_mangled_into_macon_with_a_capital_o(raw, want):
    """The Mac- rule must not fire on Macon, which is an ordinary county name."""
    assert canonical_county(raw) == want
    assert "MacO" not in canonical_county(raw)


@pytest.mark.parametrize("raw,want", [
    ("new hanover", "New Hanover"), ("NEW HANOVER COUNTY", "New Hanover"),
    ("buncombe", "Buncombe"), ("  spartanburg  ", "Spartanburg"),
    ("", ""), (None, ""), ("   ", ""),
])
def test_ordinary_names_and_empties(raw, want):
    assert canonical_county(raw) == want


def test_every_configured_county_is_already_canonical():
    """config.ALL_COUNTIES is the authority. If canonicalising a configured name changes
    it, the two disagree and every footprint check is unreliable."""
    for c in ALL_COUNTIES:
        assert canonical_county(c.name) == c.name.replace(" County", "").strip(), (
            f"config spells it {c.name!r}; canonical_county gives "
            f"{canonical_county(c.name)!r}")


def test_title_case_is_demonstrably_wrong_which_is_why_this_exists():
    """Pins the actual defect so the reason survives."""
    assert "McDowell".title() == "Mcdowell"
    assert "McCormick".title() == "Mccormick"
    assert canonical_county("McDowell".title()) == "McDowell"


@pytest.mark.parametrize("a,b", [
    ("McDowell", "mcdowell"), ("Mccormick", "McCormick"),
    ("McDowell County", "MCDOWELL"),
])
def test_same_county_sees_through_spelling(a, b):
    assert same_county(a, b) is True


def test_same_county_does_not_merge_different_counties():
    assert same_county("McDowell", "Macon") is False
    assert same_county("Union", "Unicoi") is False

"""An SC case number names its own county. Use that instead of guessing.

SC Common Pleas case numbers are YYYY-CP-NN-NNNNN and the middle pair is the COUNTY CODE
— the 46 counties numbered alphabetically. 2025-CP-38-01441 is Orangeburg;
2024-CP-42-00123 is Spartanburg.

WHY IT WAS NEEDED. Column files SC legal notices under the NEWSPAPER's coverage region
rather than the county: 58 of 98 recent SC foreclosure notices carry the county value
'Orangeburg, Bamberg and Calhoun', which routes nothing. The notice body usually says
"COUNTY OF ORANGEBURG" — but 11 of 37 parsed rows had no such line, and every one of
those 11 had a case number. After wiring this, county-less SC foreclosure rows went
11 -> 0.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.sc_case_county import (
    SC_COUNTY_BY_CODE, county_from_sc_case, normalize_sc_case,
)


@pytest.mark.parametrize("case,county", [
    ("2025-CP-38-01441", "Orangeburg"),
    ("2026-CP-38-00028", "Orangeburg"),
    ("2025CP3801109", "Orangeburg"),        # no separators
    ("2025 CP 38 01109", "Orangeburg"),     # spaces
    ("2024-CP-42-00123", "Spartanburg"),    # footprint
    ("2026-CP-39-00777", "Pickens"),        # footprint
    ("2023-CP-30-00100", "Laurens"),        # footprint
    ("2024-CP-44-00050", "Union"),          # footprint
    ("2024-CP-11-00050", "Cherokee"),       # footprint
    ("2024-CP-37-00050", "Oconee"),         # footprint
    ("2024-CP-04-00050", "Anderson"),       # footprint
])
def test_the_county_code_names_the_county(case, county):
    assert county_from_sc_case(case) == county


@pytest.mark.parametrize("bad", [
    "2024-CP-99-00001",   # no such county code
    "2024-CP-00-00001",
    "not a case number", "", None, "24-CP-38-1",
])
def test_an_unrecognised_case_yields_none_rather_than_a_guess(bad):
    assert county_from_sc_case(bad) is None


def test_all_46_counties_are_mapped_and_unique():
    assert len(SC_COUNTY_BY_CODE) == 46
    assert len(set(SC_COUNTY_BY_CODE.values())) == 46
    assert SC_COUNTY_BY_CODE["01"] == "Abbeville"
    assert SC_COUNTY_BY_CODE["46"] == "York"


def test_mccormick_keeps_its_internal_capital():
    """Code 33 is McCormick — the county .title() corrupts to 'Mccormick'."""
    assert SC_COUNTY_BY_CODE["33"] == "McCormick"
    assert county_from_sc_case("2024-CP-33-00001") == "McCormick"


@pytest.mark.parametrize("raw,canon", [
    ("2025CP3801109", "2025-CP-38-01109"),
    ("2025 CP 38 01109", "2025-CP-38-01109"),
    ("2025-CP-38-01109", "2025-CP-38-01109"),
    ("case no. 2025-cp-38-01109 filed", "2025-CP-38-01109"),
])
def test_canonical_form_lets_two_sources_match(raw, canon):
    assert normalize_sc_case(raw) == canon


def test_normalize_returns_none_for_a_non_case():
    assert normalize_sc_case("no case here") is None
    assert normalize_sc_case(None) is None

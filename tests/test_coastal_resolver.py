"""Coastal town -> county resolver regression tests.

Locks in the four bugs fixed in 2026-06: Swansboro/Cape Carteret were
unmapped, Duck was mis-attributed to Currituck (it incorporated in Dare
in 2002), and "Beaufort" collided across states (the NC town in Carteret
vs the SC county) when the lookup was keyed on city name alone. The fix
keys ``_LOOKUP`` on (city, state), so both Beauforts coexist.
"""
import pytest

from foreclosure_scraper._coastal_city_to_county import coastal_county_for


@pytest.mark.parametrize(
    "city,state,expected",
    [
        ("Swansboro", "NC", "Onslow"),
        ("Cape Carteret", "NC", "Carteret"),
        ("Duck", "NC", "Dare"),
        ("Beaufort", "NC", "Carteret"),   # the TOWN (Carteret County NC)
        ("Beaufort", "SC", "Beaufort"),   # the COUNTY (SC) — must not be clobbered
    ],
)
def test_coastal_county_for(city, state, expected):
    assert coastal_county_for(city, state) == expected


def test_case_and_whitespace_insensitive():
    assert coastal_county_for("  nags head ", "nc") == "Dare"


def test_unknown_city_returns_none():
    assert coastal_county_for("Nowheresville", "NC") is None


def test_missing_args_return_none():
    assert coastal_county_for(None, "NC") is None
    assert coastal_county_for("Duck", None) is None


def test_no_cross_state_collision():
    # Same town name in different states must resolve independently, never
    # one silently overwriting the other.
    assert coastal_county_for("Beaufort", "NC") != coastal_county_for("Beaufort", "SC")

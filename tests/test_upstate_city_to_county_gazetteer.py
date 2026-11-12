"""`_upstate_city_to_county.py` must never map a city string to the WRONG
county -- it feeds the scrape-time `_in_scope` gate (national.crexi_multifamily,
national.irs_judicial_sales, and every scraper listed below), so a wrong
county can pull an out-of-footprint lead onto the board as if it were
in-scope, or (less dangerously) deny an in-footprint lead.

LIVE-CONFIRMED BUG (2026-10-03/04): the gazetteer listed the bare county name
as one of its own city aliases for several in-footprint counties (e.g.
``_add("NC", "Henderson", "Hendersonville", ..., "Henderson")``). For most of
those counties the bare name is harmless (it IS the county seat's real name,
e.g. Spartanburg, Union). But for a few, a real, distinct, out-of-footprint
city shares that exact name in the SAME state, so the state check in
``upstate_county_for`` cannot tell them apart:

  * Henderson, NC (seat of Vance County, zips 27536/27537) vs Henderson
    COUNTY, NC (WNC footprint, seat = Hendersonville). Live-confirmed via
    national.irs_judicial_sales: an active federal auction lot at 340 Cedar
    Grove Dr, Henderson, NC 27537 was resolving to the in-footprint Henderson
    County instead of the real, out-of-footprint Vance County.
  * Gaston, NC (Northampton County, zip 27832, pop ~1,008, near Lake Gaston)
    vs Gaston COUNTY, NC (footprint, seat = Gastonia).
  * Cleveland, NC (Rowan County, zip 27013, pop ~846, near Salisbury) vs
    Cleveland COUNTY, NC (footprint, seat = Shelby).

Fixed by removing the three colliding bare aliases from their in-footprint
``_add()`` calls and mapping them to their REAL county in the "out-of-
footprint but high-volume" section instead (the same pattern the module
already uses for Charlotte/Columbia/Raleigh/etc: resolve to the real county
so ``in_scope`` denies deterministically, rather than returning None and
risking the row falling through a blank-county fallback elsewhere).

Other bare county-name aliases in the file were checked against this same
class of bug and found NOT to collide with any real, distinct place of the
same name (so they were left alone): Rutherford, Polk, Buncombe,
Transylvania, McDowell, Lincoln, Mitchell, Burke (NC); Spartanburg, Anderson,
Pickens, Oconee, Union, Laurens (SC). ``Cherokee`` (SC) was also checked: the
real, distinct Cherokee, NC (Qualla Boundary / Eastern Band of Cherokee
Indians, Swain/Jackson counties) is a cross-STATE collision, already
correctly blocked by ``upstate_county_for``'s state check -- see
``test_cherokee_cross_state_collision_is_blocked_by_state_check`` below.
"""
from __future__ import annotations

from foreclosure_scraper._upstate_city_to_county import (
    KNOWN_CITIES,
    _LOOKUP,
    upstate_county_for,
)
from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES


def test_henderson_city_resolves_to_vance_not_henderson_county():
    """340 Cedar Grove Dr, Henderson, NC 27537 (irs_judicial_sales, live
    2026-10-28 auction) must resolve to Vance County, not Henderson County."""
    assert upstate_county_for("Henderson", "NC") == "Vance"


def test_gaston_city_resolves_to_northampton_not_gaston_county():
    """Gaston, NC (Northampton County) must not resolve to Gaston County."""
    assert upstate_county_for("Gaston", "NC") == "Northampton"


def test_cleveland_city_resolves_to_rowan_not_cleveland_county():
    """Cleveland, NC (Rowan County) must not resolve to Cleveland County."""
    assert upstate_county_for("Cleveland", "NC") == "Rowan"


def test_cherokee_cross_state_collision_is_blocked_by_state_check():
    """Cherokee, NC (Qualla Boundary, Swain/Jackson) is a real, distinct place
    from Cherokee COUNTY, SC (seat Gaffney) -- but they're different states,
    so the existing state check already blocks the cross-state collision:
    querying with state=NC must not return the SC county."""
    assert upstate_county_for("Cherokee", "SC") == "Cherokee"
    assert upstate_county_for("Cherokee", "NC") is None


def test_real_county_seats_still_resolve_after_the_fix():
    """The fix must not collaterally break the legitimate, non-colliding
    resolutions for these same three counties and their real seats/towns."""
    assert upstate_county_for("Hendersonville", "NC") == "Henderson"
    assert upstate_county_for("Flat Rock", "NC") == "Henderson"
    assert upstate_county_for("Gastonia", "NC") == "Gaston"
    assert upstate_county_for("Belmont", "NC") == "Gaston"
    assert upstate_county_for("Shelby", "NC") == "Cleveland"
    assert upstate_county_for("Kings Mountain", "NC") == "Cleveland"


def test_other_bare_county_name_aliases_are_not_collisions():
    """Checked live/against general geography and confirmed NOT to collide
    with any real, distinct place of the same name -- these bare aliases are
    intentionally still present and must keep resolving to their own county."""
    still_bare = {
        "Rutherford": "NC", "Polk": "NC", "Buncombe": "NC",
        "Transylvania": "NC", "Mitchell": "NC", "Burke": "NC",
        "Spartanburg": "SC", "Anderson": "SC", "Pickens": "SC",
        "Oconee": "SC", "Union": "SC", "Laurens": "SC",
    }
    for city, state in still_bare.items():
        assert upstate_county_for(city, state) == city, (
            f"{city}/{state} unexpectedly stopped resolving to itself"
        )
    # Lowercased/differently-cased variants in the source.
    assert upstate_county_for("McDowell", "NC") == "McDowell"
    assert upstate_county_for("Lincoln", "NC") == "Lincoln"


def test_no_bare_county_name_city_alias_collides_with_the_known_real_town():
    """Belt-and-suspenders sweep: for every county name used as its own bare
    city alias anywhere in the gazetteer, the resolved (county, state) must
    actually be a real NC/SC county (this would catch a future typo'd
    re-introduction of one of the fixed collisions)."""
    all_counties = set(NC_COUNTIES) | set(SC_COUNTIES)
    for key, (county, state) in _LOOKUP.items():
        if key.lower() == county.lower():
            assert county in all_counties, (
                f"bare alias {key!r} -> {county!r}/{state} is not a real county"
            )


def test_vance_gaston_rowan_are_valid_nc_counties():
    """Sanity check on the new mappings themselves."""
    assert "Vance" in NC_COUNTIES
    assert "Gaston" in NC_COUNTIES
    assert "Rowan" in NC_COUNTIES
    assert "Northampton" in NC_COUNTIES


def test_known_cities_still_includes_henderson_gaston_cleveland():
    """KNOWN_CITIES (used by auction_dot_com.py / crexi_multifamily.py to find
    a city substring in free text) must still contain these three names --
    they're just mapped to a different county now, not removed."""
    assert "henderson" in KNOWN_CITIES
    assert "gaston" in KNOWN_CITIES
    assert "cleveland" in KNOWN_CITIES

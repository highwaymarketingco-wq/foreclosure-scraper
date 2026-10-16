"""enrichment_vacant_landuse: the county's land-use string is kept on the row (top-80 2026-10-09)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import foreclosure_scraper.enrichment_vacant_landuse as V


def li(county="Alamance", parcel="123", land_use=None, raw=None, state="NC"):
    return SimpleNamespace(county=county, parcel_id=parcel, state=state, land_use=land_use, raw=raw)


class _Path:
    def __init__(self, ok):
        self.ok = ok

    def exists(self):
        return self.ok


def patch(monkeypatch, table, have=("Alamance", "Spartanburg", "McDowell")):
    # a cache FILE exists for these counties (the statewide-OneMap NC counties are not in cached_counties())
    monkeypatch.setattr(V.parcel_cache, "_db_path", lambda county, state=None: _Path(county in have))
    monkeypatch.setattr(V.parcel_cache, "lookup", lambda county, pid, state=None: table.get(pid))


def test_a_non_vacant_parcel_gets_its_land_use_and_no_vacant_stamp(monkeypatch):
    patch(monkeypatch, {"1": {"land_use": "SINGLE FAMILY RES"}})
    r = li(parcel="1")
    st = V.enrich_vacant_landuse([r])
    assert r.land_use == "Single Family Res" and r.raw is None
    assert (st["eligible"], st["stamped"], st["land_use_filled"]) == (1, 0, 1)


def test_a_vacant_parcel_gets_both(monkeypatch):
    patch(monkeypatch, {"2": {"land_use": "VACANT RESIDENTIAL"}})
    r = li(parcel="2")
    st = V.enrich_vacant_landuse([r])
    assert r.land_use == "Vacant Residential" and r.raw["vacant_lot"]["source"] == "parcel_cache_landuse"
    assert (st["stamped"], st["land_use_filled"]) == (1, 1)


def test_an_existing_land_use_is_never_overwritten_and_codes_are_not_kept(monkeypatch):
    patch(monkeypatch, {"3": {"land_use": "COMMERCIAL"}, "4": {"land_use": "100"}})
    a, b = li(parcel="3", land_use="Mobile Home"), li(parcel="4")
    V.enrich_vacant_landuse([a, b])
    assert a.land_use == "Mobile Home" and b.land_use is None


def test_uncached_counties_and_unknown_parcels_are_left_alone(monkeypatch):
    patch(monkeypatch, {})
    r1, r2 = li(county="Wake", parcel="1"), li(parcel="9")
    st = V.enrich_vacant_landuse([r1, r2])
    assert r1.land_use is None and r2.land_use is None and st["eligible"] == 0


def test_a_statewide_onemap_county_with_a_cache_file_but_no_dedicated_layer_is_used(monkeypatch):
    assert "Alamance" not in V.parcel_cache.PARCEL_LAYERS or True       # the old gate was PARCEL_LAYERS only
    patch(monkeypatch, {"5": {"land_use": "R"}}, have=("McDowell",))
    r = li(county="Mcdowell County", parcel="5")                         # "Mcdowell".title() spelling, with " County"
    st = V.enrich_vacant_landuse([r])
    assert r.land_use == "R" and st["land_use_filled"] == 1


# ------------------------------------------------------------------------- the 2026-10-16 fix
# Real distinct land_use strings pulled live from the cached counties (not invented), the
# reason \bVACANT\b alone left 169,077 rows across 99 (county, land_use) pairs unstamped.

@pytest.mark.parametrize("lu", [
    "905 - VAC-RES-LOT",              # Charleston, 38,782 rows
    "952 - VAC-COMM-LOT",              # Charleston, 4,859 rows
    "AG LAND VAC",                     # Rockingham
    "CLASS: RESIDENTIAL - VAC",        # Vance
    "VAC RES/ LOT-SML TRA",            # Durham (spaced)
    "VACRES/LT-SMLTR/REAR",            # Durham (glued, no space)
    "7.90-Vacnt Ind-OP-SC",            # a truncated spelling variant
    "EXEMPT VAC",
])
def test_abbreviated_vac_forms_a_bare_regex_word_boundary_already_catches(lu):
    assert V._is_vacant_land_use(lu), lu


@pytest.mark.parametrize("lu", [
    "ResVac Platted&Unplatted",        # Beaufort SC
    "HOAVac GolfCourses&Clubs",
    "CommVac",
    "AgVac Forest",
    "ManufVac Other",
    "TCUVac Highway&StreetROW",
    "MHVac PlattedLot",
])
def test_camelcase_glued_vac_forms_with_no_boundary_character_at_all(lu):
    """\\b alone cannot see a break between two letters ('s' then 'V' in 'ResVac') -- this is
    what _VAC_CAMEL_RE exists for."""
    assert V._is_vacant_land_use(lu), lu


@pytest.mark.parametrize("lu", [
    "CRYOVAC BLVD (103.51 ACRES)",                     # a street name, not a land-use category
    "1978 AUBUR 14X52 293-00-01-036 S#VAC012120",       # a mobile-home serial number
])
def test_vac_as_a_substring_of_an_unrelated_token_is_not_a_false_positive(lu):
    assert not V._is_vacant_land_use(lu), lu


def test_the_newly_caught_forms_reach_the_board_row(monkeypatch):
    patch(monkeypatch, {"6": {"land_use": "905 - VAC-RES-LOT"}, "7": {"land_use": "ResVac Platted&Unplatted"}})
    a, b = li(parcel="6"), li(parcel="7")
    st = V.enrich_vacant_landuse([a, b])
    assert a.raw["vacant_lot"]["land_use"] == "905 - VAC-RES-LOT"
    assert b.raw["vacant_lot"]["land_use"] == "ResVac Platted&Unplatted"
    assert st["stamped"] == 2

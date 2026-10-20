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


# ----------------------------------------------------------------- the 2026-10-19 fix
# Horry's land_use is a bare numeric DOR code ("101", "300", ...) with no published
# legend (checked live) -- the text matcher above can never read it. Fall back to the
# layer's own improvement-dollar-value field (live-verified correlation: 2026-10-19
# memory) when the cache maps one.

def test_numeric_land_use_with_zero_improvement_value_is_stamped_vacant(monkeypatch):
    patch(monkeypatch, {"8": {"land_use": "100", "improvement_value": 0.0,
                               "market_value": 141150.0}})
    r = li(parcel="8")
    st = V.enrich_vacant_landuse([r])
    assert r.raw["vacant_lot"] == {"land_use": "100", "improvement_value": 0,
                                    "source": "parcel_cache_improvement_value"}
    assert r.land_use is None  # the bare code itself is still never written to land_use
    assert st["stamped"] == 1 and st["stamped_by_improvement_value"] == 1


def test_numeric_land_use_with_nonzero_improvement_value_is_marked_improved_not_vacant(monkeypatch):
    patch(monkeypatch, {"9": {"land_use": "101", "improvement_value": 76326.0,
                               "market_value": 225205.0}})
    r = li(parcel="9")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None  # never stamped vacant
    assert r.land_use == "Improved"  # still recorded as checked
    assert st["stamped"] == 0 and st.get("stamped_by_improvement_value", 0) == 0


def test_numeric_land_use_without_a_mapped_improvement_value_field_stays_silent(monkeypatch):
    """A county whose cache maps land_use but NOT improvement_value (every SC county
    today except Horry) must never guess -- no stamp, no land_use text, nothing."""
    patch(monkeypatch, {"10": {"land_use": "300", "market_value": 90000.0}})
    r = li(parcel="10")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None and r.land_use is None
    assert st["stamped"] == 0


def test_numeric_land_use_with_improvement_value_but_no_other_signal_stays_silent(monkeypatch):
    """A degenerate/blank cache row (no market_value, no acreage) never gets a verdict
    even if improvement_value happens to be 0 -- that 0 could just be a missing field,
    not a real reading."""
    patch(monkeypatch, {"11": {"land_use": "100", "improvement_value": 0.0}})
    r = li(parcel="11")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None and r.land_use is None
    assert st["stamped"] == 0


def test_a_real_text_land_use_that_merely_does_not_match_vac_is_never_reinterpreted(monkeypatch):
    """Only a BARE DIGIT land_use engages the improvement-value fallback -- real text
    that failed the VACANT/VAC wordlist (a land-use category this regex just doesn't
    cover yet) must not silently get reclassified through a different signal."""
    patch(monkeypatch, {"12": {"land_use": "SINGLE FAMILY RES", "improvement_value": 0.0,
                                "market_value": 50000.0}})
    r = li(parcel="12")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


# ----------------------------------------------------------------- the 2026-10-20 fix
# Greenwood SC (PropType, a coarse land-use category, no "Vacant" bucket) and Aiken SC
# (PropertyClassType, an SC 4-6% ratio class spelled out as text) both map a TEXT
# land_use that carries no vacant/improved signal of its own. Confirmed live that
# PropertyClassType never contains "VACANT" (or VAC/UNDEVELOPED/UNIMPROVED) anywhere in
# the whole Aiken layer -- the pasted-document claim for Aiken was false -- but both
# counties DO map a real improvement-dollar-value field, so they are allowlisted through
# the bare-digit gate to reach the SAME fallback as Horry/Barnwell, above.

def test_aiken_text_landuse_with_zero_improvement_value_is_stamped_vacant(monkeypatch):
    patch(monkeypatch, {"13": {"land_use": "NON-QUALIFIED LAND", "improvement_value": 0.0,
                                "market_value": 18000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Aiken"))
    r = li(parcel="13", county="Aiken", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw["vacant_lot"] == {"land_use": "NON-QUALIFIED LAND", "improvement_value": 0,
                                    "source": "parcel_cache_improvement_value"}
    assert st["stamped"] == 1 and st["stamped_by_improvement_value"] == 1


def test_aiken_text_landuse_with_nonzero_improvement_value_is_improved_not_vacant(monkeypatch):
    patch(monkeypatch, {"14": {"land_use": "OWNER OCCUPIED RESIDENTIAL", "improvement_value": 176850.0,
                                "market_value": 185000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Aiken"))
    r = li(parcel="14", county="Aiken", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0 and st.get("stamped_by_improvement_value", 0) == 0


def test_aiken_null_improvement_value_is_never_reinterpreted_as_zero(monkeypatch):
    """Aiken's ImprovementValue uses a literal 0 for 'no improvements' (live-confirmed:
    NULL on only 210/103,317 rows, not the vacancy encoding) -- unlike Greenwood, a genuine
    NULL here must stay a 'no reading', not get treated as vacant."""
    patch(monkeypatch, {"15": {"land_use": "AGRICULTURAL", "improvement_value": None,
                                "market_value": 72000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Aiken"))
    r = li(parcel="15", county="Aiken", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


def test_greenwood_null_improvement_value_is_stamped_vacant(monkeypatch):
    """Greenwood's BuildingValue encodes 'no structure' as NULL, never a literal 0
    (live-confirmed: `BuildingValue = 0` returns 0 rows) -- the one county where None is
    reinterpreted as the zero-value reading."""
    patch(monkeypatch, {"16": {"land_use": "Residential", "improvement_value": None,
                                "market_value": 65000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Greenwood"))
    r = li(parcel="16", county="Greenwood", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw["vacant_lot"] == {"land_use": "Residential", "improvement_value": 0,
                                    "source": "parcel_cache_improvement_value"}
    assert st["stamped"] == 1 and st["stamped_by_improvement_value"] == 1


def test_greenwood_nonzero_improvement_value_is_improved_not_vacant(monkeypatch):
    patch(monkeypatch, {"17": {"land_use": "Residential", "improvement_value": 141820.0,
                                "market_value": 186820.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Greenwood"))
    r = li(parcel="17", county="Greenwood", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


def test_greenwood_commercial_and_multifamily_proptypes_are_excluded_from_null_reinterpretation(monkeypatch):
    """Live-checked: for Greenwood's Commercial (19.4%) and Multi-Family (10.5%) PropTypes,
    a NULL BuildingValue predicts 'no structure' WORSE than the 38.1% base rate -- the
    opposite of a usable signal -- so these two stay silent even though they are text
    land_use on the allowlisted county."""
    patch(monkeypatch, {"19": {"land_use": "Commercial", "improvement_value": None,
                                "market_value": 250000.0},
                         "20": {"land_use": "Multi-Family", "improvement_value": None,
                                "market_value": 400000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Greenwood"))
    a, b = li(parcel="19", county="Greenwood", state="SC"), li(parcel="20", county="Greenwood", state="SC")
    st = V.enrich_vacant_landuse([a, b])
    assert a.raw is None and b.raw is None
    assert st["stamped"] == 0


def test_greenwood_null_improvement_value_with_no_other_signal_stays_silent(monkeypatch):
    """Even for Greenwood, a NULL improvement_value on an otherwise blank cache row (no
    market_value, no acreage) must stay silent -- the has_other_signal guard still applies
    after None is reinterpreted as 0."""
    patch(monkeypatch, {"18": {"land_use": "Residential", "improvement_value": None}},
          have=("Alamance", "Spartanburg", "McDowell", "Greenwood"))
    r = li(parcel="18", county="Greenwood", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


# Sumter SC (2026-10-20): the cache record carries NO land_use key at all (the layer has no
# such field) -- only improvement_value/market_value/acreage. _VALUE_ONLY_NO_LANDUSE lets
# these rows reach the improvement_value fallback without a land_use value of any kind.

def test_sumter_zero_improvement_value_with_no_landuse_field_is_stamped_vacant(monkeypatch):
    patch(monkeypatch, {"21": {"improvement_value": 0, "market_value": 19205.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Sumter"))
    r = li(parcel="21", county="Sumter", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw["vacant_lot"] == {"improvement_value": 0, "source": "parcel_cache_improvement_value"}
    assert "land_use" not in r.raw["vacant_lot"]
    assert (st["eligible"], st["stamped"], st["stamped_by_improvement_value"]) == (1, 1, 1)


def test_sumter_nonzero_improvement_value_is_improved_not_vacant(monkeypatch):
    patch(monkeypatch, {"22": {"improvement_value": 87848.0, "market_value": 95348.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Sumter"))
    r = li(parcel="22", county="Sumter", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert r.land_use == "Improved"
    assert st["stamped"] == 0 and st.get("stamped_by_improvement_value", 0) == 0


def test_sumter_missing_improvement_value_stays_silent_not_reinterpreted(monkeypatch):
    """Sumter is not on _NULL_IMPROVEMENT_VALUE_MEANS_ZERO (its field uses a literal 0, live-
    confirmed), so a genuine None must stay silent, same as every other county besides
    Greenwood."""
    patch(monkeypatch, {"23": {"improvement_value": None, "market_value": 50000.0}},
          have=("Alamance", "Spartanburg", "McDowell", "Sumter"))
    r = li(parcel="23", county="Sumter", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


def test_sumter_zero_improvement_value_with_no_other_signal_stays_silent(monkeypatch):
    patch(monkeypatch, {"24": {"improvement_value": 0}},
          have=("Alamance", "Spartanburg", "McDowell", "Sumter"))
    r = li(parcel="24", county="Sumter", state="SC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["stamped"] == 0


def test_a_county_not_on_the_value_only_allowlist_is_still_dropped_with_no_landuse(monkeypatch):
    """A plain cache miss on land_use for a county NOT on _VALUE_ONLY_NO_LANDUSE (e.g. a row
    whose cache record has nothing useful at all) is still skipped at the top, unchanged from
    before this fix -- Sumter's new allowance does not loosen anything for any other county."""
    patch(monkeypatch, {"25": {"improvement_value": 0, "market_value": 50000.0}})
    r = li(parcel="25", county="Alamance", state="NC")
    st = V.enrich_vacant_landuse([r])
    assert r.raw is None
    assert st["eligible"] == 0

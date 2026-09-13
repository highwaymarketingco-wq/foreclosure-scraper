"""THE BUG THIS PINS. parcel_cache keyed its SQLite files on the county NAME
alone. Cherokee, Union, Lee, Beaufort, Anson and Chester all exist in BOTH NC
and SC, so building an SC Cherokee cache would have served SC parcels — wrong
owner, wrong situs address — to NC Cherokee listings and vice versa, silently.

Discovered 2026-09-13 while working the queue item "build Cherokee SC / Union SC
caches" BEFORE either cache existed, so nothing was ever mis-joined on the live
board. These tests keep it that way.
"""
import pytest

from foreclosure_scraper.parcel_cache import (
    DUAL_STATE_COUNTIES,
    _db_path,
    lookup,
)


def test_dual_state_names_are_covered():
    for name in ("Cherokee", "Union", "Lee", "Beaufort"):
        assert name in DUAL_STATE_COUNTIES


def test_dual_state_cache_paths_differ_by_state():
    nc = _db_path("Cherokee", "NC")
    sc = _db_path("Cherokee", "SC")
    assert nc != sc
    assert nc.name == "cherokee_nc.sqlite"
    assert sc.name == "cherokee_sc.sqlite"


def test_dual_state_path_without_state_is_an_error():
    with pytest.raises(ValueError):
        _db_path("Cherokee")
    with pytest.raises(ValueError):
        _db_path("Union", "Georgia")


def test_unambiguous_counties_keep_their_bare_filename():
    # Buncombe only exists in NC — its path must not change, or 100 existing
    # caches on disk go cold.
    assert _db_path("Buncombe").name == "buncombe.sqlite"
    assert _db_path("Spartanburg", "SC").name == "spartanburg.sqlite"


def test_lookup_refuses_to_guess_the_state():
    # No state supplied for a dual-state county: return nothing rather than
    # serve the other state's parcel.
    assert lookup("Cherokee", "1234567890") is None


# --- "McDowell".title() == "Mcdowell", strike three -------------------------
# _NC_COUNTY_NAMES (the NC OneMap eligibility list) was built with .title() and
# held "Mcdowell". The board spells it "McDowell", so the membership test in
# resolve_layer_cfg missed it and the statewide fallback never fired for
# McDowell's 1,772 NC rows. Same bug previously hit the BT appraisal-card lookup
# and the board's own county values. Matching is now case-insensitive so a fourth
# occurrence cannot break anything.
from foreclosure_scraper.parcel_cache import _NC_COUNTY_NAMES, resolve_layer_cfg


def test_mcdowell_is_spelled_correctly():
    assert "McDowell" in _NC_COUNTY_NAMES
    assert "Mcdowell" not in _NC_COUNTY_NAMES


def test_nc_county_list_has_no_title_cased_mc_names():
    for n in _NC_COUNTY_NAMES:
        if n.lower().startswith("mc") and len(n) > 2:
            assert n[2].isupper(), f"{n!r} looks like .title() output"


def test_resolve_layer_cfg_is_case_insensitive():
    for spelling in ("McDowell", "mcdowell", "MCDOWELL", " McDowell "):
        assert resolve_layer_cfg(spelling) is not None, spelling


def test_every_board_spelling_of_a_real_nc_county_resolves():
    # Macon is the guard case: it starts with "Mac", so a naive Mc/Mac fixer
    # would corrupt it to "MacOn".
    for c in ("Macon", "Buncombe", "Mitchell"):
        assert resolve_layer_cfg(c) is not None, c

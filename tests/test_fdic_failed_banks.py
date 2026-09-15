"""fdic_failed_banks.py's State column is a full name ("Pennsylvania"), but
downstream scope checks compare state.upper() against "NC"/"SC" -- a full
name would never match, silently dropping any in-footprint bank failure.
Found in the 2026-09-15 national.* zero-row audit; currently latent (no
NC/SC failures exist right now) but worth locking in."""
from foreclosure_scraper.scrapers.national.fdic_failed_banks import _normalize_state


def test_full_nc_name_normalizes_to_abbreviation():
    assert _normalize_state("North Carolina") == "NC"


def test_full_sc_name_normalizes_to_abbreviation():
    assert _normalize_state("South Carolina") == "SC"


def test_case_insensitive():
    assert _normalize_state("north carolina") == "NC"


def test_already_abbreviated_passes_through():
    assert _normalize_state("NC") == "NC"


def test_unrelated_state_passes_through_unchanged():
    assert _normalize_state("Texas") == "Texas"


def test_empty_or_none_is_safe():
    assert _normalize_state("") == ""
    assert _normalize_state(None) == ""

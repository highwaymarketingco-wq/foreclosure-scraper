"""Parcel-id spelling variants for GIS id-field matching (enrichment_gis_attrs).

The GIS parcel fallback matches on an exact `=`, so a dashed tax-PDF parcel
(1728-00-87-8115) silently returned 0 rows against a layer storing the clean
form (172800878115). `_parcel_variants` closes that by trying each spelling.
"""
from foreclosure_scraper.enrichment_gis_attrs import _parcel_variants, _PARCEL_FIELDS


def test_dashed_parcel_yields_clean_variant():
    v = _parcel_variants("1728-00-87-8115")
    assert v[0] == "1728-00-87-8115"      # raw kept + tried first (no regression)
    assert "172800878115" in v            # clean form for parno/PIN-style fields


def test_raw_clean_parcel_first_and_deduped():
    v = _parcel_variants("172800878115")
    assert v[0] == "172800878115"
    assert v.count("172800878115") == 1   # raw == norm, only once


def test_sub_parcel_suffix_stripped():
    v = _parcel_variants("12345.678")     # Georgetown TMS + sub-parcel
    assert "12345" in v                   # suffix dropped (dashed/plain)


def test_empty_and_none():
    assert _parcel_variants("") == []
    assert _parcel_variants(None) == []
    assert _parcel_variants("   ") == []


def test_parcelid_and_account_fields_present():
    # Lincoln's short account numbers only match PARCELID/ACCOUNT, not PARCEL_ID.
    assert "PARCELID" in _PARCEL_FIELDS
    assert "ACCOUNT" in _PARCEL_FIELDS

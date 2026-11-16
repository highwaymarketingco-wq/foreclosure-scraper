"""Regression guard for scripts/backfill_orangeburg_assessed_value.py's build_patches():
fill-only semantics, the ident-based join (never dedupe_key-based -- see that module's
"JOIN KEY" docstring section on the Listing.dedupe_key() url-fallback collision), and
skipping an ident that maps to more than one existing board row rather than guessing.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import backfill_orangeburg_assessed_value as BO  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402


def _li(ident: str, assessed_value=None, tax_value=None, acreage=None,
        legal_description=None) -> Listing:
    return Listing.model_construct(
        state="SC", county="Orangeburg", source="counties_sc.qpaybill_delinquent_roll",
        assessed_value=assessed_value, tax_value=tax_value, acreage=acreage,
        legal_description=legal_description,
        raw={"qpaybill_roll": {"identification_no": ident}})


def test_fills_an_unambiguous_match():
    by_ident = {"2072064": [{"key": "url:https://orangeburgtreasurer.qpaybill.com/x",
                             "current": {"assessed_value": None, "tax_value": None,
                                         "acreage": None, "legal_description": None}}]}
    listings = [_li("2072064", assessed_value=1360.0, tax_value=22700.0)]
    patches, stats = BO.build_patches(listings, by_ident)
    assert patches == {"url:https://orangeburgtreasurer.qpaybill.com/x":
                       {"assessed_value": 1360.0, "tax_value": 22700.0}}
    assert stats["skipped_ambiguous"] == 0
    assert stats["skipped_no_match"] == 0


def test_never_overwrites_an_existing_value():
    """fill-only: a board row that already carries a (possibly different, possibly
    stale) assessed_value must not be clobbered by this backfill."""
    by_ident = {"2072064": [{"key": "k1",
                             "current": {"assessed_value": 999.0, "tax_value": None,
                                         "acreage": None, "legal_description": None}}]}
    listings = [_li("2072064", assessed_value=1360.0, tax_value=22700.0)]
    patches, _stats = BO.build_patches(listings, by_ident)
    assert patches == {"k1": {"tax_value": 22700.0}}  # assessed_value NOT in the patch


def test_skips_ident_with_no_board_match():
    by_ident = {}
    listings = [_li("9999999", assessed_value=500.0)]
    patches, stats = BO.build_patches(listings, by_ident)
    assert patches == {}
    assert stats["skipped_no_match"] == 1


def test_skips_ambiguous_ident_rather_than_guessing():
    """An ident mapping to more than one existing board row (the rare bulk-tax-buyer,
    multi-property case) must be skipped, never patched onto an arbitrary one of them."""
    by_ident = {"2072064": [
        {"key": "k1", "current": {"assessed_value": None, "tax_value": None,
                                   "acreage": None, "legal_description": None}},
        {"key": "k2", "current": {"assessed_value": None, "tax_value": None,
                                   "acreage": None, "legal_description": None}},
    ]}
    listings = [_li("2072064", assessed_value=1360.0)]
    patches, stats = BO.build_patches(listings, by_ident)
    assert patches == {}
    assert stats["skipped_ambiguous"] == 1


def test_listing_with_no_ident_is_skipped_not_crashed():
    by_ident = {"2072064": [{"key": "k1", "current": {"assessed_value": None,
                                                       "tax_value": None, "acreage": None,
                                                       "legal_description": None}}]}
    listings = [Listing.model_construct(state="SC", county="Orangeburg", raw={})]
    patches, stats = BO.build_patches(listings, by_ident)
    assert patches == {}
    assert stats["skipped_no_ident"] == 1


def test_top_fields_matches_the_real_parse_detail_canonical_fields():
    """build_patches() only ever considers _TOP_FIELDS. If parse_detail()/_to_listings()
    ever gain another canonical Listing field worth filling, this constant must grow with
    it or the new field silently never reaches the board (the same shape bug this
    project already hit once in backfill_gis_attrs_boardwide.py -- see
    tests/test_backfill_gis_attrs_top_fields.py)."""
    assert set(BO._TOP_FIELDS) == {"assessed_value", "tax_value", "acreage",
                                   "legal_description"}

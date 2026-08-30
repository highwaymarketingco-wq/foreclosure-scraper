"""Tests for Burke County parcel history diff enricher."""
from foreclosure_scraper.enrichment_burke_history import _norm_owner


def test_norm_owner_uppercases():
    assert _norm_owner("John Smith") == "JOHN SMITH"


def test_norm_owner_strips_punctuation():
    assert _norm_owner("Smith, John D.") == "SMITH JOHN D"


def test_norm_owner_collapses_whitespace():
    assert _norm_owner("  John   Smith  ") == "JOHN SMITH"


def test_norm_owner_none():
    assert _norm_owner(None) == ""
    assert _norm_owner("") == ""


def test_norm_owner_compares_equivalent():
    """Names with different punctuation/spacing should compare equal after normalization."""
    a = _norm_owner("Smith, John D.")
    b = _norm_owner("SMITH JOHN D")
    assert a == b

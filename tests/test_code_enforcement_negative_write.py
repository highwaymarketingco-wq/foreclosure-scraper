"""enrichment_code_enforcement.py's _clear_stale_block used to only POP a prior positive
block, never writing anything for a clean "the city answered, no case here" result --
invisible to gap_matrix.py's own "row"-scope contract ("checked when the row carries the
value OR a negative-result wrapper"). Fixed 2026-10-16 to write a dated negative wrapper.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_code_enforcement import _SOURCE_TAG, _clear_stale_block
from foreclosure_scraper.models import Listing


def _li(raw=None):
    return Listing(source="test", source_url="https://example.test/x", state="NC",
                   county="Mecklenburg", city="Charlotte", raw=raw or {})


def test_a_clean_negative_writes_a_dated_wrapper_not_just_a_pop():
    li = _li()
    counts = {}
    _clear_stale_block(li, counts)
    ce = li.raw["code_enforcement"]
    assert ce["has_open"] is False and ce["source"] == _SOURCE_TAG
    assert "stamped_at" in ce and "stale_after" in ce
    assert counts["cleared"] == 1


def test_a_stale_positive_block_from_this_enricher_is_overwritten_with_a_negative():
    li = _li(raw={"code_enforcement": {"has_open": True, "source": _SOURCE_TAG}})
    _clear_stale_block(li, {})
    assert li.raw["code_enforcement"]["has_open"] is False


def test_a_block_from_a_different_producer_is_left_untouched():
    other = {"has_open": True, "source": "gastonia_cityview_locator"}
    li = _li(raw={"code_enforcement": dict(other)})
    counts = {}
    _clear_stale_block(li, counts)
    assert li.raw["code_enforcement"] == other
    assert "cleared" not in counts

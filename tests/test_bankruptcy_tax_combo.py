"""Tests for enrichment_bankruptcy_tax_combo — the bankruptcy + large
delinquent-tax-balance join (Dirty Deeds Tier B #28, second half).

Pure join over two signals already on the listing: raw['bankruptcy']
(enrichment_bankruptcy.py) and raw['tax_owed'] (enrichment_tax_owed.py).
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_bankruptcy_tax_combo import (
    LARGE_TAX_BALANCE_THRESHOLD,
    enrich_bankruptcy_tax_combo,
)
from foreclosure_scraper.models import Listing, ListingType


def _li(raw):
    return Listing(source="counties_generic.some_tax_source", source_url="u",
                   listing_type=ListingType.TAX_LIEN, defendant="Owner, Some", raw=raw)


def test_combo_flags_when_both_signals_present():
    li = _li({
        "bankruptcy": {"chapter": "13", "date_filed": "2026-07-10",
                        "case_age_days": 81, "case_age_years": 0.2, "is_long_open": False},
        "tax_owed": {"balance": 654.51, "kind": "delinquent_tax", "year": 2025},
    })
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 1
    combo = li.raw["bankruptcy_tax_combo"]
    assert combo["tax_owed_balance"] == 654.51
    assert combo["bankruptcy_chapter"] == "13"
    assert combo["large_balance"] is False


def test_combo_large_balance_flag():
    li = _li({
        "bankruptcy": {"chapter": "7", "date_filed": "2026-01-01"},
        "tax_owed": {"balance": LARGE_TAX_BALANCE_THRESHOLD + 1, "kind": "delinquent_tax"},
    })
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 1
    assert stats["combo_large"] == 1
    assert li.raw["bankruptcy_tax_combo"]["large_balance"] is True


def test_combo_carries_long_open_flag_through():
    li = _li({
        "bankruptcy": {"chapter": "13", "date_filed": "2011-01-01",
                        "is_long_open": True, "case_age_years": 15.7},
        "tax_owed": {"balance": 5000.0},
    })
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo_long_open"] == 1
    assert li.raw["bankruptcy_tax_combo"]["is_long_open"] is True


def test_no_combo_when_bankruptcy_missing():
    li = _li({"tax_owed": {"balance": 5000.0}})
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 0
    assert "bankruptcy_tax_combo" not in li.raw


def test_no_combo_when_tax_owed_missing():
    li = _li({"bankruptcy": {"chapter": "7", "date_filed": "2026-01-01"}})
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 0
    assert "bankruptcy_tax_combo" not in li.raw


def test_no_combo_when_tax_owed_balance_zero_or_missing():
    li = _li({
        "bankruptcy": {"chapter": "7", "date_filed": "2026-01-01"},
        "tax_owed": {"balance": 0},
    })
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 0


def test_no_combo_when_bankruptcy_has_no_date_filed():
    """A malformed/partial bankruptcy block (no date_filed) shouldn't fire the combo --
    nothing to compute an age from, and the synthesis's signal is a dated filing."""
    li = _li({
        "bankruptcy": {"chapter": "7"},
        "tax_owed": {"balance": 5000.0},
    })
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 0


def test_combo_skips_listing_with_no_raw():
    li = Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN)
    stats = enrich_bankruptcy_tax_combo([li])
    assert stats["combo"] == 0


def test_a_carried_combo_is_cleared_when_its_tax_block_is_gone():
    """The combo used to be set-only: one carried from an earlier run outlived the tax block it
    restated once tax_binding scrubbed it or a county check ended it (audit 2026-10-09)."""
    old = {"tax_owed_balance": 900.0, "bankruptcy_chapter": "13"}
    bk = {"chapter": "13", "date_filed": "2026-07-10"}
    scrubbed = _li({"bankruptcy": bk, "bankruptcy_tax_combo": dict(old)})
    paid = _li({"bankruptcy": bk, "tax_owed": {"balance": 0}, "bankruptcy_tax_combo": dict(old)})
    no_bk = _li({"tax_owed": {"balance": 900.0}, "bankruptcy_tax_combo": dict(old)})
    moved = _li({"bankruptcy": bk, "tax_owed": {"balance": 450.0}, "bankruptcy_tax_combo": dict(old)})
    stats = enrich_bankruptcy_tax_combo([scrubbed, paid, no_bk, moved])
    assert stats["cleared"] == 3 and stats["combo"] == 1
    for li in (scrubbed, paid, no_bk):
        assert "bankruptcy_tax_combo" not in li.raw
    assert moved.raw["bankruptcy_tax_combo"]["tax_owed_balance"] == 450.0


def test_combo_is_idempotent():
    li = _li({"bankruptcy": {"chapter": "7", "date_filed": "2026-01-01"},
              "tax_owed": {"balance": 1234.5, "kind": "delinquent_tax"}})
    enrich_bankruptcy_tax_combo([li])
    first = dict(li.raw["bankruptcy_tax_combo"])
    enrich_bankruptcy_tax_combo([li])
    assert li.raw["bankruptcy_tax_combo"] == first

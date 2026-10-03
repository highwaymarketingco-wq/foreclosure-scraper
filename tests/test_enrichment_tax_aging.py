"""Tests for enrichment_tax_aging — surfacing raw['tax_owed']/raw['nc_ptscloud_
delinquent_tax'] into the two canonical fields fullmer_rank.py and
enrichment_equity.py actually read: raw['tax_aging_surfaced'] and
raw['tax_aging_high'].

This replaces the one-shot scripts/surface_tax_aging.py as the real pipeline
source of these fields — see the module docstring for the 2026-10-03 staleness
finding (11/148 counties credited vs. 49 counties' worth of real
raw['tax_owed']['year'] already on the board) and the separate RAW_KEEP gap on
raw['tax_aging_high'] (never registered, so always silently dropped at
publish).
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging
from foreclosure_scraper.fullmer_rank import years_delinquent
from foreclosure_scraper.models import Listing, ListingType

CURRENT_YEAR = date.today().year


def _li(raw):
    return Listing(source="counties_generic.some_tax_source", source_url="u",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Henderson", raw=raw)


def test_ptscloud_source_surfaces_tax_aging():
    tax_year = CURRENT_YEAR - 3
    li = _li({"nc_ptscloud_delinquent_tax": {"tax_year": tax_year, "principal_tax_due": 1200}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 1
    assert stats["by_source"]["nc_ptscloud"] == 1
    surf = li.raw["tax_aging_surfaced"]
    assert surf["source"] == "nc_ptscloud"
    assert surf["tax_year"] == tax_year
    assert surf["years_delinquent"] == 3
    assert li.raw["tax_aging_high"] is True


def test_tax_owed_year_fallback_surfaces_tax_aging():
    """The broad case: enrich_tax_owed() already ran this cycle and wrote a
    real year — this must now be picked up instead of only the narrow
    NC-PTS-Cloud path, closing the 2026-10-03 staleness gap."""
    tax_year = CURRENT_YEAR - 1
    li = _li({"tax_owed": {"balance": 611.79, "kind": "delinquent_tax",
                            "source": "x", "year": tax_year, "basis": "own_record"}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 1
    assert stats["by_source"]["tax_owed"] == 1
    surf = li.raw["tax_aging_surfaced"]
    assert surf["source"] == "tax_owed"
    assert surf["years_delinquent"] == 1
    assert li.raw["tax_aging_high"] is False  # only 1 year — not yet "high"


def test_tax_owed_explicit_years_delinquent_preferred_over_year_subtraction():
    """raw['tax_owed']['years_delinquent'] (promoted from a sibling multi-year
    block by enrich_tax_owed) is a direct count stated by the source — more
    authoritative than subtracting the earliest delinquent year, so it must
    win even when a `year` is also present."""
    li = _li({"tax_owed": {"balance": 900.0, "kind": "delinquent_tax",
                            "year": CURRENT_YEAR - 1, "years_delinquent": 5}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 1
    surf = li.raw["tax_aging_surfaced"]
    assert surf["years_delinquent"] == 5
    assert li.raw["tax_aging_high"] is True


def test_ptscloud_takes_priority_over_tax_owed_when_both_present():
    li = _li({
        "nc_ptscloud_delinquent_tax": {"tax_year": CURRENT_YEAR - 4},
        "tax_owed": {"balance": 50.0, "year": CURRENT_YEAR - 1},
    })
    enrich_tax_aging([li])
    assert li.raw["tax_aging_surfaced"]["source"] == "nc_ptscloud"
    assert li.raw["tax_aging_surfaced"]["years_delinquent"] == 4


def test_no_real_source_leaves_listing_untouched():
    li = _li({"some_other_block": {"foo": "bar"}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 0
    assert "tax_aging_surfaced" not in li.raw
    assert "tax_aging_high" not in li.raw


def test_no_real_source_does_not_clobber_existing_default_stamp():
    """A pre-existing 'default' placeholder (from the old one-shot script) is
    neither trusted nor erased when this run finds nothing real — no
    fabricated negative case, and nothing to roll back either."""
    li = _li({"tax_aging_surfaced": {"tax_year": None, "years_delinquent": 0,
                                      "status": "current", "source": "default"}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 0
    assert li.raw["tax_aging_surfaced"]["source"] == "default"


def test_stale_default_stamp_is_overwritten_once_real_data_appears():
    """The actual bug this fixes: a row stuck with the old stale 'default'
    stamp gets a real one once raw['tax_owed'] carries a real year — this is
    exactly the 38,963-row/48-county gap measured 2026-10-03."""
    li = _li({
        "tax_aging_surfaced": {"tax_year": None, "years_delinquent": 0,
                                "status": "current", "source": "default"},
        "tax_owed": {"balance": 300.0, "year": CURRENT_YEAR - 2},
    })
    enrich_tax_aging([li])
    surf = li.raw["tax_aging_surfaced"]
    assert surf["source"] == "tax_owed"
    assert surf["years_delinquent"] == 2


def test_out_of_range_year_is_rejected_not_fabricated():
    li = _li({"tax_owed": {"balance": 100.0, "year": 1850}})
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 0
    assert "tax_aging_surfaced" not in li.raw


def test_non_dict_raw_is_skipped_without_raising():
    li = _li({})
    li.raw = None
    stats = enrich_tax_aging([li])
    assert stats["surfaced"] == 0


def test_fullmer_rank_years_delinquent_reads_the_surfaced_real_value():
    """End-to-end: once this enricher surfaces a real value, fullmer_rank.py's
    own reader (which distrusts 'default') must see it as real."""
    tax_year = CURRENT_YEAR - 2
    li = _li({"tax_owed": {"balance": 500.0, "year": tax_year}})
    enrich_tax_aging([li])
    yrs, two_plus = years_delinquent(li)
    assert yrs == 2
    assert two_plus is True


def test_fullmer_rank_years_delinquent_still_rejects_untouched_default():
    li = _li({"tax_aging_surfaced": {"tax_year": None, "years_delinquent": 0,
                                      "status": "current", "source": "default"}})
    yrs, two_plus = years_delinquent(li)
    assert yrs is None
    assert two_plus is False

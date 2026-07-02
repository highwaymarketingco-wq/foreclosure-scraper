"""Unit tests for the corroboration / court-confirmation flag.

Each lead's full source set = primary li.source + every {source,url} in
raw['also_seen_in']. enrich_corroboration classifies those slugs into tiers
(court > government > aggregator > other) and stamps raw['corroboration'] with a
court_confirmed flag so the operator can tell a court-filed distress from one
only flagged by a single MLS/aggregator (realtor.com etc.).
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_corroboration import (
    enrich_corroboration,
    _classify_slug,
)
from foreclosure_scraper.models import Listing


def _mk(source: str, also_seen_in=None, **kw) -> Listing:
    raw = dict(kw.pop("raw", {}) or {})
    if also_seen_in is not None:
        raw["also_seen_in"] = also_seen_in
    return Listing(source=source, source_url=f"https://example.test/{source}", raw=raw, **kw)


def test_a_homeharvest_only_lead_is_unconfirmed_aggregator():
    li = _mk("national.homeharvest")
    stats = enrich_corroboration([li])
    corr = li.raw["corroboration"]
    assert corr["court_confirmed"] is False
    assert corr["tier"] == "aggregator"
    assert corr["multi_source"] is False
    assert corr["source_count"] == 1
    assert corr["sources"] == ["national.homeharvest"]
    assert "unconfirmed" in corr["label"].lower()
    assert stats["aggregator_only"] == 1
    assert stats["court_confirmed"] == 0
    assert stats["multi_source"] == 0


def test_aggregator_plus_public_index_is_court_confirmed_multi_source():
    li = _mk(
        "national.homeharvest",
        also_seen_in=[
            {"source": "counties_sc.sc_public_index_lis_pendens",
             "url": "https://publicindex.example/case/1"},
        ],
    )
    enrich_corroboration([li])
    corr = li.raw["corroboration"]
    assert corr["court_confirmed"] is True
    assert corr["tier"] == "court"
    assert corr["multi_source"] is True
    assert corr["source_count"] == 2
    assert corr["sources"] == [
        "counties_sc.sc_public_index_lis_pendens",
        "national.homeharvest",
    ]
    assert corr["label"].startswith("Court-confirmed")


def test_tax_sale_lead_is_government_tier():
    li = _mk("counties_sc.colleton_tax_sale")
    enrich_corroboration([li])
    corr = li.raw["corroboration"]
    assert corr["tier"] == "government"
    assert corr["court_confirmed"] is False
    assert corr["label"].startswith("Gov record")


def test_stats_rollup_across_a_mixed_board():
    board = [
        _mk("national.homeharvest"),                       # aggregator-only
        _mk("national.realtor_foreclosures"),              # aggregator-only
        _mk("counties_sc.spartanburg_delinquent_tax"),     # government
        _mk("law_firms.brock_scott"),                      # court
        _mk("national.zillow_foreclosures",
            also_seen_in=[{"source": "counties_sc.anderson_master_in_equity",
                           "url": "https://mie.example/1"}]),  # court, multi
    ]
    stats = enrich_corroboration(board)
    assert stats["tagged"] == 5
    assert stats["court_confirmed"] == 2
    assert stats["government"] == 1
    assert stats["aggregator_only"] == 2
    assert stats["multi_source"] == 1


def test_classify_slug_tiers():
    assert _classify_slug("counties_sc.sc_public_index_lis_pendens") == "court"
    assert _classify_slug("law_firms.brock_scott") == "court"
    assert _classify_slug("counties_sc.pickens_master_in_equity") == "court"
    assert _classify_slug("counties_nc.nc_rod_logan") == "court"
    assert _classify_slug("counties_sc.colleton_tax_sale") == "government"
    assert _classify_slug("counties_sc.sc_probate_net") == "government"
    assert _classify_slug("national.homeharvest") == "aggregator"
    assert _classify_slug("national.hubzu") == "aggregator"
    assert _classify_slug("reo.vrm_va_reo") == "aggregator"
    assert _classify_slug("some.brand_new_unknown_source") == "other"
    assert _classify_slug("") == "other"


def test_dupe_and_falsy_sources_are_dropped():
    li = _mk(
        "national.homeharvest",
        also_seen_in=[
            {"source": "national.homeharvest", "url": "https://dup.example/1"},  # dup slug
            {"source": None, "url": "https://noslug.example/1"},                 # falsy
            {"url": "https://noslug.example/2"},                                 # missing key
        ],
    )
    enrich_corroboration([li])
    corr = li.raw["corroboration"]
    assert corr["source_count"] == 1
    assert corr["sources"] == ["national.homeharvest"]
    assert corr["multi_source"] is False

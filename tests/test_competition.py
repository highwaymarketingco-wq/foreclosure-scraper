"""Unit tests for the publication-reach / competition tag.

A widely-published trustee sale list (Hutchens et al.) draws many bidders → HIGH
competition. A lone quiet off-market signal (tax-delinquent / code-enforcement /
probate with no other source) is one nobody else is watching → LOW competition.
Everything else is MEDIUM. The tag is transparent and never changes a grade.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_competition import (
    enrich_competition,
    _classify,
    _is_widely_published,
    REASON_WIDELY_PUBLISHED,
    REASON_QUIET_SINGLE_SOURCE,
    REASON_MODERATE,
    WIDELY_PUBLISHED_SOURCES,
)
from foreclosure_scraper.models import Listing


def _mk(source: str, also_seen_in=None, **kw) -> Listing:
    raw = dict(kw.pop("raw", {}) or {})
    if also_seen_in is not None:
        raw["also_seen_in"] = also_seen_in
    return Listing(source=source, source_url=f"https://example.test/{source}", raw=raw, **kw)


def test_hutchens_lead_is_high_competition():
    li = _mk("law_firms.hutchens")
    stats = enrich_competition([li])
    comp = li.raw["competition"]
    assert comp["level"] == "high"
    assert comp["reason"] == REASON_WIDELY_PUBLISHED
    assert comp["widely_published"] is True
    assert comp["sources"] == ["law_firms.hutchens"]
    assert stats["high"] == 1
    assert stats["widely_published"] == 1


def test_lone_tax_delinquent_is_low_competition():
    li = _mk("counties_sc.spartanburg_delinquent_tax")
    enrich_competition([li])
    comp = li.raw["competition"]
    assert comp["level"] == "low"
    assert comp["reason"] == REASON_QUIET_SINGLE_SOURCE
    assert comp["widely_published"] is False


def test_lone_probate_and_code_enforcement_are_low():
    for src in ("counties_nc.some_probate_notice", "counties_nc.asheville_code_enforcement"):
        li = _mk(src)
        enrich_competition([li])
        assert li.raw["competition"]["level"] == "low"


def test_quiet_signal_with_second_source_is_not_low():
    # A tax-delinquent lead ALSO corroborated by a court filing is no longer a
    # single quiet signal — it's medium (still not on a widely-published roster).
    li = _mk(
        "counties_sc.spartanburg_delinquent_tax",
        also_seen_in=[{"source": "counties_sc.spartanburg_master_in_equity",
                       "url": "https://mie.example/1"}],
    )
    enrich_competition([li])
    comp = li.raw["competition"]
    assert comp["level"] == "medium"
    assert comp["reason"] == REASON_MODERATE
    assert comp["widely_published"] is False
    assert comp["sources"] == [
        "counties_sc.spartanburg_delinquent_tax",
        "counties_sc.spartanburg_master_in_equity",
    ]


def test_widely_published_via_also_seen_in_wins():
    # Primary is an aggregator, but the property is ALSO on Brock & Scott's
    # published roster → high competition (the reach comes from any source).
    li = _mk(
        "national.homeharvest",
        also_seen_in=[{"source": "law_firms.brock_scott", "url": "https://bs.example/1"}],
    )
    enrich_competition([li])
    comp = li.raw["competition"]
    assert comp["level"] == "high"
    assert comp["widely_published"] is True


def test_non_quiet_single_source_is_medium():
    # A single court filing that isn't on a big published roster is medium, not
    # low (it's a public legal notice, not an unseen off-market parcel).
    li = _mk("counties_nc.nc_ecourts_lis_pendens")
    enrich_competition([li])
    assert li.raw["competition"]["level"] == "medium"


def test_stats_rollup_across_mixed_board():
    board = [
        _mk("law_firms.hutchens"),                         # high
        _mk("law_firms.shapiro_ingle_powerbi"),            # high
        _mk("counties_sc.oconee_delinquent_tax"),          # low
        _mk("counties_nc.some_probate_notice"),            # low
        _mk("national.homeharvest"),                       # medium (aggregator, not quiet)
    ]
    stats = enrich_competition(board)
    assert stats["tagged"] == 5
    assert stats["high"] == 2
    assert stats["low"] == 2
    assert stats["medium"] == 1
    assert stats["widely_published"] == 2


def test_is_widely_published_matches_every_named_firm():
    for frag in WIDELY_PUBLISHED_SOURCES:
        assert _is_widely_published(f"law_firms.{frag}") is True
    assert _is_widely_published("law_firms.ingle_firm") is False  # not shapiro_ingle
    assert _is_widely_published("national.homeharvest") is False
    assert _is_widely_published("") is False


def test_classify_helper_is_pure():
    assert _classify(["law_firms.hutchens"]) == ("high", REASON_WIDELY_PUBLISHED, True)
    assert _classify(["counties_sc.x_delinquent_tax"]) == ("low", REASON_QUIET_SINGLE_SOURCE, False)
    assert _classify(["national.homeharvest"]) == ("medium", REASON_MODERATE, False)


def test_no_sources_is_skipped():
    li = _mk("")  # empty primary slug, no also_seen_in
    stats = enrich_competition([li])
    assert stats["tagged"] == 0
    assert "competition" not in li.raw

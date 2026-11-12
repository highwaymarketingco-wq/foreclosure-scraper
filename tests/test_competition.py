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


# NOTE: to stay under git's 100 MB file limit, only 'high' leads carry the tag,
# and the tag is minimal {level, reason} (no 'sources'/'widely_published' fields —
# they're recoverable from raw['also_seen_in'] + the WIDELY_PUBLISHED_SOURCES set).
# medium/low are counted in stats but NOT stamped, so "no tag" == "not high".

def test_hutchens_lead_is_high_competition():
    li = _mk("law_firms.hutchens")
    stats = enrich_competition([li])
    comp = li.raw["competition"]
    assert comp["level"] == "high"
    assert comp["reason"] == REASON_WIDELY_PUBLISHED
    assert stats["high"] == 1
    assert stats["widely_published"] == 1
    assert stats["tagged"] == 1  # only the high lead is stamped


def test_lone_tax_delinquent_is_low_and_untagged():
    li = _mk("counties_sc.spartanburg_delinquent_tax")
    stats = enrich_competition([li])
    assert "competition" not in li.raw          # low is not stamped (size)
    assert stats["low"] == 1 and stats["tagged"] == 0


def test_lone_probate_and_code_enforcement_are_low_untagged():
    for src in ("counties_nc.some_probate_notice", "counties_nc.asheville_code_enforcement"):
        li = _mk(src)
        stats = enrich_competition([li])
        assert "competition" not in li.raw
        assert stats["low"] == 1


def test_quiet_signal_with_second_source_is_medium_untagged():
    # tax-delinquent + a corroborating court filing = medium (not a lone quiet
    # signal, but not a widely-published roster). Medium is counted, not stamped.
    li = _mk(
        "counties_sc.spartanburg_delinquent_tax",
        also_seen_in=[{"source": "counties_sc.spartanburg_master_in_equity",
                       "url": "https://mie.example/1"}],
    )
    stats = enrich_competition([li])
    assert "competition" not in li.raw
    assert stats["medium"] == 1


def test_widely_published_via_also_seen_in_wins():
    # Primary is an aggregator, but the property is ALSO on Brock & Scott's
    # published roster → high competition (reach comes from any source) → tagged.
    li = _mk(
        "national.homeharvest",
        also_seen_in=[{"source": "law_firms.brock_scott", "url": "https://bs.example/1"}],
    )
    stats = enrich_competition([li])
    assert li.raw["competition"]["level"] == "high"
    assert stats["widely_published"] == 1


def test_non_quiet_single_source_is_medium_untagged():
    li = _mk("counties_nc.nc_ecourts_lis_pendens")
    stats = enrich_competition([li])
    assert "competition" not in li.raw
    assert stats["medium"] == 1


def test_stats_rollup_across_mixed_board():
    board = [
        _mk("law_firms.hutchens"),                         # high  -> tagged
        _mk("law_firms.shapiro_ingle_powerbi"),            # high  -> tagged
        _mk("counties_sc.oconee_delinquent_tax"),          # low
        _mk("counties_nc.some_probate_notice"),            # low
        _mk("national.homeharvest"),                       # medium (aggregator, not quiet)
    ]
    stats = enrich_competition(board)
    assert stats["tagged"] == 2  # only the 2 high leads carry the tag
    assert stats["high"] == 2
    assert stats["low"] == 2
    assert stats["medium"] == 1
    assert stats["widely_published"] == 2
    assert sum(1 for li in board if "competition" in li.raw) == 2


def test_stale_full_shape_tag_is_cleared_for_non_high():
    # A lead re-tagged from high->low (or carrying an old full-shape tag) must not
    # keep a stale competition tag.
    li = _mk("counties_sc.oconee_delinquent_tax")
    li.raw["competition"] = {"level": "high", "reason": "x", "sources": ["a"]}  # stale
    enrich_competition([li])
    assert "competition" not in li.raw


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

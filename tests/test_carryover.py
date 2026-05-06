"""Pin the last-known-good carryover backstop.

The Run #14 incident showed that a single-run failure can lose hours of
data + spend. The carryover module replays last week's listings for any
source that produced ≥3 listings last week but 0 this week. This test
suite pins the policy: when carryover applies, when it doesn't, and how
the prior data is marked stale so investors can tell.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper.carryover import (
    MAX_CARRYOVER_AGE_DAYS,
    MIN_PRIOR_FOR_CARRYOVER,
    carryover_for_zeroed_sources,
)


def _write_prior(tmp_path: Path, listings: list[dict], run_age_days: int = 7) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json").write_text(json.dumps(listings))
    run_ts = datetime.now(timezone.utc) - timedelta(days=run_age_days)
    (docs / "run_meta.json").write_text(json.dumps({
        "run_time": run_ts.isoformat().replace("+00:00", "Z"),
    }))
    return docs


def _mk(slug: str, **over) -> dict:
    """Build a dict that round-trips through Listing.model_validate."""
    base = {
        "source": slug,
        "source_url": f"https://example.com/{slug}/1",
        "state": "NC",
        "county": "Wake",
        "raw": {"foo": "bar"},
    }
    base.update(over)
    return base


def test_carryover_when_source_zeroed_and_prior_had_data(tmp_path):
    """A source that had 5 listings last week and 0 this week should
    have those 5 replayed, tagged stale=True."""
    prior = [_mk("counties_nc.wake_tax", source_url=f"https://x/{i}") for i in range(5)]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        skip_slugs=set(),
        docs_dir=docs,
    )
    assert len(carried) == 5
    assert stats == {"counties_nc.wake_tax": 5}
    for li in carried:
        assert li.raw["carryover"]["stale"] is True
        assert li.raw["carryover"]["from_run"]
        assert li.raw["carryover"]["reason"]


def test_no_carryover_when_source_has_fresh_data(tmp_path):
    """If the source produced at least 1 listing this run, don't carry
    forward — fresh data wins."""
    prior = [_mk("counties_nc.wake_tax") for _ in range(5)]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 2},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    assert carried == []
    assert stats == {}


def test_no_carryover_when_prior_under_threshold(tmp_path):
    """A single-listing prior run isn't reliable enough to replay — it
    might have been spurious. Need MIN_PRIOR_FOR_CARRYOVER to fire."""
    assert MIN_PRIOR_FOR_CARRYOVER >= 2  # sanity
    prior = [_mk("counties_nc.wake_tax")
             for _ in range(MIN_PRIOR_FOR_CARRYOVER - 1)]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    assert carried == []


def test_no_carryover_for_blocked_source(tmp_path):
    """If a source is paywall/render/apify-blocked, its zero is acknowledged
    failure mode, not a regression. Don't carry forward."""
    prior = [_mk("national.foreclosure_dot_com") for _ in range(10)]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"national.foreclosure_dot_com": 0},
        expected_min={"national.foreclosure_dot_com": 1},
        skip_slugs={"national.foreclosure_dot_com"},
        docs_dir=docs,
    )
    assert carried == []


def test_no_carryover_when_expected_zero(tmp_path):
    """A source whose expected_min_count is 0 (acknowledged-empty) shouldn't
    have its prior data replayed if this run's also zero — that's normal."""
    prior = [_mk("counties_nc.empty_source") for _ in range(10)]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.empty_source": 0},
        expected_min={"counties_nc.empty_source": 0},
        docs_dir=docs,
    )
    assert carried == []


def test_no_carryover_when_prior_too_old(tmp_path):
    """Don't replay month-stale data — better to show blank than ancient."""
    prior = [_mk("counties_nc.wake_tax") for _ in range(5)]
    docs = _write_prior(
        tmp_path, prior, run_age_days=MAX_CARRYOVER_AGE_DAYS + 1,
    )

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    assert carried == []


def test_no_carryover_when_no_prior_listings(tmp_path):
    """First-ever run: no docs/listings.json exists. Don't crash."""
    docs = tmp_path / "docs"
    docs.mkdir()
    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    assert carried == []
    assert stats == {}


def test_carryover_handles_malformed_prior_listings_json(tmp_path):
    """If prior listings.json is corrupt, don't crash — return empty."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json").write_text("{ not valid json }}}")
    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    assert carried == []


def test_carryover_skips_unparseable_listing_records(tmp_path):
    """A single bad record (missing required field) shouldn't tank the
    whole carryover for that source."""
    prior = [
        _mk("counties_nc.wake_tax"),                  # good
        {"source": "counties_nc.wake_tax"},           # missing source_url, will fail
        _mk("counties_nc.wake_tax"),                  # good
        _mk("counties_nc.wake_tax"),                  # good
    ]
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={"counties_nc.wake_tax": 0},
        expected_min={"counties_nc.wake_tax": 1},
        docs_dir=docs,
    )
    # 3 good records, 1 dropped silently
    assert len(carried) == 3


def test_multiple_sources_carryover_independently(tmp_path):
    """Some sources zero, others fresh — only zeroed ones carry over."""
    prior = (
        [_mk("counties_nc.wake_tax", source_url=f"https://w/{i}") for i in range(5)]
        + [_mk("counties_nc.forsyth_tax", source_url=f"https://f/{i}") for i in range(4)]
        + [_mk("counties_nc.guilford_tax", source_url=f"https://g/{i}") for i in range(3)]
    )
    docs = _write_prior(tmp_path, prior)

    carried, stats = carryover_for_zeroed_sources(
        by_source_now={
            "counties_nc.wake_tax": 0,        # zeroed → carryover
            "counties_nc.forsyth_tax": 6,     # fresh → no carryover
            "counties_nc.guilford_tax": 0,    # zeroed → carryover
        },
        expected_min={
            "counties_nc.wake_tax": 1,
            "counties_nc.forsyth_tax": 1,
            "counties_nc.guilford_tax": 1,
        },
        docs_dir=docs,
    )
    assert stats == {
        "counties_nc.wake_tax": 5,
        "counties_nc.guilford_tax": 3,
    }
    sources = {li.source for li in carried}
    assert sources == {"counties_nc.wake_tax", "counties_nc.guilford_tax"}


def test_carryover_severity_is_attention_grabbing():
    """Carryover should rank above blocked-but-OK in run_health, so on-call
    actually sees it. Below REGRESSED so we don't drown in noise when
    carryover succeeded at backfilling."""
    from foreclosure_scraper.run_health import _severity
    assert _severity("CARRYOVER (5 stale from prior run)") == 2
    assert _severity("REGRESSED (expected ≥ 3)") == 3
    assert _severity("PAYWALL-BLOCKED") == 1
    assert _severity("OK (12)") == 0

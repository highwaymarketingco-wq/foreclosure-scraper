"""Pin the pulled-sale tracker (dad's note #6).

NC + SC trustees pull ~half of all foreclosure sales before they
auction. Without this tracker, those listings silently vanish between
weekly runs. The tracker:
  - Identifies listings present last week, absent this week
  - Tags them raw['pulled_sale'] = {presumed_withdrawn: True, ...}
  - Keeps them on the dashboard for PULLED_RETENTION_WEEKS (4) before
    dropping entirely
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper.enrichment_pulled_sales import (
    PULLED_RETENTION_WEEKS,
    enrich_with_pulled_sales,
)
from foreclosure_scraper.models import Listing, ListingType


def _li(**kw) -> Listing:
    base = dict(
        source="law_firms.brock_scott",
        source_url="https://brockandscott.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime(2026, 4, 1),
        last_seen=datetime(2026, 5, 1),
    )
    base.update(kw)
    return Listing(**base)


def _write_previous(tmp_path: Path, listings: list[Listing]) -> Path:
    """Dump listings to a temp listings.json (mimics docs/listings.json)."""
    path = tmp_path / "listings.json"
    data = [li.model_dump(mode="json") for li in listings]
    path.write_text(json.dumps(data))
    return path


# ---- core behavior ----

def test_no_previous_file_returns_current_unchanged(tmp_path):
    """First-ever run has no prior data — current passes through unchanged."""
    current = [_li(street_address="123 Main St", zip_code="28801")]
    missing_path = tmp_path / "nonexistent.json"
    out, stats = enrich_with_pulled_sales(current, previous_path=missing_path)
    assert len(out) == 1
    assert stats["previous_count"] == 0
    assert stats["tagged_new_misses"] == 0


def test_listing_present_in_both_runs_no_tag(tmp_path):
    """Property still in current run → not tagged as pulled."""
    li_prev = _li(street_address="123 Main St", zip_code="28801")
    li_cur = _li(street_address="123 Main St", zip_code="28801")
    path = _write_previous(tmp_path, [li_prev])
    out, stats = enrich_with_pulled_sales([li_cur], previous_path=path)
    assert len(out) == 1
    assert "pulled_sale" not in (out[0].raw or {})
    assert stats["tagged_new_misses"] == 0


def test_listing_missing_from_current_tagged_pulled(tmp_path):
    """Property gone this run → tagged presumed_withdrawn, kept on dashboard."""
    li_prev = _li(
        street_address="456 Oak Ave",
        zip_code="28805",
        case_number="24 SP 123",
        county="Buncombe",
        state="NC",
    )
    path = _write_previous(tmp_path, [li_prev])
    out, stats = enrich_with_pulled_sales([], previous_path=path)
    assert len(out) == 1
    pulled = out[0].raw["pulled_sale"]
    assert pulled["presumed_withdrawn"] is True
    assert pulled["consecutive_misses"] == 1
    assert out[0].auction_status == "presumed_withdrawn"
    assert stats["tagged_new_misses"] == 1


def test_consecutive_misses_increment(tmp_path):
    """A property already at consecutive_misses=2 last week → 3 this week."""
    now = datetime(2026, 5, 12)
    li_prev = _li(
        street_address="789 Pine Rd",
        zip_code="28806",
        case_number="24 SP 999",
        county="Buncombe",
        state="NC",
        raw={
            "pulled_sale": {
                "first_missed_at": "2026-04-28T00:00:00Z",
                "consecutive_misses": 2,
                "presumed_withdrawn": True,
            }
        },
    )
    path = _write_previous(tmp_path, [li_prev])
    out, stats = enrich_with_pulled_sales([], previous_path=path, now=now)
    assert len(out) == 1
    pulled = out[0].raw["pulled_sale"]
    assert pulled["consecutive_misses"] == 3
    assert pulled["first_missed_at"] == "2026-04-28T00:00:00Z"  # preserved
    assert stats["tagged_repeat_misses"] == 1


def test_past_retention_listing_dropped(tmp_path):
    """After PULLED_RETENTION_WEEKS, drop entirely."""
    li_prev = _li(
        street_address="999 Elm Way",
        zip_code="28701",
        case_number="23 SP 555",
        county="Polk",
        state="NC",
        raw={
            "pulled_sale": {
                "first_missed_at": "2026-03-01T00:00:00Z",
                "consecutive_misses": PULLED_RETENTION_WEEKS,  # at the cap
            }
        },
    )
    path = _write_previous(tmp_path, [li_prev])
    out, stats = enrich_with_pulled_sales([], previous_path=path)
    assert len(out) == 0  # dropped
    assert stats["dropped_past_retention"] == 1


def test_reappearance_resets_implicit(tmp_path):
    """A pulled listing that reappears doesn't get re-tagged — its
    dedupe_key matches the current run, so it falls through the
    'still present' branch and the tracker takes no action."""
    li_prev = _li(
        street_address="100 Cedar Ln",
        zip_code="28704",
        case_number="24 SP 777",
        county="Polk",
        state="NC",
        raw={
            "pulled_sale": {
                "first_missed_at": "2026-04-28T00:00:00Z",
                "consecutive_misses": 2,
            }
        },
    )
    li_cur = _li(
        street_address="100 Cedar Ln",
        zip_code="28704",
        case_number="24 SP 777",
        county="Polk",
        state="NC",
        # No pulled_sale tag — this is a fresh scrape
    )
    path = _write_previous(tmp_path, [li_prev])
    out, stats = enrich_with_pulled_sales([li_cur], previous_path=path)
    assert len(out) == 1
    # Current listing (without pulled tag) wins — pulled_sale absent
    assert "pulled_sale" not in (out[0].raw or {})
    assert stats["tagged_new_misses"] == 0


# ---- stats accuracy ----

def test_stats_track_all_categories(tmp_path):
    """Mix of: still-present, newly-missed, repeat-missed, past-retention."""
    still_prev = _li(street_address="1 A", zip_code="28801")
    still_cur = _li(street_address="1 A", zip_code="28801")

    new_miss = _li(street_address="2 B", zip_code="28802")

    repeat_miss = _li(
        street_address="3 C",
        zip_code="28803",
        raw={"pulled_sale": {"consecutive_misses": 2}},
    )

    expired = _li(
        street_address="4 D",
        zip_code="28804",
        raw={"pulled_sale": {"consecutive_misses": PULLED_RETENTION_WEEKS}},
    )

    path = _write_previous(tmp_path, [still_prev, new_miss, repeat_miss, expired])
    out, stats = enrich_with_pulled_sales([still_cur], previous_path=path)

    assert stats["previous_count"] == 4
    assert stats["current_count"] == 1
    assert stats["tagged_new_misses"] == 1  # B
    assert stats["tagged_repeat_misses"] == 1  # C
    assert stats["dropped_past_retention"] == 1  # D
    assert stats["kept_as_pulled"] == 2  # B + C
    assert len(out) == 3  # still + B + C  (D dropped)


def test_corrupt_previous_file_handled(tmp_path):
    """Bad JSON in the prior file shouldn't crash the run — empty
    previous treated like first-ever run."""
    path = tmp_path / "listings.json"
    path.write_text("not valid json {")
    current = [_li(street_address="1 A", zip_code="28801")]
    out, stats = enrich_with_pulled_sales(current, previous_path=path)
    assert len(out) == 1
    assert stats["previous_count"] == 0

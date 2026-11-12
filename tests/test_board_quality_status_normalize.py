"""auction_status normalization: "status:" label leaks + embedded newlines.

extraction_gaps.md queued this as a small clean fix: "auction_status
'status:'-prefix + newline leaks (25) -> strip in a normalizer". The module's
own docstring already measured real board rows with values like 'status:
active', 'status: active - outbid period', and this closes that class instead
of chasing which scraper(s) produced each one.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
from foreclosure_scraper.models import Listing, ListingType


def _li(auction_status: str | None) -> Listing:
    return Listing(
        source="test", source_url="http://x", parcel_id="P1",
        listing_type=ListingType.FORECLOSURE_SALE,
        auction_status=auction_status,
    )


def test_status_label_prefix_stripped():
    li = _li("status: active")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "active"


def test_status_label_prefix_stripped_no_colon():
    li = _li("Status Active")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "active"


def test_status_label_with_trailing_detail_stripped():
    li = _li("status: active - outbid period")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "active - outbid period"


def test_embedded_newline_collapsed():
    li = _li("active\nupset period")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "active upset period"
    assert "\n" not in li.auction_status


def test_status_prefix_plus_newline_together():
    li = _li("Status:\nActive")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "active"


def test_status_only_value_nulled_not_left_as_empty_label():
    li = _li("status:")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status is None


def test_already_clean_value_unaffected():
    li = _li("presumed_withdrawn")
    enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status == "presumed_withdrawn"


def test_none_unaffected():
    li = _li(None)
    stats = enrich_board_quality([li], today=date(2026, 1, 1))
    assert li.auction_status is None
    assert stats.get("status_normalized", 0) == 0

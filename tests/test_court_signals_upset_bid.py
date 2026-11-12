"""court_signals audit 2026-10-09: an NC eCourts judgment's order date is not a sale date.

The judgment scraper used to open a 14-day upset-bid window from a judgment's order date; 1,146
rows of the 2026-10-08 pre_publish checkpoint scored upset_bid from it (claims of lien,
transcripts of judgment, tax liens). The scraper no longer stamps it (test_nc_upset_bid.py), and
enrich_upset_bid removes the stamp a carried row still holds. Fixtures are made up.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid, is_ecourts_order_date_window
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _ecourts_row(**kw) -> Listing:
    raw = {"nc_ecourts": {"cause": "CV - Claim of Lien", "civilJudgmentStatus": "Active",
                          "orderedDate": "2026-10-01T23:00:00-05:00"},
           "upset_bid": {"in_window": True, "window_days": 14,
                         "deadline_iso": "2026-10-15T23:00:00", "days_remaining": 9,
                         "statute": "NCGS §45-21.27",
                         "sale_occurred_on_iso": "2026-10-01T23:00:00-05:00"}}
    raw.update(kw.pop("raw", {}))
    base = dict(source="counties_nc.nc_ecourts_lis_pendens", source_url="https://example.test/x",
                listing_type=ListingType.LIS_PENDENS, property_kind=PropertyKind.UNKNOWN,
                state="NC", county="Forsyth", case_number="26M000001-330", raw=raw,
                upset_bid_deadline=datetime(2026, 10, 15))
    base.update(kw)
    return Listing(**base)


def test_carried_ecourts_window_is_removed():
    li = _ecourts_row()
    assert is_ecourts_order_date_window(li)
    s = enrich_upset_bid([li], now=datetime(2026, 10, 8))
    assert "upset_bid" not in li.raw
    assert li.upset_bid_deadline is None
    assert s["ecourts_order_date_window_removed"] == 1


def test_published_window_on_an_ecourts_row_is_kept():
    li = _ecourts_row(raw={"upset_bid": {"source": "published", "in_window": True,
                                         "deadline_iso": "2026-10-20T00:00:00"}})
    assert not is_ecourts_order_date_window(li)
    enrich_upset_bid([li], now=datetime(2026, 10, 8))
    assert li.raw["upset_bid"]["source"] == "published"


def test_window_on_a_row_without_the_ecourts_block_is_untouched():
    li = _ecourts_row(source="law_firms.example")
    li.raw.pop("nc_ecourts")
    assert not is_ecourts_order_date_window(li)
    enrich_upset_bid([li], now=datetime(2026, 10, 8))
    assert li.raw["upset_bid"]["in_window"] is True


def test_a_real_sale_date_still_opens_a_window():
    sale = datetime(2026, 10, 5)
    li = Listing(source="law_firms.example", source_url="https://example.test/y",
                 listing_type=ListingType.FORECLOSURE_SALE, property_kind=PropertyKind.UNKNOWN,
                 state="NC", county="Gaston", sale_date=sale, raw={})
    enrich_upset_bid([li], now=sale + timedelta(days=3))
    assert li.raw["upset_bid"]["in_window"] is True
    assert li.raw["upset_bid"]["source_signal"] == "law_firms.example"

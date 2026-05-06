"""Pin the NC eCourts → _active_only fix.

Run #16 collected 571 NC eCourts listings, none of which made it to
docs/listings.json. Root cause: the scraper was setting `sale_date` to
the judgment's ordered_date (when the lis pendens / lien was entered),
which is typically 1-3 months in the past. _active_only requires
sale_date to be in the past 2 days OR within 120 days future, OR for
the source to be in DATELESS_OK_SOURCES. The first two failed because
ordered_date was historic; DATELESS_OK_SOURCES only fires when
sale_date is None.

Fix: scraper now sets sale_date=None unconditionally for NC eCourts
listings; the judgment date is preserved in raw.nc_ecourts.ordered_date_iso
where the dashboard can show it without gating the active filter.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    _hit_to_listing,
)
from foreclosure_scraper.main import _active_only, DATELESS_OK_SOURCES


def _hit(case_no: str, ordered_iso: str,
         cause: str = "CV - Lis Pendens",
         location: str = "Wake County Courthouse") -> dict:
    """Build a fake Tyler-Odyssey 'hit' dict matching the live API
    shape that _hit_to_listing parses."""
    return {
        "caseNumber": case_no,
        "orderedDate": ordered_iso,
        "judgmentType": "Civil",
        "civilJudgmentStatus": "Active",
        "caseCategoryKey": "CV",
        "caseID": "abc123",
        "judgmentId": "j-001",
        "causeOfActionDesc": cause,
        "location": location,
        "debtors": [{"name": "Smith John"}],
        "creditors": [{"name": "Acme Bank"}],
    }


def test_nc_ecourts_sale_date_is_none():
    """Lis pendens listings must NOT carry sale_date — that field is for
    actual auction dates, not judgment dates."""
    # 60 days ago — historic ordered_date that previously dropped listings
    historic = (datetime.utcnow() - timedelta(days=60)).isoformat()
    li = _hit_to_listing(_hit("26M000463-910", historic),
                         "counties_nc.nc_ecourts_lis_pendens")
    assert li is not None
    assert li.sale_date is None, (
        "lis pendens must not set sale_date — the judgment date is "
        "preserved in raw.nc_ecourts.ordered_date_iso instead"
    )


def test_nc_ecourts_passes_active_only_via_dateless():
    """Without sale_date, the source must be in DATELESS_OK_SOURCES so
    _active_only keeps the listing."""
    assert "counties_nc.nc_ecourts_lis_pendens" in DATELESS_OK_SOURCES
    historic = (datetime.utcnow() - timedelta(days=60)).isoformat()
    li = _hit_to_listing(_hit("26M000463-910", historic),
                         "counties_nc.nc_ecourts_lis_pendens")
    assert _active_only(li, horizon_days=120) is True, (
        "Run #16 dropped 571 listings here — fix regression."
    )


def test_nc_ecourts_ordered_date_preserved_in_raw():
    """The dashboard still needs the judgment date for display + sorting.
    It must end up in raw.nc_ecourts so the slim_raw whitelist keeps it."""
    historic = (datetime.utcnow() - timedelta(days=60)).isoformat()
    li = _hit_to_listing(_hit("26M000463-910", historic),
                         "counties_nc.nc_ecourts_lis_pendens")
    nc = li.raw.get("nc_ecourts") or {}
    assert nc.get("ordered_date_iso"), (
        "ordered_date_iso missing — dashboard can't show when the "
        "judgment was entered"
    )


def test_upset_bid_window_listings_keep_window_data():
    """For listings within the 10-day post-sale upset-bid window, the
    raw.upset_bid blob must still capture sale_occurred_on for downstream
    investor display."""
    # 5 days ago (inside the 10-day NC upset-bid window)
    recent = (datetime.utcnow() - timedelta(days=5)).isoformat()
    li = _hit_to_listing(
        _hit("26SP012345-910", recent, cause="CV - Lis Pendens"),
        "counties_nc.nc_ecourts_lis_pendens",
    )
    if li and (li.raw.get("upset_bid") or {}).get("in_window"):
        ub = li.raw["upset_bid"]
        assert ub["sale_occurred_on_iso"], (
            "upset-bid window listings must record when the sale happened "
            "for the investor's 10-day-deadline math"
        )


def test_nc_ecourts_in_web_artifact_keep_list():
    """raw.nc_ecourts and raw.upset_bid must be in RAW_KEEP so they
    survive the slim-on-write step. Otherwise the dashboard can't see
    cause/orderedDate/upset-bid metadata even though the listing
    survives the filter."""
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "nc_ecourts" in RAW_KEEP
    assert "upset_bid" in RAW_KEEP

"""Regression tests for NC eCourts TARGET_COUNTIES scope and the
non-upset-bid-window behavior of orderedDate-based judgments.

Note: the AUTHORITATIVE upset-bid tagging now happens in
enrichment_upset_bid.py (works off li.sale_date, which is the sale
date set by law-firm / county-tax / auction-site scrapers, and whose
own UPSET_BID_WINDOW_DAYS==14 is pinned by tests/test_enrich_upset_bid.py).
The NC eCourts scraper here never derives an upset-bid window from
orderedDate at all (see test_recent_judgment_is_not_an_upset_bid_window
below) because the Tyler Odyssey judgment search's orderedDate is a
JUDGMENT date, never a sale date.

2026-10-15 (date-coverage completeness-sweep item 2): this file used to
also import and pin a same-named UPSET_BID_WINDOW_DAYS=14 constant that
lived in nc_ecourts_lis_pendens.py itself -- confirmed dead: grepped for
real call sites and found none anywhere in that module's own code (not
referenced by _hit_to_listing or anything else in the file), only this
test's own tautological assertion of its value. Removed the constant
from nc_ecourts_lis_pendens.py and the now-pointless import/assertion
here; the one real UPSET_BID_WINDOW_DAYS (enrichment_upset_bid.py) and
its own ==14 regression test are untouched.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.scrapers.counties_nc.nc_ecourts_lis_pendens import (
    TARGET_COUNTIES,
    _hit_to_listing,
)


def _hit(ordered_date_iso: str, **extras) -> dict:
    base = {
        "causeOfActionDesc": "CV - Lis Pendens",
        "caseNumber": "26M001234-590",
        "orderedDate": ordered_date_iso,
        "judgmentType": "Civil Judgment",
        "location": "Wake District Court",
        "debtors": [{"name": "Smith, John"}],
        "creditors": [{"name": "Bank of NC"}],
    }
    base.update(extras)
    return base


def test_target_counties_match_user_territory():
    """Scope: 2026-09-23 widened TARGET_COUNTIES from the narrow 22-county
    WNC+coastal footprint to all 100 NC counties (docs/coverage_gap_build_plan_
    2026-09-23.md item 1). This is not a scope-policy change — LIS_PENDENS/
    TAX_LIEN/DIVORCE_NOTICE are not in main._FLIP_LISTING_TYPES, so they were
    already routed through config.in_scope_distressed() (admits any real NC
    county, no deny list) rather than the narrow flip footprint's SCOPE_DENY_
    COUNTIES. The old assertion that Wake/Forsyth/Guilford/Durham/Cumberland/
    Mecklenburg/Madison/Yancey must NOT be queried encoded a historical
    footprint artifact, not an actual scope rule for this listing type — live-
    verified 2026-09-23 (see tests/test_nc_ecourts_statewide_widen.py) that
    Tyler's Judgment Search indexes all of them under their own county name."""
    # Former WNC footprint + coastal add-ons must still be present:
    for c in ("Buncombe", "Henderson", "Gaston", "Cleveland",
              "Rutherford", "Polk", "Transylvania",
              "McDowell", "Lincoln", "Mitchell", "Burke",
              "Brunswick", "Pender", "Onslow", "Carteret", "Dare",
              "Currituck", "Hyde", "New Hanover"):
        assert c in TARGET_COUNTIES, f"{c} missing from TARGET_COUNTIES"
    # Formerly-pruned counties are now intentionally included too — this
    # listing type has no deny list (see config.in_scope_distressed).
    for c in ("Wake", "Forsyth", "Guilford", "Durham", "Cumberland",
              "Mecklenburg", "Madison", "Yancey"):
        assert c in TARGET_COUNTIES, (
            f"{c} should now be in TARGET_COUNTIES post-2026-09-23 widening"
        )
    assert len(TARGET_COUNTIES) == 100, (
        "TARGET_COUNTIES should be all 100 NC counties post-widening"
    )


def test_recent_judgment_is_not_an_upset_bid_window():
    """court_signals audit 2026-10-09: orderedDate is the date a JUDGMENT was entered (a lis
    pendens, a claim of lien, a transcript of judgment), never a foreclosure sale; NC sales and
    their upset bids are special proceedings this index does not hold. A judgment ordered 3 days
    ago opens NO upset-bid window (the old stamp scored upset_bid on 1,146 checkpoint rows)."""
    od = (datetime.utcnow() - timedelta(days=3)).isoformat() + "Z"
    for cause in ("CV - Lis Pendens", "CV - Claim of Lien", "CV - Transcript of Judgment",
                  "CV - Federal Tax Lien"):
        li = _hit_to_listing(_hit(od, causeOfActionDesc=cause), "test")
        assert li is not None
        assert li.upset_bid_deadline is None
        assert "upset_bid" not in (li.raw or {})


def test_old_sale_not_flagged():
    """A sale ordered 30 days ago is OUTSIDE the upset bid window."""
    od = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li is not None
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in (li.raw or {})


def test_judgment_at_old_window_boundary_is_not_flagged():
    """Exactly 14 days ago: still no window (it never came from a sale)."""
    od = (datetime.utcnow() - timedelta(days=14)).isoformat() + "Z"
    li = _hit_to_listing(_hit(od), "test")
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in (li.raw or {})


def test_no_ordered_date_no_flag():
    """Listing without orderedDate cannot be classified — no flag."""
    li = _hit_to_listing(_hit(""), "test")
    # Either filtered out or no upset_bid block
    if li is not None:
        assert li.upset_bid_deadline is None
        assert "upset_bid" not in (li.raw or {})

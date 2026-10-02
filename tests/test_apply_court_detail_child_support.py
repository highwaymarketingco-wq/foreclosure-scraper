"""Regression test for the child_support integration gap found 2026-10-02.

court_detail_parser.parse_register_of_actions / parse_sc_case_detail both
compute out["child_support"] = {"flag": True, "hits": [...], "count": N} when
the docket/judgment/caption text mentions child support, alimony, arrears,
etc. But enrichment_case_detail._apply_court_detail copied every OTHER roa
key onto li.raw (court_balance_due, court_docket, ...) except this one, so
the signal was computed and then silently dropped before RAW_KEEP (which
already allowlists "child_support") ever saw it -- real cause of the
child_support board column sitting at 0/148 counties despite the parser
working. Fixed by adding the missing copy in _apply_court_detail.
"""
from __future__ import annotations

from foreclosure_scraper.enrichment_case_detail import _apply_court_detail
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _make_listing() -> Listing:
    return Listing(
        source="test",
        source_url="https://example.com/case",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        raw={},
    )


def test_apply_court_detail_copies_child_support_onto_raw():
    # Tyler-text docket line: DATE followed by an uppercase label containing
    # a child-support keyword -- matches _CS_RE in parse_register_of_actions.
    text = (
        "Case Events\n"
        "01/15/2026 CHILD SUPPORT ARREARAGE ORDER FILED\n"
        "02/01/2026 NOTICE OF HEARING\n"
    )
    li = _make_listing()
    found = _apply_court_detail(li, text)
    assert found is True
    assert isinstance(li.raw.get("child_support"), dict)
    assert li.raw["child_support"]["flag"] is True
    assert li.raw["child_support"]["count"] >= 1


def test_apply_court_detail_no_child_support_key_when_absent():
    text = (
        "Case Events\n"
        "01/15/2026 NOTICE OF HEARING\n"
        "02/01/2026 SUBSTITUTE TRUSTEE DEED\n"
    )
    li = _make_listing()
    _apply_court_detail(li, text)
    assert "child_support" not in li.raw

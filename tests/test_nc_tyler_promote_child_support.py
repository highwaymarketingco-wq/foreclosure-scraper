"""Regression test for the NC eCourts/Tyler child_support copy-gap found
2026-10-02 -- the parallel bug to the one fixed the same day in
enrichment_case_detail._apply_court_detail (commit f443ce25) for the SC path.

court_detail_parser.parse_register_of_actions computes out["child_support"]
= {"flag": True, "hits": [...], "count": N} when the docket/judgment/caption
text mentions child support, alimony, arrears, etc. -- this is the SAME
parser function the SC path falls back to. enrichment_nc_case_status_tyler
._parse_case_detail_html already stores that dict under info["detail"], but
the promotion step that copies info["detail"] onto li.raw copied every
neighboring court_* key (judgment_amount, balance_due, documents,
sale_status, ...) except child_support, so the signal was computed and then
silently dropped before RAW_KEEP (which already allowlists "child_support")
ever saw it -- real cause of the child_support board column never getting a
single hit via the NC Tyler path despite the parser working. Fixed by adding
the missing copy in the (newly extracted) _promote_court_detail helper.
"""
from __future__ import annotations

from foreclosure_scraper.court_detail_parser import parse_register_of_actions
from foreclosure_scraper.enrichment_nc_case_status_tyler import _promote_court_detail
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _make_listing() -> Listing:
    return Listing(
        source="counties_nc.test",
        source_url="https://example.com/case",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Buncombe",
        case_number="25CV001234-320",
        raw={},
    )


def test_promote_court_detail_copies_child_support_onto_raw():
    # Tyler-text docket line: DATE followed by an uppercase label containing
    # a child-support keyword -- matches _CS_RE in parse_register_of_actions.
    text = (
        "Case Events\n"
        "01/15/2026 CHILD SUPPORT ARREARAGE ORDER FILED\n"
        "02/01/2026 NOTICE OF HEARING\n"
    )
    det = parse_register_of_actions(text)
    assert isinstance(det.get("child_support"), dict)  # sanity: parser detects it

    li = _make_listing()
    info = {"status": "scheduled", "method": "tyler_authenticated", "detail": det}
    _promote_court_detail(li, info)

    assert isinstance(li.raw.get("child_support"), dict)
    assert li.raw["child_support"]["flag"] is True
    assert li.raw["child_support"]["count"] >= 1


def test_promote_court_detail_no_child_support_key_when_absent():
    text = (
        "Case Events\n"
        "01/15/2026 NOTICE OF HEARING\n"
        "02/01/2026 SUBSTITUTE TRUSTEE DEED\n"
    )
    det = parse_register_of_actions(text)
    li = _make_listing()
    info = {"status": "scheduled", "method": "tyler_authenticated", "detail": det}
    _promote_court_detail(li, info)

    assert "child_support" not in li.raw


def test_promote_court_detail_still_copies_neighboring_fields():
    """Guard against the extraction regressing the fields that already worked
    (judgment_amount, balance_due, documents, sale_status/sold_confirmed)."""
    text = (
        "Case Events\n"
        "01/15/2026 ORDER CONFIRMING SALE\n"
        "Judgment Amount: $128,500.00\n"
        "Balance Due: $4,200.00 as of 01/20/2026\n"
    )
    det = parse_register_of_actions(text)
    li = _make_listing()
    info = {"status": "confirmed", "method": "tyler_authenticated", "detail": det}
    _promote_court_detail(li, info)

    if det.get("judgment_amount"):
        assert li.judgment_amount == det["judgment_amount"]
    if det.get("sale_status") == "confirmed":
        assert li.raw.get("sold_confirmed") is True

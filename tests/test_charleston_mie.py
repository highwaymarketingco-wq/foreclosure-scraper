"""Charleston County (SC) Master-in-Equity scraper.

Added 2026-06-25 to close the Charleston gap (sc_coastal_rosters deliberately
skips Charleston — its publicindex app has no Master roster; Charleston runs MIE
sales on the county website). Two methods: the MASTER'S AUCTION LIST (MSO HTML,
TMS-anchored regex) and the UncontestedRoster.pdf HEARING roster (pdfplumber).

Offline fixtures mirror the exact live layouts captured 2026-06-25. The live
network test is opt-in via RUN_NETWORK_TESTS=1.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc.charleston_mie import (
    CharlestonMasterInEquity,
    _norm_case,
    parse_auction_list,
    parse_hearing_roster,
)

# Trimmed MSO-export HTML mirroring the live runninglist.html: header row, a
# JULY SALES section with a normal row + an HOA-LIEN row, and an AUGUST SALES
# section with a RE-OPEN row (two dates, re-open date closest to the TMS).
_AUCTION_HTML = (
    "<html><body><p>MASTER'S AUCTION LIST</p>"
    "<p>Date of Sale Plaintiff Defendant TMS &amp; Address Judgment Lien "
    "Attorney Special Item</p>"
    "<p>JULY SALES</p>"
    "<p>07-07-26 25-06873 Computershare Delaware Peter J. Dieppe IV "
    "3501400030 1906 Capri Drive $453,617.57 1 st Riley Pope &amp; Laney "
    "803-799-9993 West Ashley</p>"
    "<p>07-07-26 24-04968 Colony North Management Christan A. Rainey "
    "4840800302 7814 Jean Rebault Drive $6,439.73 HOA LIEN Ashley Green "
    "803-724-5002 North Charleston</p>"
    "<p>AUGUST SALES</p>"
    "<p>08-04-26 RE-OPEN 09-03-26 26-00297 Wilmington Trust 78 Devereaux Ave "
    "3400000043 1977 Central Park Road $379,502.01 1 st J. Martin Page "
    "803-509-5078 James Island</p>"
    "</body></html>"
).encode("windows-1252")


def test_auction_list_parses_tms_anchored_rows():
    out = parse_auction_list(_AUCTION_HTML)
    assert len(out) == 3
    by_tms = {li.parcel_id: li for li in out}

    a = by_tms["3501400030"]
    assert a.county == "Charleston"
    assert a.state == "SC"
    assert a.listing_type == ListingType.FORECLOSURE_SALE
    assert a.case_number == "25-06873"
    assert a.street_address == "1906 Capri Drive"
    assert a.opening_bid == 453617.57
    assert a.judgment_amount == 453617.57
    assert a.sale_date.date().isoformat() == "2026-07-07"
    assert a.foreclosure_process == "judicial"
    assert a.source == "counties_sc.charleston_mie"


def test_auction_list_reopen_uses_reopen_date_and_status():
    out = parse_auction_list(_AUCTION_HTML)
    r = {li.parcel_id: li for li in out}["3400000043"]
    # The RE-OPEN date (closest to the TMS) is the one the auction runs on.
    assert r.sale_date.date().isoformat() == "2026-09-03"
    assert r.auction_status == "reopen"
    assert r.opening_bid == 379502.01


def test_auction_list_captures_hoa_lien_row_as_sale():
    # HOA-LIEN rows on the auction list are still scheduled SALES (with a TMS),
    # so they're emitted as foreclosure sales (distinct from the roster's
    # HOA_SALE hearing rows).
    out = parse_auction_list(_AUCTION_HTML)
    h = {li.parcel_id: li for li in out}["4840800302"]
    assert h.opening_bid == 6439.73
    assert h.street_address == "7814 Jean Rebault Drive"


def test_norm_case_collapses_padding_across_methods():
    # Roster '25-5994' must match auction list '25-05994'.
    assert _norm_case("25-5994") == _norm_case("25-05994")
    assert _norm_case("26-0242") == _norm_case("26-00242")
    assert _norm_case("") == ""


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live charlestoncounty.gov — set RUN_NETWORK_TESTS=1",
)
def test_live_both_methods_yield_rows():
    out = list(asyncio.run(CharlestonMasterInEquity().fetch()))
    assert out, "expected Charleston MIE rows"
    methods = {li.raw.get("charleston_mie", {}).get("method") for li in out}
    assert "auction_list" in methods, "auction list method produced nothing"
    assert "hearing_roster" in methods, "hearing roster method produced nothing"
    for li in out:
        assert li.state == "SC"
        assert li.county == "Charleston"
        assert li.source == "counties_sc.charleston_mie"
    # Auction rows must carry a TMS; roster rows must carry a case number.
    auction = [li for li in out if li.raw["charleston_mie"]["method"] == "auction_list"]
    roster = [li for li in out if li.raw["charleston_mie"]["method"] == "hearing_roster"]
    assert all(li.parcel_id for li in auction)
    assert all(li.case_number for li in roster)
    # Cross-method dedupe: no normalized case appears in both buckets.
    auction_cases = {_norm_case(li.case_number) for li in auction if li.case_number}
    roster_cases = {_norm_case(li.case_number) for li in roster if li.case_number}
    assert auction_cases.isdisjoint(roster_cases)


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    slugs = {s.slug for s in all_scrapers()}
    assert "counties_sc.charleston_mie" in slugs


def test_hearing_roster_requires_pdfplumber_gracefully():
    # Non-PDF bytes must not raise — parser returns [] on bad input.
    assert parse_hearing_roster(b"not a pdf") == []

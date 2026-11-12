"""NC county in-rem tax-foreclosure scraper (Gaston/McDowell/Rutherford).

Discovered 2026-06-16. Tax foreclosures are a separate track from the
eCourts mortgage pipeline; these county pages are the only public surface.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from foreclosure_scraper.scrapers.counties_nc.nc_county_tax_foreclosure import (
    COUNTY_PAGES,
    NCCountyTaxForeclosure,
    parse_kania_text,
    parse_text,
)


def test_parse_extracts_file_parcel_bid_addr():
    text = ("Upcoming Tax Foreclosure Sales  "
            "File 25 M 388 Parcel 1728-00-88-4682 128 Boiler Rd current bid $19,845.00 "
            "sale Dec 19, 2024  "
            "File 26-CVD-178 Parcel 1703-00-95-0253 minimum bid $7,000.00")
    out = parse_text(text, "Rutherford", "http://x")
    assert len(out) == 2
    first = out[0]
    assert first.case_number == "25 M 388"
    assert first.county == "Rutherford"
    assert first.state == "NC"
    assert first.opening_bid == 19845.0
    assert "Boiler Rd" in (first.street_address or "")


def test_parse_gaston_style_case_trails_its_own_record_not_the_next_one():
    """Regression for the live-confirmed off-by-one misattribution: Gaston's
    REAL page order is "Owner / Parcel / Address / Sale Date / Bid / Last Day
    to Upset / File Number: <CASE>" -- the case number is the LAST thing in
    its own record, and the next record's own Owner/Parcel/Address begin
    immediately after. The old block (start = m.start(), i.e. forward-only)
    grabbed the NEXT record's fields and labeled them with THIS case number;
    e.g. live, "File Number: 25 M 414" was paired with Heirs of Mary Suzanne
    K. Ledford / parcel 119763 / 2956 Union Rd, which is actually case
    "25 M 415"'s own record (every Gaston row was shifted by one)."""
    text = (
        "Owner: Heirs of Elsie Painter Parcel: 194353 Physical Address: "
        "5588 Fewell Rd, Gastonia, NC Sale Date: January 21, 2026 at 10 am. "
        "Current Bid: $96,600.00 Minimum of Next Upset Bid: $101,430.00 "
        "Last Day to Upset: March 5, 2026 File Number: 25 M 414 "
        "Sale Closed-Property Sold Owner: Heirs of Mary Suzanne K. Ledford "
        "Parcel: 119763 Physical Address: 2956 Union Rd., Gastonia, NC "
        "Sale Date: January 6, 2026, at 10 am. Current Bid: $175,491.75 "
        "Minimum of Next Upset Bid: $184,266.34 Last Day to Upset: "
        "February 9, 2026 File Number: 25 M 415 Settled- Property Redeemed "
        "Owner: Heirs of Mary Elizabeth Nixon Parcel: 185759 Physical "
        "Address: 118 Barnes St, Belmont, NC Sale Date: April 15, 2025 at "
        "10 am. Current Bid: $65,000.00 Minimum of Next Upset Bid: "
        "$68,250.00 Last Day to Upset: June 27, 2025 File Number: 24 M 875"
    )
    out = parse_text(text, "Gaston", "http://x")
    by_case = {li.case_number: li for li in out}
    assert by_case["25 M 414"].street_address == "5588 Fewell Rd"
    assert by_case["25 M 414"].parcel_id == "194353"
    assert by_case["25 M 414"].opening_bid == 101430.0
    assert by_case["25 M 415"].street_address == "2956 Union Rd."
    assert by_case["25 M 415"].parcel_id == "119763"
    assert by_case["25 M 415"].opening_bid == 184266.34
    assert by_case["24 M 875"].street_address == "118 Barnes St"
    assert by_case["24 M 875"].parcel_id == "185759"


def test_parse_rutherford_style_case_leads_field_trimmed_to_its_own_record():
    """Rutherford opens each record with 'In-Rem Foreclosure Parcel(s): ...'
    BEFORE its own case mark, then prints address/bid AFTER it. Without
    trimming the backward half to the nearest record-start anchor, the
    backward span for a later case reaches into the PRECEDING record's own
    trailing address/bid (nothing else marks the boundary)."""
    text = (
        "In-Rem Foreclosure Parcel(s): 1620441 - .46ac FILE # WITH CLERK OF "
        "COURT: 23 M 258 1620441 - 0 Pinnacle Parkway, Union Mills Current "
        "Bid: $21,458.29 Minimum amount needed to upset bid: $22,531.21 "
        "Last day to upset bid: 12/19/2024 "
        "**************************************** "
        "In-Rem Foreclosure Parcel: 1613770; 1.36 acres FILE # WITH CLERK "
        "OF COURT: 23 M 265 145 Boiler Rd, Mooresboro Current Bid: "
        "$18,900.00 Minimum amount needed to upset bid: $19,845.00 Last "
        "day to upset bid: 12/19/2024"
    )
    out = parse_text(text, "Rutherford", "http://x")
    by_case = {li.case_number: li for li in out}
    assert by_case["23 M 258"].street_address == "0 Pinnacle Parkway"
    assert by_case["23 M 258"].opening_bid == 22531.21
    assert by_case["23 M 265"].street_address == "145 Boiler Rd"
    assert by_case["23 M 265"].opening_bid == 19845.0


def test_parse_dedupes_repeat_file_numbers():
    text = "File 25 M 388 $1,000.00 ... again File 25 M 388 $1,000.00"
    out = parse_text(text, "Gaston", "http://x")
    assert len(out) == 1


def test_parse_empty_when_no_file_numbers():
    assert parse_text("No active tax foreclosure sales at this time.", "Polk", "http://x") == []


def test_parse_kania_text_extracts_owner_pin_addr_case_bid_and_deadline():
    """2026-10-03 (HERMES extraction-completeness audit, batch 5): Rutherford's
    nav menu links a SEPARATE "Outside Law (Kania Law Firm)" page this scraper
    never fetched at all. Its case-number format ("26CVD000526-800") doesn't
    match the module's own _FILE_RE, so a naive wire-up would have scanned the
    page and returned zero rows. Text below is a cleaned excerpt of the real
    live page (html.unescape already applied upstream -- see the separate
    &ndash;-entity regression test)."""
    text = (
        "Current Foreclosures Pictures below may not be the most recent "
        "PK Ventures I Limited Partnership – (908440) – 0 Harris Henrietta Rd "
        "– File #24743, 9.26 acres 26CVD000526-800 Current Bid: $22,100.00, "
        "amount needed to upset the bid $23,205.00, Last day for upset bid: "
        "10/12/2026 "
        "Brooks, Rosalie M., et al. - 912224 - 5970 US 221A Hwy – File #24565, "
        "House with 1.50 acres 26CV000506-800 Current Bid: $18,354.15, "
        "Amount needed to upset the bid: $19,271.86 Last day for upset bid: "
        "10/9/2026 "
        "Upcoming Kania Law Firm foreclosures"
    )
    out = parse_kania_text(text)
    assert len(out) == 2
    by_case = {li.case_number: li for li in out}

    r1 = by_case["26CVD000526-800"]
    assert r1.owner_name == "PK Ventures I Limited Partnership"
    assert r1.parcel_id == "908440"
    assert r1.street_address == "0 Harris Henrietta Rd"
    assert r1.opening_bid == 22100.0
    assert r1.upset_bid_deadline.strftime("%m/%d/%Y") == "10/12/2026"
    assert r1.county == "Rutherford"
    assert r1.state == "NC"
    assert r1.trustee == "Kania Law Firm, P.A."
    assert r1.raw["nc_county_tax_foreclosure"]["upset_bid_amount"] == 23205.0
    assert r1.raw["nc_county_tax_foreclosure"]["file_number"] == "24743"

    r2 = by_case["26CV000506-800"]
    assert r2.owner_name == "Brooks, Rosalie M., et al"
    assert r2.parcel_id == "912224"
    assert r2.street_address == "5970 US 221A Hwy"
    assert r2.opening_bid == 18354.15


def test_parse_kania_text_unescapes_literal_ndash_html_entity():
    """Live-confirmed 2026-10-03: the real page's separator is the literal
    text "&ndash;" (an un-decoded HTML entity), not a real en-dash character
    -- _fetch_page's own tag-stripping only decodes &nbsp;, so every owner/
    pin/addr match silently failed before parse_kania_text started decoding
    entities itself."""
    text = (
        "Current Foreclosures "
        "Cedar Creek Mountain, LLC &ndash; 1641050 &ndash; 186 Mountaintop Pkwy "
        "&ndash; File #23106, 1.11 Acres 24CVD001334-800 Current Bid: $4,501.00, "
        "Amount needed to upset the bid: $5,251.00 Last day for upset bid: "
        "10/2/2026"
    )
    out = parse_kania_text(text)
    assert len(out) == 1
    assert out[0].owner_name == "Cedar Creek Mountain, LLC"
    assert out[0].parcel_id == "1641050"
    assert out[0].street_address == "186 Mountaintop Pkwy"


def test_parse_kania_text_empty_when_no_records():
    assert parse_kania_text("Upcoming Kania Law Firm foreclosures on ------ below.") == []


def test_in_scope_counties_only():
    assert set(COUNTY_PAGES) == {"Gaston", "McDowell", "Rutherford"}


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.nc_county_tax_foreclosure" in {s.slug for s in all_scrapers()}


@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="live stealth fetch")
def test_live_returns_tax_foreclosures():
    out = list(asyncio.run(NCCountyTaxForeclosure().fetch()))
    for li in out:
        assert li.state == "NC"
        assert li.county in COUNTY_PAGES
        assert li.case_number

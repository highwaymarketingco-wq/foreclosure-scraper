"""Pin the Anderson MIE Sale-List / Sale-Results extraction, especially the
row-swallowing split bug found and fixed 2026-10-01.

``_parse_pdf`` (the upcoming Sale-List) used to split rows on
``"<case#> <ALL-CAPS-attorney-code>"``. Real Sale-List PDFs also carry
full-name attorneys (Cox, Driscoll, Hutchens, Nourie, Shook) that don't
match that shape, so every row after one of those names got silently
swallowed into the PRECEDING row's text and never emitted as its own
Listing -- live-verified against the October 6 2026 Sale List, this
dropped 15 of 17 real parcels. Fixed by splitting on the numbered-row
marker ("N. <case#>"), the same scheme ``_parse_results_pdf`` already used
(its own docstring even named this as the more-robust approach, but it was
never ported back to ``_parse_pdf``).

Also pins: legal_description (lot + plat-book@page) extraction, the
MH/mobile-home property_kind signal, and the ADDR_RE false-positive fix
(it used to match "Rd" inside "Edward" and "St" inside "Steele").

Fixtures below are real PDF-extracted text (pypdf), captured live
2026-10-01 from andersoncountysc.org Sale-List / Sale-Results PDFs. No
network calls in these tests.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.anderson_master_in_equity import (
    _legal_description,
    _parse_pdf,
    _parse_results_pdf,
    ADDR_RE,
)
from foreclosure_scraper.models import PropertyKind
from datetime import datetime

# A real excerpt of the October 6 2026 Sale List: a short-code attorney row
# (1) followed by FOUR full-name-attorney rows (2-5) that the old
# "<case#> [A-Z]{1,4}" split could never separate from row 1.
SALE_LIST_TEXT = """
CASE NO. ATTY. CAPTION DESCRIPTION NOTES
1. 25-3002  B&S Lakeview Loan Servicing v.
Katherine Annette Berry-
Burns, et al.
Lot 89
PS2873@4
726 Oak Hill Ln, Belton

2. 25-2481 B&S Planet Home Lending v.
Christopher Honchell, et al.
Lot 17
PB37@264
241 Hillcrest Circle, Anderson

3. 26-1257 Cox Edward A. Steele v. Amanda
Keeler, et al.
Lot 3+MH
PB1139@5-6
105 Loveland Drive, Williamston


2
CASE NO. ATTY. CAPTION DESCRIPTION NOTES
4. 23-1916 Driscoll The Cadle Company v. Roy E.
Burgan, et al.
An undivided 1/2 interest in
Lot 7, 1.11 acres
PS1038@9
112 Raspberry Lane, Anderson
SUBJECT TO
FIRST
MORTGAGE

BIDDING TO
REOPEN IN 30
DAYS
5. 22-760 Hutchens US Bank v. Wayne Thomas
Black, et al.
Lot 99
PB19@304
5 Circle Street, La France
"""

# A real excerpt of a Sale-Results PDF: deficiency rows with a hammer price.
SALE_RESULTS_TEXT = """
CASE NO. ATTY. CAPTION DESCRIPTION RESULTS
1.  24-1678 BCP Carrington Mortgage
Services v. Roger Owens, et
al.
Lot of land containing .44 acre
PB98@684
169 Cherokee Road, Williamston

WD
2. 25-2250 B&S PennyMac Loan v. Danielle
Allison
Lot 93
PB23@195
201 New St., Iva
SOLD
5. 25-1208 B&S US Bank v. Debra
McAlister, et al.
Lot 10
PB1038@1&2
118 Quartermein Ct., Piedmont
DEFICIENCY
Plaintiff bid
$261,183.24
"""


def test_sale_list_split_recovers_full_name_attorney_rows():
    """The split bug this test pins: rows 2-5 above all have full-name
    (not short-code) attorneys. Before the fix, only row 1 (B&S) survived
    as its own Listing; rows 2-5 were swallowed into it."""
    out = _parse_pdf(SALE_LIST_TEXT, "https://example.com/sale-list.pdf", "test.slug")
    cases = {li.case_number for li in out}
    assert {"25-3002", "25-2481", "26-1257", "23-1916", "22-760"} <= cases
    assert len(out) >= 5


def test_sale_list_addresses_are_clean():
    by_case = {li.case_number: li for li in _parse_pdf(
        SALE_LIST_TEXT, "https://x/sale-list.pdf", "test.slug")}
    assert by_case["25-3002"].street_address == "726 Oak Hill Ln"
    assert by_case["22-760"].street_address == "5 Circle Street"
    # Regression: ADDR_RE used to match "Rd" inside "Edward" and claim
    # "1257 Cox Edward" as the address.
    assert by_case["26-1257"].street_address == "105 Loveland Drive"


def test_sale_list_legal_description_captured():
    by_case = {li.case_number: li for li in _parse_pdf(
        SALE_LIST_TEXT, "https://x/sale-list.pdf", "test.slug")}
    assert by_case["25-3002"].legal_description == "Lot 89 PS2873@4"
    assert by_case["22-760"].legal_description == "Lot 99 PB19@304"


def test_sale_list_mobile_home_kind_from_legal_description():
    by_case = {li.case_number: li for li in _parse_pdf(
        SALE_LIST_TEXT, "https://x/sale-list.pdf", "test.slug")}
    assert by_case["26-1257"].property_kind == PropertyKind.MOBILE
    assert by_case["25-3002"].property_kind == PropertyKind.UNKNOWN


def test_sale_list_raw_carries_provenance():
    by_case = {li.case_number: li for li in _parse_pdf(
        SALE_LIST_TEXT, "https://x/sale-list.pdf", "test.slug")}
    raw = by_case["25-3002"].raw["anderson_mie"]
    assert raw["source_pdf"] == "https://x/sale-list.pdf"
    assert raw["legal_description"] == "Lot 89 PS2873@4"


def test_sale_results_legal_description_and_price():
    out = _parse_results_pdf(
        SALE_RESULTS_TEXT, "https://x/results.pdf", "test.slug", datetime(2026, 9, 1))
    by_case = {li.case_number: li for li in out}
    assert "24-1678" not in by_case  # WD -- withdrawn, correctly skipped
    assert by_case["25-1208"].legal_description == "Lot 10 PB1038@1&2"
    assert by_case["25-1208"].opening_bid == 261183.24
    assert by_case["25-1208"].raw["actual_sold_price"] == 261183.24


def test_addr_re_does_not_match_inside_a_surname():
    """'Edward' contains 'rd' (Road) and 'Steele' contains 'St' (Street) as
    bare substrings -- the old ADDR_RE (no \\b around the suffix) matched
    both as if they were street-suffix tokens."""
    assert ADDR_RE.search("1257 Cox Edward A. Steele v. Amanda") is None


def test_legal_description_handles_multiline_defendant_wrap():
    """A defendant name that wraps across PDF lines ('...Berry-\\nBurns, et
    al.') must not leak into the legal description -- anchor on the
    literal 'et al.' marker, not the (necessarily single-line) caption
    regex."""
    chunk = (
        "25-3002  B&S Lakeview Loan Servicing v. \n"
        "Katherine Annette Berry-\nBurns, et al. \n"
        "Lot 89 \nPS2873@4 \n726 Oak Hill Ln, Belton"
    )
    addr_m = ADDR_RE.search(chunk)
    desc, kind = _legal_description(chunk, addr_m)
    assert desc == "Lot 89 PS2873@4"
    assert "Burns" not in (desc or "")
    assert kind == PropertyKind.UNKNOWN

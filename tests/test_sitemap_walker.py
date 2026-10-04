"""Generic county-sitemap discovery scraper (counties.sitemap_walker).

HERMES sec 8 audit, 2026-10-01. Live-confirmed two bugs in the
case-number-anchored fallback chunker (used when a page has no
`***`/`===`/blank-line separators between records, e.g. Gaston County's
tax-foreclosure-sale page, which this scraper also discovers via its
sitemap):

1. ADDR_RE had no word boundary before the street-suffix alternation, so
   under re.I it matched a SUBSTRING inside an unrelated word ("Addr" in
   "Address" satisfies "...Dr") and fabricated "103685 Physical Addr" out of
   the page's own "103685 Physical Address:" label.
2. The fallback built each chunk as a FIXED +-200/400 char window centered on
   a case-number match. Gaston's real record order is "Owner / Parcel /
   Address / ... / File Number: <CASE>" (the case trails its own data, and
   the next record's Owner/Parcel/Address start immediately after), so the
   +400-char forward reach pulled the NEXT record's parcel into THIS
   record's listing: "File Number: 24 M 867" (which owns "2508 Gardner St")
   came back with parcel 120452, which actually belongs to the following
   record.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_generic.sitemap_walker import (
    ADDR_RE,
    _parse_listings,
    _pdf_filename_date,
    _pdf_listing,
    _real_notice_pdfs,
)

# Trimmed, field-faithful reproduction of the live Gaston County tax
# foreclosure-sale page (gastongov.com/671/Previous-Tax-Foreclosure-Sales,
# read 2026-10-01) -- note there is NO separator between records at all,
# which is exactly what forces this scraper into its case-number-anchored
# fallback chunker.
GASTON_TEXT = (
    "Owner: Macie Clark Parcel: 103685 Physical Address: 401 Pryor St., "
    "Gastonia, NC Sale Date: December 9, 2025 at 10 am. Current Bid: "
    "$87,240.23 Minimum of Next Upset Bid: $91,602.24 Last Day to Upset: "
    "March 16, 2026 File Number: 25 M 388 Sale Closed-Property Sold "
    "Owner: Gretchen Adams Parcel: 139329 Physical Address: 2508 Gardner "
    "St., Gastonia, NC Sale Date: May 6, 2025 at 10 am. Current Bid: "
    "$50,000.00 Minimum of Next Upset Bid: $52,500.00 Last Day to Upset: "
    "May 26, 2025 File Number: 24 M 867 Settled- Property Redeemed "
    "Owner: Yaulanda Michelle Waldroup Parcel: 120452 Physical Address: "
    "615 E. Lee Ave, Bessemer City, NC Sale Date: March 25, 2025 at 10 am. "
    "Current Bid: $84,000.00 Minimum of Next Upset Bid: $88,200.00 Last "
    "Day to Upset: April 20, 2025 File Number: 24 M 807"
)


def test_fallback_chunker_does_not_bleed_next_records_parcel_into_this_one():
    out = _parse_listings(GASTON_TEXT, "http://x", "NC", "Gaston")
    by_case = {li.case_number: li for li in out}
    assert "401 Pryor St" in (by_case["25 M 388"].street_address or "")
    assert by_case["25 M 388"].parcel_id == "103685"
    assert "2508 Gardner St" in (by_case["24 M 867"].street_address or "")
    assert by_case["24 M 867"].parcel_id == "139329"  # not 120452 (next record's)
    assert "615 E. Lee Ave" in (by_case["24 M 807"].street_address or "")
    assert by_case["24 M 807"].parcel_id == "120452"


def test_addr_re_does_not_fabricate_an_address_from_a_label():
    """'103685 Physical Address:' must not satisfy the '...Dr' alternative
    hidden inside 'Address'."""
    m = ADDR_RE.search("103685 Physical Address: 401 Pryor St., Gastonia, NC")
    assert m is None or "Addr" not in m.group(1).split()[-1][-4:]


def test_addr_re_still_matches_a_real_address():
    m = ADDR_RE.search("Physical Address: 401 Pryor St., Gastonia, NC")
    assert m is not None
    assert "401 Pryor St" in m.group(1)


def test_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties.sitemap_walker" in {s.slug for s in all_scrapers()}


# --------------------------------------------------------------------------
# EXTRACTION-COMPLETENESS AUDIT 2026-10-03: PDF-anchored fallback.
#
# Live-confirmed _parse_listings parses to ZERO on most of the actually-
# relevant pages across all 12 counties -- not because nothing is
# published, but because the real sale roster is a LINKED PDF, never
# embedded in the page's own text. Anderson County's live Master-in-Equity
# page (andersoncountysc.org/departments-a-z/master-in-equity/) links 226
# PDFs: a handful of real monthly sale-list/deficiency-sale documents mixed
# into mostly site chrome (an employment application, a holiday schedule,
# an unrelated road-sign PDF). This fixture is a trimmed, field-faithful
# reproduction of that real href mix, captured live 2026-10-03.
# --------------------------------------------------------------------------
ANDERSON_MOE_HTML = """
<html><body>
<a href="https://www.andersoncountysc.org/wp-content/uploads/2026/09/DJ030a-Green-Pond-Landing-Scenic-Byway-Sign-002.pdf">Sign</a>
<a href="https://www.andersoncountysc.org/wp-content/uploads/2026/07/EmploymentApplicationAndersonRev7.2026.pdf">Employment Application</a>
<a href="https://www.andersoncountysc.org/wp-content/uploads/2025/11/2026-Holiday-Schedule.pdf">Holiday Schedule</a>
<a href="https://www.andersoncountysc.org/wp-content/uploads/2026/10/October-6-2026-Sale-List.pdf">October 6 Sale List</a>
<a href="https://www.andersoncountysc.org/wp-content/uploads/2026/08/September-3-2026-Deficiency-Sale.pdf">Deficiency Sale</a>
</body></html>
"""
ANDERSON_MOE_URL = "https://www.andersoncountysc.org/departments-a-z/master-in-equity/"

# Live-confirmed on Oconee's own delinquent-tax page: a shared sidebar
# widget links an unrelated CROSS-DOMAIN bond-financing TEFRA notice (a
# different agency entirely) whose filename happens to contain "Notice".
# Must not be captured just because the page matched our keyword filter.
OCONEE_CROSS_DOMAIN_HTML = """
<html><body>
<a href="https://scjeda.com/assets/uploads/2023/04/TEFRA-Notice-Prisma-Health.pdf">TEFRA Notice</a>
</body></html>
"""
OCONEE_URL = "https://oconeesc.com/delinquent-tax/sale-list"


def test_real_sale_list_pdfs_are_found_chrome_is_excluded():
    pdfs = _real_notice_pdfs(ANDERSON_MOE_HTML, ANDERSON_MOE_URL)
    assert any("October-6-2026-Sale-List" in p for p in pdfs)
    assert any("September-3-2026-Deficiency-Sale" in p for p in pdfs)
    assert not any("Sign-002" in p for p in pdfs)
    assert not any("EmploymentApplication" in p for p in pdfs)
    assert not any("Holiday-Schedule" in p for p in pdfs)


def test_cross_domain_pdf_is_never_captured_even_if_keyword_matches():
    """REGRESSION: the exact page-wide-chrome anti-pattern city_websites.
    search was disabled for -- a page's shared sidebar can link another
    agency's own unrelated document on a different domain entirely."""
    pdfs = _real_notice_pdfs(OCONEE_CROSS_DOMAIN_HTML, OCONEE_URL)
    assert pdfs == []


def test_pdf_filename_date_parses_the_embedded_sale_date():
    dt = _pdf_filename_date(
        "https://www.andersoncountysc.org/wp-content/uploads/2026/10/October-6-2026-Sale-List.pdf"
    )
    assert dt is not None
    assert (dt.year, dt.month, dt.day) == (2026, 10, 6)


def test_pdf_listing_carries_the_document_and_a_real_sale_date():
    li = _pdf_listing(
        "https://www.andersoncountysc.org/wp-content/uploads/2026/10/October-6-2026-Sale-List.pdf",
        ANDERSON_MOE_URL, "SC", "Anderson",
    )
    assert li.raw["documents"] == [
        "https://www.andersoncountysc.org/wp-content/uploads/2026/10/October-6-2026-Sale-List.pdf"
    ]
    assert li.sale_date is not None and li.sale_date.month == 10
    assert li.listing_type.value == "foreclosure_sale"

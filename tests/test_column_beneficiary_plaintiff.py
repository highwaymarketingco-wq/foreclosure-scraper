"""Column NC foreclosure-sale lender/beneficiary extraction -- extraction-
completeness audit 2026-10-03 (counties.column_legal_notices).

Live-surveyed 44 recent NC "Foreclosure Sale" notices across 7 footprint
counties (Gaston, Buncombe, Burke, Cleveland, Rutherford, Henderson,
Brunswick): 30/44 (68%) carry a clean, labelled "Original Beneficiary:
<Lender>" line -- the real party behind the sale, analogous to a judicial
foreclosure's plaintiff -- that was parsed nowhere on this Listing before
this fix. The other 14/44 genuinely never name a beneficiary at all
(anonymized "the holder of the Note"/"the holder of the indebtedness"
prose on different trustee-firm templates) -- a real template limitation,
confirmed live, not a missed regex.

Fixtures are built from real body text captured live on Gaston County's
feed (names kept as published in the real public notice, same convention
as test_column_nc_foreclosure_owner.py / test_column_sc_quiet_title.py).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.newspapers import column_legal_notices as C

BENEFICIARY_BODY = """
NORTH CAROLINA GASTON COUNTY

Special Proceedings No. 26SP000371-350 Substitute Trustee: Philip A. Glass.

NOTICE OF FORECLOSURE SALE

Date of Sale: September 29, 2026 Time of Sale: 10:00 a.m.

Place of Sale: Gaston County Courthouse

Description of Property: See Attached Description Record Owners: Heirs of Eleanor S. Grass

Address of Property: 5306 Old Course Drive Cramerton, NC 28032

CONDITIONS OF SALE: Deed of Trust:

Book 5337 Page: 168 Dated: May 11, 2022

Grantors: Eleanor S. Grass, an unmarried woman

Original Beneficiary: State Employees' Credit Union This sale is made subject to all unpaid taxes and superior liens or encumbrances of record.

PIN: 3574-92-4237 Property Address: 5306 Course Dr. Cramerton, NC 28032
"""

# A real template that never names a beneficiary at all -- the anonymized
# "holder of the Note" prose (Buncombe's NC R.E. Trustee template, captured
# live 2026-10-03). plaintiff must stay None here, not a guess.
NO_BENEFICIARY_BODY = """
NORTH CAROLINA

25SP000318-100

BUNCOMBE COUNTY

AMENDED NOTICE OF FORECLOSURE SALE

Under and by virtue of a Power of Sale contained in that certain Deed of
Trust executed by George R. Hunter, Sr. to Neuse, Incorporated, Trustee,
which was dated November 1, 2013 and recorded on November 13, 2013 in Book
5162 at Page 853, Buncombe County Registry, North Carolina.

Default having been made of the Note thereby secured by the said Deed of
Trust and the undersigned, NC R.E. Trustee, LLC, Substitute Trustee, having
been substituted as Trustee in said Deed of trust, and the holder of the
Note evidencing said default having directed that the Deed of Trust be
foreclosed, the undersigned Substitute Trustee will offer for sale at the
courthouse door January 29, 2026 at 11:00 AM.

Address of Property: 100 Avery Creek Road, Arden, NC 28704
"""


def test_original_beneficiary_is_captured_as_plaintiff():
    """REGRESSION: the lender/noteholder name sitting clean and labelled in
    the body ("Original Beneficiary: State Employees' Credit Union") was
    never parsed. Must land on the first-class `plaintiff` field."""
    parsed = C._parse_nc_foreclosure(BENEFICIARY_BODY)
    assert parsed["plaintiff"] == "State Employees' Credit Union"


def test_beneficiary_stops_before_conditions_of_sale_not_over_captured():
    """REGRESSION PIN: the first version of this fix's stop-word lookahead
    didn't include "CONDITIONS", so on a body with no sentence-ending period
    between the lender name and the next ALL-CAPS section header, the whole
    regex failed to match at all (not merely over-captured) -- live-verified
    this exact shape on 10 of the 30 real hits. Confirmed fixed here."""
    body_with_conditions_immediately_after = (
        "Original Beneficiary: Local Government Federal Credit Union "
        "CONDITIONS OF SALE: This sale is made subject to all unpaid taxes."
    )
    parsed = C._parse_nc_foreclosure(body_with_conditions_immediately_after)
    assert parsed["plaintiff"] == "Local Government Federal Credit Union"


def test_no_beneficiary_label_leaves_plaintiff_unset_not_guessed():
    """A real template that never names the lender must NOT fabricate a
    plaintiff -- confirmed live this is a genuine template limitation."""
    parsed = C._parse_nc_foreclosure(NO_BENEFICIARY_BODY)
    assert "plaintiff" not in parsed


def test_full_listing_carries_the_plaintiff_field():
    """End-to-end: _nc_listing must actually wire parsed['plaintiff'] onto
    the Listing, not just leave it sitting in the parsed dict."""
    from foreclosure_scraper.scrapers.newspapers.column_legal_notices import (
        ColumnLegalNotices,
    )

    scraper = ColumnLegalNotices()
    item = {
        "id": "test-plaintiff-1",
        "text": BENEFICIARY_BODY,
        "county": "Gaston",
        "state": "North Carolina",
        "noticetype": "Foreclosure Sale",
        "newspapername": "The Gastonia Gaston Gazette",
        "pdfurl": "https://example.com/notice.pdf",
        "filer": "abc123",
        "publishedtimestamp": 1790553600000,
    }
    li = scraper._nc_listing(item, "Gaston")
    assert li is not None
    assert li.plaintiff == "State Employees' Credit Union"

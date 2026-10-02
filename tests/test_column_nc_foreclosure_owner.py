"""Column NC foreclosure-sale owner-name extraction — audited 2026-10-01.

HERMES sec 8 per-source audit, newspaper/legal-notice tier
(counties.column_legal_notices). Live `fetch()` against Burke County, NC
found owner_name silently None on 64 of 84 (76%) FORECLOSURE_SALE rows
across the full footprint even though the name was plainly present in the
notice body, for two distinct reasons:

1. The common "SUBSTITUTE TRUSTEE'S NOTICE" template reads "...Deed of Trust
   made by Robert R. Taylor (Deceased) (PRESENT RECORD OWNER(S): Robert R.
   Taylor) to Jennifer Grant, Trustee(s)...". `_RECORD_OWNERS`'s capture had
   no label/end-of-line boundary to stop on before the closing ")" (not in
   its allowed character class), so the ENTIRE match failed for every notice
   using this exact (very common) parenthetical form.
2. Some notices use no "Record Owner(s)" label at all — the owner is named
   only as the Deed of Trust's grantor ("...executed and delivered by
   Kenneth Sprouse and Adele Sprouse dated..."), which had no fallback at
   all before `_GRANTOR_RE` was added.

Fixtures below are built from real body text captured live on Burke County's
feed (names kept as published in the real public notice, same as the
existing column_sc_quiet_title fixtures' convention).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.newspapers import column_legal_notices as C

PRESENT_RECORD_OWNER_BODY = """
Taylor 32114

NOTICE OF FORECLOSURE SALE

26SP000144-110

Under and by virtue of the power of sale contained in a certain Deed of
Trust made by Robert R. Taylor (Deceased) (PRESENT RECORD OWNER(S): Robert
R. Taylor) to Jennifer Grant, Trustee(s), dated September 28, 2012, and
recorded in Book No. 2047, at Page 40 in Burke County Registry, North
Carolina, default having been made in the payment of the promissory note
secured by the said Deed of Trust and the undersigned, Substitute Trustee
Services, Inc., having been substituted as Trustee in said Deed of Trust,
and the holder of the note evidencing said indebtedness having directed
that the Deed of Trust be foreclosed, the undersigned Substitute Trustee
will offer for sale at the courthouse door of Burke County, North Carolina,
at 11:00 AM on October 15, 2026.

Address of Property: 100 Main Street, Morganton, NC 28655
"""

MULTI_OWNER_PARENTHETICAL_BODY = """
Coy 12525

NOTICE OF FORECLOSURE SALE

26SP000182-110

Under and by virtue of the power of sale contained in a certain Deed of
Trust made by Nicole Kay Coy and Scott M. Coy (PRESENT RECORD OWNER(S):
Nicole Kay Coy and Scott M. Coy) to James R. Ayers, Trustee(s), dated March
15, 2016, and recorded in Book No. 2227, at Page 648 in Burke County
Registry, North Carolina.
"""

GRANTOR_ONLY_BODY = """
SUBSTITUTE TRUSTEE'S AMENDED NOTICE OF SALE OF REAL PROPERTY

THIS ACTION BROUGHT PURSUANT TO THE POWER AND AUTHORITY contained within
that certain Deed of Trust executed and delivered by Kenneth Sprouse and
Adele Sprouse dated February 25, 2005 and recorded on March 11, 2005 in Book
1443 at Page 642 in the Office of Register of Deeds of Burke County, North
Carolina. As a result of a default in the obligations contained within the
Promissory Note and Deed of Trust and the failure to carry out and perform
the stipulations and agreements contained therein, the holder of the
indebtedness secured will offer for sale on October 20, 2026.
"""


def test_present_record_owner_parenthetical_form_is_captured():
    parsed = C._parse_nc_foreclosure(PRESENT_RECORD_OWNER_BODY)
    assert parsed.get("owner_name") == "Robert R. Taylor"
    # Confirm the closing-paren fix didn't break the address parse right after it.
    assert parsed.get("street_address") == "100 Main Street"


def test_multi_owner_parenthetical_form_keeps_both_names():
    parsed = C._parse_nc_foreclosure(MULTI_OWNER_PARENTHETICAL_BODY)
    assert parsed.get("owner_name") == "Nicole Kay Coy and Scott M. Coy"


def test_grantor_fallback_used_when_no_record_owner_label():
    parsed = C._parse_nc_foreclosure(GRANTOR_ONLY_BODY)
    assert parsed.get("owner_name") == "Kenneth Sprouse and Adele Sprouse"


def test_labelled_record_owners_form_still_works():
    """Regression guard: the original 'Record Owners: X Address of Property:
    Y' (template A / SECU-Nodell-Glass) form must still parse unchanged."""
    body = (
        "Date of Sale: October 15, 2026 Special Proceedings No. 26SP000999-110 "
        "Substitute Trustee: Jane A. Smith Record Owners: John Q Public "
        "Address of Property: 200 Oak Street, Morganton, NC 28655 "
        "PIN: 1234567890"
    )
    parsed = C._parse_nc_foreclosure(body)
    assert parsed.get("owner_name") == "John Q Public"
    assert parsed.get("street_address") == "200 Oak Street"


def test_address_of_property_stops_before_parenthetical_pin_aside():
    """Regression: found live 2026-10-01 on Rutherford County. The address is
    followed by a parenthetical PIN aside with no other boundary word before
    it; the opening '(' isn't in the capture's character class, so with no
    stop point the whole match used to fail and street_address was None."""
    body = (
        "Date of Sale: October 15, 2026 Special Proceedings No. 26SP000700-640 "
        "Address of Property: 149 Shenandoah Drive (PIN 1630-21-5228) and "
        "Vacant Lot, Shenandoah Drive (PIN 1630-21-5265) Deed of Trust: Book "
        "1058 Page: 758 Dated: November 2, 2020"
    )
    parsed = C._parse_nc_foreclosure(body)
    assert parsed.get("street_address") == "149 Shenandoah Drive"


def test_located_at_prose_fallback_when_no_address_label():
    """Regression: found live 2026-10-01 on Burke County (Hutchens/Substitute
    Trustee Services template) -- no 'Address of Property'/'Property
    Address'/'ADDRESS/LOCATION' label at all, only prose naming the address
    near the end of the legal description."""
    body = (
        "BEING all and the full contents of Lot Number 18 of Lake Hickory "
        "Hills Subdivision as shown on that certain plat recorded in Plat "
        "Book 11 at Page 171 Burke County Registry. Together with "
        "improvements located thereon; said property being located at 2101 "
        "Wildwood Drive, Hickory, North Carolina. This conveyance is made "
        "subject to restrictions recorded in Book 875 at Page 852."
    )
    parsed = C._parse_nc_foreclosure(body)
    assert parsed.get("street_address") == "2101 Wildwood Drive"
    assert parsed.get("city") == "Hickory"


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "counties.column_legal_notices" in {s.slug for s in all_scrapers()}

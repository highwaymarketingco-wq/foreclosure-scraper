"""Column legal-notice contact extraction — email AND phone from the notice body.

Added 2026-08-14: the scraper grabbed the attorney/trustee EMAIL but walked past the
PHONE printed in the same body. This locks in phone capture AND the guard that rejects
the parcel-PIN / case-number / amount false positives that a naive \\d{10} regex hit.
The phone is the TRUSTEE/attorney (a case contact), never promoted to owner_phone.
"""
from foreclosure_scraper.scrapers.newspapers import column_legal_notices as C


def test_phone_and_email_from_trustee_block():
    r = C._notice_email(
        "Substitute Trustee Services, Inc. Attorney for Trustee. Phone: (704) 333-8107. "
        "jane@brockscott.com PIN 1566620782 File 26SP000132")
    assert r["phone"] == "(704) 333-8107"
    assert r["email"] == "jane@brockscott.com"
    assert r["contact_role"] == "trustee/attorney"


def test_phone_only_no_email_is_still_captured():
    r = C._notice_email(
        "The Kania Law Firm, P.A., Substitute Trustee, Telephone 828-252-8010. Parcel 909421.")
    assert r["phone"] == "(828) 252-8010"
    assert r.get("email") is None


def test_parcel_pin_and_case_number_are_not_mistaken_for_a_phone():
    # bare 10-digit strings (PIN, amount) have no separators -> must NOT match
    r = C._notice_email(
        "RECORD OWNER: John Smith. PIN 2026004734. Case 25SP000049-800. Amount 9625783851.")
    assert r == {} or r.get("phone") is None


def test_bad_area_or_exchange_rejected():
    # 011-... / 1xx exchange are not valid NANP numbers -> rejected
    assert C._norm_phone("011-555-0199") is None
    assert C._norm_phone("704-133-0199") is None      # exchange starts with 1
    assert C._norm_phone("(704) 333-8107") == "(704) 333-8107"
    assert C._norm_phone("1-828-252-8010") == "(828) 252-8010"  # strips leading 1

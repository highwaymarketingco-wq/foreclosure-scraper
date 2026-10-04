"""The Coastland Times (Dare NC) public-notices scraper — audited 2026-10-01.

Live findings (HERMES sec 8 per-source audit, newspaper/legal-notice tier):

1. Many substitute-trustee notices use a LABELED-field template ("Record
   Owners: ... Address of Property: ... Grantors: ...") instead of the
   "said property being located at <street>" prose the original parser
   expected. Before the fix, the generic ADDR_RE fallback matched the
   template's OWN "Time of Sale: 10:30 a.m. Place of Sale:" boilerplate as a
   FABRICATED street address ("30 a.m. Place") -- a wrong value in a REAL
   listing, the exact "silent success" failure mode this codebase is built
   to catch -- while the genuine address and owner sat a few words later
   under their own clean labels, never read at all.
2. Tax-foreclosure (Commissioner's sale) notices date the sale as an ordinal
   clause ("...will on the 17th day of July, 2026, offer for sale...") with
   an "at 12:00 o'clock, noon" time, neither of which the "on <Month> <day>,
   <year>" / "<H>:<MM> AM/PM" patterns matched -- sale_date/sale_time were
   silently None despite the date being plainly stated.

Offline tests build minimal HTML matching the real page shape (an <h1> and a
<main> of <p> tags, per `_extract_body()`) from live-captured body text, and
monkeypatch `get_text` so no network call is made.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import main
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.newspapers import coastland_times as mod

# Live-captured body text (2026-10-01), reconstructed as a page the module's
# own _extract_body() parses the same way the real site's HTML does.
_LABELED_TEMPLATE_BODY = (
    "Special Proceedings No. 25SP000163-270 Substitute Trustee: NOTICE OF "
    "FORECLOSURE SALE Date of Sale: July 14, 2026 Time of Sale: 10:30 a.m. "
    "Place of Sale: Dare County Courthouse Description of Property: See "
    "Attached Description Record Owners: Heirs of Janson Fros Address of "
    "Property: 4013 Mill Landing Road Wanchese, NC 27981 Book : 2350 Page: "
    "773 Dated: January 24, 2020 Grantors: Janson Fros, unmarried Original "
    "Beneficiary: State Employees' Credit Union CONDITIONS OF SALE: This "
    "sale is made subject to all unpaid taxes and superior liens."
)

_ORDINAL_DATE_BODY = (
    "NOTICE OF TAX FORECLOSURE SALE Under and by virtue of an order of the "
    "District Court of Tyrrell County, North Carolina, made and entered in "
    "the action entitled COUNTY OF TYRRELL vs. THE HEIRS OF SOME DECEDENT, "
    "15CVD000021-880, the undersigned Commissioner will on the 17th day of "
    "July, 2026, offer for sale and sell for cash, to the last and highest "
    "bidder at public auction at the courthouse door in Tyrrell County, "
    "North Carolina, at 12:00 o'clock, noon, the following described real "
    "property, lying and being in Columbia Township, and more particularly "
    "described as follows: Beginning on the back road or street."
)


def _page(headline: str, body: str) -> str:
    return (
        f"<html><body><h1>{headline}</h1>"
        f"<main><p>{body}</p></main></body></html>"
    )


def test_labeled_address_template_not_fabricated_from_time_of_sale(monkeypatch):
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", _LABELED_TEMPLATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/a9aad57b",
        "newspapers.coastland_times",
    )
    assert li is not None
    # The real labeled address, not "30 a.m. Place" fabricated from the
    # "Time of Sale: 10:30 a.m. Place of Sale:" boilerplate.
    assert li.street_address == "4013 Mill Landing Road"
    assert li.city == "Wanchese"
    assert li.zip_code == "27981"
    assert "a.m." not in (li.street_address or "").lower()
    assert "place" not in (li.street_address or "").lower()
    # Owner wired from the "Record Owners:" label.
    assert li.owner_name == "Heirs of Janson Fros"
    assert li.defendant == "Heirs of Janson Fros"
    assert li.case_number == "25SP000163-270"


def test_grantors_label_used_when_no_record_owners_label():
    body = _LABELED_TEMPLATE_BODY.replace(
        "Record Owners: Heirs of Janson Fros ", ""
    )
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", body),
        "https://www.thecoastlandtimes.com/public-notices/grantors-only",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.owner_name == "Janson Fros, unmarried"


def test_ordinal_date_and_oclock_time_parsed():
    li = mod._parse_detail(
        _page("NOTICE OF TAX FORECLOSURE SALE", _ORDINAL_DATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/e9388d56",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.sale_date is not None
    assert (li.sale_date.month, li.sale_date.day, li.sale_date.year) == (7, 17, 2026)
    assert li.sale_time == "12:00 PM"
    assert li.case_number == "15CVD000021-880"


def test_am_place_boilerplate_rejected_even_without_address_label():
    """Defense in depth: even on a notice that lacks the 'Address of
    Property:' label entirely, the generic ADDR_RE fallback must not accept
    the 'Time of Sale: X a.m. Place of Sale:' phrase as a street address."""
    body = (
        "NOTICE OF FORECLOSURE SALE Date of Sale: July 14, 2026 Time of "
        "Sale: 10:30 a.m. Place of Sale: Dare County Courthouse Description "
        "of Property: See Attached Description."
    )
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", body),
        "https://www.thecoastlandtimes.com/public-notices/no-label",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.street_address is None


def _run_fetch(monkeypatch, detail_html: str):
    index_html = (
        '<html><body><a href="/public-notices/notice-of-foreclosure-sale-a9aad57b">'
        "link</a></body></html>"
    )

    async def fake_get_text(url, timeout=30.0, headers=None):
        if "/public-notices/notice-of-foreclosure-sale-a9aad57b" in url:
            return detail_html
        return index_html

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    return asyncio.run(mod.CoastlandTimesForeclosures().fetch())


def test_fetch_end_to_end_with_labeled_template(monkeypatch):
    detail_html = _page("NOTICE OF FORECLOSURE SALE", _LABELED_TEMPLATE_BODY)
    out = _run_fetch(monkeypatch, detail_html)
    assert len(out) == 1
    assert out[0].street_address == "4013 Mill Landing Road"
    assert out[0].owner_name == "Heirs of Janson Fros"


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert "newspapers.coastland_times" in {s.slug for s in all_scrapers()}


# --- FOUND 2026-10-04 (HERMES extraction-completeness audit, newspapers ------
# --- batch 1): scope-gate dead-on-arrival bug + county mislabel + parcel miss


def test_dare_substitute_trustee_sale_classified_lis_pendens_and_in_scope():
    """The dominant real shape (a scheduled substitute-trustee SALE) used to
    ship ListingType.FORECLOSURE_SALE (a flip type). Dare is never in the
    18-county flip footprint, so main._in_scope() silently dropped every
    single row this scraper ever produced -- confirmed by calling the REAL
    function, not a mock."""
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", _LABELED_TEMPLATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/a9aad57b",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.listing_type == ListingType.LIS_PENDENS
    assert li.county == "Dare"
    assert main._in_scope(li) is True


def test_tax_foreclosure_sale_classified_tax_sale_and_in_scope():
    li = mod._parse_detail(
        _page("NOTICE OF TAX FORECLOSURE SALE", _ORDINAL_DATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/e9388d56",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.listing_type == ListingType.TAX_SALE
    assert main._in_scope(li) is True


def test_unfixed_foreclosure_sale_type_was_unreachable_for_dare():
    """Documents the bug directly: the OLD hardcoded
    listing_type=FORECLOSURE_SALE for Dare county is unreachable regardless
    of any other field -- confirming the type remap (not county) is what
    fixes reachability."""
    import copy

    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", _LABELED_TEMPLATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/a9aad57b",
        "newspapers.coastland_times",
    )
    old = copy.copy(li)
    old.listing_type = ListingType.FORECLOSURE_SALE
    assert main._in_scope(old) is False


def test_real_county_named_in_body_overrides_dare_default():
    """Regression: a real live Tyrrell County tax-foreclosure notice was
    being stamped county="Dare" unconditionally even though its own body
    names Tyrrell 3 times ("District Court of Tyrrell County"... "courthouse
    door in Tyrrell County"... "Tyrrell County Register of Deeds")."""
    li = mod._parse_detail(
        _page("NOTICE OF TAX FORECLOSURE SALE", _ORDINAL_DATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/e9388d56",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.county == "Tyrrell"
    assert li.sale_location == "Tyrrell County Courthouse, North Carolina"


def test_dare_default_kept_when_no_county_named():
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", _LABELED_TEMPLATE_BODY),
        "https://www.thecoastlandtimes.com/public-notices/a9aad57b",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.county == "Dare"
    assert li.sale_location == "Dare County Courthouse, Manteo NC"


def test_parcel_identification_number_label_with_space_separated_id():
    """Regression: a real live Tyrrell notice states "Parcel Identification
    Number: C005 19 010" in plain text. The old PARCEL_RE required "Parcel"
    to be followed directly by "Number/No/ID" (no "Identification") and had
    no way to match a space-separated value, so this real, stated parcel
    number was silently dropped."""
    body = (
        "NOTICE OF TAX FORECLOSURE SALE Parcel Identification Number: "
        "C005 19 010 The undersigned Commissioner makes no warranties."
    )
    li = mod._parse_detail(
        _page("NOTICE OF TAX FORECLOSURE SALE", body),
        "https://www.thecoastlandtimes.com/public-notices/parcel-id",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.parcel_id == "C005 19 010"


def test_parcel_number_label_still_matches_single_token():
    """No regression on the original, already-working label form."""
    body = (
        "NOTICE OF FORECLOSURE SALE said property being located at 22083 "
        "Sea Gull Street, Rodanthe, North Carolina, Dare County Parcel "
        "Number 012458006."
    )
    li = mod._parse_detail(
        _page("NOTICE OF FORECLOSURE SALE", body),
        "https://www.thecoastlandtimes.com/public-notices/parcel-orig",
        "newspapers.coastland_times",
    )
    assert li is not None
    assert li.parcel_id == "012458006"

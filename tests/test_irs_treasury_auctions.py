"""national.irs_treasury — extraction-completeness audit (batch 16, 2026-10-04).

Live-verified against the one real NC auction currently posted
(irsauctions.gov/ad/half-interest-house-acreage, "Half interest in a house
and acreage!!!", Henderson NC). The old code's opening_bid was None on every
row ever produced (required a literal "$" the live page never prints), the
county came from a tiny hardcoded city dict (and didn't even know
"henderson"), and owner name / property specs / parcel number / government
contact / linked PDFs were never captured at all despite all being plainly
on the page. These tests pin the fix against a synthetic fixture that
mirrors the REAL page's class names and phrasing (confirmed live via direct
fetch+selectolax inspection, not guessed).
"""
from __future__ import annotations

from unittest.mock import Mock, patch

from selectolax.parser import HTMLParser

from foreclosure_scraper.models import PropertyKind
from foreclosure_scraper.scrapers.national.irs_treasury_auctions import (
    _extract_address_block,
    _extract_contact,
    _extract_county_from_text,
    _extract_minimum_bid,
    _extract_owner_name,
    _extract_pdf_links,
    _extract_property_specs,
    _fetch_irs_sync,
)

# A compact synthetic detail page mirroring the REAL irsauctions.gov markup
# (class names + phrasing confirmed live 2026-10-04 against
# /ad/half-interest-house-acreage) -- not a guess.
_REAL_SHAPE_DETAIL_HTML = """
<html><body>
<h1>Half interest in a house and acreage!!!</h1>
<div class="field field--name-field-asset-description field--type-text-long">
  <div class=title>Asset Description</div>
  <div class=field__item><p>Willie J. Sessions's one-half interest in a
  4,234 (2,604 living) sq. ft. 4 bedroom/3.5 bathroom Single Family
  Residence built in 1987 situated on 5.01 acres more commonly known as 340
  Cedar Grove Dr., Henderson, NC 27537 (Parcel No. 0209 02027) as well as
  the adjoining 29.31 acres of residential land more commonly known as
  Turner Land (Parcel No. 0209 02028).</p></div>
</div>
<div class="field field--name-field-property-address field--type-address">
  <div class=title>Asset Address</div>
  <div class=field__item><address translate=no>340 Cedar Grove Dr.<br>Henderson, 27537 NC<br>United States</address></div>
</div>
<div class="field field--name-field-notice-information field--type-string-long">
  <div class=title>Notice Information</div>
  <div class=field__item>Notice of Public Auction Sale<br>Under the
  authority in Internal Revenue Code section 6331, the property described
  below has been seized for nonpayment of internal revenue taxes due from
  Willie J. Sessions. The property will be sold at public auction as
  provided by Internal Revenue Code section 6335 and related regulations.</div>
</div>
<div class="field field--name-field-legal-description field--type-string-long">
  <div class=title>Legal Description</div>
  <p class=field__item>TRACT NO. 1: ... Henderson Township, Vance County,
  North Carolina ... recorded in Plat Book U Page 553 Vance County Registry.</p>
</div>
<div class="field field--name-field-minimum-bid field--type-decimal">
  <div class=title>Minimum Bid</div>
  <div content="81480.00" class=field__item>81,480.00</div>
</div>
<div class="field field--name-field-notice-of-encumbrances field--type-entity-reference">
  <span class="file file--mime-application-pdf"><a href=/sites/default/files/100/SESS_340_Cedar_Grove_F2434B_07012026_signed.pdf type=application/pdf>notice</a></span>
</div>
<div class="field field--name-field-order-of-sale field--type-entity-reference">
  <span class="file file--mime-application-pdf"><a href=/sites/default/files/100/SESS_F2434_340_Cedar_Grove_Dr_8262026_signed.pdf type=application/pdf>order</a></span>
</div>
<div class="field field--name-field-contact-information field--type-address">
  <div class=title>Contact Information</div>
  <div class=field__item><p class=address translate=no>
    <span class=given-name>Paul Reed, Property Appraisal &amp; Liquidation Specialist</span><br>
    <span class=organization>Internal Revenue Service</span><br>
    <a href="mailto:paul.reed@irs.gov?subject=Question">paul.reed@irs.gov</a>
  </p></div>
</div>
<div class="field field--name-field-contact-phone">
  <div class=title>Contact Phone Number</div>
  <div class=field__item>770-826-1271</div>
</div>
</body></html>
"""


def _tree() -> HTMLParser:
    return HTMLParser(_REAL_SHAPE_DETAIL_HTML)


def _full_text() -> str:
    t = _tree()
    return t.body.text(separator=" ") if t.body else ""


class TestMinimumBid:
    def test_reads_the_content_attribute_not_a_dollar_sign(self):
        """THE core bug: the live page never prints a literal '$' near the
        amount (confirmed live) -- a $-only regex returns None on every
        real row. The clean value lives in content="81480.00"."""
        assert _extract_minimum_bid(_tree(), _full_text()) == 81480.00

    def test_falls_back_to_a_dollar_sign_if_that_is_all_a_page_has(self):
        html = "<html><body><p>Minimum bid: $45,000.</p></body></html>"
        tree = HTMLParser(html)
        text = tree.body.text()
        assert _extract_minimum_bid(tree, text) == 45000.0

    def test_no_bid_anywhere_returns_none(self):
        html = "<html><body><p>no bid info here</p></body></html>"
        tree = HTMLParser(html)
        assert _extract_minimum_bid(tree, tree.body.text()) is None


class TestCountyFromLegalDescription:
    def test_real_county_beats_the_ambiguous_city_name(self):
        """Henderson the CITY (zip 27537) is in Vance County -- a different
        place from Henderson COUNTY, NC (seat Hendersonville). The old code
        guessed from the city name via a tiny hardcoded dict that didn't
        even contain "henderson". The real county is always stated in the
        legal description."""
        assert _extract_county_from_text(_full_text()) == "Vance"

    def test_no_county_mentioned_returns_none(self):
        assert _extract_county_from_text("no county token in this text") is None


class TestOwnerName:
    def test_middle_initial_period_does_not_truncate_the_name(self):
        """'due from Willie J. Sessions.' -- a naive 'stop at the first
        period' regex cuts this to just 'Willie J' (confirmed on the real
        page before this fix). Anchoring on the next sentence recovers the
        full name."""
        assert _extract_owner_name(_full_text()) == "Willie J. Sessions"

    def test_name_without_middle_initial_still_works_via_fallback(self):
        text = "taxes due from Jane Smith. The property will be auctioned."
        # No "The property will be sold" phrase -> exercises the fallback.
        assert _extract_owner_name(text) == "Jane Smith"

    def test_no_match_returns_none(self):
        assert _extract_owner_name("nothing relevant here") is None


class TestPropertySpecs:
    def test_full_spec_extraction_from_the_asset_description(self):
        specs = _extract_property_specs(_full_text())
        assert specs["total_sqft"] == 4234.0
        assert specs["living_sqft"] == 2604.0
        assert specs["bedrooms"] == 4.0
        assert specs["bathrooms"] == 3.5
        assert specs["year_built"] == 1987
        assert specs["acreage"] == 5.01
        assert specs["property_kind"] == PropertyKind.SINGLE_FAMILY

    def test_parcel_numbers_are_not_truncated_at_the_internal_space(self):
        """'Parcel No. 0209 02027' is TWO whitespace-separated groups -- a
        bare \\w+ match stops at the first space and captures only '0209'
        (confirmed live before this fix). Both parcels on this page must
        survive, not just the first fragment of the first one."""
        specs = _extract_property_specs(_full_text())
        assert specs["parcel_ids"] == ["0209 02027", "0209 02028"]

    def test_no_specs_text_returns_empty_dict_not_a_crash(self):
        assert _extract_property_specs("") == {"parcel_ids": []}


class TestContactInfo:
    def test_captures_name_org_email_phone(self):
        contact = _extract_contact(_tree())
        assert contact["name"] == "Paul Reed, Property Appraisal & Liquidation Specialist"
        assert contact["organization"] == "Internal Revenue Service"
        assert contact["email"] == "paul.reed@irs.gov"  # mailto query string stripped
        assert contact["phone"] == "770-826-1271"

    def test_no_contact_block_returns_empty_dict(self):
        tree = HTMLParser("<html><body><p>nothing</p></body></html>")
        assert _extract_contact(tree) == {}


class TestPdfLinks:
    def test_unquoted_href_attributes_are_still_found(self):
        """This Drupal/USWDS theme renders many hrefs UNQUOTED
        (href=/sites/.../x.pdf, no quote marks at all) -- confirmed live.
        document_links.harvest_document_links()'s regex requires a quoted
        value and would miss these entirely; selectolax's parsed tree
        normalizes the quoting away, so pulling from the tree (not a raw
        regex over the HTML string) is required."""
        links = _extract_pdf_links(_tree(), "https://www.irsauctions.gov/ad/x")
        assert len(links) == 2
        assert all(u.startswith("https://www.irsauctions.gov/sites/") for u in links)
        assert any("F2434B_07012026_signed.pdf" in u for u in links)
        assert any("8262026_signed.pdf" in u for u in links)

    def test_relative_pdf_links_are_absolutized_against_the_ad_url(self):
        tree = HTMLParser('<html><body><a href="docs/notice.pdf">x</a></body></html>')
        links = _extract_pdf_links(tree, "https://www.irsauctions.gov/ad/foo")
        assert links == ["https://www.irsauctions.gov/ad/docs/notice.pdf"]


class TestAddressBlock:
    def test_parses_the_unusual_city_comma_zip_state_order(self):
        """The live 'Asset Address' field prints 'Henderson, 27537 NC' --
        city, ZIP, STATE, not the usual city/state/zip order."""
        street, city, state, zip_code = _extract_address_block(_tree())
        assert street == "340 Cedar Grove Dr."
        assert city == "Henderson"
        assert state == "NC"
        assert zip_code == "27537"

    def test_missing_address_block_returns_all_none(self):
        tree = HTMLParser("<html><body><p>no address field here</p></body></html>")
        assert _extract_address_block(tree) == (None, None, None, None)


def _fake_response(text: str, status_code: int = 200) -> Mock:
    r = Mock()
    r.status_code = status_code
    r.text = text
    return r


class TestEndToEndFetch:
    """Full _fetch_irs_sync() run against the real-shaped fixture, mocking
    only the network layer (cf.get) -- proves every extractor is actually
    wired together correctly, not just correct in isolation."""

    def test_real_shaped_ad_produces_a_fully_populated_listing(self):
        items_html = (
            "<html><body>" + "x" * 1000
            + '<a href="/ad/half-interest-house-acreage">Half interest</a>'
            + "</body></html>"
        )

        def _get(url, **kw):
            if url.endswith("/auction/items"):
                return _fake_response(items_html)
            return _fake_response(_REAL_SHAPE_DETAIL_HTML)

        with patch(
            "foreclosure_scraper.scrapers.national.irs_treasury_auctions.cf.get",
            side_effect=_get,
        ):
            out = _fetch_irs_sync()

        assert len(out) == 1
        li = out[0]
        assert li.state == "NC"
        assert li.county == "Vance"  # from the legal description, not a city guess
        assert li.city == "Henderson"
        assert li.zip_code == "27537"
        assert li.street_address == "340 Cedar Grove Dr."
        assert li.owner_name == "Willie J. Sessions"
        assert li.parcel_id == "0209 02027"
        assert li.property_kind == PropertyKind.SINGLE_FAMILY
        assert li.bedrooms == 4.0
        assert li.bathrooms == 3.5
        assert li.living_sqft == 2604.0
        assert li.year_built == 1987
        assert li.acreage == 5.01
        assert li.opening_bid == 81480.00  # was None on every row before this fix

        irs_raw = li.raw["irs_treasury"]
        assert irs_raw["parcel_ids"] == ["0209 02027", "0209 02028"]
        assert irs_raw["county_source"] == "legal_description"
        assert irs_raw["contact"]["email"] == "paul.reed@irs.gov"
        assert irs_raw["contact"]["phone"] == "770-826-1271"

        # document_links.stamp_documents() wiring -- both linked PDFs survive.
        assert len(li.raw["documents"]) == 2
        assert li.raw["document_url"] in li.raw["documents"]

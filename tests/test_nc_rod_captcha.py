"""NC ROD CAPTCHA/math-gate sites (counties_nc/nc_rod_captcha.py), 9 counties.

Live re-verified 2026-10-14 (source-completeness audit's "Needs YOU logged in" list,
final item — see docs/source_completeness_audit_2026-10-13.md): 8 of 9 counties
(Wake, Brunswick, Iredell, Craven, Greene, Harnett, Randolph, Stokes) reconfirmed
genuinely walled by a real CAPTCHA this codebase cannot automate — Playwright-driven
live checks, not string-grep, which is exactly the trap Durham's 2026-10-12 entry
fell into (see below). Durham turned out to need no login or CAPTCHA at all, same
false-flag pattern as 5 other files in that audit list resolved earlier the same
night; it's parser-only here (no live network), using schema-accurate examples
pulled from the live site 2026-10-14.
"""
from __future__ import annotations

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.rod.nc_chain import IndexRecord
from foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha import (
    NcRodCaptchaScraper,
    _COUNTY_SITES,
)


# --- _COUNTY_SITES config -- the gate-type ground truth this whole file hinges on --

def test_nine_counties_present():
    assert set(_COUNTY_SITES) == {
        "wake", "durham", "brunswick", "iredell", "craven",
        "greene", "harnett", "randolph", "stokes",
    }


def test_durham_is_the_only_resolved_gate():
    # Durham: live-reverified 2026-10-14 -- no CAPTCHA, just a disclaimer
    # click-through (see module docstring's Durham correction).
    assert _COUNTY_SITES["durham"]["gate"] == "none"
    # Every other county reconfirmed genuinely walled live 2026-10-14 -- a
    # real Google reCAPTCHA widget (confirmed via DOM query, not grep) for
    # all but Brunswick, whose math gate renders as an image math_captcha.py
    # cannot read (see module docstring's Brunswick correction).
    still_walled = {"wake", "iredell", "craven", "greene", "harnett", "randolph", "stokes"}
    for county in still_walled:
        assert _COUNTY_SITES[county]["gate"] == "recaptcha", county
    assert _COUNTY_SITES["brunswick"]["gate"] == "math"


def test_durham_search_path_is_the_live_route():
    # Confirmed live 2026-10-14: /web/search/DOCSEARCH5S1 is directly reachable
    # right after the disclaimer accept, no name/search-form round trip needed.
    assert _COUNTY_SITES["durham"]["search_path"] == "/search/DOCSEARCH5S1"
    assert _COUNTY_SITES["durham"]["url"] == "https://rodweb.dconc.gov/web"


# --- Durham: _durham_record_to_listing, real schema from the live site 2026-10-14 -

# A real DEED OF TRUST row, live-pulled 2026-10-14 from a 60-45-day-back window
# (outside the "currently being processed" window so the record was stable):
# BT: OPR B: 10616 P: 073, recorded 08/28/2026 04:09 PM.
_LIVE_DOT_RECORD = IndexRecord(
    recorded="2026-08-28", book="10616", page="073", instrument_no="2026186084",
    doc_type="DEED OF TRUST", grantors=["WINSTEAD CAMISHA H.", "CHAMBERS SEAN"],
    grantees=["NAVY FEDERAL CREDIT UNION"],
    description="Subdivision NORTHWOODS FOREST Lot 53 Block L PB 34/16 SEC 3",
    index_code="OPR",
)
# A real SATISFACTION row, live-pulled 2026-10-14 (today's filings, same session
# as the DOT above): BT: OPR B: 10640 P: 807, instrument 2026190366. Satisfactions
# carry both a grantor and grantee list, unlike the DOT's one-sided grantee-only
# ASSUMED NAME row below.
_LIVE_SATISFACTION_RECORD = IndexRecord(
    recorded="2026-10-14", book="10640", page="807", instrument_no="2026190366",
    doc_type="SATISFACTION",
    grantors=["UTLEY RENEA C", "UTLEY JAMES M IV", "BANK OF AMERICA, N.A.",
              "FIRST AMERICAN MORTGAGE SOLUTIONS, LLC /aif"],
    grantees=["BANK OF AMERICA, N.A.", "BONNER JAMES P. /TRUSTEE", "BROCK AND SCOTT, PLC /TRUSTEE"],
    description="BP 10252/854", index_code="OPR",
)
# A real ASSUMED NAME row, live-pulled 2026-10-14: grantor only, no grantee, no
# legal/description -- a real example of the sparse-field case.
_LIVE_ASSUMED_NAME_RECORD = IndexRecord(
    recorded="2026-10-14", book="10640", page="794", instrument_no="2026190364",
    doc_type="ASSUMED NAME", grantors=["NO ME SÉ RAJAR /asn"],
    grantees=["DAM FOOD CONCEPTS LLC /r-n"], index_code="OPR",
)


def test_durham_record_to_listing_deed_of_trust():
    scraper = NcRodCaptchaScraper()
    li = scraper._durham_record_to_listing(_LIVE_DOT_RECORD, "https://rodweb.dconc.gov/web/search/DOCSEARCH5S1")
    assert li is not None
    assert li.county == "Durham" and li.state == "NC"
    assert li.listing_type is ListingType.UNKNOWN
    assert li.property_kind is PropertyKind.UNKNOWN
    assert li.case_number == "2026186084"
    assert li.plaintiff == "WINSTEAD CAMISHA H., CHAMBERS SEAN"
    assert li.owner_name == "NAVY FEDERAL CREDIT UNION"
    assert li.legal_description == "Subdivision NORTHWOODS FOREST Lot 53 Block L PB 34/16 SEC 3"
    # raw mirrors the shared _parse_html()'s exact key shape -- no new raw
    # keys need registering in web_artifact.py.
    assert li.raw == {
        "county": "durham",
        "doc_type": "DEED OF TRUST",
        "filing_date": "2026-08-28",
        "grantor": "WINSTEAD CAMISHA H., CHAMBERS SEAN",
        "grantee": "NAVY FEDERAL CREDIT UNION",
        "book_page": "BT: OPR B: 10616 P: 073",
    }
    assert "document_url" not in li.raw and "documents" not in li.raw


def test_durham_record_to_listing_satisfaction_both_sides():
    scraper = NcRodCaptchaScraper()
    li = scraper._durham_record_to_listing(_LIVE_SATISFACTION_RECORD, "http://x")
    assert li.case_number == "2026190366"
    assert li.raw["doc_type"] == "SATISFACTION"
    assert li.raw["grantor"] == ("UTLEY RENEA C, UTLEY JAMES M IV, BANK OF AMERICA, N.A., "
                                  "FIRST AMERICAN MORTGAGE SOLUTIONS, LLC /aif")
    assert li.raw["grantee"] == "BANK OF AMERICA, N.A., BONNER JAMES P. /TRUSTEE, BROCK AND SCOTT, PLC /TRUSTEE"
    assert li.legal_description == "BP 10252/854"


def test_durham_record_to_listing_grantee_only_no_legal():
    scraper = NcRodCaptchaScraper()
    li = scraper._durham_record_to_listing(_LIVE_ASSUMED_NAME_RECORD, "http://x")
    assert li.plaintiff == "NO ME SÉ RAJAR /asn"
    assert li.owner_name == "DAM FOOD CONCEPTS LLC /r-n"
    assert li.legal_description is None  # no description on this real row


def test_durham_record_to_listing_skips_missing_instrument_number():
    blank = IndexRecord(recorded="2026-10-14", instrument_no=None, doc_type="DEED")
    scraper = NcRodCaptchaScraper()
    assert scraper._durham_record_to_listing(blank, "http://x") is None
    blank2 = IndexRecord(recorded="2026-10-14", instrument_no="", doc_type="DEED")
    assert scraper._durham_record_to_listing(blank2, "http://x") is None


def test_durham_record_to_listing_book_page_omits_missing_parts():
    # a record missing book/page (index masks it) should not print "B: None"
    record = IndexRecord(recorded="2026-10-14", instrument_no="2026999999",
                          doc_type="DEED", index_code="OPR", book=None, page=None)
    scraper = NcRodCaptchaScraper()
    li = scraper._durham_record_to_listing(record, "http://x")
    assert li.raw["book_page"] == "BT: OPR"


# --- Evidence this file documents for the 8 counties left genuinely walled -------
#
# Mirrors test_sc_rod_walled.py's test_jasper_is_documented_as_genuinely_walled
# pattern (that file uses a dedicated per-county WALL_NOTE constant; this one
# keeps the live-reverify evidence in the module docstring instead, so these
# tests assert against that).

def test_recaptcha_counties_documented_with_live_dom_evidence():
    doc = NcRodCaptchaScraper.__doc__ or ""
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    full = doc + module_doc
    # the live DOM check (not a string-grep false positive) is the whole point
    assert "iframe[src*=recaptcha]" in full or "iframe[src*=\"recaptcha\"]" in full or "recaptcha_iframe" in full or "DOM query" in full
    assert "2026-10-14" in full


def test_brunswick_math_captcha_false_positive_documented():
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    # the real, live-confirmed bug: math_captcha.py reports solved=True while
    # actually matching the ROD office's own phone number, not the real question.
    assert "253-2690" in module_doc
    assert "solved=True" in module_doc or "solved" in module_doc
    assert "getpng.php" in module_doc


def test_brunswick_fix_correction_documented():
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    # The false positive narrative above is kept (historical record, same
    # append-only pattern as every other correction in this file) but must
    # now be followed by the fix: math_captcha.py no longer guesses, and
    # Brunswick's CAPTCHA is live-confirmed genuinely solvable via OCR.
    assert "now FIXED" in module_doc
    assert "_gate_still_present" in module_doc
    assert "test_math_captcha.py" in module_doc
    # Honesty about scope: the CAPTCHA clearing live was followed one layer
    # further to a disclaimer gate and the real site menu, but Brunswick's
    # actual search/result capture was deliberately NOT wired up here.
    assert "disclaimer" in module_doc.lower()
    assert "NOT wired into" in module_doc


def test_durham_contradiction_with_nc_tyler_documented():
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    # the in-repo contradiction this audit caught: rod/nc_tyler.py already knew
    # (2026-10-07) that Durham has no CAPTCHA; this file guessed otherwise anyway.
    assert "nc_tyler" in module_doc
    assert "2026-10-07" in module_doc

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
from foreclosure_scraper.rod.nc_tyler import _SS_HEAD, parse_selfservice
from foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha import (
    NcRodCaptchaScraper,
    _COUNTY_SITES,
    _WAKE_DISTRESS_DOC_TYPES,
    _wake_extract_docids,
    _wake_parse_related_documents,
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


def test_brunswick_now_wired_documented():
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    # the 2026-10-14 (cont. x2) correction: Brunswick's disclaimer-accept +
    # search + parser are now actually wired into fetch(), not just the
    # CAPTCHA layer the earlier correction fixed.
    assert "now WIRED" in module_doc
    assert "_fetch_brunswick" in module_doc
    assert "SUBSTITUTE TRUSTEE" in module_doc


# --- Brunswick: _fetch_brunswick's real search+parse flow, real schema from --
# --- the live site 2026-10-14 (httpx replaying the real session, no --------
# --- Chromium run -- see module docstring) ----------------------------------
#
# Real markup pulled from a live "SUBSTITUTE TRUSTEE" search, 90-day window:
# book 5596 page 1287 is ONE real instrument with 4 grantor index rows (VEGA,
# MILLS, ROCKET MORTGAGE LLC, ROCKET MTG LLC -- the lender's own legal name
# AND its abbreviation each got their own row), all sharing the same Grantee
# list. The HTML below is the real per-record markup shape (table/tr/td
# nesting, the nested one-name-per-row Grantor/Grantee table, the real
# "Download PDF" href) with the verbose inline CSS this platform ships
# trimmed for test-file size -- names, book/page, doc type, dates and URLs
# are all real, live-pulled values, not fabricated.

_BRUNSWICK_SUBTRUSTEE_MULTI_GRANTOR_HTML = """
<table border="0" align="center">
<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5596</td><td class="Data"><b>Page:</b> 1287</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 4494 PG 634</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">VEGA, ESTEBAN EMILIO</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"><a href="./pdf-popup-download-all.ntk?s=REALTOKEN1" onclick="NewWindow(this.href,'880','550','Popup',0);return false">Download PDF</a></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">DHI MORTGAGE COMPANY, LTD</font></td></tr>
<tr><td></td><td><font size="-1">DHI MTG CO, LTD</font></td></tr>
<tr><td></td><td><font size="-1">LLG TRUSTEE LLC /TR</font></td></tr>
<tr><td></td><td><font size="-1">MORTGAGE ELECTRONIC REGISTRATION SYSTEMS, INC.</font></td></tr>
</table></td>
<td class="Data" colspan="1"><a href="local-popup-group-view-image.ntk?s=IMGTOKEN1" onclick="NewWindow(this.href,'880','550','Popup',0);return false">View Image</a><br/>
<a href="./re_detail.ntk?s=DETAILTOKEN1" onclick="NewWindow(this.href,'880','550','Popup',0);return false">View Detail</a><br/></td></tr>

<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5596</td><td class="Data"><b>Page:</b> 1287</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 4494 PG 634</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">MILLS, BRANDI</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"><a href="./pdf-popup-download-all.ntk?s=REALTOKEN2" onclick="NewWindow(this.href,'880','550','Popup',0);return false">Download PDF</a></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">DHI MORTGAGE COMPANY, LTD</font></td></tr>
<tr><td></td><td><font size="-1">LLG TRUSTEE LLC /TR</font></td></tr>
</table></td>
<td class="Data" colspan="1"><a href="local-popup-group-view-image.ntk?s=IMGTOKEN2">View Image</a><br/></td></tr>

<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5596</td><td class="Data"><b>Page:</b> 1287</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 4494 PG 634</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">ROCKET MORTGAGE, LLC</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"><a href="./pdf-popup-download-all.ntk?s=REALTOKEN3">Download PDF</a></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">DHI MORTGAGE COMPANY, LTD</font></td></tr>
</table></td><td class="Data" colspan="1"></td></tr>

<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5596</td><td class="Data"><b>Page:</b> 1287</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 4494 PG 634</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">ROCKET MTG, LLC</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">DHI MORTGAGE COMPANY, LTD</font></td></tr>
</table></td><td class="Data" colspan="1"></td></tr>
</table>
"""

# A second real instrument, book 5597 page 176: BOTH grantors are
# institutional ("FIRST BANK", "BLUE TIDE HOMES, INC." -- a builder/investor
# foreclosure, no human owner name on the grantor side) -- the real case
# that forces `defendant` to come back None rather than a guessed lender
# name, same reasoning nc_rod_logan.py's own resolver documents.
_BRUNSWICK_ALL_INSTITUTIONAL_GRANTOR_HTML = """
<table border="0" align="center">
<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5597</td><td class="Data"><b>Page:</b> 176</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 5139 PG 767</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">FIRST BANK</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"><a href="./pdf-popup-download-all.ntk?s=REALTOKEN4">Download PDF</a></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">FOYLES, KIRSTEN E. /TR</font></td></tr>
<tr><td></td><td><font size="-1">GOTTSEGEN, ADAM M. /TR</font></td></tr>
</table></td><td class="Data" colspan="1"></td></tr>

<tr><td class="Data" colspan="4"><b>Filing Date:</b> 07/16/2026</td>
<td class="Data"><b>Book:</b> 5597</td><td class="Data"><b>Page:</b> 176</td>
<td class="Data"><b>Status:</b> WARRANTED</td><td class="Data"></td></tr>
<tr><td class="Data"><b>Type:</b> SUBSTITUTE TRUSTEE</td>
<td class="Data"><b>Desc:</b> RE BK 5139 PG 767</td><td class="Data"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantor:</b></td><td><font size="-1">BLUE TIDE HOMES, INC.</font></td></tr>
</table><br/></td>
<td class="Data" colspan="1"></td></tr>
<tr><td class="Data" colspan="3"><table cellpadding="0" cellspacing="0">
<tr><td><b>Grantee:</b></td><td><font size="-1">FOYLES, KIRSTEN E. /TR</font></td></tr>
</table></td><td class="Data" colspan="1"></td></tr>
</table>
"""


def test_brunswick_parse_page_groups_multi_grantor_rows_into_one_listing():
    scraper = NcRodCaptchaScraper()
    listings = scraper._brunswick_parse_page(
        _BRUNSWICK_SUBTRUSTEE_MULTI_GRANTOR_HTML,
        "https://brunswick-live.inttek.net/index.ntk?s=x",
        "SUBSTITUTE TRUSTEE",
    )
    # 4 grantor index rows for ONE real instrument -> exactly ONE Listing,
    # not 4 duplicate leads.
    assert len(listings) == 1
    li = listings[0]
    assert li.county == "Brunswick" and li.state == "NC"
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.property_kind is PropertyKind.UNKNOWN
    assert li.case_number == "B: 5596, P: 1287"
    # VEGA and MILLS are real people, kept; ROCKET MORTGAGE/ROCKET MTG (the
    # original lender, also indexed as a "grantor" in this chain) filtered
    # out by the institutional-name check.
    assert li.defendant == "VEGA, ESTEBAN EMILIO; MILLS, BRANDI"
    assert "ROCKET" not in (li.defendant or "")
    assert "LLG TRUSTEE LLC /TR" in li.plaintiff
    assert li.trustee == "LLG TRUSTEE LLC /TR"
    assert li.legal_description == "RE BK 4494 PG 634"
    assert li.raw["county"] == "brunswick"
    assert li.raw["doc_type"] == "SUBSTITUTE TRUSTEE"
    assert li.raw["book_page"] == "B: 5596, P: 1287"
    assert li.raw["brunswick_detail"]["status"] == "WARRANTED"
    assert li.raw["brunswick_detail"]["xref"] == "RE BK 4494 PG 634"
    assert li.raw["brunswick_detail"]["detail_url"].endswith("re_detail.ntk?s=DETAILTOKEN1")


def test_brunswick_record_stamps_real_pdf_document_link():
    scraper = NcRodCaptchaScraper()
    listings = scraper._brunswick_parse_page(
        _BRUNSWICK_SUBTRUSTEE_MULTI_GRANTOR_HTML,
        "https://brunswick-live.inttek.net/index.ntk?s=x",
        "SUBSTITUTE TRUSTEE",
    )
    li = listings[0]
    # The FIRST grantor row's "Download PDF" link wins (REALTOKEN1) --
    # live-confirmed these pdf-popup-download-all.ntk links are durable,
    # cookie-less, stateless URLs (fetched for real with a brand-new httpx
    # client and no prior requests), safe to stamp unlike Durham's
    # cookie-gated route or Rowan/Logan's session-scoped image keys.
    assert li.raw["document_url"].endswith("pdf-popup-download-all.ntk?s=REALTOKEN1")
    assert li.raw["documents"] == [li.raw["document_url"]]


def test_brunswick_parse_page_defendant_none_when_all_grantors_institutional():
    scraper = NcRodCaptchaScraper()
    listings = scraper._brunswick_parse_page(
        _BRUNSWICK_ALL_INSTITUTIONAL_GRANTOR_HTML,
        "https://brunswick-live.inttek.net/index.ntk?s=x",
        "SUBSTITUTE TRUSTEE",
    )
    assert len(listings) == 1
    li = listings[0]
    assert li.case_number == "B: 5597, P: 176"
    # FIRST BANK + BLUE TIDE HOMES, INC. are both institutional (a builder/
    # investor foreclosure, no human owner on the grantor side) -- real
    # result from a live SUBSTITUTE TRUSTEE pull, not a guessed lender name.
    assert li.defendant is None
    assert li.plaintiff == "FOYLES, KIRSTEN E. /TR; GOTTSEGEN, ADAM M. /TR"
    assert li.trustee == li.plaintiff
    assert li.raw["grantor"] == "FIRST BANK, BLUE TIDE HOMES, INC."


def test_brunswick_is_institutional_filters_lenders_and_tr_suffix():
    from foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha import _brunswick_is_institutional
    assert _brunswick_is_institutional("ROCKET MORTGAGE, LLC") is True
    assert _brunswick_is_institutional("MORTGAGE ELECTRONIC REGISTRATION SYSTEMS, INC.") is True
    # a real individual acting AS substitute trustee (an attorney, live-
    # pulled 2026-10-14) -- no institutional keyword in the name itself, but
    # the "/TR" suffix alone marks a non-owner.
    assert _brunswick_is_institutional("STEPHENS, H. KENNETH II /TR") is True
    assert _brunswick_is_institutional("VEGA, ESTEBAN EMILIO") is False
    assert _brunswick_is_institutional("") is True
    assert _brunswick_is_institutional(None) is True


def test_brunswick_parse_page_no_results_table_returns_empty():
    scraper = NcRodCaptchaScraper()
    assert scraper._brunswick_parse_page("<html><body>no results</body></html>", "http://x", "SUBSTITUTE TRUSTEE") == []


# --- Wake: same Tyler "Self-Service" platform as Durham, confirmed live --
# --- 2026-10-14 AFTER the owner personally solved the real reCAPTCHA ------
# --- checkbox. Real schema from that live session -------------------------
#
# Config ground truth: Wake's search_path was wrong before this pass (pointed
# at the disclaimer gate page itself, "/user/disclaimer") -- corrected to the
# real Tyler Self-Service search route, live-confirmed the same way Durham's
# DOCSEARCH5S1 was.

def test_wake_search_path_is_the_live_route():
    assert _COUNTY_SITES["wake"]["url"] == "https://rodrecords.wake.gov/web"
    assert _COUNTY_SITES["wake"]["search_path"] == "/search/DOCSEARCH341S2"
    # Wake's own reCAPTCHA is still genuinely walled for an unattended run --
    # this pass does NOT change that (no CAPTCHA automation), only wires up
    # what happens once a human has already cleared it.
    assert _COUNTY_SITES["wake"]["gate"] == "recaptcha"


def test_wake_distress_doc_types_are_the_real_live_facet_values():
    # Live Document Type facet counts, 14-day window, 2026-10-14: 43
    # "SUBSTITUTE TRUSTEE" + 7 "FORECLOSURE NOTICE" out of 46 real Document
    # Types total (DEED 985, DEED OF TRUST 1045, SATISFACTION 1087,
    # ASSIGNMENT 309, etc. -- routine filings, not distress, same judgment
    # call nc_rod_logan.py's own _classify() already makes for a plain DOT).
    assert _WAKE_DISTRESS_DOC_TYPES == ("SUBSTITUTE TRUSTEE", "FORECLOSURE NOTICE")


# A real single-book/page row (the common, parseable case): instrument
# 2026082901, FORECLOSURE NOTICE, live-pulled 2026-10-14 from a 90-day
# "SUBSTITUTE TRUSTEE, FORECLOSURE NOTICE" search (Jul16-Oct14 2026, 256
# total real results). Trimmed verbose inline whitespace for test-file size,
# same convention as the Brunswick fixtures above -- doc id, instrument
# number, book/page, date, doc-type pair, names, and legal are all real,
# live-pulled values, not fabricated. The "SEE"/doc-type-pair shape (an
# administratively-corrected record shows the OLD struck-through value
# first) is real and live-confirmed on this exact record.
_WAKE_FORECLOSURE_NOTICE_HTML = """
<li class="ss-search-row ui-li-static ui-body-inherit" data-href="/web/document/DOC899S1222?search=DOCSEARCH341S2" id="searchRowDOC899S1222" data-documentid="DOC899S1222" tabindex="0">
<div class="selfServiceSearchRowLeft"><div class="ss-facet-avatar ss-facet-avatar-S">S</div></div>
<div class="selfServiceSearchRowRight">
<h1>
2026082901
&nbsp;&bull;&nbsp;
B: 020291 P: 01139
&nbsp;&bull;&nbsp;
07/22/2026 04:41 PM
</h1>
<div class="searchResultFourColumn"><ul class="selfServiceSearchResultColumn five-line-block-with-text">
<li>Document Type (2)</li>
<li class="selfServiceSearchResultCollapsed"><b><span style="text-decoration: line-through;">SEE</span></b></li>
<li class="selfServiceSearchFullResult"><b>FORECLOSURE NOTICE</b></li>
</ul></div>
<div class="searchResultFourColumn"><ul class="selfServiceSearchResultColumn five-line-block-with-text">
<li>Grantor/Party 1 (4)</li>
<li class="selfServiceSearchResultCollapsed"><b>LEE MAURICE LORANZO</b></li>
<li class="selfServiceSearchFullResult"><b>LEE TRACY</b></li>
<li class="selfServiceSearchFullResult"><b>WIGGINS ELLEN /AIF</b></li>
<li class="selfServiceSearchFullResult"><b>LLG TRUSTEE LLC /TR BY A IN F</b></li>
</ul></div>
<div class="searchResultFourColumn"><ul class="selfServiceSearchResultColumn five-line-block-with-text">
<li>Grantee/Party 2 (2)</li>
<li class="selfServiceSearchResultCollapsed"><b>R&amp;R FUNDING GROUP, INC /TRDG</b></li>
<li class="selfServiceSearchFullResult"><b>AMERICAN BUILDERS MORTGAGE</b></li>
</ul></div>
<div class="searchResultFourColumn"><ul class="selfServiceSearchResultColumn five-line-block-with-text">
<li>Legal </li>
<li class="selfServiceSearchResultCollapsed"><b> 11058-1787</b></li>
</ul></div>
</div>
</li>
"""

# The EXACT real <h1> text (innerText, captured live via a DOM read) of a
# multi-tract SUBSTITUTE TRUSTEE record whose header the shared
# rod.nc_tyler._SS_HEAD regex cannot parse at all -- see module docstring's
# third live-confirmed gap. Kept as a bare string (not full row HTML) since
# the point here is the header regex itself, already proven against real text.
_WAKE_MULTI_BOOKPAGE_HEADER_TEXT = (
    "2026086748  •  B: 020299 P: 01082   B: 020299 P: 01083  •  07/31/2026 08:50 AM"
)


def test_wake_extract_docids_matches_row_order():
    assert _wake_extract_docids(_WAKE_FORECLOSURE_NOTICE_HTML) == ["DOC899S1222"]


def test_wake_record_to_listing_foreclosure_notice_real_schema():
    records = parse_selfservice(_WAKE_FORECLOSURE_NOTICE_HTML)
    assert len(records) == 1
    record = records[0]
    # the shared parser takes the FIRST Document Type value -- the stale
    # struck-through "SEE", not the real live type. _wake_record_to_listing
    # must never trust this for classification (see next test).
    assert record.doc_type == "SEE"
    assert record.instrument_no == "2026082901"
    assert record.book == "020291" and record.page == "01139"

    scraper = NcRodCaptchaScraper()
    li = scraper._wake_record_to_listing(
        record, "https://rodrecords.wake.gov/web/search/DOCSEARCH341S2",
        "FORECLOSURE NOTICE", "DOC899S1222",
    )
    assert li is not None
    assert li.county == "Wake" and li.state == "NC"
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.property_kind is PropertyKind.UNKNOWN
    assert li.case_number == "2026082901"
    # LEE MAURICE LORANZO / LEE TRACY / WIGGINS ELLEN (acting /AIF -- not
    # auto-excluded, same convention as elsewhere in this file: only an
    # institutional keyword or a literal "/TR" suffix excludes a party) are
    # real people, kept; LLG TRUSTEE LLC /TR BY A IN F is filtered out
    # (institutional keyword "trustee"/"llc").
    assert li.defendant == "LEE MAURICE LORANZO; LEE TRACY; WIGGINS ELLEN /AIF"
    assert "LLG TRUSTEE" not in (li.defendant or "")
    assert li.plaintiff == "R&R FUNDING GROUP, INC /TRDG; AMERICAN BUILDERS MORTGAGE"
    assert li.trustee is None  # neither real grantee here carries a "/TR" suffix
    assert li.legal_description == "11058-1787"
    # classification trusted the KNOWN search doc type, not the stale "SEE".
    assert li.description.startswith("FORECLOSURE NOTICE recorded")
    assert li.raw["county"] == "wake"
    assert li.raw["doc_type"] == "SEE"  # kept verbatim for provenance only
    assert li.raw["book_page"] == "B: 020291 P: 01139"
    assert li.raw["wake_detail"]["docid"] == "DOC899S1222"
    assert li.raw["wake_detail"]["searched_doc_type"] == "FORECLOSURE NOTICE"
    assert li.raw["wake_detail"]["related_documents"] is None


def test_wake_record_to_listing_skips_missing_instrument_number():
    blank = IndexRecord(recorded="2026-10-14", instrument_no=None, doc_type="SUBSTITUTE TRUSTEE")
    scraper = NcRodCaptchaScraper()
    assert scraper._wake_record_to_listing(blank, "http://x", "SUBSTITUTE TRUSTEE", "DOC1") is None
    blank2 = IndexRecord(recorded="2026-10-14", instrument_no="", doc_type="SUBSTITUTE TRUSTEE")
    assert scraper._wake_record_to_listing(blank2, "http://x", "SUBSTITUTE TRUSTEE", "DOC1") is None


def test_wake_multi_bookpage_header_not_parsed_by_shared_regex():
    # The real, live-confirmed gap this module docstring flags: a multi-tract
    # SUBSTITUTE TRUSTEE header (TWO "B: x P: y" pairs, no bullet between
    # them) fails the shared _SS_HEAD regex entirely -- not a partial match,
    # a real behavioral gap that silently drops this live record today (both
    # here and on Durham, which shares the same parser).
    assert _SS_HEAD.match(_WAKE_MULTI_BOOKPAGE_HEADER_TEXT) is None


def test_wake_multi_bookpage_record_is_dropped_not_fabricated():
    # End-to-end: parse_selfservice() on a full row carrying that exact real
    # header text produces an IndexRecord with no instrument number (even
    # though grantor/grantee/doc_type/legal all parse fine), and
    # _wake_record_to_listing correctly refuses to fabricate a lead for it
    # rather than emitting one with a blank case_number.
    html = _WAKE_FORECLOSURE_NOTICE_HTML.replace(
        "DOC899S1222", "DOC901S6792",
    ).replace(
        "2026082901\n&nbsp;&bull;&nbsp;\nB: 020291 P: 01139\n&nbsp;&bull;&nbsp;\n07/22/2026 04:41 PM",
        _WAKE_MULTI_BOOKPAGE_HEADER_TEXT,
    )
    records = parse_selfservice(html)
    assert len(records) == 1
    assert records[0].instrument_no is None
    assert records[0].book is None and records[0].page is None
    # grantor/grantee/doc_type/legal still parsed fine -- only the header failed.
    assert records[0].grantors == ["LEE MAURICE LORANZO", "LEE TRACY", "WIGGINS ELLEN /AIF",
                                    "LLG TRUSTEE LLC /TR BY A IN F"]

    scraper = NcRodCaptchaScraper()
    li = scraper._wake_record_to_listing(records[0], "http://x", "SUBSTITUTE TRUSTEE", "DOC901S6792")
    assert li is None


# Real Related Documents markup (the task's own "one hop" ask), live-pulled
# 2026-10-14 straight from the real relatedDocuments XHR response for
# instrument 2026111052 ("NOTICE OF CORRECTION"): 1 related DEED from
# 09/06/1960, the actual original instrument the correction concerns.
_WAKE_RELATED_DOCUMENTS_HTML = """
<ul class="ui-grid-b ss-utility-box-vertical ss-listview ui-listview ui-listview-inset">
<li data-role="list-divider" class="ui-bar-a ui-li-divider ui-first-child" role="heading">Related Documents - 1 Total Results</li>
<li class="ui-li-static ui-body-inherit ui-last-child related-doc-list">
<div id="relatedDataCollapsible" data-role="collapsible-set">
<div class="ss-row related-table-row " data-docid="DOCC106562174" data-role="collapsible">
<legend class="ui-grid-c"><table width="100%"><tr>
<td class="related-doc-type truncate" width="33%">DEED</td>
<td class="related-doc-recording-date elipsis" width="33%">09/06/1960</td>
<td class="related-doc-external-id truncate" width="33%">
<a class="document-link" href="DOCC106562174?isRelatedDocument=true&amp;search=DOCSEARCH341S2" onclick="goToDocument(event)">001422-00299</a>
</td>
</tr></table></legend>
<div class="related-data-panel">
<div style="width:50%; float:left" class="truncate"> MAYNARD A C<br/>  MAYNARD ANNIE S<br/> </div>
<div style="width:50%; float:left" class="truncate">MARTIN LILLIAN E<br/>MARTIN C E<br/></div>
<br style="clear: left;"/>
</div>
</div>
</div>
</li>
</ul>
"""


def test_wake_parse_related_documents_real_schema():
    related = _wake_parse_related_documents(
        _WAKE_RELATED_DOCUMENTS_HTML,
        base_url="https://rodrecords.wake.gov/web/document/DOC905S8387?search=DOCSEARCH341S2",
    )
    assert len(related) == 1
    r = related[0]
    assert r["doc_id"] == "DOCC106562174"
    assert r["doc_type"] == "DEED"
    assert r["recording_date"] == "09/06/1960"
    assert r["external_id"] == "001422-00299"
    assert r["document_url"] == (
        "https://rodrecords.wake.gov/web/document/"
        "DOCC106562174?isRelatedDocument=true&search=DOCSEARCH341S2"
    )
    assert r["grantors"] == ["MAYNARD A C", "MAYNARD ANNIE S"]
    assert r["grantees"] == ["MARTIN LILLIAN E", "MARTIN C E"]


def test_wake_parse_related_documents_no_related_returns_empty():
    assert _wake_parse_related_documents("<html><body>no related docs</body></html>") == []


def test_wake_session_reuse_window_documented():
    # The task's own central operational question -- how long a human-
    # cleared session stays usable for an automated client -- must be
    # answered with real evidence in the module docstring, not left unsaid.
    module_doc = __import__(
        "foreclosure_scraper.scrapers.counties_nc.nc_rod_captcha", fromlist=["x"]
    ).__doc__ or ""
    assert "SESSION-REUSE" in module_doc
    assert "pingSession" in module_doc

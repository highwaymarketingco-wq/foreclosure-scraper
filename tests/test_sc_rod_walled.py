"""SC ROD walled-site scrapers — Beaufort (free JSON API), Clarendon
(Cloudflare, cleared via nodriver), Jasper (Cloudflare cleared via nodriver;
a real reCAPTCHA v2 on top stays a manual/operator step, but the search +
parse + classify path behind it is fully built and tested here). Parser-only;
no live network calls (see docs/source_completeness_audit_2026-10-13.md's
correction note and rod/ccs_devexpress.py's module docstring for the live
evidence these fixtures are drawn from, 2026-10-14)."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod import acclaim, beaufort_dmp, ccs_devexpress
from foreclosure_scraper.rod.models import RodDoc
from foreclosure_scraper.scrapers.counties_sc.sc_rod_walled import (
    _beaufort_doc_to_listing,
    _clarendon_doc_to_listing,
    _jasper_defendant,
    _jasper_doc_to_listing,
    _jasper_is_institutional,
    _JASPER_RECAPTCHA_RE,
)


# --- Beaufort (rod/beaufort_dmp.py) -----------------------------------------

def test_pdf_url_and_body():
    url, body = beaufort_dmp.pdf_url_and_body(8696471)
    assert url == f"{beaufort_dmp.BASE}/api/pdf"
    assert body == {"Token": None, "ID": " 8696471"}
    # float-shaped id (defensive — grid fields are sometimes floats)
    url2, body2 = beaufort_dmp.pdf_url_and_body(8696471.0)
    assert body2["ID"] == " 8696471"
    assert beaufort_dmp.pdf_url_and_body(None) is None
    assert beaufort_dmp.pdf_url_and_body(0) is None
    assert beaufort_dmp.pdf_url_and_body(-5) is None
    assert beaufort_dmp.pdf_url_and_body("not-a-number") is None


def test_parse_date():
    d = beaufort_dmp._parse_date("2026-01-16T00:00:00")
    assert d == datetime(2026, 1, 16)
    assert beaufort_dmp._parse_date(None) is None
    assert beaufort_dmp._parse_date("garbage") is None


# Real schema from a LIVE api/search row, 2026-10-14 (DocTypes=LIEN,
# FromDate=20260101, ToDate=20261014): doc_id 8696471, a lien against a
# Palmetto Dunes HPR unit. Confirmed that same session to resolve to a real
# 200 application/pdf (153003 bytes, correct %PDF-1.4 header) at
# api/pdf with body {"Token": None, "ID": " 8696471"}.
_LIVE_LIEN_ROW = {
    "doc_id": 8696471, "party_code": "*",
    "party_name": "ANCHORAGE AT SHELTER COVE HORIZONTAL PROPERTY REGIME",
    "cross_party_name": "RUSSELL, H PATRICK",
    "rec_date": "2026-01-16T00:00:00", "doc_type": "LIEN",
    "file_num": "2026002395", "book": 4500, "page": 2144,
    "legal_1": "UNIT 7457 ANCHORAGE AT SHELTER COVE HPR PALMETTO DUNES RESORT HHI",
    "consid_1": 0.0, "doc_status": "V", "rowid": 1,
}
# Real schema from a LIVE DC (death certificate) row, same session: doc_id
# 8701418 -- book/page were not read back from this particular probe (only
# doc_id/party names/rec_date/file_num/doc_type), so they are left out here
# rather than invented.
_LIVE_DC_ROW = {
    "doc_id": 8701418, "party_name": "ABEAR, ALTON LEONARD",
    "cross_party_name": "ABEAR, MARTHA ANN",
    "rec_date": "2026-02-13T00:00:00", "doc_type": "DC",
    "file_num": "2026006763",
}


def test_row_to_doc_lien():
    d = beaufort_dmp._row_to_doc(_LIVE_LIEN_ROW, "SC", "Beaufort")
    assert d.county == "Beaufort" and d.state == "SC" and d.doc_type == "LIEN"
    assert d.recorded_date == datetime(2026, 1, 16)
    assert d.book == "4500" and d.page == "2144"
    assert d.grantor == "ANCHORAGE AT SHELTER COVE HORIZONTAL PROPERTY REGIME"
    assert d.grantee == "RUSSELL, H PATRICK"
    assert d.instrument_no == "2026002395"
    assert d.notes == "UNIT 7457 ANCHORAGE AT SHELTER COVE HPR PALMETTO DUNES RESORT HHI"
    # the free PDF recipe is staged in raw for the scraper layer to surface
    assert d.raw["beaufort_pdf_fetch"] == {
        "method": "POST", "url": f"{beaufort_dmp.BASE}/api/pdf",
        "body": {"Token": None, "ID": " 8696471"},
    }
    assert d.raw["beaufort_rod"] is _LIVE_LIEN_ROW


def test_row_to_doc_missing_book_page_is_none():
    d = beaufort_dmp._row_to_doc(_LIVE_DC_ROW, "SC", "Beaufort")
    assert d.doc_type == "DC"
    assert d.book is None and d.page is None
    assert d.grantor == "ABEAR, ALTON LEONARD"
    assert d.grantee == "ABEAR, MARTHA ANN"


def test_distress_codes_whitelist():
    # live-verified real hits (2026-01-01..2026-10-14): LIEN=123, MECH=71,
    # US=21, DC=296; SC/BNKRUPCY returned 0 in that window but are kept on
    # the vendor's own doctypes taxonomy, not dropped for lack of an example.
    for code in ("LIEN", "MECH", "SC", "US", "DC", "BNKRUPCY"):
        assert code in beaufort_dmp.DISTRESS_CODES
    # resolutions/unrelated codes must NOT be in the whitelist
    for code in ("SATIS", "RELMORT", "MLSAT", "SCSAT", "USSAT", "CANCEL",
                 "TERM", "VOID", "MORT", "RED", "PLAT"):
        assert code not in beaufort_dmp.DISTRESS_CODES


def test_beaufort_doc_to_listing_lien_is_tax_lien():
    doc = beaufort_dmp._row_to_doc(_LIVE_LIEN_ROW, "SC", "Beaufort")
    li = _beaufort_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.state == "SC" and li.county == "Beaufort"
    assert li.defendant == "ANCHORAGE AT SHELTER COVE HORIZONTAL PROPERTY REGIME"
    assert li.case_number == "2026002395"
    assert "relationship_signal" not in li.raw
    assert li.raw["beaufort_pdf_fetch"]["url"] == f"{beaufort_dmp.BASE}/api/pdf"


def test_beaufort_doc_to_listing_death_cert_tags_probate_signal():
    doc = beaufort_dmp._row_to_doc(_LIVE_DC_ROW, "SC", "Beaufort")
    li = _beaufort_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"


def test_beaufort_doc_to_listing_bankruptcy():
    row = dict(_LIVE_LIEN_ROW, doc_id=9999, doc_type="BNKRUPCY", file_num="2026099999")
    doc = beaufort_dmp._row_to_doc(row, "SC", "Beaufort")
    li = _beaufort_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.BANKRUPTCY


def test_beaufort_doc_to_listing_skips_non_distress():
    row = dict(_LIVE_LIEN_ROW, doc_type="SATIS")  # a real Beaufort code, but a resolution
    doc = beaufort_dmp._row_to_doc(row, "SC", "Beaufort")
    assert _beaufort_doc_to_listing(doc, "s", "u") is None


# --- Clarendon (rod/acclaim.py browser path + sc_rod_walled Listing build) -

# Real schema from a LIVE Clarendon GridResults row fetched via a
# Cloudflare-cleared nodriver tab, 2026-10-14: TransactionItemId 932508, a
# mechanics-adjacent lien. Confirmed that session to resolve to a real 200
# application/pdf (153003 bytes) at
# Image/DocumentPdfAllPages/932508 -- but ONLY from within that same
# cleared browser session (a cold GET of the identical URL 403s with a
# Cloudflare "Just a moment..." challenge page).
_CLARENDON_BASE = "https://acclaimprod.clarendoncountygov.org/acclaimweb"
_LIVE_CLARENDON_ROW = {
    "TransactionItemId": 932508, "DirectName": "FORTNER BRITTANY C",
    "IndirectName": "LOT 51 HOA", "DocType": "LIEN/MTG",
    "RecordDate": "/Date(1791072000000)/", "InstrumentNumber": "2026000217454",
    "BookType": "MTG", "BookPage": "1151/9999", "ParcelNumber": None,
    "Comments": "LOT 51",
}


def test_clarendon_doc_to_listing_lien_stamps_browser_gated_recipe():
    doc = acclaim._row_to_doc(_LIVE_CLARENDON_ROW, "SC", "Clarendon", _CLARENDON_BASE)
    li = _clarendon_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.defendant == "FORTNER BRITTANY C"
    assert li.case_number == "2026000217454"
    fetch = li.raw["clarendon_pdf_fetch"]
    assert fetch["url"] == f"{_CLARENDON_BASE}/Image/DocumentPdfAllPages/932508"
    assert fetch["requires"] == "cloudflare_cleared_session"
    # must NOT flow into the generic, GET-only enrich_doc_ocr.py pass — a
    # cold GET of this URL 403s, so stamping it under document_url/documents
    # would feed that pass a Cloudflare challenge page instead of a PDF.
    assert "document_url" not in li.raw
    assert "documents" not in li.raw


def test_clarendon_doc_to_listing_probate_and_foreclosure_and_skip():
    probate_row = dict(_LIVE_CLARENDON_ROW, DocType="D/DEATH")
    li = _clarendon_doc_to_listing(
        acclaim._row_to_doc(probate_row, "SC", "Clarendon", _CLARENDON_BASE),
        "s", "u")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"

    sale_row = dict(_LIVE_CLARENDON_ROW, DocType="NOTICE OF SALE")
    li2 = _clarendon_doc_to_listing(
        acclaim._row_to_doc(sale_row, "SC", "Clarendon", _CLARENDON_BASE), "s", "u")
    assert li2.listing_type is ListingType.LIS_PENDENS

    resolved_row = dict(_LIVE_CLARENDON_ROW, DocType="REL/MTG")
    assert _clarendon_doc_to_listing(
        acclaim._row_to_doc(resolved_row, "SC", "Clarendon", _CLARENDON_BASE), "s", "u"
    ) is None


def test_clarendon_doc_to_listing_no_fetch_block_without_pdf_url():
    doc = acclaim._row_to_doc(dict(_LIVE_CLARENDON_ROW, TransactionItemId=None),
                              "SC", "Clarendon", _CLARENDON_BASE)
    li = _clarendon_doc_to_listing(doc, "s", "u")
    assert "clarendon_pdf_fetch" not in li.raw


# --- rod/acclaim.py browser-driven search (Clarendon's Cloudflare tier) ----

class _FakeTab:
    """Stands in for a nodriver Tab: returns canned JSON for evaluate()."""

    def __init__(self, payloads: list[str]):
        self._payloads = list(payloads)

    async def evaluate(self, js, await_promise=True, return_by_value=True):
        return self._payloads.pop(0)


@pytest.mark.asyncio
async def test_search_chunk_via_tab_parses_grid_results():
    import json
    body = json.dumps({"data": [_LIVE_CLARENDON_ROW]})
    tab = _FakeTab([json.dumps({"status": 200, "body": body})])
    rows = await acclaim._search_chunk_via_tab(tab, _CLARENDON_BASE,
                                               datetime(2026, 9, 1), datetime(2026, 10, 14))
    assert rows == [_LIVE_CLARENDON_ROW]


@pytest.mark.asyncio
async def test_search_chunk_via_tab_over_cap_returns_empty():
    import json
    tab = _FakeTab([json.dumps({"over_cap": True})])
    rows = await acclaim._search_chunk_via_tab(tab, _CLARENDON_BASE,
                                               datetime(2026, 9, 1), datetime(2026, 10, 14))
    assert rows == []


@pytest.mark.asyncio
async def test_search_chunk_via_tab_non_200_returns_empty():
    import json
    tab = _FakeTab([json.dumps({"status": 403, "body": "blocked"})])
    rows = await acclaim._search_chunk_via_tab(tab, _CLARENDON_BASE,
                                               datetime(2026, 9, 1), datetime(2026, 10, 14))
    assert rows == []


@pytest.mark.asyncio
async def test_discover_recent_nods_via_browser_dedupes_and_classifies():
    import json
    lien_row = dict(_LIVE_CLARENDON_ROW)
    resolved_row = dict(_LIVE_CLARENDON_ROW, TransactionItemId=1,
                        InstrumentNumber="2026000217454", DocType="REL/MTG")
    body = json.dumps({"data": [lien_row, resolved_row]})
    one_window = json.dumps({"status": 200, "body": body})
    empty_window = json.dumps({"status": 200, "body": json.dumps({"data": []})})
    # 45-day lookback at _CHUNK_DAYS=10 -> 5 windows; first returns real
    # data, the rest are empty (same instrument as the resolved row is
    # already `seen`, so it must not double-count even though its own
    # DocType doesn't pass is_distress anyway).
    tab = _FakeTab([one_window] + [empty_window] * 4)
    docs = await acclaim.discover_recent_nods_via_browser(
        tab, "SC", "Clarendon", _CLARENDON_BASE, days_back=45)
    assert len(docs) == 1
    assert docs[0].doc_type == "LIEN/MTG"
    assert docs[0].raw["document_pdf_url"] == f"{_CLARENDON_BASE}/Image/DocumentPdfAllPages/932508"


# --- Jasper: reCAPTCHA clear stays manual; search+parse+classify (built) ---

def test_jasper_is_documented_as_genuinely_walled():
    from foreclosure_scraper.scrapers.counties_sc import sc_rod_walled
    assert "reCAPTCHA" in sc_rod_walled.JASPER_WALL_NOTE


def test_jasper_base_url():
    assert ccs_devexpress.base_url("SC", "Jasper") == \
        "https://us6.courthousecomputersystems.com/JasperSC"
    assert ccs_devexpress.base_url("SC", "Beaufort") is None


def test_jasper_recaptcha_regex_matches_real_modal_text():
    # the exact heading text read live off the reCAPTCHA modal, 2026-10-14.
    assert _JASPER_RECAPTCHA_RE.search("Please complete the CAPTCHA to enter this site.")
    assert _JASPER_RECAPTCHA_RE.search('<div class="g-recaptcha" data-sitekey="...">')
    assert not _JASPER_RECAPTCHA_RE.search("<table><tr><td>Book Type</td></tr></table>")


def test_classify_kind_code_live_confirmed_codes():
    # all 6 live-confirmed from the real #DocTypes hidden field, 2026-10-14
    # (see rod/ccs_devexpress.py module docstring).
    assert ccs_devexpress.classify_kind_code("DETH") == "probate"
    assert ccs_devexpress.classify_kind_code("DETH-DB") == "probate"
    assert ccs_devexpress.classify_kind_code("LIEN") == "lien"
    assert ccs_devexpress.classify_kind_code("ML") == "lien"
    assert ccs_devexpress.classify_kind_code("TXLN") == "lien"
    assert ccs_devexpress.classify_kind_code("LPEN") == "lis_pendens"
    # routine filings seen live (MTG, DEED, RELS, COR, SMTG) -- not distress.
    for routine in ("MTG", "DEED", "RELS", "COR", "SMTG", "UCC", ""):
        assert ccs_devexpress.classify_kind_code(routine) is None
    assert ccs_devexpress.classify_kind_code(None) is None


# Real grid rows, captured live 2026-10-14 from a Standard/Advanced search on
# the owner's own reCAPTCHA-cleared session (cell order: ... 5=Book, 6=Page,
# 7=Kind, 8="<or|ee>\t<name>" party col 1, 11=party col 2, 14=Date,
# 15=Description, 16=internal seq, 17=Doc#, 18=Tax Map# -- see
# rod/ccs_devexpress.py's module docstring for the full column-layout
# evidence).
_LIVE_DETH_ROW = [
    "", "", "1", "", "", "1228", "95", "DETH", "or\tTURNER, JAY", "or", "TURNER, JAY",
    "ee", "ee", "", "07/17/2026", "", "1-494540", "202600005464", "", "", "", "", "",
]
# A real $0-amount IRS federal tax lien against an individual, 09/30/2026.
_LIVE_TXLN_ROW = [
    "", "", "1", "", "", "1236", "1230", "TXLN",
    "or\tINTERNAL REVENUE SERVICE", "or", "INTERNAL REVENUE SERVICE",
    "ee\tDEISS, MATTHEW A", "ee", "DEISS, MATTHEW A",
    "09/30/2026", "SERIAL NUMBER 552678526", "1-500880", "202600007664",
    "", "", "", "", "",
]
# A real HOA assessment lien, two party rows (same book/page/doc#), 08/17/2026.
_LIVE_LIEN_ROW_1 = [
    "", "", "16", "", "", "1231", "1014", "LIEN",
    "or\tSUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC", "or",
    "SUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC",
    "ee\tBUDD, ROBERT D", "ee", "BUDD, ROBERT D",
    "08/17/2026", "LOT 866 BLOCK 25 BOTANY BAY", "1-496775", "202600006323",
    "067-36-00-866", "", "", "", "",
]
_LIVE_LIEN_ROW_2 = [
    "", "", "17", "", "", "1231", "1014", "LIEN",
    "ee\tBUDD, JUDITH A", "ee", "BUDD, JUDITH A",
    "or\tSUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC", "or",
    "SUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC",
    "08/17/2026", "LOT 866 BLOCK 25 BOTANY BAY", "1-496776", "202600006323",
    "067-36-00-866", "", "", "", "",
]
# A real mechanics lien, two party rows, 09/11/2026.
_LIVE_ML_ROW_1 = [
    "", "", "13", "", "", "1234", "1156", "ML",
    "or\tBACKYARD OASIS SERVICES LLC", "or", "BACKYARD OASIS SERVICES LLC",
    "ee\tRAMANAUSKAS, JOHN J", "ee", "RAMANAUSKAS, JOHN J",
    "09/11/2026", "LOT 543 BLOCK 11B MAGNOLIA CROSSING S/D",
    "1-498844", "202600007112", "067-24-00-543", "", "", "", "",
]
_LIVE_ML_ROW_2 = [
    "", "", "14", "", "", "1234", "1156", "ML",
    "ee\tRAMANAUSKAS, FRANCES", "ee", "RAMANAUSKAS, FRANCES",
    "or\tBACKYARD OASIS SERVICES LLC", "or", "BACKYARD OASIS SERVICES LLC",
    "09/11/2026", "LOT 543 BLOCK 11B MAGNOLIA CROSSING S/D",
    "1-498845", "202600007112", "067-24-00-543", "", "", "", "",
]
# A real routine mortgage (not distress) -- used to confirm classify_kind_code
# correctly excludes it, and that a plain grantor=borrower row still parses.
_LIVE_MTG_ROW = [
    "", "", "1", "E", "", "945", "211", "MTG",
    "or\tOGDEN, JEFFREY", "or", "OGDEN, JEFFREY",
    "ee\tFAIRWAY INDEPENDENT MORTGAGE CORPORATION", "ee",
    "FAIRWAY INDEPENDENT MORTGAGE CORPORATION",
    "03/31/2017", "LOTS 68,69,70, 71 AND 137, BLOCK A OF BASS LAKE SUBDIVISION "
    "CONTAINING THREE (3) ACRES, MORE OR LESS.",
    "1-307839", "201700001318", "", "", "", "", "",
]
# A real multi-parcel deed -- used only to confirm the Tax Map# cell's
# newline-joined parcels split correctly (not itself a distress kind).
_LIVE_MULTI_PARCEL_DEED_ROW = [
    "", "", "3", "E", "", "1105", "998", "DEED",
    "or\tNOAHS ARKS RESCUE", "or", "NOAHS ARKS RESCUE",
    "ee\tARGENT CONSTRUCTION & DEVELOPMENT LLC", "ee", "ARGENT CONSTRUCTION & DEVELOPMENT LLC",
    "07/05/2022", "0.816 ACRES - PARCEL 15 6.101 ACRES - PARCEL 21",
    "1-397781", "202200002613", "090-00-01-015\n090-00-01-021",
    "", "$90,000.00", "$90,000.00", "NO",
]
# CONSTRUCTED, schema-accurate (same cell shape as the live rows above) --
# no live LIS PENDENS row surfaced in the 90-day sample this pass pulled
# (see module docstring); the LPEN code itself IS live-confirmed from the
# #DocTypes picker's own hidden-field echo. Used only to exercise the LPEN
# branch of the classifier/listing-builder.
_CONSTRUCTED_LPEN_ROW = [
    "", "", "1", "", "", "1240", "500", "LPEN",
    "or\tACME FORECLOSURE SERVICES LLC", "or", "ACME FORECLOSURE SERVICES LLC",
    "ee\tSMITH, JOHN Q", "ee", "SMITH, JOHN Q",
    "10/10/2026", "LOT 1 TEST SUBDIVISION", "1-999001", "202600009001",
    "067-00-00-001", "", "", "", "",
]


def test_parse_grid_row_death_certificate():
    parsed = ccs_devexpress.parse_grid_row(_LIVE_DETH_ROW)
    assert parsed["book"] == "1228" and parsed["page"] == "95" and parsed["kind"] == "DETH"
    assert parsed["grantor"] == "TURNER, JAY"
    assert parsed["grantee"] is None
    assert parsed["recorded_date"] == datetime(2026, 7, 17)
    assert parsed["doc_no"] == "202600005464"


def test_parse_grid_row_multi_parcel_deed_splits_lines():
    parsed = ccs_devexpress.parse_grid_row(_LIVE_MULTI_PARCEL_DEED_ROW)
    assert parsed["parcel_ids"] == ["090-00-01-015", "090-00-01-021"]
    assert parsed["parcel_id"] == "090-00-01-015"


def test_parse_grid_row_short_row_returns_none():
    assert ccs_devexpress.parse_grid_row(["", "", "1"]) is None
    assert ccs_devexpress.parse_grid_row([]) is None
    assert ccs_devexpress.parse_grid_row(None) is None


def test_collapse_rows_to_docs_merges_lien_party_rows():
    docs = ccs_devexpress.collapse_rows_to_docs(
        [_LIVE_LIEN_ROW_1, _LIVE_LIEN_ROW_2], "SC", "Jasper")
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_type == "LIEN" and doc.book == "1231" and doc.page == "1014"
    assert doc.grantor == "SUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC"
    assert doc.grantee == "BUDD, ROBERT D"
    payload = doc.raw["ccs_devexpress_rod"]
    assert "BUDD, JUDITH A" in payload["grantees"]
    assert payload["parcel_ids"] == ["067-36-00-866"]


def test_collapse_rows_to_docs_merges_mechanics_lien_party_rows():
    docs = ccs_devexpress.collapse_rows_to_docs(
        [_LIVE_ML_ROW_1, _LIVE_ML_ROW_2], "SC", "Jasper")
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_type == "ML"
    assert doc.grantor == "BACKYARD OASIS SERVICES LLC"
    assert doc.grantee == "RAMANAUSKAS, JOHN J"
    assert "RAMANAUSKAS, FRANCES" in doc.raw["ccs_devexpress_rod"]["grantees"]


def test_collapse_rows_to_docs_distinct_docs_stay_separate():
    docs = ccs_devexpress.collapse_rows_to_docs(
        [_LIVE_DETH_ROW, _LIVE_TXLN_ROW], "SC", "Jasper")
    assert len(docs) == 2
    assert {d.doc_type for d in docs} == {"DETH", "TXLN"}


# --- rod/ccs_devexpress.py in-page browser search (reuses _FakeTab above) --

@pytest.mark.asyncio
async def test_discover_recent_distress_via_browser_parses_real_rows():
    import json
    tab = _FakeTab([json.dumps({
        "total_records": "3", "total_documents": "2", "pages_read": 1,
        "rows": [_LIVE_DETH_ROW, _LIVE_TXLN_ROW],
    })])
    docs = await ccs_devexpress.discover_recent_distress_via_browser(tab, "SC", "Jasper")
    assert len(docs) == 2
    assert {d.doc_type for d in docs} == {"DETH", "TXLN"}


@pytest.mark.asyncio
async def test_discover_recent_distress_via_browser_search_error_returns_empty():
    import json
    tab = _FakeTab([json.dumps({"error": "search_timeout"})])
    docs = await ccs_devexpress.discover_recent_distress_via_browser(tab, "SC", "Jasper")
    assert docs == []


@pytest.mark.asyncio
async def test_discover_recent_distress_via_browser_unknown_county_short_circuits():
    tab = _FakeTab([])  # evaluate must never be called
    docs = await ccs_devexpress.discover_recent_distress_via_browser(tab, "SC", "Pickens")
    assert docs == []


# --- Jasper Listing building (sc_rod_walled._jasper_doc_to_listing) --------

def test_jasper_is_institutional():
    assert _jasper_is_institutional("SUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC")
    assert _jasper_is_institutional("INTERNAL REVENUE SERVICE")
    assert _jasper_is_institutional("BACKYARD OASIS SERVICES LLC")
    assert _jasper_is_institutional("")
    assert _jasper_is_institutional(None)
    assert not _jasper_is_institutional("DEISS, MATTHEW A")
    assert not _jasper_is_institutional("RAMANAUSKAS, JOHN J")


def test_jasper_defendant_lien_prefers_debtor_over_institutional_claimant():
    # live-observed Jasper convention for LIEN/ML/TXLN: claimant=grantor,
    # owner/debtor=grantee -- opposite of a mortgage's grantor=borrower.
    assert _jasper_defendant(
        "SUN CITY HILTON HEAD COMMUNITY ASSOCIATION INC", "BUDD, ROBERT D", "lien"
    ) == "BUDD, ROBERT D"
    assert _jasper_defendant(
        "INTERNAL REVENUE SERVICE", "DEISS, MATTHEW A", "lien"
    ) == "DEISS, MATTHEW A"
    assert _jasper_defendant(
        "BACKYARD OASIS SERVICES LLC", "RAMANAUSKAS, JOHN J", "lien"
    ) == "RAMANAUSKAS, JOHN J"


def test_jasper_defendant_probate_uses_grantor_decedent():
    assert _jasper_defendant("TURNER, JAY", None, "probate") == "TURNER, JAY"


def test_jasper_defendant_both_institutional_falls_back_to_grantee():
    assert _jasper_defendant(
        "RIVERS REACH PROPERTIES OWNERS ASSOCIATIONS INC", "INSHORE PROPERTIES LLC", "lien"
    ) == "INSHORE PROPERTIES LLC"


def test_jasper_doc_to_listing_death_certificate_tags_probate_signal():
    doc = ccs_devexpress.collapse_rows_to_docs([_LIVE_DETH_ROW], "SC", "Jasper")[0]
    li = _jasper_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.defendant == "TURNER, JAY"
    assert li.case_number == "202600005464"
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert "jasper_doc_image" in li.raw  # book+page present -> image recipe stamped


def test_jasper_doc_to_listing_tax_lien_real_irs_example():
    doc = ccs_devexpress.collapse_rows_to_docs([_LIVE_TXLN_ROW], "SC", "Jasper")[0]
    li = _jasper_doc_to_listing(doc, "counties_sc.sc_rod_walled", "http://x")
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.defendant == "DEISS, MATTHEW A"
    assert li.legal_description == "SERIAL NUMBER 552678526"
    # the per-document PDF viewer needs the SAME reCAPTCHA+Cloudflare session
    # as the search -- never routed through the generic, cold-GET-only
    # document_links.stamp_documents pass (document_links.py's own
    # _ROD_IMAGE_VENDOR denylist already excludes /ProcessedImages/ for this
    # exact reason).
    fetch = li.raw["jasper_doc_image"]
    assert fetch["requires"] == "jasper_recaptcha_and_cloudflare_cleared_session"
    assert "ShowDocImage" in fetch["url"] and "BookNum=1236" in fetch["url"]
    assert "document_url" not in li.raw
    assert "documents" not in li.raw


def test_jasper_doc_to_listing_mechanics_lien_defendant_is_homeowner():
    docs = ccs_devexpress.collapse_rows_to_docs([_LIVE_ML_ROW_1, _LIVE_ML_ROW_2], "SC", "Jasper")
    li = _jasper_doc_to_listing(docs[0], "s", "u")
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.defendant == "RAMANAUSKAS, JOHN J"
    assert li.parcel_id == "067-24-00-543"


def test_jasper_doc_to_listing_lien_defendant_is_homeowner_not_hoa():
    docs = ccs_devexpress.collapse_rows_to_docs([_LIVE_LIEN_ROW_1, _LIVE_LIEN_ROW_2], "SC", "Jasper")
    li = _jasper_doc_to_listing(docs[0], "s", "u")
    assert li.defendant == "BUDD, ROBERT D"
    assert "SUN CITY" not in (li.defendant or "")


def test_jasper_doc_to_listing_lis_pendens_constructed_schema():
    doc = ccs_devexpress.collapse_rows_to_docs([_CONSTRUCTED_LPEN_ROW], "SC", "Jasper")[0]
    li = _jasper_doc_to_listing(doc, "s", "u")
    # its own bucket, same as _clarendon_doc_to_listing()'s LIS PENDENS kind
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.defendant == "SMITH, JOHN Q"


def test_jasper_doc_to_listing_non_distress_kind_returns_none():
    doc = ccs_devexpress.collapse_rows_to_docs([_LIVE_MTG_ROW], "SC", "Jasper")[0]
    assert _jasper_doc_to_listing(doc, "s", "u") is None


def test_jasper_doc_to_listing_no_image_recipe_without_book_page():
    doc = ccs_devexpress.collapse_rows_to_docs([_LIVE_DETH_ROW], "SC", "Jasper")[0]
    doc.book = None
    li = _jasper_doc_to_listing(doc, "s", "u")
    assert "jasper_doc_image" not in li.raw

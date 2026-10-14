"""SC ROD walled-site scrapers — Beaufort (free JSON API), Clarendon
(Cloudflare, cleared via nodriver), Jasper (genuinely walled). Parser-only;
no live network calls (see docs/source_completeness_audit_2026-10-13.md's
correction note for the live evidence these fixtures are drawn from)."""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod import acclaim, beaufort_dmp
from foreclosure_scraper.rod.models import RodDoc
from foreclosure_scraper.scrapers.counties_sc.sc_rod_walled import (
    _beaufort_doc_to_listing,
    _clarendon_doc_to_listing,
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


# --- Jasper: documented genuine wall, no code path to test -----------------

def test_jasper_is_documented_as_genuinely_walled():
    from foreclosure_scraper.scrapers.counties_sc import sc_rod_walled
    assert "reCAPTCHA" in sc_rod_walled.JASPER_WALL_NOTE
    assert "6LfblzYqAAAAAFNl9g-RwU5zbI97HFqwWbhoD4Rb" in sc_rod_walled.JASPER_WALL_NOTE

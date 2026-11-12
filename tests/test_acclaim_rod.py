"""Harris Acclaim ROD adapter + SC ROD scraper (probate + liens), parser-only."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.rod import acclaim
from foreclosure_scraper.scrapers.counties_sc.sc_rod_acclaim import _classify, _to_listing
from foreclosure_scraper.models import ListingType


# --- adapter ---
def test_is_distress():
    assert acclaim.is_distress("D/DIST")          # deed of distribution (probate)
    assert acclaim.is_distress("D/DEATH")
    assert acclaim.is_distress("LIEN")
    assert acclaim.is_distress("L/MECH")          # mechanics lien
    assert not acclaim.is_distress("DEED")
    assert not acclaim.is_distress("MTG")
    assert not acclaim.is_distress("M/SAT")       # satisfaction = resolved
    assert not acclaim.is_distress("L/MECH REL")  # lien release = resolved
    assert not acclaim.is_distress("LN/REL")


def test_parse_date():
    d = acclaim._parse_date("/Date(1780315746000)/")
    assert d and d.year == 2026 and d.month == 6
    assert acclaim._parse_date(None) is None
    assert acclaim._parse_date("garbage") is None


def test_row_to_doc():
    row = {"DocType": "D/DIST", "DirectName": "ADAMS J ESTATE",
           "IndirectName": "COOPER A", "RecordDate": "/Date(1780315746000)/",
           "InstrumentNumber": "202608330", "BookType": "DE", "BookPage": "2962/293",
           "ParcelNumber": "5019-11-66-0241", "Comments": "LOT 9 EASLEY"}
    d = acclaim._row_to_doc(row, "SC", "Pickens")
    assert d.county == "Pickens" and d.state == "SC" and d.doc_type == "D/DIST"
    assert d.grantor == "ADAMS J ESTATE" and d.grantee == "COOPER A"
    assert d.book == "2962" and d.page == "293"
    assert d.instrument_no == "202608330" and d.parcel_id == "5019-11-66-0241"
    assert d.notes == "LOT 9 EASLEY"
    # no `base` passed (old call shape) -> no document_pdf_url key at all, not even None
    assert "document_pdf_url" not in d.raw


# --- document image/PDF resolution (added 2026-10-14) ---
# Pickens' "Needs YOU logged in" flag in source_completeness_audit_2026-10-13.md was
# wrong: the owner confirmed live that both the search AND the per-document image/PDF
# viewer are fully public, no login anywhere on this AcclaimWeb deployment. Real schema
# below is from a LIVE GridResults row (2026-10-14): a D/DIST (probate) recording,
# instrument 202613635, TransactionItemId 1461677 -- confirmed that same day to resolve
# to a real 200 application/pdf at Image/DocumentPdfAllPages/1461677.
_LIVE_ROW = {
    "TransactionItemId": 1461677, "U": "", "DirectName": "ESTATE OF SMITH JOHN A",
    "CompressedDirectName": "ESTATEOFSMITHJOHNA", "IndirectName": "SMITH MARY",
    "CompressedIndirectName": "SMITHMARY", "DocType": "D/DIST",
    "RecordDate": "/Date(1790000000000)/", "InstrumentNumber": "202613635",
    "NumericInstrumentNumber": 202613635.000000, "BookType": "DE", "BookPage": "2990/112",
    "NumericPage": 112.000000, "ParcelNumber": "4140-00-52-9999", "Comments": "LOT 4 EASLEY",
    "TransactionId": 291000, "DeletedAfterVerify": 0, "IsViewed": None, "GUID": 1,
}
_BASE = "https://www.pickensscrod.us/AcclaimWeb"


def test_document_pdf_url():
    assert (acclaim.document_pdf_url(_BASE, 1464750)
            == f"{_BASE}/Image/DocumentPdfAllPages/1464750")
    # trailing slash on base is tolerated
    assert (acclaim.document_pdf_url(_BASE + "/", 1464750)
            == f"{_BASE}/Image/DocumentPdfAllPages/1464750")
    # the grid's own float-encoded id shape (same style as NumericInstrumentNumber)
    assert (acclaim.document_pdf_url(_BASE, 1461677.0)
            == f"{_BASE}/Image/DocumentPdfAllPages/1461677")
    # a string id (defensive -- the live field is numeric, but never trust the shape)
    assert (acclaim.document_pdf_url(_BASE, "1461677")
            == f"{_BASE}/Image/DocumentPdfAllPages/1461677")
    assert acclaim.document_pdf_url(_BASE, None) is None
    assert acclaim.document_pdf_url(_BASE, "") is None
    assert acclaim.document_pdf_url(_BASE, "  ") is None
    assert acclaim.document_pdf_url(_BASE, "not-a-number") is None
    assert acclaim.document_pdf_url(_BASE, 0) is None
    assert acclaim.document_pdf_url(_BASE, -5) is None


def test_row_to_doc_carries_document_pdf_url_when_base_given():
    d = acclaim._row_to_doc(_LIVE_ROW, "SC", "Pickens", _BASE)
    assert d.raw["document_pdf_url"] == f"{_BASE}/Image/DocumentPdfAllPages/1461677"
    # the full raw grid row (incl. TransactionItemId) is still kept verbatim too
    assert d.raw["acclaim"]["TransactionItemId"] == 1461677


def test_row_to_doc_no_document_pdf_url_without_transaction_item_id():
    row = dict(_LIVE_ROW)
    row.pop("TransactionItemId")
    d = acclaim._row_to_doc(row, "SC", "Pickens", _BASE)
    assert "document_pdf_url" not in d.raw


# --- scraper classification / listing build ---
def test_classify():
    assert _classify("D/DIST")[0] is ListingType.PROBATE_NOTICE
    assert _classify("D/DEATH")[0] is ListingType.PROBATE_NOTICE
    assert _classify("LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("L/MECH")[0] is ListingType.TAX_LIEN
    assert _classify("L/MECH REL") is None  # release
    assert _classify("DEED") is None
    assert _classify("MTG") is None


def _doc(doc_type, **kw):
    from foreclosure_scraper.rod.models import RodDoc
    base = dict(county="Pickens", state="SC", doc_type=doc_type, grantor="SMITH JOHN ESTATE",
                instrument_no="202600001", parcel_id="1-2-3", notes="LOT 1",
                recorded_date=datetime(2026, 6, 1))
    base.update(kw)
    return RodDoc(**base)


def test_to_listing_probate_tags_signal():
    li = _to_listing(_doc("D/DIST"), "counties_sc.sc_rod_acclaim", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.state == "SC" and li.county == "Pickens" and li.parcel_id == "1-2-3"
    assert li.defendant == "SMITH JOHN ESTATE"
    assert li.raw["relationship_signal"]["kind"] == "probate"


def test_to_listing_lien_is_tax_lien():
    li = _to_listing(_doc("LIEN", grantor="DOE JANE"), "counties_sc.sc_rod_acclaim", "http://x")
    assert li.listing_type is ListingType.TAX_LIEN
    assert "relationship_signal" not in li.raw


def test_to_listing_skips_non_distress():
    assert _to_listing(_doc("DEED"), "s", "u") is None
    assert _to_listing(_doc("M/SAT"), "s", "u") is None


def test_to_listing_stamps_document_pdf_url_into_raw():
    """_to_listing must surface the free scanned PDF the same way
    anderson_acpass_deeds.py / sheriff_sales.py do: flat raw['documents']
    (capped list) + raw['document_url'] (primary), via
    document_links.stamp_documents -- so enrichment_doc_ocr.py picks it up
    with no source-specific wiring needed."""
    from foreclosure_scraper.rod.acclaim import document_pdf_url as _pdf_url
    pdf_url = _pdf_url("https://www.pickensscrod.us/AcclaimWeb", 1461677)
    doc = _doc("D/DIST")
    doc.raw["document_pdf_url"] = pdf_url
    li = _to_listing(doc, "counties_sc.sc_rod_acclaim", "http://x")
    assert li.raw["document_url"] == pdf_url
    assert li.raw["documents"] == [pdf_url]
    # the source-specific rod block + relationship_signal survive alongside it
    assert li.raw["rod"]["instrument"] == "202600001"
    assert li.raw["relationship_signal"]["kind"] == "probate"


def test_to_listing_no_document_block_when_pdf_url_missing():
    """A doc with no `document_pdf_url` in raw (e.g. a malformed grid row
    with no TransactionItemId) must not get a document_url/documents key at
    all -- stamp_documents is simply never called."""
    li = _to_listing(_doc("LIEN", grantor="DOE JANE"), "counties_sc.sc_rod_acclaim", "http://x")
    assert "document_url" not in li.raw
    assert "documents" not in li.raw

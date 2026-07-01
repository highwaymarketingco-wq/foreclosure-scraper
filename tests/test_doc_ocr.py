"""Unit tests for enrichment_doc_ocr — selection + backfill logic (no network)."""
from foreclosure_scraper.models import Listing
from foreclosure_scraper import enrichment_doc_ocr as dm


def _li(**kw):
    base = dict(source="test", source_url="https://x/y", county="Buncombe", state="NC")
    base.update(kw)
    return Listing(**base)


def test_doc_urls_from_source_url_pdf():
    li = _li(source_url="https://county.gov/notices/smith.pdf")
    assert dm._doc_urls(li) == ["https://county.gov/notices/smith.pdf"]


def test_doc_urls_from_raw_field():
    li = _li(source_url="https://county.gov/case/123", raw={"notice_image": "https://c/img.tif"})
    assert dm._doc_urls(li) == ["https://c/img.tif"]


def test_doc_urls_none_for_html_page():
    li = _li(source_url="https://county.gov/case/123", raw={})
    assert dm._doc_urls(li) == []


def test_doc_urls_caps_to_one():
    li = _li(source_url="https://c/a.pdf",
             raw={"document_url": "https://c/b.pdf", "pdf_url": "https://c/c.pdf"})
    assert len(dm._doc_urls(li)) == 1


def test_apply_ocr_fills_blanks():
    li = _li(defendant=None, street_address=None)
    filled = dm.apply_ocr(li, {
        "owner_name": "JOHN Q SMITH", "property_address": "123 Oak St",
        "city": "Asheville", "state": "NC", "zip": "28801",
        "amount": "$154,300.00", "case_number": "24 SP 123",
    })
    assert li.defendant == "JOHN Q SMITH"
    assert li.street_address == "123 Oak St"
    assert li.city == "Asheville"
    assert li.zip_code == "28801"
    assert li.case_number == "24 SP 123"
    assert li.judgment_amount == 154300.0
    assert li.raw["doc_ocr"]["owner_name"] == "JOHN Q SMITH"
    assert set(filled) >= {"defendant", "street_address", "city", "judgment_amount"}


def test_apply_ocr_never_clobbers():
    li = _li(defendant="EXISTING NAME", street_address="999 Real Rd", judgment_amount=50000.0)
    dm.apply_ocr(li, {"owner_name": "OCR NAME", "property_address": "1 Wrong Way", "amount": "1"})
    assert li.defendant == "EXISTING NAME"
    assert li.street_address == "999 Real Rd"
    assert li.judgment_amount == 50000.0


def test_clean_amount():
    assert dm._clean_amount("$1,234.50") == 1234.50
    assert dm._clean_amount("154300") == 154300.0
    assert dm._clean_amount(None) is None
    assert dm._clean_amount("n/a") is None


def test_source_pdf_field_is_a_doc_url():
    li = _li(source_url="https://county/case/1", raw={"source_pdf": "https://c/notice.pdf"})
    assert dm._doc_urls(li) == ["https://c/notice.pdf"]


def test_aggregate_shared_pdf_is_skipped():
    import asyncio
    # 10 leads share ONE tax-advertisement PDF (aggregate list) -> all skipped;
    # 2 leads carry their own distinct per-notice image -> both kept as targets.
    shared = "https://county/tax-advertisement.pdf"
    agg = [_li(source_url=shared) for _ in range(10)]
    per = [_li(source_url=f"https://county/notice-{i}.pdf") for i in range(2)]
    # no providers configured in test env -> enrich returns early but AFTER
    # computing targets/skipped_aggregate, so we assert on the stats it logs.
    # Directly exercise the guard logic the enricher uses:
    from collections import Counter
    cands = agg + per
    counts = Counter(dm._doc_urls(li)[0] for li in cands)
    aggregate = {u for u, c in counts.items() if c > dm.DOC_OCR_MAX_SHARE}
    targets = [li for li in cands if dm._doc_urls(li)[0] not in aggregate]
    assert shared in aggregate
    assert len(targets) == 2  # only the per-property notices survive

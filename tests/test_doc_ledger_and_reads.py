"""The processed-documents ledger and the document-read fixes of the 2026-10-09 documents_images
audit. All fixtures are made up (names, addresses, case numbers, URLs)."""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper import doc_inventory as inv
from foreclosure_scraper import doc_ledger as dl
from foreclosure_scraper import enrichment_doc_ocr as dm
from foreclosure_scraper.models import Listing


def _li(**kw):
    base = dict(source="test.src", source_url="https://example.test/page", state="NC",
                county="Testcounty")
    raw = kw.pop("raw", None)
    base.update(kw)
    li = Listing(**base)
    li.raw = dict(raw or {})
    return li


@pytest.fixture
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_LEDGER_DIR", str(tmp_path / "led"))
    monkeypatch.setenv("DOC_LEDGER_PRIVATE_DIR", str(tmp_path / "priv"))
    dl.reset_cache()
    yield tmp_path
    dl.reset_cache()


# ------------------------------------------------------------------ ledger
def test_ledger_terminal_and_retry_rules(ledger_dir):
    led = dl.DocLedger("doc_ocr", {})
    assert led.is_due("u:a", "v2")
    led.record("u:a", outcome="extracted", version="v2")
    assert not led.is_due("u:a", "v2")            # terminal for this version
    assert led.is_due("u:a", "v3")                # a new extractor version re-reads it
    e = led.record("u:b", outcome="fetch_failed", version="v2")
    assert e["retry_after"] and not led.is_due("u:b", "v2")
    e2 = led.record("u:b", outcome="fetch_failed", version="v2")
    assert e2["attempts"] == 2 and e2["retry_after"] > e["retry_after"]   # the wait doubles


def test_a_retryable_answer_never_erases_a_terminal_result(ledger_dir):
    led = dl.DocLedger("doc_ocr", {})
    led.record("u:a", outcome="extracted", version="v2", values={"case_number": "99SP000001"})
    kept = led.record("u:a", outcome="fetch_failed", version="v2")
    assert kept["outcome"] == "extracted" and kept["last_attempt"]["outcome"] == "fetch_failed"


def test_public_ledger_never_carries_names_addresses_or_phones(ledger_dir):
    led = dl.DocLedger("doc_ocr", {}, persistent=True)
    led.record("u:a", outcome="extracted", version="v2", url="https://docs.example.test/a.pdf",
               values={"owner_name": "PAT EXAMPLE", "property_address": "1 Fake St",
                       "case_number": "99SP000001", "amount": 1200.5,
                       "doc_type": "call 555-123-4567"})
    p = led.save()
    text = p.read_text()
    assert "PAT EXAMPLE" not in text and "Fake St" not in text and "555-123" not in text
    assert "https://docs.example.test" not in text            # the URL itself is never stored
    assert "99SP000001" in text and "docs.example.test" in text  # host + public values are
    priv = json.loads((ledger_dir / "priv" / "doc_ocr.private.json").read_text())
    assert priv["u:a"]["owner_name"] == "PAT EXAMPLE"          # names only in the private store


def test_save_is_merge_safe(ledger_dir):
    a = dl.DocLedger.load("doc_ocr")
    a.persistent = True
    a.record("u:one", outcome="extracted", version="v2")
    a.save()
    b = dl.DocLedger("doc_ocr", {}, persistent=True, path=a.path)    # another copy, older
    b.record("u:two", outcome="fetch_failed", version="v2")
    b.save()
    merged = dl.DocLedger.load("doc_ocr")
    assert set(merged.rows) == {"u:one", "u:two"}


def test_under_pytest_without_a_dir_the_ledger_is_in_memory(monkeypatch):
    monkeypatch.delenv("DOC_LEDGER_DIR", raising=False)
    led = dl.get_ledger("doc_ocr")
    assert led.persistent is False and led.rows == {}
    assert led.save() is None


# ------------------------------------------------------------------ inventory
def test_cache_buster_does_not_split_one_document():
    a = "https://county.example.test/files/Sale-List.pdf?v=292"
    b = "https://county.example.test/files/Sale-List.pdf?v=688"
    assert inv.normalize_url(a) == inv.normalize_url(b)
    assert inv.doc_key(a) == inv.doc_key(b)


def test_ocr_doc_urls_reads_source_specific_notice_blocks_but_not_the_js_viewer():
    li = _li(raw={"column": {"pdfurl": "https://cdn.example.test/n1.pdf"},
                  "billtrax_dorchester_delinquent_tax": {"notice_pdf_view_url": "https://bt.example.test/view/bill/pdfbill?x"}})
    assert inv.ocr_doc_urls(li) == ["https://cdn.example.test/n1.pdf"]
    assert inv.legacy_ocr_doc_urls(li) == []                 # the old reader never saw it
    only_viewer = _li(raw={"billtrax_dorchester_delinquent_tax": {"notice_pdf_view_url": "https://bt.example.test/v"}})
    assert inv.ocr_doc_urls(only_viewer) == []
    assert inv.unreadable_notice_reason(only_viewer) == "js_viewer_needs_browser"


def test_image_categories():
    assert inv.image_category("parcel_photos/x_1.jpg") == "assessor_photo"
    assert inv.image_category("https://server.arcgisonline.com/ArcGIS/rest/x") == "aerial"
    assert inv.image_category("https://staticmap.openstreetmap.de/x") == "map"
    assert inv.image_category("https://ap.rdcpix.com/x.jpg") == "listing_photo"


def test_lead_value_order_hot_warm_then_score():
    hot = _li(raw={"distress_stack": {"tier": "HOT", "score": 10}})
    warm_hi = _li(raw={"distress_stack": {"tier": "WARM", "score": 90}})
    warm_lo = _li(raw={"distress_stack": {"tier": "WARM", "score": 20}})
    cold = _li(raw={})
    got = sorted([cold, warm_lo, hot, warm_hi], key=inv.lead_value_key)
    assert got == [hot, warm_hi, warm_lo, cold]


def test_owner_search_key_hides_the_name():
    k = inv.owner_search_key("NC", "Testcounty", "EXAMPLE, PAT")
    assert k.startswith("o:") and "EXAMPLE" not in k


# ------------------------------------------------------------------ read rules
def test_notice_to_creditors_deadline_is_not_a_sale_date_and_its_address_is_dropped():
    out = dm.normalize_parsed({"doc_type": "probate_notice", "owner_name": "Estate of Pat Example",
                               "sale_date": "2026-12-04", "property_address": "9 Lawyer Ave",
                               "city": "Faketown", "zip": "00000"})
    assert out["sale_date"] is None and out["claims_deadline"] == "2026-12-04"
    assert out["property_address"] is None and out["city"] is None
    fc = dm.normalize_parsed({"doc_type": "foreclosure_notice", "sale_date": "2026-06-16",
                              "property_address": "12 Oak Ln"})
    assert fc["sale_date"] == "2026-06-16" and fc["property_address"] == "12 Oak Ln"


@pytest.mark.parametrize("doc_type,fills", [
    ("judgment_lien", True), ("lien", True), (None, False), ("auction_notice", False),
    ("tax_sale", False), ("deed_of_trust", False), ("foreclosure_notice", False)])
def test_only_a_judgment_or_lien_figure_becomes_judgment_amount(doc_type, fills):
    li = _li()
    dm.apply_ocr(li, {"amount": "5,000.00", "doc_type": doc_type})
    assert (li.judgment_amount == 5000.0) is fills
    assert li.raw["doc_ocr"]["_v"] == dm.DOC_OCR_VERSION


def test_a_sale_list_read_as_its_first_entry_does_not_bind_to_another_case():
    li = _li(case_number="2099-CP-01-00468", street_address="704 Sample Rd")
    first_entry = {"case_number": "2099-CP-01-00843", "owner_name": "FIRST ENTRY PERSON",
                   "property_address": "504 Other St"}
    assert dm.read_conflicts_with_lead(li, first_entry) == "case_number_mismatch"
    assert dm.read_conflicts_with_lead(li, {"case_number": "2099 CP 1 468"}) is None
    no_case = _li(street_address="704 Sample Rd")
    assert dm.read_conflicts_with_lead(no_case, {"property_address": "504 Other St"}) == "house_number_mismatch"
    assert dm.read_conflicts_with_lead(no_case, {"property_address": "704 Sample Road"}) is None


def test_revise_columns_undoes_only_unvouched_fills():
    old = {"owner_name": "FIRST ENTRY PERSON", "case_number": "2099-CP-01-00843"}
    li = _li(owner_name="FIRST ENTRY PERSON", defendant="ROW OWN DEFENDANT",
             case_number="2099-CP-01-00468", raw={"scraper_block": {"defendant": "ROW OWN DEFENDANT"}})
    assert dm.revise_columns(li, old, None) == ["owner_name"]
    assert li.owner_name is None and li.defendant == "ROW OWN DEFENDANT"
    # the same value also carried by the scraper's own block stays
    li2 = _li(owner_name="FIRST ENTRY PERSON", raw={"scraper_block": {"name": "First Entry Person"}})
    assert dm.revise_columns(li2, old, None) == []
    assert li2.owner_name == "FIRST ENTRY PERSON"


# ------------------------------------------------------------------ roster matcher
def test_lot_numbers_are_not_house_numbers():
    text = "EXAMPLE PAT S 11111-22-333 LOT 43 MEETING ST 1 2 32\n"
    li = _li(parcel_id="11111-22-333", street_address=None)
    assert dm._row_backfill_from_aggregate(li, text) == []
    text2 = "EXAMPLE PAT S 11111-22-333 TRK 4 OFF HWY 57 9 20\n"
    assert dm._row_backfill_from_aggregate(_li(parcel_id="11111-22-333"), text2) == []
    ok = "11111-22-333 EXAMPLE PAT 264 SAMPLE OAK DR\n"
    li3 = _li(parcel_id="11111-22-333", street_address=None)
    assert dm._row_backfill_from_aggregate(li3, ok) == ["street_address"]
    assert li3.street_address == "264 SAMPLE OAK DR"


def test_a_parcel_id_matches_a_whole_token_only():
    text = "123 SAMPLE TRUST 999900001111A 307 WRONG DR\n"
    li = _li(parcel_id="999900001111", street_address=None)
    assert dm._row_backfill_from_aggregate(li, text) == []


def test_reverify_clears_an_old_lot_number_stamp_and_keeps_a_later_address():
    text = "EXAMPLE PAT S 11111-22-333 LOT 43 MEETING ST 1 2 32\n"
    li = _li(parcel_id="11111-22-333", street_address="43 MEETING ST",
             raw={"doc_ocr": {"_source": "aggregate_row_match", "matched_on": "11111-22-333"}})
    assert dm.reverify_aggregate_stamp(li, text) == "cleared"
    assert li.street_address is None and "doc_ocr" not in li.raw
    later = _li(parcel_id="11111-22-333", street_address="77 RESOLVED WAY",
                raw={"doc_ocr": {"_source": "aggregate_row_match"}})
    assert dm.reverify_aggregate_stamp(later, text) is None     # not the roster's text: untouched
    assert later.street_address == "77 RESOLVED WAY"


# ------------------------------------------------------------------ formats
def test_html_notice_is_read_as_text_and_office_files_are_unsupported(monkeypatch):
    seen = {}

    async def fake_text(txt, http, keys):
        seen["txt"] = txt
        return {"owner_name": "X"}

    monkeypatch.setattr(dm, "_ocr_text", fake_text)
    html = b"<html><head><script>var a=1</script></head><body><p>" + b"Notice of sale words " * 20 + b"</p></body></html>"
    res, kind = asyncio.run(dm._ocr_bytes(html, "text/html", None, ["k"]))
    assert kind == "html_text" and "var a" not in seen["txt"] and "Notice of sale" in seen["txt"]
    res, kind = asyncio.run(dm._ocr_bytes(b"PK\x03\x04rest", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", None, ["k"]))
    assert res is None and kind == "unsupported:office_file"


def test_tiff_is_converted_before_the_vision_call(monkeypatch):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("L", (40, 40), 255).save(buf, "TIFF")
    sent = {}

    async def fake_chain(keys, payload, is_text):
        sent["mime"] = payload[0][1]
        return {"owner_name": "X"}

    monkeypatch.setattr(dm, "_gemini_chain", fake_chain)
    res, kind = asyncio.run(dm._ocr_bytes(buf.getvalue(), "image/tiff", None, ["k"]))
    assert kind == "image" and sent["mime"] == "image/png"


def test_gemini_overload_stops_the_key_chain(monkeypatch):
    calls = []

    async def overloaded(key, payload, is_text):
        calls.append(key)
        raise dm._Overloaded(key)

    monkeypatch.setattr(dm, "_gemini_call", overloaded)
    dm._GEMINI_OVERLOAD.update(streak=0, until=0.0)
    assert asyncio.run(dm._gemini_chain(["k1", "k2", "k3"], "t", True)) is None
    assert calls == ["k1"]                      # the other keys reach the same overloaded model
    dm._GEMINI_OVERLOAD.update(streak=0, until=0.0)


def test_paid_fallback_needs_the_owner_opt_in(monkeypatch):
    called = []

    async def fake_anthropic(http, key, blocks, text=None):
        called.append(1)
        return {"owner_name": "X"}

    for k in ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN", "GROQ_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setattr(dm, "_anthropic_call", fake_anthropic)
    monkeypatch.delenv("DOC_OCR_ALLOW_PAID", raising=False)
    assert asyncio.run(dm._compat_chain(None, text="t")) is None and not called
    monkeypatch.setenv("DOC_OCR_ALLOW_PAID", "1")
    assert asyncio.run(dm._compat_chain(None, text="t")) == {"owner_name": "X"}


def test_small_scanned_page_rasterizes_large():
    pytest.importorskip("pdfplumber")
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (84, 251), "white").save(buf, "PDF", resolution=72)
    data = buf.getvalue()
    assert dm._first_page_long_side(data) < dm._SMALL_PAGE_PT
    png, mime = dm._raster_scan(data)
    im = Image.open(BytesIO(png))
    assert mime == "image/png" and max(im.size) >= 2000


# ------------------------------------------------------------------ the enricher end to end
def _fake_io(monkeypatch, docs: dict, reads: dict, fetched: list, ocred: list):
    async def fake_fetch(hc, url):
        fetched.append(url)
        if url not in docs:
            return None, "", "fetch_failed:http_404"
        return docs[url], "application/pdf", ""

    async def fake_ocr(data, mime, hc, keys):
        ocred.append(data)
        r = reads.get(data)
        return (dict(r), "pdf_text") if r else (None, "pdf_text")

    monkeypatch.setattr(dm, "_fetch_doc_checked", fake_fetch)
    monkeypatch.setattr(dm, "_ocr_bytes", fake_ocr)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")


def test_enricher_records_every_outcome_reads_best_leads_first_and_resumes(ledger_dir, monkeypatch):
    fetched, ocred = [], []
    docs = {"https://n.example.test/a.pdf": b"A", "https://n.example.test/c.pdf": b"C"}
    reads = {b"A": {"owner_name": "Pat Example", "case_number": "99SP000001", "doc_type": "foreclosure_notice"},
             b"C": {}}
    _fake_io(monkeypatch, docs, reads, fetched, ocred)
    cold = _li(case_number="99SP000001", raw={"document_url": "https://n.example.test/a.pdf"})
    hot = _li(raw={"document_url": "https://n.example.test/b.pdf", "distress_stack": {"tier": "HOT"}})
    warm = _li(raw={"document_url": "https://n.example.test/c.pdf", "distress_stack": {"tier": "WARM"}})
    stats = asyncio.run(dm.enrich_doc_ocr([cold, hot, warm], http=object()))
    assert fetched == ["https://n.example.test/b.pdf", "https://n.example.test/c.pdf",
                       "https://n.example.test/a.pdf"]          # HOT, WARM, then the rest
    led = dl.DocLedger.load("doc_ocr")
    outcomes = {k: e["outcome"] for k, e in led.rows.items()}
    assert outcomes[inv.doc_key("https://n.example.test/b.pdf")] == "fetch_failed"
    assert outcomes[inv.doc_key("https://n.example.test/c.pdf")] == "provider_failed"
    assert outcomes[inv.doc_key("https://n.example.test/a.pdf")] == "extracted"
    assert cold.defendant == "Pat Example" and stats["fetch_failed"] == 1
    # a second run: the read document is not fetched again, the failures wait for their retry
    fetched.clear()
    dl.reset_cache()
    asyncio.run(dm.enrich_doc_ocr([cold, hot, warm], http=object()))
    assert fetched == []


def test_enricher_reuses_a_read_of_the_same_bytes_under_another_url(ledger_dir, monkeypatch):
    fetched, ocred = [], []
    docs = {"https://n.example.test/x.pdf": b"SAME", "https://mirror.example.test/y.pdf": b"SAME"}
    reads = {b"SAME": {"case_number": "99SP000002", "doc_type": "foreclosure_notice"}}
    _fake_io(monkeypatch, docs, reads, fetched, ocred)
    a = _li(raw={"document_url": "https://n.example.test/x.pdf", "distress_stack": {"tier": "HOT"}})
    b = _li(raw={"document_url": "https://mirror.example.test/y.pdf"})
    stats = asyncio.run(dm.enrich_doc_ocr([a, b], http=object()))
    assert len(ocred) == 1 and stats["same_content_reused"] == 1
    assert b.case_number == "99SP000002"


def test_enricher_never_applies_another_leads_entry_from_a_list(ledger_dir, monkeypatch):
    fetched, ocred = [], []
    docs = {"https://mie.example.test/list.pdf": b"LIST"}
    reads = {b"LIST": {"owner_name": "FIRST ENTRY PERSON", "case_number": "2099-CP-01-00843",
                       "doc_type": "foreclosure_notice"}}
    _fake_io(monkeypatch, docs, reads, fetched, ocred)
    li = _li(case_number="2099-CP-01-00468", raw={"document_url": "https://mie.example.test/list.pdf"})
    stats = asyncio.run(dm.enrich_doc_ocr([li], http=object()))
    assert li.defendant is None and li.owner_name is None and "doc_ocr" not in li.raw
    e = dl.DocLedger.load("doc_ocr").rows[inv.doc_key("https://mie.example.test/list.pdf")]
    assert e["outcome"] == "no_fields" and e["reason"].startswith("read_is_another_lead")
    assert stats["reads_of_another_lead"] == 1


def test_enricher_sets_aside_an_old_read_of_another_case(ledger_dir, monkeypatch):
    _fake_io(monkeypatch, {}, {}, [], [])
    li = _li(case_number="2099-CP-01-00468", defendant="FIRST ENTRY PERSON",
             raw={"document_url": "https://gone.example.test/l.pdf",
                  "doc_ocr": {"_source": "pdf_text", "owner_name": "FIRST ENTRY PERSON",
                              "case_number": "2099-CP-01-00843"}})
    stats = asyncio.run(dm.enrich_doc_ocr([li], http=object()))
    assert stats["old_reads_rejected"] == 1
    assert li.defendant is None and li.raw["doc_ocr_rejected"]["reason"] == "case_number_mismatch"


def test_roster_pass_runs_first_and_has_its_own_budget(ledger_dir, monkeypatch):
    order = []

    async def fake_fetch(hc, url):
        order.append(url)
        if "roster" in url:
            return b"%PDF-roster", "application/pdf", ""
        return b"%PDF-n", "application/pdf", ""

    async def fake_ocr(data, mime, hc, keys):
        return ({"case_number": "1"}, "pdf_text")

    monkeypatch.setattr(dm, "_fetch_doc_checked", fake_fetch)
    monkeypatch.setattr(dm, "_ocr_bytes", fake_ocr)
    monkeypatch.setattr(dm, "_pdf_text", lambda data, **kw: "11111-22-333 EXAMPLE 264 SAMPLE OAK DR\n" * 20)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    roster = "https://county.example.test/roster.pdf"
    leads = [_li(parcel_id="11111-22-333", source_url=roster, street_address=None)]
    leads += [_li(parcel_id=f"2222{i}", source_url=roster, street_address="1 X ST") for i in range(4)]
    leads.append(_li(raw={"document_url": "https://n.example.test/n.pdf", "distress_stack": {"tier": "HOT"}}))
    stats = asyncio.run(dm.enrich_doc_ocr(leads, http=object()))
    assert order[0] == roster and stats["agg_backfilled"] == 1
    assert leads[0].street_address == "264 SAMPLE OAK DR"
    e = dl.DocLedger.load("doc_ocr").rows[inv.doc_key(roster)]
    assert e["outcome"] == "aggregate_read" and e["values"]["rows_filled"] == 1


def test_roster_pass_runs_without_any_model_key(ledger_dir, monkeypatch):
    for k in ("GEMINI_API_KEY", "GITHUB_MODELS_TOKEN", "GITHUB_TOKEN", "GROQ_API_KEY",
              "NVIDIA_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for i in range(1, 10):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

    async def fake_fetch(hc, url):
        return b"%PDF-roster", "application/pdf", ""

    monkeypatch.setattr(dm, "_fetch_doc_checked", fake_fetch)
    monkeypatch.setattr(dm, "_pdf_text", lambda data, **kw: "11111-22-333 EXAMPLE 264 SAMPLE OAK DR\n")
    roster = "https://county.example.test/roster.pdf"
    leads = [_li(parcel_id="11111-22-333", source_url=roster, street_address=None)]
    leads += [_li(parcel_id=f"2222{i}", source_url=roster, street_address="1 X ST") for i in range(4)]
    stats = asyncio.run(dm.enrich_doc_ocr(leads, http=object()))
    assert stats["no_provider"] == 1 and stats["agg_backfilled"] == 1

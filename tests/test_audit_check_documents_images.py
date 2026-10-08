"""scripts/audit_checks/documents_images.py on made-up rows (2026-10-09 audit)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from foreclosure_scraper import doc_inventory as inv
from foreclosure_scraper import doc_ledger as dl

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "documents_images.py"


def _mod():
    spec = importlib.util.spec_from_file_location("audit_documents_images", _PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(rows):
    m = _mod()
    checks = m.make_checks()
    for r in rows:
        for c in checks:
            c.feed(r)
    return {res["name"]: res for res in (c.finish() for c in checks)}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_LEDGER_DIR", str(tmp_path / "led"))
    monkeypatch.setenv("DOC_LEDGER_PRIVATE_DIR", str(tmp_path / "priv"))
    monkeypatch.setenv("AUDIT_DOCS_DIR", str(tmp_path / "docs"))
    (tmp_path / "docs").mkdir()
    dl.reset_cache()
    led = {lane: dl.DocLedger(lane, {}, persistent=True, path=tmp_path / "led" / f"{lane}.json")
           for lane in dl.LANES}
    yield led, tmp_path
    dl.reset_cache()


def _row(**kw):
    raw = kw.pop("raw", {})
    base = {"source": "test.src", "state": "NC", "county": "Testcounty", "parcel_id": "P1",
            "source_url": "https://example.test/page", "raw": raw}
    base.update(kw)
    return base


def test_interface_shape(ledger):
    out = _run([_row()])
    for res in out.values():
        assert set(res) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
        assert res["ok"] == (res["violations"] <= res["max_violations"])


def test_a_read_without_a_ledger_entry_is_a_violation(ledger):
    led, _ = ledger
    url = "https://n.example.test/a.pdf"
    read = _row(raw={"document_url": url, "doc_ocr": {"_source": "pdf_text", "owner_name": "X"}})
    assert _run([read])["docs-processed-has-ledger-entry"]["violations"] == 1
    led["doc_ocr"].record(inv.doc_key(url), outcome="extracted", version="v1")
    led["doc_ocr"].save()
    dl.reset_cache()
    assert _run([read])["docs-processed-has-ledger-entry"]["violations"] == 0


def test_per_lead_docs_need_an_outcome_rosters_need_a_read(ledger):
    led, _ = ledger
    rows = [_row(parcel_id=f"R{i}", source_url="https://c.example.test/roster.pdf",
                 street_address=None) for i in range(5)]
    rows += [_row(parcel_id="N1", raw={"document_url": "https://n.example.test/own.pdf"})]
    out = _run(rows)
    assert out["docs-roster-rows-read"]["violations"] == 5
    assert out["docs-per-lead-doc-outcome"]["checked"] == 1
    assert out["docs-per-lead-doc-outcome"]["violations"] == 1
    led["doc_ocr"].record(inv.doc_key("https://c.example.test/roster.pdf?v=9"), outcome="aggregate_read", version="v")
    led["doc_ocr"].record(inv.doc_key("https://n.example.test/own.pdf"), outcome="fetch_failed", version="v")
    led["doc_ocr"].save()
    dl.reset_cache()
    out = _run(rows)
    assert out["docs-roster-rows-read"]["violations"] == 0       # cache buster ignored
    assert out["docs-per-lead-doc-outcome"]["violations"] == 0   # a failure is an outcome too


def test_hot_warm_photo_rows_need_a_grade_or_outcome(ledger):
    warm = _row(raw={"distress_stack": {"tier": "WARM"},
                     "images": {"real": ["https://img.example.test/a.jpg"]}})
    cold = _row(raw={"images": {"real": ["https://img.example.test/b.jpg"]}})
    graded = _row(raw={"distress_stack": {"tier": "HOT"}, "vision": {"condition_tier": "cosmetic"},
                       "images": {"real": ["https://img.example.test/c.jpg"]}})
    res = _run([warm, cold, graded])["images-hot-warm-graded"]
    assert res["checked"] == 2 and res["violations"] == 1 and "1 of 1" in res["detail"]


def test_missing_relative_photo_and_shared_stamp_and_tax_amount(ledger):
    _, tmp = ledger
    (tmp / "docs" / "parcel_photos").mkdir()
    (tmp / "docs" / "parcel_photos" / "here.jpg").write_bytes(b"x")
    rows = [_row(raw={"images": {"real": ["parcel_photos/here.jpg"]}}),
            _row(raw={"images": {"real": ["parcel_photos/gone.jpg"]}})]
    stamp = {"_source": "pdf_text", "owner_name": "SAME PERSON", "property_address": "1 A St"}
    rows += [_row(parcel_id=f"S{i}", raw={"doc_ocr": dict(stamp)}) for i in range(5)]
    rows += [_row(judgment_amount=812.0, raw={"doc_ocr": {"_source": "pdf_text", "amount": "812.00",
                                                          "doc_type": "tax_sale"}})]
    out = _run(rows)
    assert out["images-relative-photo-present"]["violations"] == 1
    assert out["docs-ocr-no-shared-stamp"]["violations"] == 5
    assert out["docs-ocr-tax-not-judgment"]["violations"] == 1


def test_dot_counties_without_any_attempt(ledger):
    led, _ = ledger
    rows = [_row(state="NC", county="Burke", owner_name="EXAMPLE, PAT"),
            _row(state="NC", county="Lincoln", owner_name="EXAMPLE, LEE")]
    assert _run(rows)["docs-dot-county-attempted"]["violations"] == 2
    led["dot_ocr"].record("o:x", outcome="no_document", version="v", county="NC:Burke")
    led["dot_ocr"].save()
    dl.reset_cache()
    assert _run(rows)["docs-dot-county-attempted"]["violations"] == 1


def test_a_read_of_another_case_is_a_violation(ledger):
    rows = [_row(case_number="2099-CP-01-00468",
                 raw={"doc_ocr": {"_source": "pdf_text", "case_number": "2099-CP-01-00843"}}),
            _row(case_number="99SP000001",
                 raw={"doc_ocr": {"_source": "pdf_scan", "case_number": "99 SP 1"}})]
    res = _run(rows)["docs-ocr-binds-to-row"]
    assert res["checked"] == 2 and res["violations"] == 1

"""dot_ocr: the processed-documents ledger, a fair share of the run per county, and the
fallback chain's `blocks` binding (2026-10-09 documents_images audit). Made-up owners; the
vendor lookup is always monkeypatched (no network, no vendor code runs)."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from foreclosure_scraper import doc_inventory as inv
from foreclosure_scraper import doc_ledger as dl
from foreclosure_scraper import enrichment_dot_ocr as dm
from foreclosure_scraper.models import Listing
from foreclosure_scraper.rod import doc_images as di
from foreclosure_scraper.rod.models import RodDoc


def _lead(county: str, state: str, owner: str, tier: str = "") -> Listing:
    li = Listing(source="test.src", source_url="https://example.test/x", state=state,
                 county=county, owner_name=owner)
    li.raw = {"distress_stack": {"tier": tier}} if tier else {}
    return li


@pytest.fixture
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC_LEDGER_DIR", str(tmp_path / "led"))
    monkeypatch.setenv("DOC_LEDGER_PRIVATE_DIR", str(tmp_path / "priv"))
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    dl.reset_cache()
    yield tmp_path
    dl.reset_cache()


def test_every_configured_county_gets_a_share_of_the_cap(ledger_dir, monkeypatch):
    """2026-10-07: Lincoln 200 + Burke 200 took the whole 400 cap; 9 counties never searched."""
    monkeypatch.setenv("FORECLOSURE_DOT_OCR_MAX", "6")
    seen = []

    async def _none(state, county, owner, **kw):
        seen.append(county)
        return []

    monkeypatch.setattr(di, "owner_dot_documents", _none)
    leads = [_lead("Burke", "NC", f"FIRST{i}, A") for i in range(10)]
    leads += [_lead("Cleveland", "NC", f"SECOND{i}, B") for i in range(10)]
    leads += [_lead("Henderson", "NC", f"THIRD{i}, C") for i in range(10)]
    stats = asyncio.run(dm.enrich_dot_ocr(leads))
    assert sorted(set(seen)) == ["Burke", "Cleveland", "Henderson"]
    assert stats["county_share"] == 2 and stats["searched"] == 6
    assert stats["left_for_next_run"] == 24 and stats["budget_exhausted"] is True


def test_a_search_that_found_nothing_is_not_repeated_next_run(ledger_dir, monkeypatch):
    calls = []

    async def _none(state, county, owner, **kw):
        calls.append(owner)
        return []

    monkeypatch.setattr(di, "owner_dot_documents", _none)
    li = _lead("Burke", "NC", "EXAMPLE, PAT")
    asyncio.run(dm.enrich_dot_ocr([li]))
    key = inv.owner_search_key("NC", "Burke", "EXAMPLE, PAT")
    e = dl.DocLedger.load("dot_ocr").rows[key]
    assert e["outcome"] == "no_document" and "EXAMPLE" not in str(e)
    dl.reset_cache()
    stats = asyncio.run(dm.enrich_dot_ocr([li]))
    assert calls == ["EXAMPLE, PAT"] and stats["ledger_not_due"] == 1


def test_best_leads_are_searched_first_inside_a_county(ledger_dir, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_DOT_OCR_MAX", "1")
    seen = []

    async def _none(state, county, owner, **kw):
        seen.append(owner)
        return []

    monkeypatch.setattr(di, "owner_dot_documents", _none)
    leads = [_lead("Burke", "NC", "COLD, ONE"), _lead("Burke", "NC", "HOT, ONE", tier="HOT")]
    asyncio.run(dm.enrich_dot_ocr(leads))
    assert seen == ["HOT, ONE"]


def test_a_found_loan_is_recorded_with_public_values_only(ledger_dir, monkeypatch):
    from foreclosure_scraper import enrichment_doc_ocr as ocr

    async def _one(state, county, owner, **kw):
        return [(b"%PDF-note", "application/pdf",
                 RodDoc(county="Burke", state="NC", doc_type="D/T",
                        recorded_date=datetime(2019, 4, 12), book="1", page="2",
                        instrument_no="INST1", grantor="EXAMPLE PAT", grantee="FAKE BANK",
                        raw={"image_key": "k", "vendor": "cchs"}))]

    async def _gem(key, parts, is_text):
        return {"amount": 123456.0, "doc_type": "deed_of_trust", "owner_name": "EXAMPLE PAT",
                "_provider": "gemini"}

    monkeypatch.setattr(di, "owner_dot_documents", _one)
    monkeypatch.setattr(ocr, "_gemini_call", _gem)
    li = _lead("Burke", "NC", "EXAMPLE, PAT")
    asyncio.run(dm.enrich_dot_ocr([li]))
    led = dl.DocLedger.load("dot_ocr")
    e = led.rows[inv.owner_search_key("NC", "Burke", "EXAMPLE, PAT")]
    assert e["outcome"] == "loan_found" and e["values"]["loan_amount"] == 123456
    assert "EXAMPLE" not in (led.path.read_text())


def test_a_gemini_answer_without_a_result_does_not_kill_the_county(ledger_dir, monkeypatch):
    """`blocks` used to be bound only when every Gemini key was quota-out; with an NVIDIA key
    set, a Gemini that answered nothing usable raised UnboundLocalError and the rest of the
    county was dropped."""
    from foreclosure_scraper import enrichment_doc_ocr as ocr
    monkeypatch.setenv("NVIDIA_API_KEY", "fake")
    seen = []

    async def _doc(state, county, owner, **kw):
        seen.append(owner)
        return [(b"\x89PNG\r\n\x1a\nfake", "image/png",
                 RodDoc(county="Burke", state="NC", doc_type="D/T",
                        recorded_date=datetime(2019, 4, 12), instrument_no="I", raw={}))]

    async def _gem(key, parts, is_text):
        return None

    async def _compat(http, name, url, key, model, blocks=None, text=None):
        return {"amount": 90000.0, "doc_type": "deed_of_trust", "_provider": name}

    monkeypatch.setattr(di, "owner_dot_documents", _doc)
    monkeypatch.setattr(ocr, "_gemini_call", _gem)
    monkeypatch.setattr(ocr, "_openai_compat_call", _compat)
    leads = [_lead("Burke", "NC", "FIRST, A"), _lead("Burke", "NC", "SECOND, B")]
    stats = asyncio.run(dm.enrich_dot_ocr(leads))
    assert seen == ["FIRST, A", "SECOND, B"] and stats["loan_found"] == 2

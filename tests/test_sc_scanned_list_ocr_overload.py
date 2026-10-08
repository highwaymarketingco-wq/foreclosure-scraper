"""Scanned SC tax lists: a Gemini overload (503) is transient, and Cherokee finds the list
its delinquent-tax page links even when the media search does not return it.

2026-10-08 VM run: Gemini answered "503 UNAVAILABLE ... high demand ... try again" on every
key for about 15 s. sc_flc and laurens_overage_claims read that as a hard error (the page
came back None and the document counted as 0 rows, a clean zero); cherokee gave up after one
pass over the keys. Made-up names and parcels throughout.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from foreclosure_scraper.scrapers.counties_sc import cherokee_delinquent_tax as cher
from foreclosure_scraper.scrapers.counties_sc import laurens_overage_claims as laur
from foreclosure_scraper.scrapers.counties_sc import sc_flc

OVERLOAD = ("503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently "
            "experiencing high demand. Spikes in demand are usually temporary. Please try again later.'}}")


def _fake_genai(monkeypatch, answers: list):
    """A google.genai stand-in: each generate_content call pops the next answer; an
    Exception instance is raised, a string is returned as resp.text."""
    calls = {"n": 0}

    class _Resp:
        def __init__(self, text):
            self.text = text

    class _Models:
        async def generate_content(self, **_kw):
            calls["n"] += 1
            a = answers.pop(0) if answers else ""
            if isinstance(a, Exception):
                raise a
            return _Resp(a)

    class _Client:
        def __init__(self, api_key=None):
            self.aio = types.SimpleNamespace(models=_Models())

    gtypes = types.SimpleNamespace(
        Part=types.SimpleNamespace(from_bytes=lambda data, mime_type: ("part", len(data))),
        GenerateContentConfig=lambda **kw: kw,
    )
    fake = types.ModuleType("google.genai")
    fake.Client = _Client
    fake.types = gtypes
    import google
    monkeypatch.setattr(google, "genai", fake, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    return calls


async def _no_sleep(_s):
    return None


# --- sc_flc -------------------------------------------------------------------------------

def test_sc_flc_page_survives_a_pool_wide_overload(monkeypatch):
    rows = [{"parcel": "100-00-00-001", "owner": "SAMPLE OWNER A"}]
    calls = _fake_genai(monkeypatch, [RuntimeError(OVERLOAD), RuntimeError(OVERLOAD),
                                      json.dumps({"rows": rows})])
    monkeypatch.setattr(sc_flc.asyncio, "sleep", _no_sleep)
    got = asyncio.run(sc_flc._ocr_page(b"%PDF-1.4", ["k1", "k2"]))
    assert got == rows
    assert calls["n"] == 3


def test_sc_flc_overload_all_sweeps_is_not_a_clean_zero(monkeypatch):
    _fake_genai(monkeypatch, [RuntimeError(OVERLOAD)] * 20)
    monkeypatch.setattr(sc_flc.asyncio, "sleep", _no_sleep)
    with pytest.raises(sc_flc._OCRQuotaOut):
        asyncio.run(sc_flc._ocr_page(b"%PDF-1.4", ["k1", "k2"]))


# --- laurens ------------------------------------------------------------------------------

def test_laurens_page_survives_a_pool_wide_overload(monkeypatch):
    page = {"tax_sale_date": "December 1, 2025",
            "rows": [{"item": "7", "map_number": "900-00-00-001",
                      "owner_name": "SAMPLE OWNER B", "amount": "$1,000.00"}]}
    _fake_genai(monkeypatch, [RuntimeError(OVERLOAD), json.dumps(page)])
    monkeypatch.setattr(laur.asyncio, "sleep", _no_sleep)
    got = asyncio.run(laur._ocr_page(b"%PDF-1.4", ["k1"]))
    assert got == page


def test_laurens_ships_the_pages_read_before_the_pool_gives_out(monkeypatch):
    page1 = {"tax_sale_date": "December 1, 2025",
             "rows": [{"item": "7", "map_number": "900-00-00-001",
                       "owner_name": "SAMPLE OWNER B", "amount": "$1,000.00"}]}
    monkeypatch.setattr(laur, "_split_pdf_pages", lambda data: [b"p1", b"p2"])
    _fake_genai(monkeypatch, [json.dumps(page1)] + [RuntimeError(OVERLOAD)] * 20)
    monkeypatch.setattr(laur.asyncio, "sleep", _no_sleep)
    monkeypatch.setenv("GEMINI_API_KEY", "k1")
    monkeypatch.setattr(laur, "OCR_ENABLED", True, raising=False)

    async def fake_doc_url(_c):
        return "https://example.invalid/overage.pdf"

    class _Resp:
        content = b"%PDF-1.4 fake"

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(laur, "_discover_doc_url", fake_doc_url)
    monkeypatch.setattr(laur.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(laur, "_parcel_lookup", lambda *a, **k: None)
    s = laur.LaurensOverageClaims()
    rows = asyncio.run(s.safe_run())
    assert [r.parcel_id for r in rows] == ["900-00-00-001"]
    assert [r.parcel_id for r in s.partial] == ["900-00-00-001"]


# --- cherokee -----------------------------------------------------------------------------

def test_cherokee_ocr_waits_out_an_overload(monkeypatch):
    text = "1 SAMPLE OWNER C 099-01-00-022.000 1 EXAMPLE ST"
    calls = _fake_genai(monkeypatch, [RuntimeError(OVERLOAD), RuntimeError(OVERLOAD), text])
    monkeypatch.setattr(cher, "_parse_gemini_keys", lambda: ["k1", "k2"])
    monkeypatch.setattr(cher.asyncio, "sleep", _no_sleep)
    got = asyncio.run(cher._ocr_pdf_text(b"%PDF-1.4"))
    assert got == text and calls["n"] == 3


PAGE_HTML = """
<a href="https://cherokeecountysc.gov/wp-content/uploads/2026/10/DOC010.pdf">Delinquent Tax Sale</a>
<a href="https://cherokeecountysc.gov/wp-content/uploads/2026/10/DOC011.pdf">Tax Sale Bidders</a>
<a href="https://cherokeecountysc.gov/wp-content/uploads/2025/02/Web-Policy.pdf">Web Policy</a>
"""
LIST_TEXT = """Item Number Owner Name Map Number Description
1 SAMPLE OWNER D 101-01-00-001.000 10 EXAMPLE RD
2 SAMPLE OWNER E 101-01-00-002.000 12 EXAMPLE RD
"""


def test_cherokee_reads_the_list_its_page_links_when_the_media_search_misses_it(monkeypatch):
    async def fake_get_text(url, **_kw):
        if "wp-json" in url:
            return json.dumps([])            # the media search does not return DOC010.pdf
        return PAGE_HTML

    fetched: list[str] = []

    async def fake_get_bytes(url, **_kw):
        fetched.append(url)
        return url.encode()

    monkeypatch.setattr(cher, "get_text", fake_get_text)
    monkeypatch.setattr(cher, "get_bytes", fake_get_bytes)
    monkeypatch.setattr(cher, "_extract_pdf_text",
                        lambda b: LIST_TEXT if b.endswith(b"DOC010.pdf") else "x" * 50)
    rows = asyncio.run(cher.CherokeeDelinquentTaxScraper().safe_run())
    assert sorted(r.parcel_id for r in rows) == ["101-01-00-001.000", "101-01-00-002.000"]
    assert fetched == ["https://cherokeecountysc.gov/wp-content/uploads/2026/10/DOC010.pdf"]


def test_page_links_keep_tax_sale_lists_only():
    got = cher._page_pdf_links(PAGE_HTML)
    assert [g["source_url"].rsplit("/", 1)[-1] for g in got] == ["DOC010.pdf"]

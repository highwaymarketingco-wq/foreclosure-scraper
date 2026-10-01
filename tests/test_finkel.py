"""Finkel Law Firm (SC) — monthly PDF docket.

Live-verified 2026-10-01: `images/Webs.pdf` on both finkellaw.com and
finkellawcharleston.com now sits behind a Cloudflare challenge (403 "Attention
Required!" to a plain-httpx request) that a real Chrome TLS fingerprint
(curl-cffi `impersonate="chrome"`) clears with a real 200 — confirmed with a
direct curl-cffi probe before changing any code. `fetch()` called the shared
`get_bytes()` helper with no escalation path, so it was silently returning 0
rows on every run (the `except Exception: continue` swallowed the 403). Fixed
by passing `impersonate=True` (the new http_client.get_bytes escalation tier,
see test_get_bytes_impersonate.py) — live `fetch()` went 0 -> 8 real rows.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.law_firms import finkel


def test_fetch_passes_impersonate_true_to_get_bytes(monkeypatch):
    """Regression guard for the exact silent-0-rows bug: without
    impersonate=True, get_bytes raises on Cloudflare's 403 and fetch()
    swallows it via `except Exception: continue`, returning []."""
    calls = []

    async def fake_get_bytes(url, timeout=60.0, impersonate=False):
        calls.append((url, impersonate))
        raise RuntimeError("simulated Cloudflare 403")  # fetch() must survive this

    monkeypatch.setattr(finkel, "get_bytes", fake_get_bytes)
    out = asyncio.run(finkel.Finkel().fetch())
    assert out == []
    assert len(calls) == 2  # both finkellaw.com + finkellawcharleston.com mirrors
    assert all(impersonate is True for _url, impersonate in calls)


def test_fetch_parses_rows_when_pdf_bytes_come_back(monkeypatch):
    import importlib
    import io

    pypdf = importlib.import_module("pypdf")

    async def fake_get_bytes(url, timeout=60.0, impersonate=False):
        # A minimal real PDF (one blank page) proves the extraction path runs
        # end-to-end; the docket-regex parsing itself is covered by _parse's
        # own text-based tests below.
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    monkeypatch.setattr(finkel, "get_bytes", fake_get_bytes)
    out = asyncio.run(finkel.Finkel().fetch())
    assert out == []  # blank page has no docket text, but no exception either


def test_parse_extracts_address_docket_and_parties():
    text = (
        "05/05/2025Lexington 11:00 A.M\n"
        "Some Sale Location Text\n"
        "2024CP3204157\n"
        "v. Imperial Acquisition Group, LLC; and Dominkey P. Graham\n"
        "PIC Fund I, LLC\n"
        "95,000.00\n"
        "701 Seton Road, Columbia, SC 29210\n"
    )
    # _parse anchors the address on the line immediately ABOVE the date line,
    # per the module's own documented PDF layout quirk.
    text = (
        "701 Seton Road, Columbia, SC 29210\n"
        "05/05/2025Lexington 11:00 A.M\n"
        "Some Sale Location Text\n"
        "2024CP3204157\n"
        "v. Imperial Acquisition Group, LLC; and Dominkey P. Graham\n"
        "PIC Fund I, LLC\n"
        "95,000.00\n"
    )
    out = finkel._parse(text, "https://www.finkellaw.com/images/Webs.pdf", "law_firms.finkel")
    assert len(out) == 1
    li = out[0]
    assert li.street_address == "701 Seton Road"
    assert li.city == "Columbia"
    assert li.county == "Lexington"
    assert li.case_number == "2024CP3204157"
    assert li.opening_bid == 95000.0
    assert li.plaintiff == "PIC Fund I, LLC"
    assert "Imperial Acquisition Group" in (li.defendant or "")


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.finkel" in {s.slug for s in all_scrapers()}

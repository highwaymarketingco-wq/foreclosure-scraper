"""york_sc.py -- guard-clause + helper unit tests (no network in CI).

The render path (StealthyFetcher driving a live ASP.NET UpdatePanel search) was
LIVE-VERIFIED manually against 3 real York TMS on 2026-11-16 (see the module's own
docstring and project_york_tax_portal_waf_2026-11-16.md) -- not exercised here, same
reason qpublic_render.py's render path has no CI test either (a real browser session
against a live county site is not something CI should depend on or hammer). This
file guards the parts that ARE deterministic: the TMS digit-normalizer and the
no-network early-outs, so a future refactor can't silently turn those into live
calls or break the "no parcel/owner -> None, no fetch" contract.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.assessor_cards import york_sc


def test_digits_strips_non_numeric():
    assert york_sc._digits("555-00-00-151") == "5550000151"
    assert york_sc._digits("5550000151") == "5550000151"
    assert york_sc._digits(None) == ""
    assert york_sc._digits("") == ""


def test_fetch_card_pdf_url_short_circuits_with_no_identity():
    """No parcel_id and no owner_name -> None immediately, no browser launch."""
    assert asyncio.run(york_sc.fetch_card_pdf_url(None)) is None
    assert asyncio.run(york_sc.fetch_card_pdf_url("")) is None


def test_fetch_card_pdf_bytes_short_circuits_with_no_identity():
    result = asyncio.run(york_sc.fetch_card_pdf_bytes(None, owner_name=None))
    assert result is None


def test_search_url_and_timeout_constants_are_sane():
    assert york_sc.SEARCH_URL.startswith("http://evolvepublic.yorkcountygov.com")
    assert york_sc._TIMEOUT_MS > 0

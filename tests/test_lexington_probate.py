"""Tests for LexingtonProbateScraper (counties_sc.lexington_probate).

Covers:
 - _parse_html: table rows -> Listing objects (happy path, header skip, empty)
 - reCAPTCHA audio helpers: _speech_to_text_groq (mocked), _solve_audio_challenge,
   _do_captcha_flow (mocked page frames)
 - Groq key fallback (env var vs file)

No live network calls; no browser launched.
"""
from __future__ import annotations

import asyncio
import os
import types
import unittest.mock as mock

import pytest

from foreclosure_scraper.scrapers.counties_sc.lexington_probate import (
    LexingtonProbateScraper,
    _get_recaptcha_response,
    _speech_to_text_groq,
    _find_challenge_frame,
    _find_anchor_frame,
    _solve_audio_challenge,
    _do_captcha_flow,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


# ---------------------------------------------------------------------------
# _parse_html
# ---------------------------------------------------------------------------

_TABLE_HTML = """
<html><body>
<table>
  <tr><th>Case #</th><th>Decedent</th><th>Filed</th><th>Status</th></tr>
  <tr>
    <td>2024-ES-32-00123</td>
    <td>SMITH, JOHN A</td>
    <td>01/15/2024</td>
    <td>Open</td>
  </tr>
  <tr>
    <td>2024-ES-32-00456</td>
    <td>JONES, MARY B</td>
    <td>03/22/2024</td>
    <td>Open</td>
  </tr>
</table>
</body></html>
"""


def test_parse_html_happy_path():
    scraper = LexingtonProbateScraper()
    results = scraper._parse_html(_TABLE_HTML)
    assert len(results) == 2

    r0 = results[0]
    assert isinstance(r0, Listing)
    assert r0.case_number == "2024-ES-32-00123"
    assert r0.owner_name == "SMITH, JOHN A"
    assert r0.county == "Lexington"
    assert r0.state == "SC"
    assert r0.listing_type == ListingType.PROBATE_NOTICE
    assert r0.property_kind == PropertyKind.UNKNOWN
    assert r0.raw["filed_date"] == "01/15/2024"
    assert r0.raw["status"] == "Open"
    assert r0.raw["decedent"] == "SMITH, JOHN A"

    r1 = results[1]
    assert r1.case_number == "2024-ES-32-00456"
    assert r1.owner_name == "JONES, MARY B"


def test_parse_html_skips_header_row():
    """First <tr> is headers — must not be treated as a data row."""
    scraper = LexingtonProbateScraper()
    results = scraper._parse_html(_TABLE_HTML)
    # Header row has no case number / decedent in the data pattern
    for r in results:
        assert r.case_number != "Case #"
        assert r.owner_name != "Decedent"


def test_parse_html_empty_table():
    """Empty table yields no listings."""
    html = "<html><body><table><tr><th>Case #</th></tr></table></body></html>"
    scraper = LexingtonProbateScraper()
    assert scraper._parse_html(html) == []


def test_parse_html_no_table():
    """No table in HTML yields no listings (not an exception)."""
    scraper = LexingtonProbateScraper()
    assert scraper._parse_html("<html><body><p>No results</p></body></html>") == []


def test_parse_html_skips_rows_with_missing_case_or_decedent():
    """Rows missing case_num or decedent are silently skipped, not fabricated."""
    html = """
    <html><body><table>
      <tr><td></td><td>SMITH</td><td>01/01/2024</td><td>Open</td></tr>
      <tr><td>2024-ES-32-00001</td><td></td><td>01/01/2024</td><td>Open</td></tr>
      <tr><td>2024-ES-32-00002</td><td>DOE, JANE</td><td>01/01/2024</td><td>Open</td></tr>
    </table></body></html>
    """
    scraper = LexingtonProbateScraper()
    results = scraper._parse_html(html)
    assert len(results) == 1
    assert results[0].case_number == "2024-ES-32-00002"


def test_parse_html_source_slug():
    """source field must be the scraper slug."""
    scraper = LexingtonProbateScraper()
    results = scraper._parse_html(_TABLE_HTML)
    for r in results:
        assert r.source == "counties_sc.lexington_probate"


# ---------------------------------------------------------------------------
# _speech_to_text_groq
# ---------------------------------------------------------------------------

def test_speech_to_text_groq_returns_none_when_no_key(monkeypatch):
    """With no key anywhere, STT returns None cleanly."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Patch file reads to raise
    orig_open = open

    def no_open(path, *a, **kw):
        raise FileNotFoundError(path)

    monkeypatch.setattr("builtins.open", no_open)
    result = asyncio.run(_speech_to_text_groq(b"fake_audio"))
    assert result is None


def test_speech_to_text_groq_uses_env_key(monkeypatch):
    """Key from GROQ_API_KEY env var is sent in the Authorization header."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_testkey123")

    import httpx

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "3 7 2 9"}

    async def fake_post(url, headers, files, **kw):
        assert headers["Authorization"] == "Bearer gsk_testkey123"
        return FakeResponse()

    with mock.patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.post = fake_post
        result = asyncio.run(_speech_to_text_groq(b"\x00" * 100))

    assert result == "3 7 2 9"


# ---------------------------------------------------------------------------
# _find_challenge_frame / _find_anchor_frame
# ---------------------------------------------------------------------------

def _make_frame(url: str):
    f = types.SimpleNamespace(url=url)
    return f


def test_find_challenge_frame_found():
    page = types.SimpleNamespace(
        frames=[
            _make_frame("https://www.google.com/recaptcha/api2/anchor?..."),
            _make_frame("https://www.google.com/recaptcha/api2/bframe?..."),
        ]
    )
    frame = asyncio.run(_find_challenge_frame(page))
    assert frame is not None
    assert "bframe" in frame.url


def test_find_challenge_frame_not_found():
    page = types.SimpleNamespace(
        frames=[_make_frame("https://www.example.com/")]
    )
    frame = asyncio.run(_find_challenge_frame(page))
    assert frame is None


def test_find_anchor_frame_found():
    page = types.SimpleNamespace(
        frames=[
            _make_frame("https://www.google.com/recaptcha/api2/anchor?..."),
        ]
    )
    frame = asyncio.run(_find_anchor_frame(page))
    assert frame is not None
    assert "anchor" in frame.url


# ---------------------------------------------------------------------------
# _do_captcha_flow — mocked page, auto-solved after checkbox
# ---------------------------------------------------------------------------

def _async_ret(val):
    async def inner(*a, **kw):
        return val
    return inner


def test_do_captcha_flow_auto_solved_after_checkbox():
    """If checkbox click yields a token immediately, return True without audio."""
    anchor = types.SimpleNamespace(
        url="https://www.google.com/recaptcha/api2/anchor?...",
    )
    # click on anchor frame
    async def anchor_click(sel):
        pass
    anchor.click = anchor_click

    call_count = [0]

    async def get_token(page):
        call_count[0] += 1
        # First call (after checkbox click): solved
        if call_count[0] >= 1:
            return "fake-recaptcha-token"
        return ""

    page = types.SimpleNamespace(
        frames=[anchor],
        evaluate=_async_ret(""),
    )

    import foreclosure_scraper.scrapers.counties_sc.lexington_probate as mod
    with mock.patch.object(mod, "_get_recaptcha_response", get_token):
        result = asyncio.run(_do_captcha_flow(page, max_attempts=3))

    assert result is True


def test_do_captcha_flow_returns_false_when_no_anchor_and_no_challenge():
    """No reCAPTCHA frames at all -> returns False gracefully."""
    page = types.SimpleNamespace(frames=[])

    async def no_token(page):
        return ""

    import foreclosure_scraper.scrapers.counties_sc.lexington_probate as mod
    with mock.patch.object(mod, "_get_recaptcha_response", no_token):
        result = asyncio.run(_do_captcha_flow(page, max_attempts=2))

    assert result is False


# ---------------------------------------------------------------------------
# Scraper slug / name / category invariants
# ---------------------------------------------------------------------------

def test_scraper_metadata():
    s = LexingtonProbateScraper()
    assert s.slug == "counties_sc.lexington_probate"
    assert s.name == "Lexington SC Probate"
    assert s.category == "probate"
    assert s.timeout_s >= 120

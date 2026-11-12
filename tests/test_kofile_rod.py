"""Kofile PublicSearch (Oconee SC) — offline tests for rod/kofile.py.

2026-10-02: the old flat `GET /api/search` REST endpoint this module used to
call is dead sitewide (404, React SPA error body). Live browser devtools
network capture against https://oconee.sc.publicsearch.us/search/advanced
found the real replacement: a persistent WebSocket at `wss://{host}/ws`
speaking the vendor's `@kofile/FETCH_DOCUMENTS/v4` protocol (see rod/kofile.py's
module docstring for the full handshake). This is a vendor API-contract
migration, not a wall — no CAPTCHA, no login, no WAF challenge anywhere in the
flow (the `authToken` is an anonymous visitor UUID the server hands any plain
GET, even a 404).

Fixtures in fixtures/kofile_fetch_documents_oconee.json are REAL byHash
entries from a live FETCH_DOCUMENTS_FULFILLED reply, captured 2026-10-02,
trimmed to the fields `_doc_to_rod` reads. `highlighted_doc` reproduces a real
quirk: a party-name search hit comes back with the match wrapped in
`<em>...</em>` inside the grantor/grantee strings, which `_doc_to_rod` must
strip. `correction_foreclosure_doc` reproduces Oconee's "FORECLOS" vendor
code (docType label "CORRECT FORECLOSURES") — a rare post-sale correction,
not a pre-foreclosure notice, confirmed against the live facet list
(meta.statistics.docTypes, 148 codes, no LIS PENDENS / NOTICE OF SALE /
NOTICE OF DEFAULT code exists for this county) — it must NOT match `_is_nod`.

CI never hits the network: `search_by_name`/`discover_recent_nods` are
exercised by monkeypatching `kofile._fetch_documents` (the module's one
network-touching seam) with canned fixture data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.rod import kofile

FIX = Path(__file__).parent / "fixtures" / "kofile_fetch_documents_oconee.json"
DOCS = json.loads(FIX.read_text())


def test_kofile_counties_only_oconee():
    assert ("SC", "Oconee") in kofile.KOFILE_COUNTIES
    assert kofile.KOFILE_COUNTIES[("SC", "Oconee")] == "oconee.sc.publicsearch.us"


def test_strip_highlight():
    assert kofile._strip_highlight("<em>SMITH</em> EVAN") == "SMITH EVAN"
    assert kofile._strip_highlight("PLAIN NAME") == "PLAIN NAME"
    assert kofile._strip_highlight("<em>A</em> and <em>B</em>") == "A and B"


def test_doc_to_rod_plain_doc():
    d = kofile._doc_to_rod(DOCS["plain_doc"], "Oconee", "SC")
    assert d is not None
    assert d.recorded_date is not None and d.recorded_date.year == 2026
    assert d.recorded_date.month == 7 and d.recorded_date.day == 31
    # "book" on the wire is a record-TYPE label ("DEED"), not a number — the
    # real book/volume lives in "volume".
    assert d.book == "4930"
    assert d.page == "168"
    assert d.instrument_no == "20260001907"
    assert "CARLSON" in d.grantor
    assert "RIDDERING" in d.grantee
    # FORECLOS DEED is a post-sale recording, not a pre-foreclosure notice.
    assert kofile._is_nod(d.doc_type) is False


def test_doc_to_rod_strips_html_highlight_from_names():
    d = kofile._doc_to_rod(DOCS["highlighted_doc"], "Oconee", "SC")
    assert d is not None
    assert "<em>" not in (d.grantee or "")
    assert "</em>" not in (d.grantee or "")
    assert "SMITH EVAN" in d.grantee and "SMITH OUIDA" in d.grantee
    assert d.grantor == "MCFADDEN KATHERINE"


def test_correction_foreclosures_is_not_a_nod():
    """Oconee's 'FORECLOS' vendor code is a rare post-sale correction
    document (grantor = Clerk of Court on an already-completed foreclosure),
    not a pre-foreclosure notice. The live facet list has no actual
    LIS PENDENS / NOTICE OF SALE / NOTICE OF DEFAULT code for this county."""
    d = kofile._doc_to_rod(DOCS["correction_foreclosure_doc"], "Oconee", "SC")
    assert d is not None
    assert kofile._is_nod(d.doc_type) is False


def test_doc_to_rod_handles_missing_and_malformed_fields():
    assert kofile._doc_to_rod({}, "Oconee", "SC") is not None  # doesn't raise
    assert kofile._doc_to_rod(None, "Oconee", "SC") is None
    assert kofile._doc_to_rod("not a dict", "Oconee", "SC") is None


def test_is_nod_keywords():
    assert kofile._is_nod("NOTICE OF SALE") is True
    assert kofile._is_nod("LIS PENDENS") is True
    assert kofile._is_nod("DEED") is False
    assert kofile._is_nod(None) is False


@pytest.mark.asyncio
async def test_unmapped_county_returns_empty():
    assert await kofile.search_by_name("NC", "Wake", "SMITH") == []
    assert await kofile.discover_recent_nods("NC", "Wake") == []


@pytest.mark.asyncio
async def test_search_by_name_empty_name_short_circuits():
    assert await kofile.search_by_name("SC", "Oconee", "") == []
    assert await kofile.search_by_name("SC", "Oconee", "   ") == []


@pytest.mark.asyncio
async def test_search_by_name_builds_both_role_parties_query(monkeypatch):
    """search_by_name must search BOTH grantor and grantee (lien-stack /
    payoff tracing needs every role a name appears in) — the same shape the
    live UI's 'Party Names (search both Grantor and Grantee)' field sends."""
    captured = {}

    async def fake_fetch(host, query, max_docs):
        captured["host"] = host
        captured["query"] = query
        captured["max_docs"] = max_docs
        return [DOCS["highlighted_doc"]]

    monkeypatch.setattr(kofile, "_fetch_documents", fake_fetch)
    out = await kofile.search_by_name("SC", "Oconee", "smith", max_docs=10)

    assert captured["host"] == "oconee.sc.publicsearch.us"
    parties = json.loads(captured["query"]["parties"])
    assert parties == {"parties": [{"term": "SMITH", "types": ["grantor", "grantee"]}]}
    assert captured["query"]["department"] == "RP"
    assert len(out) == 1 and out[0].grantee and "SMITH EVAN" in out[0].grantee


@pytest.mark.asyncio
async def test_discover_recent_nods_filters_and_dedupes(monkeypatch):
    """Feeds a mix of a real NOD-style doc, a non-NOD doc, and a duplicate —
    verifies the keyword filter and the (book, page, instrument_no) dedupe."""
    nod_doc = dict(DOCS["plain_doc"])
    nod_doc["docType"] = "NOTICE OF SALE"  # force a NOD-shaped label for this test

    async def fake_fetch(host, query, max_docs):
        return [nod_doc, DOCS["correction_foreclosure_doc"], dict(nod_doc)]  # dup of nod_doc

    monkeypatch.setattr(kofile, "_fetch_documents", fake_fetch)
    out = await kofile.discover_recent_nods("SC", "Oconee", days_back=9999, max_docs=10)

    assert len(out) == 1  # the correction doc is filtered out, the dup collapses
    assert out[0].doc_type == "NOTICE OF SALE"


@pytest.mark.asyncio
async def test_fetch_documents_auth_failure_returns_empty(monkeypatch):
    """_auth_token failing (host unreachable, no cookie) must degrade to [],
    never raise — same compliant-no-op contract as every other rod/ adapter."""
    async def fake_auth(host):
        return None

    monkeypatch.setattr(kofile, "_auth_token", fake_auth)
    out = await kofile._fetch_documents("oconee.sc.publicsearch.us", {}, 10)
    assert out == []

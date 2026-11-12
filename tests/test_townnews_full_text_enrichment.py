"""newspapers._townnews — full-text detail-page enrichment (`fetch_full_text` /
`DetailFetchBudget`), added 2026-10-13 (HERMES source-completeness audit,
Pattern D).

FOUND: index_journal.py / journal_scene.py / post_and_courier.py all stored
each RSS item's `<link>` and never fetched it, relying only on the feed's
~250-550-char `<description>` truncation -- while the sibling
newspapers.daily_courier.py (same TownNews/TNCMS platform) already proved
the full notice body is server-rendered in the detail page's
`[itemprop="description"]` element and fetchable with plain httpx (no JS, no
login, no WAF). Live-confirmed 2026-10-13 the same selector also works
unchanged on indexjournal.com and postandcourier.com (both the
classifieds_new and journal-scene sections) -- same platform, same selector.
`fetch_full_text()`/`DetailFetchBudget` (in `_townnews.py`) are the shared
best-effort enrichment every one of those 3 scrapers now calls.

These tests exercise the shared mechanism directly with synthetic TNCMS-
shaped detail-page HTML (invented notice text, same convention as
test_daily_courier_notice_contact.py's NOTICE_HTML): the full notice sits in
`[itemprop="description"]`, same selector daily_courier.py's own
`_notice_text()` reads.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.newspapers import _townnews as mod

# A detail page shaped like a real TNCMS ad page: the full notice (much
# longer than any RSS <description> truncation) server-rendered inside
# itemprop="description", same element daily_courier.py already reads.
FULL_NOTICE_HTML = """<html><head><title>NOTICE OF SALE | Classifieds</title></head>
<body><h1>NOTICE OF SALE</h1>
<div itemprop="description">
<p>STATE OF SOUTH CAROLINA COUNTY OF DORCHESTER IN THE COURT OF COMMON PLEAS
C/A No. 2026CP1801986 SUMMONS AND NOTICES (NON-JURY MORTGAGE FORECLOSURE)
Example Lending, LLC, Plaintiff, vs. Pat Q. Testerperson, Defendant(s).</p>
<p>The property to be sold is located at 120 Example Pond Court, Summerville,
SC 29485, TMS No. 999-99-99-999, more fully described in the Complaint on
file with the Clerk of Court.</p>
<p>Any person having a lien or claim upon the premises must present proof of
the same to the undersigned before the sale, or be forever barred.</p>
</div>
<div class="asset-body"></div>
</body></html>"""

NO_ITEMPROP_HTML = "<html><body><div class=\"asset-body\"></div></body></html>"


def _run(coro):
    return asyncio.run(coro)


def _listing(desc: str, *, url: str = "https://example.test/ad_x.html") -> Listing:
    from datetime import UTC, datetime

    return Listing(
        source="newspapers.test",
        source_url=url,
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Dorchester",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        raw={"townnews_legal": {"title": "NOTICE OF SALE", "desc": desc, "published": None}},
    )


def test_fetch_full_text_reads_the_itemprop_description_element(monkeypatch):
    async def fake_get_text(url, timeout=20.0):
        return FULL_NOTICE_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    txt = _run(mod.fetch_full_text("https://example.test/ad_x.html"))
    assert txt is not None
    assert "120 Example Pond Court" in txt
    assert "2026CP1801986" in txt
    assert "TMS No. 999-99-99-999" in txt


def test_fetch_full_text_returns_none_when_element_missing(monkeypatch):
    async def fake_get_text(url, timeout=20.0):
        return NO_ITEMPROP_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    assert _run(mod.fetch_full_text("https://example.test/ad_y.html")) is None


def test_fetch_full_text_never_raises_on_network_error(monkeypatch):
    async def fake_get_text(url, timeout=20.0):
        raise ConnectionError("boom")

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    assert _run(mod.fetch_full_text("https://example.test/ad_z.html")) is None


def test_budget_enrich_fills_full_text_when_longer_than_rss_snippet(monkeypatch):
    async def fake_get_text(url, timeout=20.0):
        return FULL_NOTICE_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    li = _listing("STATE OF SOUTH CAROLINA COUNTY OF DORCHESTER...SUMMONS AND NOTICES")
    budget = mod.DetailFetchBudget(delay_s=0)
    _run(budget.enrich(li))
    block = li.raw["townnews_legal"]
    assert "full_text" in block
    assert len(block["full_text"]) > len(block["desc"])
    assert "120 Example Pond Court" in block["full_text"]


def test_budget_enrich_leaves_snippet_untouched_when_fetch_fails(monkeypatch):
    async def fake_get_text(url, timeout=20.0):
        raise ConnectionError("boom")

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    li = _listing("some short rss snippet")
    budget = mod.DetailFetchBudget(delay_s=0)
    _run(budget.enrich(li))
    assert "full_text" not in li.raw["townnews_legal"]


def test_budget_caps_at_max_fetches(monkeypatch):
    calls = []

    async def fake_get_text(url, timeout=20.0):
        calls.append(url)
        return FULL_NOTICE_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    budget = mod.DetailFetchBudget(max_fetches=2, delay_s=0)

    async def run_three():
        for i in range(3):
            await budget.enrich(_listing("x", url=f"https://example.test/ad_{i}.html"))

    _run(run_three())
    # The 3rd enrich() call must be a no-op: the budget was exhausted by the
    # first two (it decrements `remaining` before the fetch, so two calls
    # consume the whole cap of 2).
    assert len(calls) == 2


def test_budget_trips_circuit_breaker_after_three_consecutive_failures(monkeypatch):
    calls = []

    async def fake_get_text(url, timeout=20.0):
        calls.append(url)
        raise ConnectionError("boom")

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    budget = mod.DetailFetchBudget(max_fetches=10, delay_s=0)

    async def run_five():
        for i in range(5):
            await budget.enrich(_listing("x", url=f"https://example.test/ad_{i}.html"))

    _run(run_five())
    # After 3 consecutive failures the breaker trips (`blocked` is True) and
    # the 4th/5th calls never even attempt a fetch -- exactly the "stop
    # instead of asking again" behavior these scrapers' own feed-loop 403/429
    # handling already uses.
    assert budget.blocked is True
    assert len(calls) == 3

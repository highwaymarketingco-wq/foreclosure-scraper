"""Court-records enrichment: NC via Tyler batch search (fast/compliant). The SC
path is DISABLED as of 2026-10-01 -- see enrichment_courts.SC_PUBLIC_INDEX_WALLED
and counties_sc.sc_public_index's disabled_reason. It used to run a per-county
bulk scrape (counties_sc.sc_public_index._scrape_county) against
publicindex.sccourts.org/PublicIndex, which is F5/Shape WAF-challenged and
whose own disclaimer expressly prohibits automated scraping -- the same
violation class as the sibling counties_sc.sc_public_index_lis_pendens,
disabled the same day. Disabling only the registry scraper would not have
stopped this module, since both of its SC code paths called the scraper's
internals directly rather than going through BaseScraper.safe_run()'s
disabled-gate.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_courts as ec
from foreclosure_scraper.models import Listing, ListingType


def _sc(i: int) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="SC", county="Spartanburg", case_number=f"2026CP{i:06d}")


def _nc(case: str, **kw) -> Listing:
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", case_number=case, **kw)


async def _fake_no_sleep(*a, **k):
    return None


def test_sc_path_never_touches_the_walled_scraper(monkeypatch):
    """AUDITED 2026-10-01: the SC bulk county-scrape backfill was removed as a
    WAF-defeat + ToS violation. enrich_with_court_records must never import or
    call counties_sc.sc_public_index._scrape_county, and must leave SC
    listings' plaintiff/defendant exactly as they arrived."""
    from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi

    calls = {"scrape": 0, "render": 0}

    async def boom_scrape(county):
        calls["scrape"] += 1
        raise AssertionError("the walled SC scraper must never be called")

    async def boom_render(*a, **k):
        calls["render"] += 1
        raise AssertionError("SC enrichment must not render anything either")

    monkeypatch.setattr(scpi, "_scrape_county", boom_scrape)
    monkeypatch.setattr(ec, "fetch_rendered", boom_render)
    monkeypatch.setattr(ec.asyncio, "sleep", _fake_no_sleep)

    targets = [_sc(i) for i in range(5)]
    asyncio.run(ec.enrich_with_court_records(targets))

    assert calls == {"scrape": 0, "render": 0}
    assert all(li.plaintiff is None and li.defendant is None for li in targets)


def test_sc_path_never_clobbers_existing_fields_either():
    """Even with the walled path removed, a listing that already carries
    plaintiff/defendant (from its own compliant scraper) must be untouched."""
    li = _sc(1)
    li.plaintiff = "Original Plaintiff"
    li.defendant = "Original Defendant"
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.plaintiff == "Original Plaintiff"
    assert li.defendant == "Original Defendant"


def test_discover_lis_pendens_sc_branch_never_fetches(monkeypatch):
    """AUDITED 2026-10-01: SC lis-pendens discovery hit the same WAF-walled
    /PublicIndex/CaseSearchResults.aspx endpoint. It must now be skipped for
    every SC county without ever calling fetch_rendered, while NC counties
    still go through the normal (compliant) WorkspaceMode search."""
    from foreclosure_scraper.config import ALL_COUNTIES

    calls = []

    async def fake_render(url, token=None):
        calls.append(url)
        return ""  # no case numbers; we only care which URLs were hit

    monkeypatch.setattr(ec, "fetch_rendered", fake_render)
    asyncio.run(ec.discover_lis_pendens())

    assert not any("sccourts.org" in u for u in calls)
    sc_counties = [c for c in ALL_COUNTIES if c.state == "SC"]
    nc_counties = [c for c in ALL_COUNTIES if c.state == "NC"]
    if nc_counties:
        assert len(calls) == len(nc_counties)
    if sc_counties:
        # Every SC county was genuinely skipped, not silently merged with NC.
        assert len(calls) < len(ALL_COUNTIES)


# ---- NC batch-search path ------------------------------------------------------

def test_nc_batch_match_fills_empty_fields(monkeypatch):
    hit = {"caseNumber": "26 SP000359-440",
           "debtors": [{"name": "John Doe"}], "creditors": [{"name": "Acme Bank"}],
           "causeOfActionDesc": "Foreclosure", "location": "Gaston District Court"}

    async def fake_index():
        return {ec._norm_case("26 SP000359-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    li = _nc("26SP000359-440", raw={})
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.defendant == "John Doe" and li.plaintiff == "Acme Bank"
    assert li.raw["court_record"]["source"] == "nc_ecourts_search"


def test_nc_batch_does_not_overwrite_existing(monkeypatch):
    hit = {"caseNumber": "26 SP1-440", "debtors": [{"name": "New Debtor"}], "creditors": []}

    async def fake_index():
        return {ec._norm_case("26 SP1-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    li = _nc("26SP1-440", defendant="Original Defendant", raw={})
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.defendant == "Original Defendant"  # preserved


def test_no_nc_index_call_when_no_nc_listings(monkeypatch):
    called = {"n": 0}

    async def spy():
        called["n"] += 1
        return {}

    monkeypatch.setattr(ec, "_build_nc_case_index", spy)
    monkeypatch.setattr(ec, "fetch_rendered", lambda *a, **k: "")
    asyncio.run(ec.enrich_with_court_records([_sc(1)]))  # SC only
    assert called["n"] == 0  # never touches the NC search when no NC case#s

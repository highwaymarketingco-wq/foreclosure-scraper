"""Court-records enrichment: NC via Tyler batch search (fast/compliant). The SC
path was re-enabled 2026-10-02 per owner direction -- it runs a per-county
bulk scrape (counties_sc.sc_public_index._scrape_county) against
publicindex.sccourts.org/PublicIndex and backfills plaintiff/defendant from
the results. discover_lis_pendens also hits the SC CaseSearchResults.aspx
endpoint for lis-pendens discovery.
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


def test_sc_path_backfills_empty_fields(monkeypatch):
    """RE-ENABLED 2026-10-02: the SC bulk county-scrape backfill is active.
    enrich_with_court_records should call counties_sc.sc_public_index._scrape_county
    once per county and fill in empty plaintiff/defendant from the results."""
    from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi
    from foreclosure_scraper.models import Listing as L

    calls = {"scrape": 0}

    async def fake_scrape(county):
        calls["scrape"] += 1
        # Return a listing with a matching case number
        return [L(
            source="counties_sc.sc_public_index",
            source_url="u",
            listing_type=ListingType.FORECLOSURE_SALE,
            state="SC",
            county=county,
            case_number="2026CP000001",
            plaintiff="SC Plaintiff LLC",
            defendant="John Doe Defendant",
        )]

    monkeypatch.setattr(scpi, "_scrape_county", fake_scrape)
    monkeypatch.setattr(ec.asyncio, "sleep", _fake_no_sleep)

    targets = [_sc(1)]
    asyncio.run(ec.enrich_with_court_records(targets))

    assert calls["scrape"] >= 1
    assert targets[0].plaintiff == "SC Plaintiff LLC"
    assert targets[0].defendant == "John Doe Defendant"


def test_sc_path_never_clobbers_existing_fields(monkeypatch):
    """A listing that already carries plaintiff/defendant (from its own
    compliant scraper) must be untouched by the SC backfill."""
    from foreclosure_scraper.scrapers.counties_sc import sc_public_index as scpi
    from foreclosure_scraper.models import Listing as L

    async def fake_scrape(county):
        return [L(
            source="counties_sc.sc_public_index",
            source_url="u",
            listing_type=ListingType.FORECLOSURE_SALE,
            state="SC",
            county=county,
            case_number="2026CP000001",
            plaintiff="Should Not Overwrite",
            defendant="Should Not Overwrite Either",
        )]

    monkeypatch.setattr(scpi, "_scrape_county", fake_scrape)
    monkeypatch.setattr(ec.asyncio, "sleep", _fake_no_sleep)

    li = _sc(1)
    li.plaintiff = "Original Plaintiff"
    li.defendant = "Original Defendant"
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.plaintiff == "Original Plaintiff"
    assert li.defendant == "Original Defendant"


def test_discover_lis_pendens_sc_branch_fetches_sccourts(monkeypatch):
    """RE-ENABLED 2026-10-02: SC lis-pendens discovery hits
    publicindex.sccourts.org/PublicIndex/CaseSearchResults.aspx for SC counties.
    NC counties go through the normal (compliant) WorkspaceMode search."""
    from foreclosure_scraper.config import ALL_COUNTIES

    calls = []

    async def fake_render(url, token=None):
        calls.append(url)
        return ""  # no case numbers; we only care which URLs were hit

    monkeypatch.setattr(ec, "fetch_rendered", fake_render)
    asyncio.run(ec.discover_lis_pendens())

    sc_counties = [c for c in ALL_COUNTIES if c.state == "SC"]
    nc_counties = [c for c in ALL_COUNTIES if c.state == "NC"]
    sc_calls = [u for u in calls if "sccourts.org" in u]
    nc_calls = [u for u in calls if "tylertech" in u]
    if sc_counties:
        assert len(sc_calls) == len(sc_counties)
    if nc_counties:
        assert len(nc_calls) == len(nc_counties)


# ---- NC batch-search path ------------------------------------------------------

def test_nc_batch_match_fills_empty_fields(monkeypatch):
    hit = {"caseNumber": "26 SP000359-440",
           "debtors": [{"name": "John Doe"}], "creditors": [{"name": "Acme Bank"}],
           "causeOfActionDesc": "Foreclosure", "location": "Gaston District Court"}

    async def fake_index():
        return {ec._norm_case("26 SP000359-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    monkeypatch.setattr(ec, "fetch_rendered", lambda *a, **k: "")
    li = _nc("26SP000359-440", raw={})
    asyncio.run(ec.enrich_with_court_records([li]))
    assert li.defendant == "John Doe" and li.plaintiff == "Acme Bank"
    assert li.raw["court_record"]["source"] == "nc_ecourts_search"


def test_nc_batch_does_not_overwrite_existing(monkeypatch):
    hit = {"caseNumber": "26 SP1-440", "debtors": [{"name": "New Debtor"}], "creditors": []}

    async def fake_index():
        return {ec._norm_case("26 SP1-440"): hit}

    monkeypatch.setattr(ec, "_build_nc_case_index", fake_index)
    monkeypatch.setattr(ec, "fetch_rendered", lambda *a, **k: "")
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

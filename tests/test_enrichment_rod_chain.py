"""enrichment_rod_chain.py offline: the switches (off by default), stamping raw['rod_chain'] through
a real adapter on canned pages (made-up names), skipping counties outside the registry, and a
walled county ending that county's pass with its leads left unstamped."""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.enrichment_rod_chain import chain_registry, enrich_rod_chain
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod import nc_cott_v4 as cott
from foreclosure_scraper.rod import nc_polite
from tests._nc_rod_fakes import CLOUDFLARE_403, FakeResp, install
from tests.test_nc_rod_cott_v4 import FORM, OWNER_GRID, SAMPLE_GRID, _post_router


def _lead(county, owner, state="NC"):
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state=state,
                   county=county, owner_name=owner, raw={})


@pytest.fixture(autouse=True)
def _clean():
    yield
    cott.ADAPTER.drop_sessions()
    nc_polite.reset_state()


def test_registry_includes_chain_only_counties():
    reg = chain_registry()
    assert reg[("NC", "Nash")][0] == "nc_cott_v4"
    assert reg[("NC", "Buncombe")][0] == "nc_cott_v4" and reg[("NC", "Polk")][0] == "nc_cott_v4"
    assert ("SC", "Oconee") not in reg                    # kofile has no chain()


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_ROD_CHAIN", raising=False)
    assert "skipped" in asyncio.run(enrich_rod_chain([_lead("Nash", "TESTER ALVIN Q")]))


def test_platform_flag_off_skips_the_county(monkeypatch):
    sess = install(monkeypatch, [], cott.ADAPTER)
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN", "1")
    monkeypatch.delenv(cott.ENV_FLAG, raising=False)
    li = _lead("Nash", "TESTER ALVIN Q")
    stats = asyncio.run(enrich_rod_chain([li]))
    assert stats["disabled_counties"] == 1 and "rod_chain" not in li.raw and sess.calls == []


def test_stamps_the_chain(monkeypatch):
    install(monkeypatch, [("GET", "SrchName.aspx", FakeResp(FORM)),
                          ("POST", "SrchName.aspx", _post_router({"TESTER": OWNER_GRID, "SAMPLE": SAMPLE_GRID}))],
            cott.ADAPTER)
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN", "1")
    monkeypatch.setenv(cott.ENV_FLAG, "1")
    li, other = _lead("Nash", "TESTER ALVIN Q"), _lead("Wake", "TESTER ALVIN Q")
    stats = asyncio.run(enrich_rod_chain([li, other]))
    rc = li.raw["rod_chain"]
    assert rc["status"] == "ok" and rc["last_deed"]["book"] == "500"
    assert [p["book"] for p in rc["prior_instruments"]] == ["350"]
    assert stats["stamped"] == 1 and stats["with_last_deed"] == 1 and stats["with_open_dot_est"] == 1
    assert "rod_chain" not in other.raw
    # a fresh stamp is not re-read on the next pass
    again = asyncio.run(enrich_rod_chain([li]))
    assert again["targets"] == 0


def test_walled_county_stops_and_leaves_leads_unstamped(monkeypatch):
    sess = install(monkeypatch, [("GET", "SrchName.aspx", CLOUDFLARE_403)], cott.ADAPTER)
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN", "1")
    monkeypatch.setenv(cott.ENV_FLAG, "1")
    leads = [_lead("Nash", "TESTER ALVIN Q"), _lead("Nash", "SAMPLE CORA B")]
    stats = asyncio.run(enrich_rod_chain(leads))
    assert stats["walled_counties"] == ["Nash"] and stats["stamped"] == 0
    assert all("rod_chain" not in li.raw for li in leads)
    assert len(sess.calls) == 1

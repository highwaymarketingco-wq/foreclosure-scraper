"""Run shape of the register-of-deeds passes (audit 2026-10-09, additions_verify).

The 10/8 gated run read the generic register counties one after another inside a 900 s cap (5 of
about 60 enabled counties started, and the cap cancelled the phase before its counts were kept),
and the deed chain read its counties in alphabetical order inside 1,800 s (the same six counties
every run). These tests pin the new shape on fake adapters (made-up names, no network):
counties run side by side, the counties holding imminent leads go first, the budget returns the
counts, the generic pass leaves the deed chain its share of the shared per-county lookup cap, and a
cancelled pass logs its counts."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from foreclosure_scraper import enrichment_generic_rod as G
from foreclosure_scraper import enrichment_rod_chain as C
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.rod.models import RodDoc


def _lead(county: str, owner: str, *, hot: bool = False, state: str = "NC") -> Listing:
    raw = {"distress_stack": {"tier": "HOT"}} if hot else {}
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state=state,
                   county=county, owner_name=owner, raw=raw)


def _fake_search(delay: float, log: list):
    async def search_by_name(state, county, name, max_docs=80):
        log.append((county, name, time.monotonic()))
        await asyncio.sleep(delay)
        return [RodDoc(county=county, state=state, doc_type="DEED",
                       recorded_date=datetime(2020, 1, 2), book="1", page="2",
                       grantor="SELLER SAMPLE", grantee=name)]
    return SimpleNamespace(search_by_name=search_by_name)


@pytest.fixture
def two_counties(monkeypatch):
    calls: list = []
    cfg = {("NC", "Alphaville"): ("fake_a", "FAKE_A_ROD", "1"),
           ("NC", "Zetaburg"): ("fake_z", "FAKE_Z_ROD", "1")}
    monkeypatch.setattr(G, "ROD_CONFIG", cfg)
    mods = {"fake_a": _fake_search(0.2, calls), "fake_z": _fake_search(0.2, calls)}
    monkeypatch.setattr(G, "_get_module", lambda name: mods[name])
    monkeypatch.delenv("FORECLOSURE_ROD_CHAIN", raising=False)
    monkeypatch.setattr(G.asyncio, "sleep", _no_pause_sleep(asyncio.sleep))
    return calls


def _no_pause_sleep(real):
    async def sleep(s):
        # the 0.3 s politeness pause after a stamp is not what these tests measure
        await real(0 if s == 0.3 else s)
    return sleep


def test_counties_run_side_by_side(two_counties):
    leads = [_lead("Alphaville", "TESTER ALVIN"), _lead("Zetaburg", "SAMPLE CORA")]
    t = time.monotonic()
    stats = asyncio.run(G.enrich_generic_rod(leads))
    took = time.monotonic() - t
    assert stats["counties"] == 2 and stats["searched"] == 2 and stats["with_instruments"] == 2
    assert took < 0.38, f"counties ran one after another ({took:.2f} s)"
    assert all(li.raw["rod"]["source"] == "generic_rod" for li in leads)


def test_imminent_county_first_and_imminent_lead_first(two_counties, monkeypatch):
    monkeypatch.setenv("GENERIC_ROD_COUNTY_CONCURRENCY", "1")
    monkeypatch.setenv("GENERIC_ROD_CONCURRENCY", "1")
    monkeypatch.setattr(G, "_CONCURRENCY", 1)
    leads = [_lead("Alphaville", "TESTER ALVIN"), _lead("Alphaville", "TESTER BOB"),
             _lead("Zetaburg", "SAMPLE CORA"), _lead("Zetaburg", "SAMPLE DAN", hot=True)]
    asyncio.run(G.enrich_generic_rod(leads))
    order = [(c, n) for c, n, _ in two_counties]
    assert order[0] == ("Zetaburg", "SAMPLE DAN")          # the HOT lead's county, the HOT lead first
    assert [c for c, _ in order] == ["Zetaburg", "Zetaburg", "Alphaville", "Alphaville"]


def test_budget_returns_counts_and_starts_nothing_after(two_counties, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_GENERIC_ROD_BUDGET_S", "-1")
    stats = asyncio.run(G.enrich_generic_rod([_lead("Alphaville", "TESTER ALVIN")]))
    assert stats["budget_exhausted"] is True and stats["searched"] == 0 and two_counties == []


def test_chain_county_keeps_its_share_of_the_lookup_cap(two_counties, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN", "1")
    monkeypatch.setenv("GENERIC_ROD_MAX_PER_CHAIN_COUNTY", "2")
    monkeypatch.setattr(C, "chain_registry", lambda: {("NC", "Alphaville"): ("fake_a", "FAKE_A_ROD", "1")})
    leads = [_lead("Alphaville", f"TESTER N{i}") for i in range(5)] + \
            [_lead("Zetaburg", f"SAMPLE N{i}") for i in range(5)]
    stats = asyncio.run(G.enrich_generic_rod(leads))
    by_county = {}
    for c, _, _ in two_counties:
        by_county[c] = by_county.get(c, 0) + 1
    assert by_county == {"Alphaville": 2, "Zetaburg": 5}
    assert stats["chain_share_capped"] == 1


def test_cancelled_pass_logs_its_counts(two_counties, monkeypatch):
    seen = {}
    monkeypatch.setattr(G.log, "warning", lambda ev, **kw: seen.setdefault(ev, kw))

    async def run():
        task = asyncio.ensure_future(G.enrich_generic_rod(
            [_lead("Alphaville", "TESTER ALVIN"), _lead("Zetaburg", "SAMPLE CORA")]))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert "generic_rod.cancelled" in seen and seen["generic_rod.cancelled"]["counties"] == 2


# ------------------------------------------------------------------------------- deed chain
class _FakeChainMod:
    def __init__(self, delay: float, log: list):
        self.delay, self.log = delay, log

    def chain(self, county, owner, *, state="NC", depth=3):
        self.log.append((county, owner, time.monotonic()))
        time.sleep(self.delay)
        return {"status": "ok", "state": state, "county": county, "owner_searched": owner,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "last_deed": {"book": "1", "page": "2"}, "prior_instruments": [], "liens": {}}


@pytest.fixture
def chain_counties(monkeypatch):
    calls: list = []
    reg = {("NC", "Alphaville"): ("fake_a", "FAKE_A_ROD", "1"),
           ("NC", "Betaville"): ("fake_b", "FAKE_B_ROD", "1"),
           ("NC", "Zetaburg"): ("fake_z", "FAKE_Z_ROD", "1")}
    mods = {k: _FakeChainMod(0.2, calls) for k in ("fake_a", "fake_b", "fake_z")}
    monkeypatch.setattr(C, "chain_registry", lambda: reg)
    monkeypatch.setattr(C, "_module", lambda name: mods[name])
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN", "1")
    return calls


def test_chain_counties_run_side_by_side(chain_counties):
    leads = [_lead("Alphaville", "TESTER ALVIN"), _lead("Betaville", "SAMPLE CORA"),
             _lead("Zetaburg", "EXAMPLE DORA")]
    t = time.monotonic()
    stats = asyncio.run(C.enrich_rod_chain(leads))
    assert time.monotonic() - t < 0.5
    assert stats["counties"] == 3 and stats["stamped"] == 3


def test_chain_order_is_by_imminent_leads_not_alphabetical(chain_counties, monkeypatch):
    monkeypatch.setenv("ROD_CHAIN_COUNTY_CONCURRENCY", "1")
    soon = (datetime.now(timezone.utc) + timedelta(days=5)).date().isoformat()
    z = _lead("Zetaburg", "EXAMPLE DORA")
    z.sale_date = soon
    leads = [_lead("Alphaville", "TESTER ALVIN"), _lead("Betaville", "SAMPLE CORA"),
             _lead("Betaville", "SAMPLE EVA"), z]
    asyncio.run(C.enrich_rod_chain(leads))
    assert [c for c, _, _ in chain_counties] == ["Zetaburg", "Betaville", "Betaville", "Alphaville"]


def test_chain_budget_counts_only_counties_started(chain_counties, monkeypatch):
    monkeypatch.setenv("FORECLOSURE_ROD_CHAIN_BUDGET_S", "-1")
    stats = asyncio.run(C.enrich_rod_chain([_lead("Alphaville", "TESTER ALVIN"),
                                            _lead("Zetaburg", "EXAMPLE DORA")]))
    assert stats["budget_exhausted"] and stats["counties"] == 0 and stats["targets"] == 0


# ------------------------------------------------------------------------------- chain binding
def _chain(recorded, **extra):
    return {"status": "ok", "last_deed": {"recorded": recorded, "book": "1", "page": "2"}, **extra}


def _row_sold(date_str):
    li = _lead("Alphaville", "TESTER ALVIN")
    li.raw = {"gis": {"last_sale": {"date": date_str}}}
    return li


NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


def test_binding_confirms_a_deed_on_the_parcel_sale_date():
    assert C.bind_chain(_row_sold("2020-06-19"), _chain("2020-06-19"), NOW)["status"] == "sale_date"
    assert C.bind_chain(_row_sold("20040101"), _chain("2004-05-18"), NOW)["status"] == "sale_date"


def test_binding_refuses_another_parcels_newer_deed_and_a_parcel_sold_since():
    other = C.bind_chain(_row_sold("2004-01-01"), _chain("2020-04-29"), NOW)
    assert other["status"] == "contradicted" and other["reason"] == "deed_newer_than_parcel_sale"
    sold = C.bind_chain(_row_sold("2024-03-01"), _chain("2015-02-02"), NOW)
    assert sold["status"] == "contradicted" and sold["reason"] == "parcel_sold_after_chain_deed"
    # a deed newer than the parcel record (the county roll lags) is not judged
    assert C.bind_chain(_row_sold("2016-07-06"), _chain("2026-08-12"), NOW)["status"] == "name_only"


def test_binding_without_a_parcel_sale_or_with_an_outgoing_deed_is_name_only():
    li = _lead("Alphaville", "TESTER ALVIN")
    assert C.bind_chain(li, _chain("2018-03-01"), NOW)["status"] == "name_only"
    b = C.bind_chain(_row_sold("2012-08-01"), _chain("2012-08-01",
                     conveyed_out_since=[{"recorded": "2026-08-11"}]), NOW)
    assert b["status"] == "name_only" and b["reason"] == "owner_conveyed_since_last_deed"


def test_a_contradicted_chain_is_stamped_unbound(chain_counties, monkeypatch):
    li = _row_sold("2004-01-01")
    li.county = "Alphaville"
    li.raw["gis"]["last_sale"]["date"] = "1989-01-01"
    stats = asyncio.run(C.enrich_rod_chain([li]))
    # the fake chain's last deed is today's date: newer than 180 days is not judged
    assert li.raw["rod_chain"]["binding"]["status"] in ("name_only", "contradicted")
    assert stats["stamped"] == 1 and stats["unbound"] + stats["name_only"] + stats["bound_sale_date"] == 1

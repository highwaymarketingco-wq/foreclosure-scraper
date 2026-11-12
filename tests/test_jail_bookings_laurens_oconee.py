"""Laurens SC (J-03) and Oconee SC (J-04) Zuercher rosters.

Both counties ride the Zuercher adapter that Cherokee and Anderson already use,
so each is one ROSTERS entry in BOTH lists (the enricher's and the standalone
scraper's). Live, 2026-09-20 (counts only): laurens-911-sc 181 in custody with
DOB blank on the tenant, oconee-so-sc 183 in custody with DOB on every row. The
sheriff's own inmate-search page links to the Oconee tenant.

Fixtures use obvious placeholder names; nothing here touches a live server.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper import enrichment_jail_bookings as ej
from foreclosure_scraper.models import Listing
from foreclosure_scraper.scrapers.national import jail_bookings as scraper


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _ZuercherSession:
    def __init__(self, records):
        self.records = records
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        return _Resp({"records": self.records})


def _patch(monkeypatch, records):
    fake = _ZuercherSession(records)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    return fake


def _rec(name, dob=None):
    return {"name": name, "dob": dob, "arrest_date": "2026-09-01T00:00:00.000Z",
            "hold_reasons": ["PLACEHOLDER CHARGE"]}


def _lead(county, owner, state="SC"):
    return Listing(source="test", source_url="http://x", state=state, county=county,
                   raw={"owner_mailing": {"owner": owner}})


@pytest.mark.parametrize("county,sub", [("Laurens", "laurens-911-sc"), ("Oconee", "oconee-so-sc")])
def test_roster_is_registered_in_both_lists(county, sub):
    entry = ("SC", county, "zuercher", sub)
    assert entry in ej.ROSTERS
    assert entry in scraper.ROSTERS


def test_the_pre_existing_sc_zuercher_rosters_are_still_there():
    for sub in ("cherokee-so-sc", "anderson-so-sc"):
        assert any(v == "zuercher" and t == sub for _s, _c, v, t in ej.ROSTERS)


@pytest.mark.parametrize("county,sub", [("Laurens", "laurens-911-sc"), ("Oconee", "oconee-so-sc")])
def test_listing_source_url_points_at_the_tenant(county, sub):
    li = scraper._to_listing({"last": "TESTCASE", "first": "ALPHA", "arrest_date": "2026-09-01"},
                             "SC", county)
    assert li.source_url == f"https://{sub}.zuercherportal.com/"
    assert li.county == county and li.state == "SC"


@pytest.mark.asyncio
async def test_laurens_match_sets_both_signals_and_uses_the_existing_body(monkeypatch):
    fake = _patch(monkeypatch, [_rec("Testcase, Alpha Beta"), _rec("Placeholder, Gamma")])
    li = _lead("Laurens County", "TESTCASE ALPHA")
    res = await ej.enrich_jail_bookings([li])

    assert res["matched"] == 1
    url, body = fake.posts[0]
    assert url == "https://laurens-911-sc.zuercherportal.com/api/portal/inmates/load"
    assert body["paging"] == {"count": 2000, "start": 0} and body["name"] == ""
    jbk = li.raw["jail_booking"]
    assert jbk["county"] == "Laurens" and jbk["state"] == "SC"
    assert jbk["matched_name"] == "ALPHA TESTCASE"
    assert jbk["roster_dob"] is None                  # blank on this tenant, not an error
    assert jbk["confidence"] == "name_only_low"
    assert li.raw["incarceration"]["source"] == "Laurens County jail roster"


@pytest.mark.asyncio
async def test_oconee_match_carries_the_dob(monkeypatch):
    fake = _patch(monkeypatch, [_rec("Testcase, Alpha Beta", dob="01/02/1980")])
    li = _lead("Oconee", "TESTCASE ALPHA")
    res = await ej.enrich_jail_bookings([li])

    assert res["matched"] == 1
    assert fake.posts[0][0] == "https://oconee-so-sc.zuercherportal.com/api/portal/inmates/load"
    assert li.raw["jail_booking"]["roster_dob"] == "01/02/1980"
    assert li.raw["incarceration"]["source"] == "Oconee County jail roster"


@pytest.mark.asyncio
async def test_a_different_name_and_a_company_owner_do_not_match(monkeypatch):
    _patch(monkeypatch, [_rec("Testcase, Alpha Beta")])
    other = _lead("Laurens County", "SOMEBODY ELSE")
    company = _lead("Laurens County", "TESTCASE ALPHA HOLDINGS LLC")
    res = await ej.enrich_jail_bookings([other, company])
    assert res["matched"] == 0
    assert "jail_booking" not in other.raw and "jail_booking" not in company.raw


@pytest.mark.asyncio
async def test_only_the_counties_on_the_board_are_fetched(monkeypatch):
    fake = _patch(monkeypatch, [_rec("Testcase, Alpha Beta")])
    await ej.enrich_jail_bookings([_lead("Oconee County", "SOMEBODY ELSE")])
    assert len(fake.posts) == 1 and "oconee-so-sc" in fake.posts[0][0]

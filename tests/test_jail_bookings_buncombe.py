"""Buncombe NC CentralSquare P2C jail-booking enricher — handshake + parse + match.

Buncombe's modern P2C roster (policetocitizen.com) needs an XSRF-TOKEN cookie
handshake: GET an app route, echo the cookie as X-XSRF-TOKEN on the JSON search
POST. The endpoint caps Take at ~200 and never fills TotalCount, so we page in
blocks of 200 until a short page. DOB is redacted on the public feed; Age +
ArrestDate (booking date) survive. All mocked so it never hits the live server.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_jail_bookings import (
    _fetch_p2c_centralsquare,
    enrich_jail_bookings,
)
from foreclosure_scraper.models import Listing


class _FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _FakeCookies(dict):
    def get(self, k, default=None):  # mirror curl_cffi Cookies.get
        return dict.get(self, k, default)


class _FakeSession:
    """Stand-in for curl_cffi AsyncSession. Serves a token on the app-route GET
    and pages Inmates on POST, honoring Skip/Take so paging logic is exercised."""

    def __init__(self, inmates, token="CfDJ8-fake-token", page_size=200):
        self._inmates = inmates
        self._page_size = page_size
        self.cookies = _FakeCookies()
        self._token = token
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None):
        # Handshake sets the XSRF-TOKEN cookie, like the real SPA route.
        if self._token is not None:
            self.cookies["XSRF-TOKEN"] = self._token
        return _FakeResp({})

    async def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers, json))
        paging = (json or {}).get("PagingOptions", {})
        skip = paging.get("Skip", 0)
        take = paging.get("Take", self._page_size)
        page = self._inmates[skip:skip + min(take, self._page_size)]
        return _FakeResp({"Inmates": page, "TotalCount": None})


def _mk_inmate(last, first, age="40", arrest="7/1/2026 12:00:00 AM",
               charge="REMAND TO CUSTODY OF SHERIFF"):
    return {"FirstName": first, "LastName": last, "MiddleName": "M",
            "DateOfBirth": None, "Age": age, "ArrestDate": arrest,
            "PrimaryChargeDescription": charge,
            "BookingAgency": "BUNCOMBE COUNTY SHERIFF DEPT"}


@pytest.mark.asyncio
async def test_handshake_and_parse(monkeypatch):
    roster = [_mk_inmate("BANKS", "ERNEST", age="51")]
    fake = _FakeSession(roster)
    # curl_cffi is imported inside the fn; patch the module it pulls from.
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)

    recs = await _fetch_p2c_centralsquare("https://buncombecountyso.policetocitizen.com|23")
    assert len(recs) == 1
    r = recs[0]
    assert r["last"] == "BANKS" and r["first"] == "ERNEST"
    assert r["age"] == "51"
    assert r["arrest_date"] == "7/1/2026 12:00:00 AM"
    assert r["dob"] is None  # redacted on the public feed
    # The search POST must carry the echoed anti-forgery header.
    _, headers, _ = fake.posts[0]
    assert headers["X-XSRF-TOKEN"] == "CfDJ8-fake-token"


@pytest.mark.asyncio
async def test_no_token_bails(monkeypatch):
    fake = _FakeSession([_mk_inmate("X", "Y")], token=None)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    recs = await _fetch_p2c_centralsquare("https://host|23")
    assert recs == []  # no XSRF cookie -> no scrape
    assert fake.posts == []  # never posted without a token


@pytest.mark.asyncio
async def test_pages_past_first_block(monkeypatch):
    # 250 inmates with a 200 page-size forces a second page + short-page stop.
    roster = [_mk_inmate(f"LAST{i:03d}", f"FIRST{i:03d}") for i in range(250)]
    fake = _FakeSession(roster, page_size=200)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    recs = await _fetch_p2c_centralsquare("https://host|23")
    assert len(recs) == 250
    assert len(fake.posts) == 2  # two pages, then short page ends the loop


@pytest.mark.asyncio
async def test_end_to_end_match_sets_signals(monkeypatch):
    roster = [_mk_inmate("HARRIS", "MICHAEL", age="47")]
    fake = _FakeSession(roster)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)

    li = Listing(source="test", source_url="http://x", state="NC",
                 county="Buncombe County",
                 raw={"owner_mailing": {"owner": "HARRIS MICHAEL"}})
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 1
    jbk = li.raw["jail_booking"]
    assert jbk["county"] == "Buncombe" and jbk["state"] == "NC"
    assert jbk["matched_name"] == "MICHAEL HARRIS"
    assert jbk["roster_age"] == "47"
    assert jbk["confidence"] == "name_only_low"
    # Reuses the existing LEGAL incarceration distress signal.
    assert li.raw["incarceration"]["source"] == "Buncombe County jail roster"


@pytest.mark.asyncio
async def test_no_match_leaves_listing_untouched(monkeypatch):
    roster = [_mk_inmate("SOMEONE", "ELSE")]
    fake = _FakeSession(roster)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    li = Listing(source="test", source_url="http://x", state="NC",
                 county="Buncombe",
                 raw={"owner_mailing": {"owner": "NOBODY HOME"}})
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 0
    assert "jail_booking" not in li.raw

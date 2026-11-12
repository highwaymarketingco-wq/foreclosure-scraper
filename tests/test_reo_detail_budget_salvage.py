"""REO sources whose per-listing detail pages pushed them past their soft timeout (2026-10-04
additions) must ship the rows they already parsed, and must stop the detail pages in time.

national.hud_homestore and national.freddie_homesteps timed out with 0 rows on every run since
2026-10-04 (60 s timeout, one detail request per listing); national.usda_properties on alternate
runs (120 s, up to 112 requests). None of them used BaseScraper.partial, so a cut-off discarded the
whole source. Offline; every address and number below is invented.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.national import freddie_homesteps as FH
from foreclosure_scraper.scrapers.national import hud_homestore as HH
from foreclosure_scraper.scrapers.national import usda_properties as UP


class _Resp:
    def __init__(self, text="", status=200, payload=None):
        self.text, self.status_code, self._payload = text, status, payload

    def json(self):
        return self._payload


def _hud_row(i, state):
    return {"propertyCaseNumber": f"387-00{i}", "propertyAddress": f"{i} Pretend St",
            "propertyCity": "Gastonia" if state == "NC" else "Greer", "propertyState": state,
            "propertyZip": "28052" if state == "NC" else "29651",
            "propertyCounty": "Gaston" if state == "NC" else "Greenville",
            "listPrice": 90000 + i}


def _hud_client(detail_delay):
    @asynccontextmanager
    async def fake_client(**kw):
        class _C:
            async def get(self, url, headers=None, follow_redirects=True):
                if "propertydetails" in url:
                    await asyncio.sleep(detail_delay)
                    return _Resp("<html></html>")
                return _Resp('<input id="request-verification-token" value="tok123">')

            async def post(self, url, headers=None, content=""):
                st = "NC" if "citystate=NC" in content else "SC"
                return _Resp(payload={"searchresult": [_hud_row(i, st) for i in range(1, 4)]})
        yield _C()
    return fake_client


def test_hud_ships_search_rows_when_broker_pages_run_past_the_timeout(monkeypatch):
    monkeypatch.setattr(HH, "client", _hud_client(detail_delay=5.0))
    s = HH.HudHomeStore()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome != "TIMEOUT" and len(rows) >= 3      # NC's search rows at least
    assert all(li.case_number for li in rows)


def test_hud_broker_pages_stop_at_the_deadline(monkeypatch):
    monkeypatch.setattr(HH, "client", _hud_client(detail_delay=0.0))
    sink: list = []
    calls = {"n": 0}
    orig = HH._extract_broker

    def counting(html):
        calls["n"] += 1
        return orig(html)

    monkeypatch.setattr(HH, "_extract_broker", counting)
    out = asyncio.run(HH._fetch_state("NC", sink=sink, deadline=0.0))   # already past
    assert len(out) == 3 and sink == out and calls["n"] == 0


_FH_CARD = """
<div class="property-teaser">
  <a href="/listingdetails/{i}"><div class="property-price">$150,000</div>
  <div class="property-details">3 beds, 2 baths, 1,200 sq. ft.</div>
  <div class="property-address">{i} Madeup Ln, Shelby, NC 28150</div></a>
</div>"""


def _fh_client(detail_delay):
    @asynccontextmanager
    async def fake_client(**kw):
        class _C:
            async def get(self, url, headers=None, follow_redirects=True):
                if "listingdetails" in url:
                    await asyncio.sleep(detail_delay)
                    return _Resp("<html>" + "x" * 2000 + "</html>")
                if "search=NC" in url:
                    return _Resp("<html>" + "".join(_FH_CARD.format(i=i) for i in range(1, 4))
                                 + "x" * 5000 + "</html>")
                return _Resp("<html>" + "x" * 5000 + "</html>")
        yield _C()
    return fake_client


def test_homesteps_ships_list_rows_when_detail_pages_run_past_the_timeout(monkeypatch):
    monkeypatch.setattr(FH, "client", _fh_client(detail_delay=5.0))
    s = FH.FreddieHomeSteps()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome != "TIMEOUT"
    assert len(rows) == 3 and {li.state for li in rows} == {"NC"}


def test_homesteps_detail_pages_stop_at_the_deadline(monkeypatch):
    monkeypatch.setattr(FH, "client", _fh_client(detail_delay=0.0))
    seen = {"n": 0}
    orig = FH._parse_detail_page

    def counting(html):
        seen["n"] += 1
        return orig(html)

    monkeypatch.setattr(FH, "_parse_detail_page", counting)
    sink: list = []
    out = asyncio.run(FH._fetch_state("NC", FH.URLS[0][1], sink=sink, deadline=0.0))
    assert len(out) == 3 and sink == out and seen["n"] == 0


def _usda_page(n):
    cards = "".join(
        f'<div class="card" data-price="100000" data-beds="2" data-baths="1.0" data-type="home" '
        f'data-elig="1" data-zip="29323"><a href="/property/sc/29323/{900 + i}/">'
        f'<div class="caddr">{i} Madeup St</div></a></div>' for i in range(n))
    return f'<div id="hgGrid">{cards}</div>' + "x" * 5000


def test_usda_ships_parsed_cards_when_a_detail_page_runs_past_the_timeout(monkeypatch):
    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if "/county/" in url:
            return _usda_page(2) if url.rstrip("/").endswith("spartanburg") else _usda_page(0)
        await asyncio.sleep(5.0)
        return ""

    monkeypatch.setattr(UP, "get_text", fake_get_text)
    s = UP.USDAProperties()
    s.timeout_s = 0.6
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome != "TIMEOUT"
    # the first card is recorded before its (hanging) detail page, so the cut-off ships it
    assert len(rows) == 1 and rows[0].street_address == "0 Madeup St"


def test_usda_detail_pages_stop_at_the_deadline(monkeypatch):
    calls = {"detail": 0}

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if "/county/" in url:
            return _usda_page(4)
        calls["detail"] += 1
        return ""

    monkeypatch.setattr(UP, "get_text", fake_get_text)
    rows = asyncio.run(UP._fetch_county("national.usda_properties", "anderson", deadline=0.0))
    assert len(rows) == 4 and calls["detail"] == 0


# ----------------------------------------------------------------------------- cash buyers, US Marshals

def test_cash_buyer_deeds_ships_finished_counties_on_a_timeout(monkeypatch):
    from foreclosure_scraper.models import Listing, ListingType
    from foreclosure_scraper.scrapers.national import cash_buyer_deeds as CB

    async def done(state, county, days):
        return ["deed-1", "deed-2"]

    async def hangs(state, county, days):
        await asyncio.sleep(5.0)
        return []

    monkeypatch.setattr(CB, "VENDOR_DISPATCH", (("Burke", "NC", done), ("Polk", "NC", hangs)))
    monkeypatch.setattr(CB, "_identify_cash_buyers", lambda docs: list(docs))
    monkeypatch.setattr(CB, "_deed_to_listing", lambda d, url: Listing(
        source=CB.CashBuyerDeeds.slug, source_url=url, listing_type=ListingType.UNKNOWN,
        state="NC", county="Burke", case_number=d))
    s = CB.CashBuyerDeeds()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome != "TIMEOUT"
    assert sorted(li.case_number for li in rows) == ["deed-1", "deed-2"]


def test_usmarshals_ships_parsed_details_on_a_timeout(monkeypatch):
    from foreclosure_scraper.models import Listing, ListingType
    from foreclosure_scraper.scrapers.national import usmarshals_realproperty as UM

    async def hits():
        return [("/properties/1-0", "1 Pretend Rd, Conway, SC 29526"),
                ("/properties/2-0", "2 Pretend Rd, Conway, SC 29526")]

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if url.endswith("/2-0"):
            await asyncio.sleep(5.0)
        return "<html></html>"

    monkeypatch.setattr(UM, "_list_ids_for_state", hits)
    monkeypatch.setattr(UM, "get_text", fake_get_text)
    monkeypatch.setattr(UM, "_parse_detail", lambda html, href, addr: Listing(
        source=UM.USMarshalsRealProperty.slug, source_url=href, listing_type=ListingType.REO,
        state="SC", street_address=addr.split(",")[0]))
    s = UM.USMarshalsRealProperty()
    s.timeout_s = 0.5
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome != "TIMEOUT"
    assert [li.street_address for li in rows] == ["1 Pretend Rd"]

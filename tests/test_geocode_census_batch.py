"""Census batch pre-pass.

Census was already tier 1 of the per-lead cascade, but called ONE address at a
time: 17,161 separate round-trips on the 2026-08-04 run, which burned the whole
600s budget and left 6,266 leads with no coordinates.

The same free service takes many addresses per request. Measured 2026-08-05
against real board addresses: 625/750 filled in 8 seconds using 3 requests.

Nominatim's usage policy forbids bulk geocoding on the shared instance, so this
is also the compliant shape: bulk goes to the service built for it, and the
1-req/sec tier only ever sees the tail.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import foreclosure_scraper.enrichment_geocode as G
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(street="1 A ST", city="ASHEVILLE", state="NC", zip_="28801"):
    return Listing(source="x", source_url="https://e.com/1",
                   listing_type=ListingType.UNKNOWN, property_kind=PropertyKind.UNKNOWN,
                   street_address=street, city=city, state=state, zip_code=zip_)


def _resp(status=200, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    return r


def test_batchable_needs_a_street_and_locality():
    assert G._batchable(_li())
    assert not G._batchable(_li(street=""))
    assert not G._batchable(_li(city="", zip_=""))
    assert not G._batchable(_li(state=""))
    assert G._batchable(_li(city="", zip_="28801"))     # zip alone is enough


def test_batch_fills_coordinates_and_maps_rows_by_id():
    """Row order is not guaranteed, so the id column is the join. Getting this
    wrong silently assigns one property's coordinates to another."""
    leads = [_li(street=f"{i} A ST") for i in range(3)]
    body = ("2,\"2 A ST\",Match,Exact,\"2 A ST\",\"-82.5,35.5\",1,L\n"
            "0,\"0 A ST\",Match,Exact,\"0 A ST\",\"-80.1,34.1\",1,L\n"
            "1,\"1 A ST\",No_Match\n")
    c = MagicMock()
    c.post = AsyncMock(return_value=_resp(200, body))
    filled = asyncio.run(G._census_batch(c, leads))
    assert filled == 2
    assert (leads[0].latitude, leads[0].longitude) == (34.1, -80.1)
    assert (leads[2].latitude, leads[2].longitude) == (35.5, -82.5)
    assert leads[1].latitude is None


def test_lonlat_order_is_not_flipped():
    """Census returns lon,lat. Swapping puts every NC property in Antarctica."""
    lead = _li()
    c = MagicMock()
    c.post = AsyncMock(return_value=_resp(200, '0,"x",Match,Exact,"x","-82.55,35.59",1,L\n'))
    asyncio.run(G._census_batch(c, [lead]))
    assert 33 < lead.latitude < 37, lead.latitude       # NC/SC latitude band
    assert -84 < lead.longitude < -78, lead.longitude


def test_502_is_retried_then_given_up_on(monkeypatch):
    """The service 502s non-deterministically — size is not the variable; n=250
    succeeded while n=100 and n=1000 failed on the same data."""
    monkeypatch.setattr(G, "CENSUS_BATCH_TRIES", 3)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    c = MagicMock()
    c.post = AsyncMock(return_value=_resp(502, ""))
    assert asyncio.run(G._census_batch(c, [_li()])) == 0
    assert c.post.await_count == 3


def test_a_transient_502_still_resolves_on_retry(monkeypatch):
    monkeypatch.setattr(G, "CENSUS_BATCH_TRIES", 3)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    lead = _li()
    c = MagicMock()
    c.post = AsyncMock(side_effect=[
        _resp(502, ""),
        _resp(200, '0,"x",Match,Exact,"x","-81.0,35.0",1,L\n'),
    ])
    assert asyncio.run(G._census_batch(c, [lead])) == 1
    assert lead.latitude == 35.0


def test_existing_coordinates_are_never_overwritten():
    lead = _li()
    lead.latitude, lead.longitude = 35.0, -82.0
    c = MagicMock()
    c.post = AsyncMock(return_value=_resp(200, '0,"x",Match,Exact,"x","-99.9,10.1",1,L\n'))
    asyncio.run(G._census_batch(c, [lead]))
    assert (lead.latitude, lead.longitude) == (35.0, -82.0)


def test_no_batchable_rows_makes_no_request():
    c = MagicMock()
    c.post = AsyncMock()
    assert asyncio.run(G._census_batch(c, [_li(street="")])) == 0
    c.post.assert_not_awaited()


def test_garbage_rows_do_not_take_the_batch_down():
    leads = [_li()]
    c = MagicMock()
    c.post = AsyncMock(return_value=_resp(200,
        'notanint,"x",Match,Exact,"x","-81.0,35.0",1,L\n'
        '99,"x",Match,Exact,"x","-81.0,35.0",1,L\n'      # index out of range
        '0,"x",Match,Exact,"x","not,coords",1,L\n'))
    assert asyncio.run(G._census_batch(c, leads)) == 0
    assert leads[0].latitude is None

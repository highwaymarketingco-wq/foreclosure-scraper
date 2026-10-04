"""Buncombe County NC tax foreclosures via the public Trumba JSON calendar.

EXTRACTION-COMPLETENESS AUDIT 2026-10-03: `location`'s own Google Maps <a>
href carries the county's own precise lat/lng for the parcel (live-confirmed
43 of 66 current events) -- the code already stripped that same link down to
plain text to regex out a street address, but threw the coordinates in the
href away. The event shape below mirrors the real Trumba JSON (captured live
2026-10-03); names/ids changed.

Found WHILE verifying that fix against the real feed: ADDR_RE's street-suffix
alternation had no word boundaries, so a suffix abbreviation embedded inside a
longer word (no preceding space needed) could match -- two REAL live rows were
corrupted ("368 N FORK RD BARNARDSVILLE" -> "...RD BARNARD" via the "RD" inside
"BARNARDsville"; "539 Deaverview" -> "539 Deave" via the "AVE" inside
"De-AVE-rview"). Fixed in the same pass (same field, same function).
"""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper.scrapers.counties_nc import buncombe_tax as m

GEO_EVENT = {
    "eventID": 1, "title": "LARRY A WOOTEN",
    "description": "** PROPERTY HAS BEEN REDEEMED **",
    "location": ('<a href="http://maps.google.com/?q=35.785141,-82.432815(LARRY+A+WOOTEN)" '
                 'target="_blank" rel="noopener">368 N FORK RD BARNARDSVILLE</a>'),
    "startDateTime": "2024-01-24T11:15:00",
    "customFields": [
        {"label": "Opening/Current Bid", "value": "$6,909.03"},
        {"label": "Redeemed", "value": "No"},
        {"label": "Case Number", "value": "23 CVD 03805"},
        {"label": "PIN lookup", "value": '<a href="...PINN=978528122800000">gis…</a>'},
        {"label": "Property Type", "value": "Land &amp; Structures"},
        {"label": "Fire District", "value": "BARNARDSVILLE"},
    ],
    "permaLinkUrl": "https://taxforeclosures.buncombenc.gov/x1",
}

NO_GEO_EVENT = {
    "eventID": 2, "title": "GRIFFIN DUNN PROPERTIES",
    "description": "0.09 ACRES, MORE OR LESS",
    "location": "",  # no Google Maps link at all on this one (live-observed, 23/66)
    "startDateTime": "2022-01-18T11:00:00",
    "customFields": [
        {"label": "Opening/Current Bid", "value": "5,587.16"},
        {"label": "Redeemed", "value": "No"},
        {"label": "Case Number", "value": "21 CVD 03272"},
    ],
    "permaLinkUrl": "https://taxforeclosures.buncombenc.gov/x2",
}

REDEEMED_EVENT = {
    "eventID": 3, "title": "SOMEONE ELSE",
    "location": '<a href="http://maps.google.com/?q=35.1,-82.2(X)">1 X ST</a>',
    "startDateTime": "2023-05-01T11:00:00",
    "customFields": [{"label": "Redeemed", "value": "Yes"}],
}


class _FakeResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class _FakeHttp:
    def __init__(self, text: str, status_code: int = 200):
        self._resp = _FakeResp(text, status_code)
        self.calls: list = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._resp


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(events: list[dict]) -> list:
    http = _FakeHttp(json.dumps(events))  # top-level JSON array, matching the real feed
    s = m.BuncombeTax()
    original = m.client
    m.client = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(s.fetch())
    finally:
        m.client = original


def test_geo_re_extracts_the_countys_own_lat_lng_from_the_maps_link():
    loc = GEO_EVENT["location"]
    m_ = m.GEO_RE.search(loc)
    assert m_ is not None
    assert (float(m_.group(1)), float(m_.group(2))) == (35.785141, -82.432815)


def test_fetch_sets_latitude_longitude_from_the_google_maps_link():
    rows = _run_fetch([GEO_EVENT])
    assert len(rows) == 1
    li = rows[0]
    assert li.latitude == 35.785141 and li.longitude == -82.432815
    # The trailing "BARNARDSVILLE" is a locality name, not part of the street --
    # ADDR_RE correctly stops at the real "RD" token, not a fake one embedded
    # inside "BARNARDsville" (see the word-boundary fix below).
    assert li.street_address == "368 N FORK RD"


def test_addr_re_does_not_match_a_suffix_abbreviation_embedded_in_a_longer_word():
    """Regression for the real truncation bug this audit found: a street-suffix
    abbreviation (Rd/Ave/...) must only match as its own token, never as a
    substring sitting inside a longer, unrelated word."""
    barnardsville = m.ADDR_RE.search("368 N FORK RD BARNARDSVILLE")
    assert barnardsville is not None and barnardsville.group(1) == "368 N FORK RD"
    # "539 Deaverview" has NO real street-type suffix at all (live-confirmed
    # shape) -- correctly matching nothing beats confidently returning "539
    # Deave" (the "AVE" hiding inside "DeAVErview").
    assert m.ADDR_RE.search("539 Deaverview") is None


def test_fetch_does_not_fabricate_a_truncated_address_but_still_keeps_the_geo_point():
    """BRYAN TALLANT's real live location text is '539 Deaverview' (no usable
    street suffix) with a Google Maps point alongside it -- the lead must ship
    with street_address=None (not a mangled "539 Deave") while still carrying
    the real lat/lng, so the row isn't silently lost for want of a bad regex."""
    deaverview_event = dict(GEO_EVENT, eventID=9, title="BRYAN TALLANT",
                            location='<a href="http://maps.google.com/?q=35.583034,-82.633908'
                                     '(BRYAN+TALLANT)" target="_blank">539 Deaverview</a>')
    rows = _run_fetch([deaverview_event])
    assert len(rows) == 1
    assert rows[0].street_address is None
    assert rows[0].latitude == 35.583034 and rows[0].longitude == -82.633908


def test_fetch_leaves_lat_lng_none_when_location_has_no_maps_link():
    rows = _run_fetch([NO_GEO_EVENT])
    assert len(rows) == 1
    assert rows[0].latitude is None and rows[0].longitude is None


def test_redeemed_rows_are_still_dropped_regardless_of_geo():
    rows = _run_fetch([GEO_EVENT, NO_GEO_EVENT, REDEEMED_EVENT])
    assert len(rows) == 2
    assert all(l.defendant != "SOMEONE ELSE" for l in rows)


def test_registered_in_the_scraper_registry():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    assert m.BuncombeTax.slug in slugs

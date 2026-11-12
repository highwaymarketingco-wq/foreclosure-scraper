"""court_wall: walled court/notice claims are labelled with their manual-lane card, never fetched."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import court_walls as W


def _row(**kw):
    r = {"state": "SC", "county": "Anderson", "source": "counties_sc.sc_public_index",
         "listing_type": "lis_pendens", "raw": {}}
    r.update(kw)
    return r


def test_registered_as_a_wall_that_governs_nothing():
    v = {x.name: x for x in registry.discover()}["court_walls"]
    assert v.wall and v.signal == "court_wall" and v.governs == ()


def test_cards():
    assert W.card_of(_row()) == "sc_publicindex"
    assert W.card_of(_row(county="Charleston")) is None         # open copy: not a wall
    assert W.card_of(_row(source="counties_sc.sc_public_notices", listing_type="foreclosure_sale")) == "sc_notice_body"
    assert W.card_of(_row(state="NC", source="public_notices.nc_notices_counties",
                          listing_type="foreclosure_sale")) == "nc_sp"
    assert W.card_of(_row(state="NC", source="counties.column_legal_notices",
                          listing_type="probate_notice")) == "nc_est"
    assert W.card_of(_row(state="NC", source="law_firms.hutchens", listing_type="foreclosure_sale")) is None


def test_never_fetches():
    f = ReplayFetcher({})
    r = asyncio.run(W.verify(_row(), f))
    assert r.verdict == "wall" and r.evidence["card"] == "sc_publicindex"
    assert f.asked == []

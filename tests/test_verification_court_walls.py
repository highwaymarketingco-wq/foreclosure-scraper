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
    # nc_notices_counties.py's own _FLIP_FOOTPRINT_NAMES rule remaps a real "NOTICE OF
    # FORECLOSURE SALE ... FILE NO. 26SP..." (raw.public_notice.kind == "foreclosure") down to
    # listing_type lis_pendens outside the flip footprint (Dare, Brunswick, ...) -- it is still
    # the identical SP file behind the identical eCourts picture-CAPTCHA, so nc_sp must cover it
    # too (2026-11-18 gap_matrix built-not-verified sweep; board_stream audit found 81 such rows
    # across 13 NC counties with no verdict before this fix).
    assert W.card_of(_row(state="NC", source="public_notices.nc_notices_counties", county="Dare",
                          listing_type="lis_pendens",
                          raw={"public_notice": {"kind": "foreclosure"}})) == "nc_sp"
    # a genuine (non-remapped) lis_pendens notice -- no raw.public_notice.kind == "foreclosure"
    # marker -- must NOT be swept into nc_sp just because it shares the same source.
    assert W.card_of(_row(state="NC", source="public_notices.nc_notices_counties", county="Dare",
                          listing_type="lis_pendens", raw={"public_notice": {"kind": "lien_claim"}})) is None
    assert W.card_of(_row(state="NC", source="public_notices.nc_notices_counties", county="Dare",
                          listing_type="lis_pendens", raw={})) is None


def test_never_fetches():
    f = ReplayFetcher({})
    r = asyncio.run(W.verify(_row(), f))
    assert r.verdict == "wall" and r.evidence["card"] == "sc_publicindex"
    assert f.asked == []

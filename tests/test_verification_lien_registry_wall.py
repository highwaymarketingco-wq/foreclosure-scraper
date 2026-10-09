"""lien_registry_wall: lien claims whose registry no code may read are labelled with their card."""
from __future__ import annotations

import asyncio

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import lien_registry_wall as W


def _row(**kw):
    r = {"state": "NC", "county": "Iredell", "source": "counties_generic.liensnc",
         "listing_type": "tax_lien", "raw": {}}
    r.update(kw)
    return r


def test_registered_as_a_wall_that_governs_nothing():
    v = {x.name: x for x in registry.discover()}["lien_registry_wall"]
    assert v.wall and v.signal == "lien_registry_wall" and v.governs == ()


def test_cards_by_source():
    assert W.card_of(_row()) == "liensnc_login"
    assert W.card_of(_row(source="liensnc")) == "liensnc_login"
    assert W.card_of(_row(state="SC", source="counties_sc.sc_dew_lien_registry")) == "sc_lien_registries"
    assert W.card_of(_row(state="SC", source="counties_sc.sc_state_tax_lien")) == "sc_lien_registries"
    assert W.card_of(_row(county="Rutherford", source="counties_nc.rutherford_tax")) == "avalon_tax"
    assert W.card_of(_row(county="Rutherford", source="counties_nc.rutherford_wildfire_tax",
                          listing_type="tax_sale")) == "avalon_tax"


def test_county_property_tax_rows_and_other_listing_types_are_not_walled():
    assert W.card_of(_row(source="counties_nc.nc_ptscloud_delinquent_tax")) is None
    assert W.card_of(_row(listing_type="lis_pendens")) is None
    assert not W.applies(_row(source="counties_sc.qpaybill_delinquent_roll", state="SC"))


def test_never_overlaps_a_live_tax_verifier_on_the_same_row():
    """a wall row is either another lien's listing (the county verifiers skip it) or a county whose
    site no live verifier reads: no tax_lien verifier may also apply (their applies must not overlap)"""
    live = [v for v in registry.discover() if v.signal == "tax_lien" and not v.wall]
    rows = [_row(), _row(state="SC", source="counties_sc.sc_dew_lien_registry", county="Spartanburg"),
            _row(county="Rutherford", source="counties_nc.rutherford_tax")]
    for r in rows:
        assert W.applies(r)
        assert not any(v.applies(r) for v in live), r["source"]


def test_the_wall_sources_are_the_non_property_tax_sources_plus_rutherford():
    assert (W.LIENSNC_SOURCES | W.SC_REGISTRY_SOURCES) <= tc.NON_PROPERTY_TAX_SOURCES


def test_never_fetches():
    f = ReplayFetcher({})
    r = asyncio.run(W.verify(_row(), f))
    assert r.verdict == "wall" and r.evidence["card"] == "liensnc_login"
    assert f.asked == []

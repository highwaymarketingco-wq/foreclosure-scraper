"""Oconee SC FLC / Assignment register (Assignment_FLC FeatureServer).

Fixture is a saved slice of the live service (layer 1 "FLC", layer 0
"Assignment"), captured 2026-08. Locks in:
  * the published money trail is carried verbatim, with the two identities the
    county's own numbers satisfy on every live row:
        FLC_Price = DT_Cost + Total_Tax + Proc_Fee
        Bid       = DT_Cost + Total_Tax - Abated_Tax
  * opening_bid is the OVER-THE-COUNTER assignment price (FLC_Price), not Bid
  * Total_Tax lands on the raw key enrichment_tax_owed's generic scan reads
  * parcels that left the inventory (SOLD/REDEEMED/ASSIGNED/CANCELED) are not
    emitted as leads
  * a TMS in both registers is emitted once, from the richer layer-1 row
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper.scrapers.counties_sc import oconee_flc_assignment as m

FIXTURE = Path(__file__).parent / "fixtures" / "oconee_flc_assignment.json"


@pytest.fixture(scope="module")
def feats():
    d = json.loads(FIXTURE.read_text())
    return d["flc"], d["assignment"]


def _by_tms(listings):
    return {m.tms_key(li.parcel_id): li for li in listings}


def test_emits_only_still_assignable_parcels(feats):
    flc, assign = feats
    out = m.build_listings(flc, assign)
    got = _by_tms(out)

    # fixture holds 4 FLC rows (2 NONE, 1 SOLD, 1 HOLD) + 3 assignment rows
    # (2 NONE, 1 REDEEMED). SOLD and REDEEMED must not become leads.
    assert m.tms_key("236-01-01-029") not in got, "SOLD parcel must not be emitted"
    assert m.tms_key("307-02-01-151") not in got, "REDEEMED parcel must not be emitted"
    # HOLD is still county-held inventory, so it stays.
    assert m.tms_key("310-00-03-066") in got
    assert len(out) == 5


def test_money_trail_is_carried_verbatim(feats):
    flc, assign = feats
    li = _by_tms(m.build_listings(flc, assign))[m.tms_key("161-00-04-015")]
    blk = li.raw["oconee_flc_assignment"]

    assert blk["dt_cost"] == 795.0
    assert blk["taxes_owed"] == 112.68        # Total_Tax, the delinquent tax
    assert blk["abated_tax"] == 15.05
    assert blk["processing_fee"] == 20.0
    assert blk["bid"] == 892.63
    assert blk["flc_price"] == 927.68
    assert blk["year"] == 2015
    assert blk["assignable"] is True

    # The county's own arithmetic, both directions.
    assert round(blk["dt_cost"] + blk["taxes_owed"] + blk["processing_fee"], 2) == blk["flc_price"]
    assert round(blk["dt_cost"] + blk["taxes_owed"] - blk["abated_tax"], 2) == blk["bid"]


def test_opening_bid_is_the_assignment_price_not_the_struck_off_bid(feats):
    flc, assign = feats
    li = _by_tms(m.build_listings(flc, assign))[m.tms_key("161-00-04-015")]
    # Buying direct costs FLC_Price; Bid is only the historical struck-off figure.
    assert li.opening_bid == 927.68
    assert li.raw["oconee_flc_assignment"]["bid"] == 892.63


def test_parcel_identity_and_geo(feats):
    flc, assign = feats
    li = _by_tms(m.build_listings(flc, assign))[m.tms_key("161-00-04-015")]
    assert li.state == "SC" and li.county == "Oconee"
    assert li.parcel_id == "161-00-04-015"
    assert li.owner_name and li.defendant == li.owner_name
    assert li.listing_type.value == "tax_sale"
    assert li.foreclosure_process == "tax"
    # centroid lands inside Oconee County's bounding box
    assert 34.4 < li.latitude < 35.1
    assert -83.4 < li.longitude < -82.7


def test_assignment_only_parcels_come_from_layer_zero(feats):
    flc, assign = feats
    li = _by_tms(m.build_listings(flc, assign))[m.tms_key("039-00-01-168")]
    blk = li.raw["oconee_flc_assignment"]
    assert blk["layer"] == "Assignment"
    assert blk["flc_bid"] == 425.3
    assert li.opening_bid == 425.3
    # layer 0 has no cost buildup, so no taxes_owed is invented
    assert "taxes_owed" not in blk


def test_shared_tms_is_emitted_once_from_the_richer_register(feats):
    flc, assign = feats
    # The live layers do not currently overlap; synthesize the collision so the
    # merge path stays covered if the county ever lists a parcel in both.
    dup = json.loads(json.dumps(assign[0]))
    dup["attributes"]["TMS"] = flc[0]["attributes"]["TMS"]
    dup["attributes"]["TMS_NUMBER"] = flc[0]["attributes"]["TMS"]
    dup["attributes"]["FLC_Bid"] = 111.11
    dup["attributes"]["Redeem_Assign"] = "NONE"

    out = m.build_listings(flc, assign + [dup])
    key = m.tms_key(flc[0]["attributes"]["TMS"])
    hits = [li for li in out if m.tms_key(li.parcel_id) == key]
    assert len(hits) == 1
    blk = hits[0].raw["oconee_flc_assignment"]
    assert blk["layer"] == "FLC"                  # keeps the full money trail
    assert blk["assignment_bid"] == 111.11        # picks up the layer-0 figure
    assert blk["assignment_status"] == "NONE"


def test_rows_without_a_tms_are_skipped(feats):
    flc, assign = feats
    orphan = json.loads(json.dumps(flc[0]))
    orphan["attributes"]["TMS"] = " "
    orphan["attributes"]["TMS_NUMBER"] = None
    assert len(m.build_listings([orphan], [])) == 0


def test_departed_statuses():
    for s in ("SOLD", "Redeemed", "assigned", "CANCELED", "CANCELLED"):
        assert m.is_departed(s)
    for s in ("NONE", "HOLD", "", None):
        assert not m.is_departed(s)

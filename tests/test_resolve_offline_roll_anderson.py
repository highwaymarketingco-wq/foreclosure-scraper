"""Anderson SC owner-name -> parcel resolution from the offline bulk assessor roll.

Anderson was a wall (no owner column on the live viewer, ACPASS is login-walled, the live
County_Parcels layer dropped owners). The 2026-08-03 roll on disk holds 113,406 Anderson
owners and sc_parcel_mailing.lookup_by_owner searches it offline with the strict matcher,
but nothing called it. These tests pin the wiring: the roll acts as one more pinned county
layer, decides nothing on its own, and never touches the network.
"""
from __future__ import annotations

import asyncio

import pytest

import foreclosure_scraper.enrichment_resolve_name_to_property as R
import foreclosure_scraper.sc_parcel_mailing as pm
from foreclosure_scraper.models import Listing, ListingType


def _lead(owner="SMITH JOHN A", county="Anderson", **kw):
    base = dict(source="counties_sc.sc_public_index", listing_type=ListingType.FORECLOSURE_SALE,
                source_url="https://example.invalid/case/1", state="SC", county=county,
                owner_name=owner)
    base.update(kw)
    return Listing(**base)


def _rec(owner="SMITH JOHN A", tms="123-45-67-089.000", situs="12 OAK ST", **kw):
    rec = {"owner": owner, "taxpayer": owner, "parcel_key": tms, "parcel_raw": tms,
           "situs": situs, "situs_street": situs, "market_value": 145000.0,
           "living_sqft": 1800, "year_built": 1995, "acreage": 0.4}
    rec.update(kw)
    return rec


@pytest.fixture
def roll_present(monkeypatch):
    monkeypatch.setattr(pm, "covered_counties", lambda: {("SC", "Anderson")})


def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the offline roll backend must not touch the network")
    monkeypatch.setattr(R, "_layer_health", boom)


def test_anderson_is_served_from_the_roll_when_it_is_on_disk(roll_present):
    plan = R._endpoint_plan(_lead())
    assert [c["kind"] for c in plan] == ["offline_roll"]
    assert plan[0]["label"] == "sc_offline_roll_anderson"
    assert plan[0]["pinned"] and plan[0]["mail_fields"] == ()
    assert R._is_target(_lead()) is True


def test_anderson_is_a_wall_again_when_the_roll_is_absent(monkeypatch):
    monkeypatch.setattr(pm, "covered_counties", lambda: set())
    assert R._endpoint_plan(_lead()) == []
    assert R._is_target(_lead()) is False


def test_cherokee_stays_a_wall_even_with_the_roll_present(roll_present):
    assert R._endpoint_plan(_lead(county="Cherokee")) == []


def test_roll_rows_use_the_county_layers_own_field_names(monkeypatch):
    monkeypatch.setattr(pm, "lookup_by_owner", lambda s, c, n, limit=5: [_rec()])
    rows = R._offline_roll_rows({"county": "Anderson"}, "SMITH JOHN A")
    assert rows == [{"OWNER": "SMITH JOHN A", "PHYS_ADDR": "12 OAK ST", "TMS": "123-45-67-089.000",
                     "MRKT_VALUE": 145000.0, "Heated_Sqf": 1800, "YearBuilt": 1995, "Acreage": 0.4}]


def test_unique_strong_match_fills_address_parcel_and_value(roll_present, monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(pm, "lookup_by_owner", lambda s, c, n, limit=5: [_rec()])
    li = _lead()
    stats = asyncio.run(R.enrich_resolve_name_to_property([li]))
    assert stats["resolved"] == 1 and stats["resolved_sc_offline_roll"] == 1
    assert li.street_address == "12 OAK ST" and li.parcel_id == "123-45-67-089.000"
    assert li.market_value == 145000.0
    prov = li.raw["resolved_from_name"]
    assert prov["queried"] is True and prov["backend"] == "sc_offline_roll_anderson"


def test_two_different_parcels_for_one_owner_is_flagged_not_guessed(roll_present, monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(pm, "lookup_by_owner", lambda s, c, n, limit=5: [
        _rec(tms="111-00-00-001.000", situs="1 A ST"), _rec(tms="222-00-00-002.000", situs="2 B ST")])
    li = _lead()
    stats = asyncio.run(R.enrich_resolve_name_to_property([li]))
    assert stats["ambiguous"] == 1 and stats["resolved"] == 0
    assert not (li.street_address or "").strip() and not (li.parcel_id or "").strip()
    assert li.raw["resolved_from_name"]["confidence"] == "ambiguous_multi_parcel"


def test_a_weak_name_is_rejected_by_the_shared_strict_matcher(roll_present, monkeypatch):
    """lookup_by_owner is trusted to pre-filter, but the resolver's own matcher still
    adjudicates: a different person's row must never be written onto the lead."""
    _no_network(monkeypatch)
    monkeypatch.setattr(pm, "lookup_by_owner", lambda s, c, n, limit=5: [_rec(owner="SMITHSON ROBERT Q")])
    li = _lead()
    asyncio.run(R.enrich_resolve_name_to_property([li]))
    assert not (li.street_address or "").strip() and not (li.parcel_id or "").strip()
    assert li.raw["resolved_from_name"]["confidence"] == "no_match"


def test_no_roll_hit_is_marked_queried_so_it_is_not_retried_forever(roll_present, monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(pm, "lookup_by_owner", lambda s, c, n, limit=5: [])
    li = _lead()
    asyncio.run(R.enrich_resolve_name_to_property([li]))
    prov = li.raw["resolved_from_name"]
    assert prov["confidence"] == "no_match" and prov["queried"] is True


def test_a_lead_that_already_has_a_parcel_is_not_a_target(roll_present):
    assert R._is_target(_lead(parcel_id="123-45-67-089.000")) is False

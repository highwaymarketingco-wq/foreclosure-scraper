"""Comps are carried forward with their age when the fresh lookup is empty (audit 2026-10-09).

The 2026-10-08 gated run lost the comps of 1,160 rows whose identity changed between runs (the
prior row never folded onto them) while the comps phase hit its time cap. Made-up rows.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper import enrichment_comps as ec
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

TODAY = date(2026, 10, 9)


def _li(**kw) -> Listing:
    base = dict(source="counties_nc.test_vacant", source_url="http://x/1",
                listing_type=ListingType.TAX_SALE, state="NC", county="Lincoln",
                property_kind=PropertyKind.SINGLE_FAMILY, street_address="12 Test Rd",
                city="Lincolnton")
    base.update(kw)
    return Listing(**base)


def _comp(sold: str, price: float = 200_000, kind: str = "sfr", **kw) -> dict:
    d = {"sold_price": price, "sold_date": sold, "sqft": 1500, "kind": kind,
         "price_per_sqft": price / 1500, "geo_anchored": True}
    d.update(kw)
    return d


def test_age_comps_keeps_fresh_comps_and_stamps_their_age():
    li = _li(raw={"comps": [_comp("2026-09-01", picked_on=TODAY.isoformat())]})
    s = ec.age_comps([li], TODAY)
    assert s["fresh"] == 1
    c = li.raw["comps"][0]
    assert c["age_days"] == 38 and "carried" not in c


def test_age_comps_marks_kept_comps_carried_and_drops_old_ones():
    li = _li(raw={"comps": [_comp("2026-05-01", 210_000, picked_on="2026-10-01"),
                            _comp("2025-06-01", 150_000, picked_on="2026-10-01"),
                            _comp("2026-04-01", 190_000, picked_on="2026-10-01")],
                  "comp_median_ppsf": 999.0})
    s = ec.age_comps([li], TODAY)
    comps = li.raw["comps"]
    assert len(comps) == 2 and s["aged_out_comps"] == 1 and s["carried"] == 1
    assert all(c["carried"] and c["age_days"] <= ec.COMPS_CARRY_MAX_AGE_DAYS for c in comps)
    assert li.raw["comp_median_ppsf"] == 210_000 / 1500   # recomputed from what is left


def test_age_comps_drops_a_list_that_aged_out_entirely_and_says_so():
    li = _li(raw={"comps": [_comp("2025-01-01")], "comp_median_ppsf": 133.0})
    s = ec.age_comps([li], TODAY)
    assert li.raw["comps"] == [] and s["aged_out_rows"] == 1
    assert "comp_median_ppsf" not in li.raw
    assert "dropped" in li.raw["comps_note"]


def test_carry_from_prior_board_for_a_row_whose_identity_changed():
    """The prior row had no parcel id; the fresh row has the county's new PIN. Same numbered
    address in the same county: the prior comps come across, marked with their age."""
    prior = [{"source": "counties_nc.test_vacant", "state": "NC", "county": "Lincoln",
              "street_address": "12 Test Rd", "parcel_id": None,
              "raw": {"comps": [_comp("2026-07-01"), _comp("2026-06-15")]}}]
    li = _li(parcel_id="3600123456")
    s = ec.carry_forward_from_prior([li], prior, prior_as_of="2026-10-07", today=TODAY)
    assert s["carried"] == 1
    comps = li.raw["comps"]
    assert len(comps) == 2
    assert all(c["carried"] and c["carried_from"] == "2026-10-07" for c in comps)
    assert comps[0]["age_days"] == 100
    assert li.raw["comp_median_ppsf"]
    assert "carried from the 2026-10-07 board" in li.raw["comps_note"]


def test_carry_skips_rows_that_have_comps_and_comps_of_another_kind():
    have = _li(street_address="1 A St", raw={"comps": [_comp("2026-09-01")]})
    lot = _li(street_address="2 B St", property_kind=PropertyKind.LAND)
    prior = [{"state": "NC", "county": "Lincoln", "street_address": "1 A St",
              "raw": {"comps": [_comp("2026-08-01", 1)]}},
             {"state": "NC", "county": "Lincoln", "street_address": "2 B St",
              "raw": {"comps": [_comp("2026-08-01", kind="sfr")]}}]
    s = ec.carry_forward_from_prior([have, lot], prior, today=TODAY)
    assert s["carried"] == 0 and s["kind_mismatch"] == 1
    assert have.raw["comps"][0]["sold_price"] == 200_000
    assert not lot.raw.get("comps")


def test_carry_refuses_comps_outside_the_age_window_and_other_counties():
    li = _li()
    prior = [{"state": "NC", "county": "Lincoln", "street_address": "12 Test Rd",
              "raw": {"comps": [_comp("2025-01-01")]}},
             {"state": "NC", "county": "Gaston", "street_address": "12 Test Rd",
              "raw": {"comps": [_comp("2026-09-01")]}}]
    s = ec.carry_forward_from_prior([li], prior, today=TODAY)
    assert s["carried"] == 0 and s["aged_out"] == 1
    assert not li.raw.get("comps")


def test_carry_refuses_a_key_two_prior_rows_of_different_addresses_claim():
    li = _li(street_address=None, parcel_id="3600999999")
    prior = [{"state": "NC", "county": "Lincoln", "parcel_id": "3600999999",
              "street_address": "5 One St", "raw": {"comps": [_comp("2026-09-01")]}},
             {"state": "NC", "county": "Lincoln", "parcel_id": "3600999999",
              "street_address": "9 Two St", "raw": {"comps": [_comp("2026-09-02")]}}]
    s = ec.carry_forward_from_prior([li], prior, today=TODAY)
    assert s["carried"] == 0
    assert not li.raw.get("comps")


def test_comps_loop_order_puts_rows_without_comps_and_hot_warm_first():
    a = _li(street_address="1 A St", raw={"comps": [_comp("2026-09-01", picked_on="2026-10-01")]})
    b = _li(street_address="2 B St", raw={"distress_stack": {"tier": "COLD"}})
    c = _li(street_address="3 C St", raw={"distress_stack": {"tier": "WARM"}})
    d = _li(street_address="4 D St", raw={"comps": [_comp("2026-09-01", picked_on="2026-09-01")],
                                          "distress_stack": {"tier": "HOT"}})
    order = sorted([a, b, c, d], key=ec._comps_priority)
    assert [x.street_address for x in order] == ["3 C St", "2 B St", "4 D St", "1 A St"]


def test_median_ppsf_ignores_unanchored_comps():
    comps = [_comp("2026-09-01", geo_anchored=False)]
    assert ec._median_ppsf(comps) is None
    assert ec._median_ppsf([_comp("2026-09-01")]) == 200_000 / 1500


def test_carry_recorded_sales_basket_for_a_row_that_lost_it():
    basket = {"median_ppsf": 142.0, "count": 18, "p25_ppsf": 120.0, "p75_ppsf": 160.0,
              "radius_mi": 1.0, "confidence": "HIGH", "source": "county_gis_recorded_sales"}
    prior = [{"state": "NC", "county": "Lincoln", "street_address": "12 Test Rd",
              "raw": {"recorded_comps": basket, "comp_median_ppsf_recorded": 142.0,
                      "comps": [_comp("2026-08-01")]}}]
    li = _li(parcel_id="3600123456", raw={"comps": [_comp("2026-09-20", picked_on="2026-10-09")]})
    s = ec.carry_forward_from_prior([li], prior, prior_as_of="2026-10-07", today=TODAY)
    assert s["carried_recorded"] == 1 and s["carried"] == 0
    assert li.raw["comp_median_ppsf_recorded"] == 142.0
    assert li.raw["recorded_comps"]["carried_from"] == "2026-10-07"
    assert li.raw["comps"][0]["sold_date"] == "2026-09-20"     # fresh comps untouched


def test_enrich_stamps_picked_on_and_drops_a_stale_median(monkeypatch):
    """Fresh comps carry the day they were picked; a county-wide (unanchored) pick leaves no
    median behind from last run's comps."""
    import asyncio
    sold = dict(street="1 Hickory Ln", city="Hickory", state="NC", zip_code="28601",
                sold_price=250000, sqft=1500, beds=3, full_baths=2, year_built=2005,
                last_sold_date="2026-05-01", style="Single Family", property_url="u1")
    monkeypatch.setattr(ec, "_sold_pool_for_seat", lambda c, s: [dict(sold)])
    monkeypatch.setattr(ec, "_rent_pool_for_seat", lambda c, s: [])
    monkeypatch.setattr(ec, "_active_count_for_seat", lambda c, s: 5)
    local = _li(county="Catawba", zip_code="28601", city="Hickory", living_sqft=1500, bedrooms=3)
    far = _li(county="Catawba", zip_code="28699", city="Elsewhere", living_sqft=1500, bedrooms=3,
              street_address="9 Far Rd", raw={"comp_median_ppsf": 999.0})
    asyncio.run(ec.enrich_with_comps([local, far]))
    today = date.today().isoformat()
    assert local.raw["comps"][0]["picked_on"] == today
    assert round(local.raw["comp_median_ppsf"]) == 167
    assert far.raw["comps"][0]["geo_anchored"] is False
    assert "comp_median_ppsf" not in far.raw

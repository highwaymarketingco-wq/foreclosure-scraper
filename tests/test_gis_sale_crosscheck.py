"""County-recorded sale-price cross-check (enrichment_gis_sale_crosscheck.py)
and its wiring into enrichment_comps.py's sold-comp matcher.

Fixture numbers are the REAL, live-confirmed 140 Old Leicester Rd, Asheville
NC 28804 case (2026-10-04): HomeHarvest's own `sold_price` is $140,000;
Buncombe County's own ArcGIS parcel layer (`property_bc_dis/MapServer/1`)
says SalePrice=$160,000, DeedDate=2026-04-06, Stamps=320 (320 * $500 =
$160,000 exactly, the NC excise-tax-stamp consideration proxy) -- a 12.5%
disagreement, which should trip the preference at the module's 8% tolerance.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from foreclosure_scraper import enrichment_gis_sale_crosscheck as xc
from foreclosure_scraper.enrichment_comps import _apply_gis_crosscheck

# ---- real numbers, captured live 2026-10-04 --------------------------------
REAL_HOMEHARVEST_SOLD_PRICE = 140_000.0
REAL_COUNTY_SALE_PRICE = 160_000.0
REAL_DEED_DATE = "20260406"            # Buncombe's own 'YYYYMMDD' string format
REAL_SOLD_DATE = "2026-04-06 00:00:00"  # HomeHarvest's last_sold_date format
REAL_STAMPS = 320.0


def _resp(body: dict, status: int = 200):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    return r


def _feature(**attrs) -> dict:
    return {"attributes": attrs}


def _buncombe_response(features: list[dict]) -> dict:
    return {"features": features}


# ---- pure helpers -----------------------------------------------------------

def test_split_house_street_basic():
    assert xc.split_house_street("140 Old Leicester Rd") == ("140", "OLD LEICESTER")


def test_split_house_street_no_number_returns_none():
    assert xc.split_house_street("Old Leicester Rd") is None


def test_deed_date_iso_parses_buncombe_yyyymmdd_string():
    assert xc._deed_date_iso(REAL_DEED_DATE) == "2026-04-06"
    assert xc._deed_date_iso("garbage") is None


def test_parse_any_date_handles_homeharvest_timestamp_format():
    assert xc.parse_any_date(REAL_SOLD_DATE).isoformat() == "2026-04-06"
    assert xc.parse_any_date("2026-04-06") .isoformat() == "2026-04-06"
    assert xc.parse_any_date(None) is None


#  _disambiguate operates on already-unwrapped ATTRIBUTE dicts (the shape
#  `_buncombe_lookup` hands it, after stripping ArcGIS's {"attributes": {...}}
#  envelope) -- unlike `_buncombe_response`/`_feature` below, which build the
#  raw wire-format JSON body a mocked httpx client returns.
def test_disambiguate_single_feature_passes_through():
    feats = [{"DeedDate": REAL_DEED_DATE, "SalePrice": REAL_COUNTY_SALE_PRICE}]
    rec = xc._disambiguate(feats, xc.parse_any_date(REAL_SOLD_DATE))
    assert rec is feats[0]


def test_disambiguate_refuses_to_guess_without_a_claimed_date():
    feats = [{"DeedDate": "20260101"}, {"DeedDate": "20250101"}]
    assert xc._disambiguate(feats, None) is None


def test_disambiguate_picks_the_closer_deed_date():
    near = {"DeedDate": REAL_DEED_DATE, "SalePrice": 160000.0}
    far = {"DeedDate": "20180101", "SalePrice": 99999.0}
    rec = xc._disambiguate([far, near], xc.parse_any_date(REAL_SOLD_DATE))
    assert rec is near


def test_disambiguate_refuses_a_genuine_tie():
    claimed = xc.parse_any_date("2026-04-06 00:00:00")
    a = {"DeedDate": "20260401"}
    b = {"DeedDate": "20260411"}  # both 5 days off -> tie
    assert xc._disambiguate([a, b], claimed) is None


# ---- crosscheck_sold_price (mocked httpx) ----------------------------------

def _client_returning(body: dict):
    http = MagicMock()

    async def _get(url, params=None, **kw):
        return _resp(body)

    http.get = _get
    return http


def test_crosscheck_flags_and_prefers_the_real_140_old_leicester_case():
    """The exact confirmed bug: 12.5% disagreement at an 8% tolerance ->
    preferred=True, county price surfaced, stamps carried for audit."""
    http = _client_returning(_buncombe_response([_feature(
        pinnum="972073757600000", Address="PO BOX 304", HouseNumber="140",
        streetname="OLD LEICESTER", CityName="ARDEN",
        SalePrice=REAL_COUNTY_SALE_PRICE, DeedDate=REAL_DEED_DATE, Stamps=REAL_STAMPS,
    )]))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd",
        city="Arden", claimed_sold_price=REAL_HOMEHARVEST_SOLD_PRICE,
        claimed_sold_date=REAL_SOLD_DATE,
    ))
    assert result is not None
    assert result["county_sale_price"] == REAL_COUNTY_SALE_PRICE
    assert result["county_deed_date"] == "2026-04-06"
    assert result["county_stamps"] == REAL_STAMPS
    assert result["disagreement_pct"] == pytest.approx(12.5, abs=0.1)
    assert result["preferred"] is True


def test_crosscheck_does_not_prefer_when_within_tolerance():
    http = _client_returning(_buncombe_response([_feature(
        HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
        SalePrice=160_000.0, DeedDate=REAL_DEED_DATE, Stamps=320.0,
    )]))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd",
        city="Arden", claimed_sold_price=156_000.0,  # 2.5% off -> under 8% tolerance
        claimed_sold_date=REAL_SOLD_DATE,
    ))
    assert result is not None
    assert result["preferred"] is False


def test_crosscheck_returns_none_when_county_has_no_matching_parcel():
    http = _client_returning(_buncombe_response([]))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="999 Nowhere Ln", city=None,
        claimed_sold_price=100_000.0, claimed_sold_date="2026-01-01",
    ))
    assert result is None


def test_crosscheck_refuses_when_deed_date_too_far_from_claimed_date():
    """Same parcel, but the county's recorded deed is a DIFFERENT, much older
    sale -- must not be treated as confirming (or contradicting) this one."""
    http = _client_returning(_buncombe_response([_feature(
        HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
        SalePrice=50_000.0, DeedDate="19990101", Stamps=100.0,
    )]))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd",
        city="Arden", claimed_sold_price=140_000.0, claimed_sold_date=REAL_SOLD_DATE,
    ))
    assert result is None


def test_crosscheck_disambiguates_by_city_when_house_number_collides():
    """Buncombe really does carry >1 parcel sharing a house number + street
    (e.g. two distinct '140 Old Leicester' parcels in different towns) --
    the city field must pick the right one rather than averaging/guessing."""
    http = _client_returning(_buncombe_response([
        _feature(HouseNumber="140", streetname="OLD LEICESTER", CityName="ASHEVILLE",
                 SalePrice=0.0, DeedDate="20160121", Stamps=0.0),
        _feature(HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
                 SalePrice=REAL_COUNTY_SALE_PRICE, DeedDate=REAL_DEED_DATE, Stamps=REAL_STAMPS),
    ]))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd",
        city="Arden", claimed_sold_price=REAL_HOMEHARVEST_SOLD_PRICE,
        claimed_sold_date=REAL_SOLD_DATE,
    ))
    assert result is not None
    assert result["county_sale_price"] == REAL_COUNTY_SALE_PRICE


def test_crosscheck_out_of_scope_county_returns_none_without_a_query():
    http = MagicMock()
    http.get = MagicMock(side_effect=AssertionError("should never be called"))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="SC", county="Anderson", address="41 Olive St", city=None,
        claimed_sold_price=100_000.0, claimed_sold_date="2026-01-01",
    ))
    assert result is None
    http.get.assert_not_called()


def test_anderson_and_cleveland_are_not_in_scope():
    """Pin the documented scope decision: Buncombe only, for now."""
    assert ("NC", "Buncombe") in xc.SUPPORTED
    assert ("SC", "Anderson") not in xc.SUPPORTED
    assert ("NC", "Cleveland") not in xc.SUPPORTED


# ---- _apply_gis_crosscheck (enrichment_comps.py integration) --------------

def test_apply_gis_crosscheck_overrides_sold_price_and_ppsf_when_preferred():
    http = _client_returning(_buncombe_response([_feature(
        HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
        SalePrice=REAL_COUNTY_SALE_PRICE, DeedDate=REAL_DEED_DATE, Stamps=REAL_STAMPS,
    )]))
    comps = [{
        "address": "140 Old Leicester Rd", "city": "Arden",
        "sold_price": REAL_HOMEHARVEST_SOLD_PRICE, "sold_date": REAL_SOLD_DATE,
        "sqft": 1529.0, "price_per_sqft": round(REAL_HOMEHARVEST_SOLD_PRICE / 1529.0, 2),
        "adjusted_ppsf": round(REAL_HOMEHARVEST_SOLD_PRICE / 1529.0, 2),
        "adjustments": {},
    }]
    asyncio.run(_apply_gis_crosscheck(http, comps, ("NC", "Buncombe"), {}))
    c = comps[0]
    assert c["sold_price"] == REAL_COUNTY_SALE_PRICE
    assert c["sold_price_homeharvest"] == REAL_HOMEHARVEST_SOLD_PRICE
    assert c["price_per_sqft"] == round(REAL_COUNTY_SALE_PRICE / 1529.0, 2)
    assert c["adjustments"]["gis_price_corrected"] is True
    assert c["gis_crosscheck"]["preferred"] is True


def test_apply_gis_crosscheck_leaves_price_alone_when_within_tolerance():
    http = _client_returning(_buncombe_response([_feature(
        HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
        SalePrice=160_000.0, DeedDate=REAL_DEED_DATE, Stamps=320.0,
    )]))
    comps = [{
        "address": "140 Old Leicester Rd", "city": "Arden",
        "sold_price": 156_000.0, "sold_date": REAL_SOLD_DATE,
        "sqft": 1529.0, "price_per_sqft": round(156_000.0 / 1529.0, 2),
    }]
    asyncio.run(_apply_gis_crosscheck(http, comps, ("NC", "Buncombe"), {}))
    c = comps[0]
    assert c["sold_price"] == 156_000.0  # unchanged
    assert c["gis_crosscheck"]["preferred"] is False


def test_apply_gis_crosscheck_caches_by_address_across_comps():
    calls = {"n": 0}

    async def _get(url, params=None, **kw):
        calls["n"] += 1
        return _resp(_buncombe_response([_feature(
            HouseNumber="140", streetname="OLD LEICESTER", CityName="ARDEN",
            SalePrice=REAL_COUNTY_SALE_PRICE, DeedDate=REAL_DEED_DATE, Stamps=REAL_STAMPS,
        )]))

    http = MagicMock()
    http.get = _get
    comps = [
        {"address": "140 Old Leicester Rd", "city": "Arden",
         "sold_price": REAL_HOMEHARVEST_SOLD_PRICE, "sold_date": REAL_SOLD_DATE, "sqft": 1529.0},
        {"address": "140 Old Leicester Rd", "city": "Arden",
         "sold_price": REAL_HOMEHARVEST_SOLD_PRICE, "sold_date": REAL_SOLD_DATE, "sqft": 1529.0},
    ]
    cache: dict = {}
    asyncio.run(_apply_gis_crosscheck(http, comps, ("NC", "Buncombe"), cache))
    assert calls["n"] == 1
    assert all(c["sold_price"] == REAL_COUNTY_SALE_PRICE for c in comps)

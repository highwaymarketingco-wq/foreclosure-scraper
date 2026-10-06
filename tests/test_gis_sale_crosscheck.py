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


# The two real "140 Old Leicester" parcels, as the layer answers today (situs + sale columns,
# live 2026-10-06). The layer's CityName/Address are the OWNER'S MAILING address ("PO BOX 304"
# ARDEN for the RD parcel, "27 AUDUBON DR" ASHEVILLE for the HWY one), so the first version,
# which narrowed by CityName == the comp's city, picked the HWY parcel for the board's real comp
# (city "Asheville") and never corrected the case it was built for.
_OLD_LEICESTER_RD = dict(pinnum="972073757600000", HouseNumber="140", NumberSuffix="",
                         direction="", streetname="OLD LEICESTER", StreetType="RD",
                         SalePrice=REAL_COUNTY_SALE_PRICE, DeedDate=REAL_DEED_DATE,
                         Stamps=REAL_STAMPS, DeedBook="6581", DeedPage="0333")
_OLD_LEICESTER_HWY = dict(pinnum="972081073200000", HouseNumber="140", NumberSuffix="",
                          direction="", streetname="OLD LEICESTER", StreetType="HWY",
                          SalePrice=0.0, DeedDate="20160121", Stamps=0.0)


def _router(features: list[dict], deed_count):
    """A mocked httpx client: the parcel query answers `features`, the deed count query
    answers {"count": deed_count} (an Exception to raise one)."""
    http = MagicMock()
    calls = []

    async def _get(url, params=None, **kw):
        calls.append(dict(params or {}))
        if (params or {}).get("returnCountOnly") == "true":
            if isinstance(deed_count, BaseException):
                raise deed_count
            return _resp({"count": deed_count})
        return _resp(_buncombe_response([_feature(**f) for f in features]))

    http.get = _get
    http.calls = calls
    return http


def test_crosscheck_picks_the_parcel_by_its_situs_not_the_owners_mailing_city():
    http = _router([_OLD_LEICESTER_HWY, _OLD_LEICESTER_RD], deed_count=1)
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd",
        city="Asheville", claimed_sold_price=REAL_HOMEHARVEST_SOLD_PRICE,
        claimed_sold_date=REAL_SOLD_DATE,
    ))
    assert result is not None
    assert result["county_sale_price"] == REAL_COUNTY_SALE_PRICE
    assert result["preferred"] is True and result["deed_parcels"] == 1
    assert "CityName" not in http.calls[0]["outFields"]
    assert "Address" not in http.calls[0]["outFields"].split(",")


def test_crosscheck_keeps_homeharvest_when_the_deed_conveys_several_parcels():
    """117 Lookout Rd, live 2026-10-06: deed 6617/0478 records $205,000 on each of 3 parcels;
    HomeHarvest's $135,000 is the house. A combined price is not a correction."""
    lookout = dict(pinnum="973080857100000", HouseNumber="117", NumberSuffix="", direction="",
                   streetname="LOOKOUT", StreetType="RD", SalePrice=205000.0,
                   DeedDate="20260731", Stamps=410.0, DeedBook="6617", DeedPage="0478")
    http = _router([lookout], deed_count=3)
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="117 Lookout Rd", city="Asheville",
        claimed_sold_price=135000.0, claimed_sold_date="2026-07-31 00:00:00"))
    assert result["preferred"] is False and result["deed_parcels"] == 3


def test_crosscheck_keeps_homeharvest_when_the_deed_count_fails():
    http = _router([_OLD_LEICESTER_RD], deed_count=RuntimeError("timeout"))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd", city=None,
        claimed_sold_price=REAL_HOMEHARVEST_SOLD_PRICE, claimed_sold_date=REAL_SOLD_DATE))
    assert result["preferred"] is False and result["deed_parcels"] is None


def test_no_deed_count_request_when_the_prices_agree():
    http = _router([_OLD_LEICESTER_RD], deed_count=AssertionError("not needed"))
    result = asyncio.run(xc.crosscheck_sold_price(
        http, state="NC", county="Buncombe", address="140 Old Leicester Rd", city=None,
        claimed_sold_price=158000.0, claimed_sold_date=REAL_SOLD_DATE))
    assert result["preferred"] is False and len(http.calls) == 1


@pytest.mark.parametrize("addr,want", [
    ("140 Old Leicester Rd", ("140", "", "", "OLD LEICESTER", "RD")),
    ("4B Heather Way", ("4", "B", "", "HEATHER", "WAY")),
    ("50 N Main St Unit 4", ("50", "", "N", "MAIN", "ST")),
    ("12 Mountain View Trl", ("12", "", "", "MOUNTAIN VIEW", "TRL")),
    ("15 Eaglebear Dr, Asheville, NC 28806", ("15", "", "", "EAGLEBEAR", "DR")),
    ("78 and 80 Taylor St, Woodfin, NC, 28804", None),
    ("99999 Lookout Rd", None),                 # the placeholder of an unaddressed lot
    ("0 Old Leicester Rd", None),
    ("Old Leicester Rd", None),
])
def test_parse_address(addr, want):
    p = xc.parse_address(addr)
    got = None if p is None else (p["house"], p["number_suffix"], p["direction"], p["street"],
                                  p["street_type"])
    assert got == want


def test_narrow_candidates_by_situs_columns():
    parts = xc.parse_address("22 Waters Rd")
    a = {"streetname": "WATERS", "StreetType": "RD"}
    b = {"streetname": "WATERS COVE", "StreetType": "RD"}
    assert xc.narrow_candidates([b, a], parts) == [a]
    parts = xc.parse_address("4 Heather Way")          # the comp dropped the unit letter
    a4, b4 = {"streetname": "HEATHER", "NumberSuffix": "A"}, {"streetname": "HEATHER", "NumberSuffix": "B"}
    assert xc.narrow_candidates([a4, b4], parts) == [a4, b4]   # left to the deed-date pin


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

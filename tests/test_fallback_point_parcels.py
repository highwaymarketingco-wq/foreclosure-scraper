"""No parcel, and no situs address, from a geocoder FALLBACK point (2026-10-06).

THE BUG THIS PINS
    enrichment_geocode puts a lead with no usable address on its city centre (Tier 3) or county
    seat (Tier 4), and enrichment_parcel_from_geo then took whatever parcel lies under that point.
    On the 10/5 checkpoint Rutherford parcel 1654116 (a church at the Rutherfordton county seat,
    35.371,-81.957) was attached to 619 rows of 10 sources and New Hanover 3115-88-8610.000 (at a
    point shared by the Wilmington rows) to 121; on the published board Lincoln 3633940779 sits on
    1,618 rows. The church's situs '252 N WASHINGTON ST' was then copied onto address-less rows by
    scripts/fill_address_from_parcel.py ('parcel_cache:exact') and enrichment_situs_address.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_parcel_from_geo as pfg
from foreclosure_scraper import enrichment_situs_address as sa
from foreclosure_scraper.enrichment_geocode import imprecise_point_flag, is_county_seat_point
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.placeholder_twins import fallback_point_parcel

RUTH_SEAT = (35.371, -81.957)


def _row(n, lat, lng, *, county="Rutherford", raw=None, parcel=None, addr=None):
    return Listing(source="counties_nc.rutherford_tax", source_url=f"https://example.test/{n}",
                   listing_type=ListingType.TAX_LIEN, state="NC", county=county,
                   latitude=lat, longitude=lng, parcel_id=parcel, street_address=addr,
                   raw=dict(raw or {}))


def test_fallback_point_tests():
    assert is_county_seat_point(*RUTH_SEAT) and is_county_seat_point(35.37100001, -81.957)
    assert not is_county_seat_point(35.3712, -81.9571)        # a real point near the seat
    assert not is_county_seat_point(35.3337279, -81.8649245)
    assert imprecise_point_flag({"geo_imprecise": "centroid_snap"})
    assert imprecise_point_flag({"geo_imprecise": {"state": "centroid_snap", "source": "x"}})
    assert imprecise_point_flag({"geocoded_by_name": {"approx": True}})
    assert not imprecise_point_flag({"geo_imprecise": "census_geocode"})
    assert not imprecise_point_flag({})
    seat = {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.371, "lng": -81.957}}
    assert fallback_point_parcel(seat)
    # the Lincoln row whose own point is precise but whose parcel came from the county seat
    assert fallback_point_parcel({"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.47,
                                                      "lng": -81.255}})
    precise = {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.5711, "lng": -82.5936}}
    assert not fallback_point_parcel(precise)
    assert fallback_point_parcel({**precise, "geo_imprecise": "centroid_snap"})
    assert not fallback_point_parcel({"parcel_from_address": {"source": "x"}})


def test_parcel_from_geo_skips_fallback_points(monkeypatch):
    seen = []

    async def fake_resolve(c, li, counts):
        seen.append(li.source_url)
        li.parcel_id = "9999999999"
        counts["resolved"] += 1

    monkeypatch.setattr(pfg, "_resolve_one", fake_resolve)
    rows = [
        _row(1, *RUTH_SEAT),                                                   # county seat
        _row(2, 35.3337, -81.8649, raw={"geo_imprecise": "centroid_snap"}),   # flagged
        _row(3, 35.3337, -81.8649, raw={"geocoded_by_name": {"approx": True}}),
    ]
    # a point 9 rows share (a town centre the seat table does not list)
    rows += [_row(10 + i, 35.33421, -81.86512) for i in range(9)]
    precise = _row(99, 35.3412345, -81.8812345)
    census = _row(98, 35.3312345, -81.8712345, raw={"geo_imprecise": "census_geocode"})
    rows += [precise, census]
    counts = asyncio.run(pfg.enrich_parcel_from_geo(rows))
    assert sorted(seen) == sorted([precise.source_url, census.source_url])
    assert counts["skipped_fallback_point"] == 12
    assert rows[0].parcel_id is None and precise.parcel_id == "9999999999"


CHURCH_BAG = {"parno": "1654116", "cntyname": "Rutherford", "siteadd": "252 N WASHINGTON ST",
              "scity": "RUTHERFORDTON", "szip": "28139"}


@pytest.mark.parametrize("point,writes", [((35.371, -81.957), False),
                                          ((35.3412345, -81.8812345), True)])
def test_situs_writer_ignores_a_fallback_point_parcel(monkeypatch, point, writes):
    monkeypatch.setattr(sa, "_resolve_layer", lambda li: None)   # no network: read the cached bag
    li = _row(1, None, None, parcel="1654116",
              raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": point[0],
                                       "lng": point[1]},
                   "gis_attrs_full": dict(CHURCH_BAG)})
    asyncio.run(sa.enrich_situs_address([li]))
    assert (li.street_address == "252 N WASHINGTON ST") is writes


def _fill_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "fill_address_from_parcel.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("fill_address_from_parcel_t", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fill_address_from_parcel_skips_a_fallback_point_parcel():
    F = _fill_module()
    base = dict(state="NC", county="Rutherford", listing_type="tax_lien", parcel_id="1654116",
                street=None, city=None, zip_code=None, mailing=None,
                hit={"address": "252 N WASHINGTON ST"}, tier="exact", cache_exists=True)
    assert F.plan_fill(**base)["status"] == "filled"
    assert F.plan_fill(**base, fallback_parcel=True)["status"] == "skip_fallback_point_parcel"
    row = {"state": "NC", "county": "Rutherford", "listing_type": "tax_lien", "parcel_id": "1654116",
           "raw": {"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.371,
                                       "lng": -81.957}}}
    assert F.plan_row(row)["status"] == "skip_fallback_point_parcel"

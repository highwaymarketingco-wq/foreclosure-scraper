"""Footprint area math, point-in-polygon, and the sqft-estimate enricher."""
from __future__ import annotations

import json

import pytest

from foreclosure_scraper import sc_building_footprints as fp
from foreclosure_scraper import enrichment_footprint_sqft as efs
from foreclosure_scraper.models import Listing, ListingType


def test_area_sqft_of_known_square():
    # ~100ft x ~100ft square near lat 34.94 -> ~10,000 sqft (within a few %).
    lat = 34.94
    dlat = 100 / fp._FT_PER_DEG_LAT
    import math
    dlon = 100 / (fp._FT_PER_DEG_LAT * math.cos(math.radians(lat)))
    ring = [[-81.9, lat], [-81.9 + dlon, lat], [-81.9 + dlon, lat + dlat],
            [-81.9, lat + dlat], [-81.9, lat]]
    area = fp._poly_area_sqft(ring, lat)
    assert 9500 < area < 10500


def test_point_in_ring():
    ring = [[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]
    assert fp._point_in_ring(1, 1, ring) is True
    assert fp._point_in_ring(3, 1, ring) is False


def _seed_fp(db, rows):
    fp.DB_PATH = db
    con = fp._connect()
    con.executemany("INSERT INTO footprints VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()


def _fprow(cx, cy, area, half=0.0003):
    ring = [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half],
            [cx - half, cy + half], [cx - half, cy - half]]
    return ("SC", "Spartanburg", cx, cy, cx - half, cy - half, cx + half, cy + half,
            area, json.dumps(ring))


def test_lookup_contains_and_nearest(tmp_path, monkeypatch):
    db = tmp_path / "fp.db"
    monkeypatch.setattr(fp, "DB_PATH", db)
    _seed_fp(db, [_fprow(-81.9, 34.94, 1600.0)])
    assert fp.has_data("SC", "Spartanburg") is True
    hit = fp.lookup_area("SC", "Spartanburg", -81.9, 34.94)  # inside the ring
    assert hit and hit[1] == "contains" and hit[0] == 1600.0
    # a point just outside the ring but within the ~75m pad -> nearest
    near = fp.lookup_area("SC", "Spartanburg", -81.9 + 0.0005, 34.94)
    assert near and near[1] == "nearest"
    assert fp.lookup_area("SC", "Spartanburg", -80.0, 33.0) is None


def test_largest_in_polygon_picks_biggest_inside(tmp_path, monkeypatch):
    db = tmp_path / "fp.db"
    monkeypatch.setattr(fp, "DB_PATH", db)
    # two footprints inside the parcel (house 1800, shed 200) + one outside (9999)
    _seed_fp(db, [_fprow(-81.9, 34.94, 1800.0), _fprow(-81.8999, 34.9401, 200.0),
                  _fprow(-81.95, 34.99, 9999.0)])
    parcel = [[-81.901, 34.939], [-81.898, 34.939], [-81.898, 34.941],
              [-81.901, 34.941], [-81.901, 34.939]]
    hit = fp.largest_in_polygon("SC", "Spartanburg", parcel)
    assert hit == (1800.0, "in_parcel")  # picks the house, ignores outside 9999


def test_enricher_in_parcel_path(tmp_path, monkeypatch):
    db = tmp_path / "fp.db"
    monkeypatch.setattr(fp, "DB_PATH", db)
    _seed_fp(db, [_fprow(-81.9, 34.94, 1500.0)])
    parcel = [[-81.901, 34.939], [-81.899, 34.939], [-81.899, 34.941],
              [-81.901, 34.941], [-81.901, 34.939]]
    monkeypatch.setattr(efs, "_scdot_parcel_ring", lambda *a, **k: parcel)
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Spartanburg", parcel_id="713320362391",
                 raw={"cama": {"story_height": 2.0}})
    out = efs.enrich_footprint_sqft([li])
    assert out["estimated"] == 1
    assert li.living_sqft == 2850  # 1500*2 - 1500*0.10
    assert li.living_sqft_estimated is True
    assert li.raw["footprint"]["match"] == "in_parcel"
    assert li.raw["footprint"]["band"] == "2500+"


def test_enricher_point_fallback_when_no_ring(tmp_path, monkeypatch):
    db = tmp_path / "fp.db"
    monkeypatch.setattr(fp, "DB_PATH", db)
    _seed_fp(db, [_fprow(-81.9, 34.94, 1500.0)])
    monkeypatch.setattr(efs, "_scdot_parcel_ring", lambda *a, **k: None)
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Spartanburg", parcel_id="713320362391",
                 longitude=-81.9, latitude=34.94, raw={"cama": {"story_height": 1.0}})
    efs.enrich_footprint_sqft([li])
    assert li.living_sqft_estimated is True
    assert li.raw["footprint"]["match"] == "contains"


def test_enricher_skips_when_true_sqft_present(tmp_path, monkeypatch):
    db = tmp_path / "fp.db"
    monkeypatch.setattr(fp, "DB_PATH", db)
    monkeypatch.setattr(efs, "_scdot_parcel_ring", lambda *a, **k: None)
    _seed_fp(db, [_fprow(-81.9, 34.94, 1500.0)])
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="SC", county="Spartanburg", parcel_id="713320362391",
                 longitude=-81.9, latitude=34.94, living_sqft=1800,
                 raw={"cama": {"story_height": 1.0}})
    efs.enrich_footprint_sqft([li])
    assert li.living_sqft == 1800 and li.living_sqft_estimated is False


def test_estimated_sqft_caps_arv_confidence():
    """A footprint-estimated sqft must cap the comp ARV to MEDIUM, never HIGH."""
    from foreclosure_scraper.valuation import calc
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="SC", county="Spartanburg", living_sqft=1500,
                 living_sqft_estimated=True,
                 raw={"comps": [{"price_per_sqft": 150, "adjusted_ppsf": 150, "geo_anchored": True},
                                {"price_per_sqft": 150, "adjusted_ppsf": 150, "geo_anchored": True},
                                {"price_per_sqft": 150, "adjusted_ppsf": 150, "geo_anchored": True}],
                      "comp_median_ppsf": 150})
    _exp, _lo, _hi, conf, notes = calc._arv_signals(li)
    assert conf == "MEDIUM"
    assert any("ESTIMATE" in n for n in notes)

"""counties_sc.sc_heir_estate_parcel_cache -- pure-local heir/estate signal read
directly from parcel_cache SQLite files (no network).

Hermetic: builds tiny real SQLite fixtures using parcel_cache's own PARCELS_DDL (the
exact schema the real cache files use), monkeypatches parcel_cache._db_path to point
at them, and never touches a real cache file or the network.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from foreclosure_scraper import parcel_cache as pc
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_sc import sc_heir_estate_parcel_cache as m


def _make_cache(tmp_path, county: str, rows: list[dict]):
    """Write a real parcel_cache SQLite file for `county` at a temp path, in the
    exact PARCELS_DDL shape, and monkeypatch `_db_path` to serve it for ("SC",)."""
    path = tmp_path / f"{county.lower()}.sqlite"
    con = sqlite3.connect(path)
    con.execute(pc.PARCELS_DDL)
    for r in rows:
        vals = [r.get("id")] + [r.get(c) for c in pc._COLS]
        con.execute(f"INSERT INTO parcels VALUES({','.join('?' * len(vals))})", vals)
    con.commit()
    con.close()
    return path


@pytest.fixture
def fake_county(tmp_path, monkeypatch):
    rows = [
        # Two id-variants of the SAME physical parcel (same owner/address/value) --
        # must collapse to exactly one Listing.
        dict(id="100-01-01", owner="SMITH JOHN HEIRS", address="1 MAIN ST",
             owner_mailing="PO BOX 1, COLUMBIA, SC", acreage=1.0, market_value=50000.0,
             tax_value=40000.0, land_use="101"),
        dict(id="1000101000000", owner="SMITH JOHN HEIRS", address="1 MAIN ST",
             owner_mailing="PO BOX 1, COLUMBIA, SC", acreage=1.0, market_value=50000.0,
             tax_value=40000.0, land_use="101"),
        # A genuinely distinct second parcel, same owner, real "ESTATE OF" lead.
        dict(id="200-02-02", owner="ESTATE OF JANE DOE", address="2 OAK ST",
             owner_mailing=None, acreage=2.0, market_value=90000.0, tax_value=70000.0,
             land_use="101"),
        # Noise this classifier must drop: LIFE ESTATE (space) and LIFE-ESTATE
        # (hyphen, the 2026-10-19 Greenville finding).
        dict(id="300-03-03", owner="JONES MARY LIFE ESTATE", address="3 ELM ST",
             owner_mailing=None, acreage=1.5, market_value=60000.0, tax_value=50000.0,
             land_use="101"),
        dict(id="400-04-04", owner="CLARK LOTTIE B (LIFE-ESTATE)", address="4 PINE ST",
             owner_mailing=None, acreage=1.0, market_value=70000.0, tax_value=55000.0,
             land_use="101"),
        # Noise: a brokerage name containing ESTATE, correctly excluded.
        dict(id="500-05-05", owner="ACME REAL ESTATE HOLDINGS LLC", address="5 BIRCH ST",
             owner_mailing=None, acreage=5.0, market_value=500000.0, tax_value=400000.0,
             land_use="300"),
        # A normal, non-decedent owner: must never surface.
        dict(id="600-06-06", owner="BROWN ROBERT", address="6 ASH ST",
             owner_mailing=None, acreage=1.0, market_value=80000.0, tax_value=65000.0,
             land_use="101"),
    ]
    path = _make_cache(tmp_path, "FakeCounty", rows)

    real_db_path = pc._db_path

    def fake_db_path(county, state=None):
        if county == "FakeCounty":
            return path
        return real_db_path(county, state)

    monkeypatch.setattr(pc, "_db_path", fake_db_path)
    monkeypatch.setattr(
        m, "_candidate_counties", lambda: ("FakeCounty",))
    monkeypatch.setattr(
        pc, "resolve_layer_cfg",
        lambda county, state=None: {"url": "https://example.test/query"}
        if county == "FakeCounty" else None)
    return path


def test_county_rows_dedupes_id_variants_to_one_physical_parcel(fake_county):
    rows = m._county_rows("FakeCounty")
    smith_rows = [r for r in rows if r["owner"] == "SMITH JOHN HEIRS"]
    assert len(smith_rows) == 1, "two id-variants of the same parcel must collapse to one row"


def test_county_rows_picks_the_shorter_id_variant(fake_county):
    rows = m._county_rows("FakeCounty")
    smith = next(r for r in rows if r["owner"] == "SMITH JOHN HEIRS")
    assert smith["_id"] == "100-01-01"


def test_fetch_keeps_real_decedent_rows_and_drops_noise(fake_county):
    s = m.SCHeirEstateParcelCache()
    s.partial = []
    rows = asyncio.run(s.fetch())
    owners = {li.defendant for li in rows}
    assert owners == {"SMITH JOHN HEIRS", "ESTATE OF JANE DOE"}
    for li in rows:
        assert li.listing_type == ListingType.ESTATE_LEAD
        assert li.state == "SC"
        assert li.raw["heir_estate"]["owner_of_record"] == li.defendant
        assert li.raw["relationship_signal"]["kind"] == "probate"
        assert li.source == m.SCHeirEstateParcelCache.slug


def test_fetch_sets_parcel_id_from_the_deduped_id(fake_county):
    s = m.SCHeirEstateParcelCache()
    s.partial = []
    rows = asyncio.run(s.fetch())
    smith = next(li for li in rows if li.defendant == "SMITH JOHN HEIRS")
    assert smith.parcel_id == "100-01-01"


def test_fetch_run_stats_count_rows_and_county(fake_county):
    s = m.SCHeirEstateParcelCache()
    s.partial = []
    asyncio.run(s.fetch())
    assert s.run_stats["counties"] == 1
    assert s.run_stats["kept"] == 2
    assert s.run_stats["rows_read"] == 6  # 7 raw rows, 1 collapsed id-variant


def test_missing_cache_file_is_a_silent_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "_candidate_counties", lambda: ("NoSuchCounty",))
    assert m._county_rows("NoSuchCounty") == []


def test_already_live_covered_counties_are_never_candidates():
    """York/Charleston/Beaufort stay on the live nc_heir_estate_parcels.py producer --
    never double-sourced from parcel_cache too."""
    candidates = m._candidate_counties()
    assert "York" not in candidates
    assert "Charleston" not in candidates
    assert "Beaufort" not in candidates


def test_candidate_counties_only_includes_sc_layers_with_an_owner_field():
    candidates = m._candidate_counties()
    assert "Horry" in candidates       # real county this module targets
    assert len(candidates) >= 15       # the 2026-10-19 live sample found 18 total

"""2026-10-07: parcel-cache fact columns, migration on read, the county-roll sidecar, and the
cache join that enrich_gis_attrs now runs over every row before its live loop.

Hand-written fixtures; every name, street and id is made up.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from foreclosure_scraper import parcel_cache as pc
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.parcel_cache_join import join_listings, mail_state

OLD_DDL = ("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, "
           "market_value REAL, tax_value REAL, acreage REAL, living_sqft REAL, "
           "land_use TEXT, sale_price REAL, sale_date TEXT)")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    pc._CONN_COLS.clear()
    yield
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    pc._CONN_COLS.clear()


def _old_cache(path, rows):
    con = sqlite3.connect(path)
    con.execute(OLD_DDL)
    con.executemany("INSERT INTO parcels(id, owner, address, owner_mailing, market_value) "
                    "VALUES(?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _new_cache(path, rows, *, roll=False):
    con = sqlite3.connect(path)
    con.execute(pc.PARCELS_DDL)
    if roll:
        pc.ensure_columns(con, extra=pc.ROLL_PROV_COLS)
    cols = ["id", *pc._COLS] + (list(pc.ROLL_PROV_COLS) if roll else [])
    for r in rows:
        con.execute(f"INSERT INTO parcels({','.join(r)}) VALUES({','.join('?' * len(r))})",
                    tuple(r.values()))
    con.commit()
    con.close()
    return cols


def L(pid, county="Gaston", state="NC", **kw):
    return Listing(source="t", source_url="https://example.invalid/x", county=county, state=state,
                   parcel_id=pid, street_address=kw.pop("street", "10 FAKE ST"), **kw)


# ---------------------------------------------------------------- schema

def test_ddl_carries_every_column_with_types():
    for c in ("year_built", "bedrooms", "bathrooms", "stories"):
        assert c in pc._COLS and f"{c} REAL" in pc.PARCELS_DDL
    assert "sale_price REAL" in pc.PARCELS_DDL and "sale_date TEXT" in pc.PARCELS_DDL


def test_baths_spec_counts_half_baths_as_half():
    spec = {"baths": ["FULL", "HALF"]}
    assert pc._map_val({"FULL": 2, "HALF": 1}, "bathrooms", spec) == 2.5
    assert pc._map_val({"FULL": 2, "HALF": None}, "bathrooms", spec) == 2.0
    assert pc._map_val({"FULL": 0, "HALF": 1}, "bathrooms", spec) is None
    assert set(pc._src_fields(["PIN"], {"bathrooms": spec}).split(",")) == {"PIN", "FULL", "HALF"}


def test_fact_maps_are_merged_without_replacing_existing_mappings():
    g = pc.PARCEL_LAYERS["Gaston"]["map"]
    assert g["year_built"] == "YEARBLT" and g["bedrooms"] == "XBEDRM"
    assert g["owner"] == "CURR_NAME1"                       # untouched
    assert pc.nc_onemap_cfg("Wake")["map"]["year_built"] == "structyear"
    sp = pc.PARCEL_LAYERS["Spartanburg"]["map"]
    assert sp["sale_price"] == "SaleAmount"                 # setdefault kept the old one


def test_dorchester_is_configured_with_its_licence_note():
    cfg = pc.resolve_layer_cfg("Dorchester")
    assert cfg["state"] == "SC" and cfg["id_fields"][0] == "FULL_TMS"
    assert cfg["map"]["owner_mailing"] == ["MAILING_ADDRESS", "CITY_STATE_ZIP"]
    src = open(pc.__file__).read()
    assert "not to be added to any\n#: pay for use locations" in src


# ---------------------------------------------------------------- migration on read

def test_old_schema_cache_still_answers(tmp_path):
    _old_cache(tmp_path / "gaston.sqlite", [("1234567890", "DOE JANE", "10 FAKE ST",
                                             "PO BOX 1 SOMEWHERE NC 28000", 90000.0)])
    hit = pc.lookup("Gaston", "1234567890", "NC")
    assert hit["owner"] == "DOE JANE" and "year_built" not in hit


def test_ensure_columns_adds_missing_columns_in_place(tmp_path):
    p = tmp_path / "gaston.sqlite"
    _old_cache(p, [("1", "A", "B", None, None)])
    con = sqlite3.connect(p)
    added = pc.ensure_columns(con)
    con.commit(); con.close()
    assert set(added) == {"year_built", "bedrooms", "bathrooms", "stories"}
    con = sqlite3.connect(p)
    assert pc.ensure_columns(con) == []                    # idempotent
    con.close()
    assert pc.lookup("Gaston", "1", "NC")["owner"] == "A"


# ---------------------------------------------------------------- roll sidecar

def _roll(tmp_path, county="perquimans", rows=(), date=None):
    date = date or datetime.now(timezone.utc).date().isoformat()
    p = tmp_path / f"{county}.roll.sqlite"
    con = sqlite3.connect(p)
    con.execute(pc.PARCELS_DDL)
    pc.ensure_columns(con, extra=pc.ROLL_PROV_COLS)
    for r in rows:
        r = {**r, "prov": pc.ROLL_PROVENANCE, "prov_date": date}
        con.execute(f"INSERT INTO parcels({','.join(r)}) VALUES({','.join('?' * len(r))})",
                    tuple(r.values()))
    con.commit(); con.close()
    return p


def test_roll_alone_answers_and_names_its_provenance(tmp_path):
    assert pc.roll_db_path("Perquimans").name == "perquimans.roll.sqlite"
    _roll(tmp_path, rows=[{"id": "7890001234", "owner": "ROE RICHARD",
                           "owner_mailing": "9 ELSEWHERE LN NORFOLK VA 23501",
                           "market_value": 55000.0, "year_built": 1950.0}])
    hit, tier = pc.lookup_with_tier("Perquimans", "7890-001-234", "NC")
    assert hit["owner_mailing"].endswith("VA 23501") and hit["year_built"] == 1950.0
    assert hit["roll_prov"] == "county_roll_request" and "owner_mailing" in hit["roll_fields"]
    assert tier == "roll_exact"


def test_roll_fills_only_what_the_layer_lacks(tmp_path):
    _new_cache(tmp_path / "perquimans.sqlite", [{"id": "55", "owner": "LAYER OWNER",
                                                  "market_value": 1.0}])
    _roll(tmp_path, rows=[{"id": "55", "owner": "ROLL OWNER", "owner_mailing": "1 A ST X NC 27000",
                           "bedrooms": 3.0}])
    hit = pc.lookup("Perquimans", "55", "NC")
    assert hit["owner"] == "LAYER OWNER"                   # the layer wins
    assert hit["owner_mailing"] == "1 A ST X NC 27000" and hit["bedrooms"] == 3.0
    assert set(hit["roll_fields"]) == {"owner_mailing", "bedrooms"}


def test_an_old_roll_keeps_mailing_but_drops_values(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=900)).date().isoformat()
    _roll(tmp_path, rows=[{"id": "77", "owner_mailing": "1 A ST X NC 27000",
                           "market_value": 9.0}], date=old)
    hit = pc.lookup("Perquimans", "77", "NC")
    assert "market_value" not in hit and hit["owner_mailing"]


# ---------------------------------------------------------------- the join

def test_join_fills_canonical_mailing_and_facts(tmp_path, monkeypatch):
    hit = {"owner": "DOE JANE", "address": "10 FAKE ST", "owner_mailing": "PO BOX 1 RALEIGH NC 27601",
           "market_value": 90000.0, "year_built": 1961.0, "bedrooms": 3.0, "bathrooms": 1.5,
           "stories": 1.0, "sale_price": 40000.0, "sale_date": "2001-02-03"}
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: dict(hit))
    li = L("1234567890")
    c = join_listings([li])
    om = li.raw["owner_mailing"]
    assert om["mailing"] == hit["owner_mailing"] and om["absentee"] is True and om["mail_state"] == "NC"
    assert li.raw["gis"]["mailing"] == hit["owner_mailing"]
    assert (li.year_built, li.bedrooms, li.bathrooms) == (1961, 3.0, 1.5)
    assert li.raw["gis"]["last_sale"] == {"amount": 40000.0, "date": "2001-02-03"}
    assert c["filled owner mailing"] == 1 and c["filled year built"] == 1


def test_join_is_fill_only_and_withholds_a_differing_owners_mailing(monkeypatch):
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"owner_mailing": "X", "year_built": 1999.0})
    li = L("1", year_built=1950)
    li.raw = {"parcel_from_address": {"owner_agrees": False}}
    c = join_listings([li])
    assert li.year_built == 1950 and "owner_mailing" not in li.raw
    assert c["mailing withheld: parcel owner differs from the lead's party"] == 1


def test_join_skips_overage_rows_and_rows_without_ids(monkeypatch):
    called = []
    monkeypatch.setattr(pc, "lookup", lambda *a: called.append(a) or {"owner_mailing": "X"})
    ov = L("1", listing_type=ListingType.TAX_SALE_OVERAGE)
    c = join_listings([ov, L(None)])
    assert not called and c["no parcel_id"] == 1


def test_mail_state():
    assert mail_state("250 SAMPLE CT SUMTER SC 29150") == "SC"
    assert mail_state("nowhere") is None


def test_gis_attrs_runs_the_join_before_its_skip_gates(monkeypatch):
    """A row a prior run marked raw['gis']['queried'] used to return before the cache lookup."""
    import foreclosure_scraper.enrichment_gis_attrs as G
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"owner_mailing": "1 MAIL RD X NC 28000"})
    monkeypatch.setattr(G, "_load_cache", lambda: None)
    monkeypatch.setattr(G, "_save_cache", lambda: None)
    li = L("1234567890", market_value=1.0, owner_name="DOE JANE", living_sqft=900.0)
    li.raw = {"gis": {"queried": True}}
    stats = asyncio.run(G.enrich_gis_attrs([li]))
    assert li.raw["owner_mailing"]["mailing"] == "1 MAIL RD X NC 28000"
    assert stats["cache_join"]["filled owner mailing"] == 1


def test_gis_attrs_join_can_be_switched_off(monkeypatch):
    import foreclosure_scraper.enrichment_gis_attrs as G
    monkeypatch.setenv("FORECLOSURE_CACHE_JOIN", "0")
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"owner_mailing": "1 MAIL RD X NC 28000"})
    monkeypatch.setattr(G, "_load_cache", lambda: None)
    monkeypatch.setattr(G, "_save_cache", lambda: None)
    li = L("1", market_value=1.0, owner_name="DOE", living_sqft=900.0)
    li.raw = {"gis": {"queried": True}}
    asyncio.run(G.enrich_gis_attrs([li]))
    assert "owner_mailing" not in li.raw

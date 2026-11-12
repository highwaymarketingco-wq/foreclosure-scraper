"""SC Assessor CAMA value+specs ingest, lookup, and the backfill enricher."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper import sc_assessor_cama as cama
from foreclosure_scraper.enrichment_sc_cama import enrich_sc_cama
from foreclosure_scraper.models import Listing, ListingType


def test_norm_helpers():
    assert cama._norm_tms("7133-20-3623.91") == "713320362391"
    assert cama.norm_addr("1101 Partridge Road") == "1101 PARTRIDGE RD"
    assert cama.norm_addr("712 Rutledge St.") == "712 RUTLEDGE ST"


def _seed(db, rows):
    cama.DB_PATH = db
    con = cama._connect()
    con.executemany("INSERT OR REPLACE INTO sc_cama VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()


def _row(tms, mapnum, addr, val, yr, beds, baths, cond, distressed, story=1.0):
    return ("SC", "Spartanburg", tms, cama._norm_tms(mapnum), cama.norm_addr(addr), val, yr, beds, baths,
            cond, distressed, "B", "SINGLE FAM", "2016-11-08", addr, story, datetime.utcnow().isoformat())


def test_lookup_by_tms_map_and_address(tmp_path, monkeypatch):
    db = tmp_path / "cama.db"
    monkeypatch.setattr(cama, "DB_PATH", db)
    _seed(db, [_row("713320362391", "7-17-02-041.00", "1101 PARTRIDGE RD", 384600, 1956, 4, 3.0, "GD", 0)])
    assert cama.has_data("SC", "Spartanburg") is True
    assert cama.lookup("SC", "Spartanburg", parcel_id="7133-20-3623.91")["market_value"] == 384600
    assert cama.lookup("SC", "Spartanburg", parcel_id="7-17-02-041.00")["year_built"] == 1956  # map_digits
    assert cama.lookup("SC", "Spartanburg", street_address="1101 Partridge Road")["beds"] == 4
    assert cama.lookup("SC", "Spartanburg", parcel_id="999") is None


def test_enricher_backfills_value_specs_and_condition(tmp_path, monkeypatch):
    db = tmp_path / "cama.db"
    monkeypatch.setattr(cama, "DB_PATH", db)
    _seed(db, [_row("713320362391", "7-17-02-041.00", "1101 PARTRIDGE RD", 384600, 1956, 4, 3.0, "PR", 1)])
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                 state="SC", county="Spartanburg", parcel_id="7133-20-3623.91")
    out = enrich_sc_cama([li])
    assert out["matched"] == 1
    assert li.market_value == 384600 and li.year_built == 1956
    assert li.bedrooms == 4 and li.bathrooms == 3.0
    assert li.raw["cama"]["condition_code"] == "PR" and li.raw["cama"]["source"] == "sc_assessor_csv"
    assert li.raw["distressed"] is True   # poor condition -> distress signal


def test_enricher_does_not_overwrite_existing(tmp_path, monkeypatch):
    db = tmp_path / "cama.db"
    monkeypatch.setattr(cama, "DB_PATH", db)
    _seed(db, [_row("713320362391", "7-17-02-041.00", "1101 PARTRIDGE RD", 384600, 1956, 4, 3.0, "GD", 0)])
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="SC",
                 county="Spartanburg", parcel_id="7133-20-3623.91",
                 market_value=500000, year_built=2001)
    enrich_sc_cama([li])
    assert li.market_value == 500000 and li.year_built == 2001  # preserved
    assert li.bedrooms == 4   # was missing -> filled


def test_enricher_skips_other_counties(tmp_path, monkeypatch):
    db = tmp_path / "cama.db"
    monkeypatch.setattr(cama, "DB_PATH", db)
    _seed(db, [_row("1", "0001", "1 A ST", 100000, 1990, 3, 2.0, "GD", 0)])
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                 county="Gaston", parcel_id="1")
    assert enrich_sc_cama([li])["matched"] == 0

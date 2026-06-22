"""Bulk parcel-inventory: layer map, per-feature extraction, cache lookup."""
from __future__ import annotations

from foreclosure_scraper import parcel_inventory as pi


def test_layers_cover_all_18_counties():
    L = pi._layers()
    assert len(L) == 18
    # the two SCDOT-backed special cases are present
    assert L[("SC", "Anderson")].get("scdot") is True
    assert L[("SC", "Cherokee")].get("scdot") is True
    assert ("NC", "Polk") in L and ("SC", "Spartanburg") in L


def test_extract_from_county_gis_spec():
    spec = {"parcel": "PIN", "owner": ["OwnerName"], "situs": ["SitusAddr"],
            "mail": ["Mail1", "City"]}
    attrs = {"PIN": "123-45", "OwnerName": "DOE JANE", "SitusAddr": "1 MAIN ST",
             "Mail1": "PO BOX 9", "City": "TOWN", "AppraisedValue": 250000}
    e = pi._extract(attrs, spec)
    assert e["parcel_id"] == "123-45"
    assert e["owner"] == "DOE JANE"
    assert e["situs"] == "1 MAIN ST"
    assert e["value"] == 250000


def test_extract_from_scdot_via_aliases():
    spec = {"url": "x", "parcel": None, "owner": None, "situs": None, "scdot": True}
    attrs = {"parno": "1000001001", "ownname": "SMITH JOHN", "siteadd": "5 OAK"}
    e = pi._extract(attrs, spec)
    assert e["parcel_id"] == "1000001001"
    assert e["owner"] == "SMITH JOHN"
    assert e["situs"] == "5 OAK"


def test_lookup_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(pi, "DB_PATH", tmp_path / "pi.db")
    con = pi._connect()
    con.execute("INSERT OR REPLACE INTO parcels VALUES (?,?,?,?,?,?,?,?)",
                ("NC", "Polk", "P1", "DOE JANE", "1 MAIN ST", "PO 9", 100.0, "now"))
    con.commit()
    con.close()
    hit = pi.lookup_parcel("NC", "Polk", "P1")
    assert hit and hit["owner"] == "DOE JANE" and hit["situs"] == "1 MAIN ST"
    assert pi.lookup_parcel("NC", "Polk", "NOPE") is None
    assert pi.inventory_stats().get("NC:Polk") == 1

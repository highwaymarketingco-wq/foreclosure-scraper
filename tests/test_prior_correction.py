"""enrichment_prior_correction: the in-run correction of carried board data (docs/HANDOFF.md item 71).

Row shapes are real board rows of 2026-10-06 (the sources, raw blocks, provenance stamps and
fallback points the replay found), pseudonymized: owner names, street words and parcel ids are
replaced; county seats, sources, stamps and field layouts are kept.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper import enrichment_prior_correction as pc
from foreclosure_scraper.enrichment_geocode import COUNTY_SEAT_CENTROIDS
from foreclosure_scraper.models import Listing

ANDERSON_SEAT = COUNTY_SEAT_CENTROIDS[("SC", "Anderson")]
RUTHERFORD_SEAT = COUNTY_SEAT_CENTROIDS[("NC", "Rutherford")]
TOWN_CENTRE = (35.47371, -81.21983)        # a geocoder town centroid: not a county seat


def _li(**kw) -> Listing:
    base = {"source": "counties_nc.rutherford_tax", "source_url": "https://example.test/x", "state": "NC",
            "county": "Rutherford"}
    base.update(kw)
    return Listing(**base)


class FakeCache(pc.CacheReader):
    """parcel_cache stand-in: {(county, pid): row}; counties not in `have` have no cache file."""

    def __init__(self, rows: dict, have=("Rutherford", "Anderson", "Buncombe", "Transylvania", "Spartanburg",
                                         "Lincoln")):
        self.rows = rows
        super().__init__(lookup=self._fake_lookup, available=lambda c, s: c in have)

    def _fake_lookup(self, county, pid, state):
        hit = self.rows.get((county, str(pid)))
        return (dict(hit), "exact") if hit else (None, None)


def _seat_row(pid="5550001111", **kw) -> Listing:
    lat, lng = RUTHERFORD_SEAT
    raw = {"parcel_from_geo": {"source": "nc_onemap_point", "lat": lat, "lng": lng},
           "geo_imprecise": "centroid_snap",
           "rutherford_tax": {"parcel": "400001", "owner": "DOE, JANE Q"},
           "gis_attrs_full": {"parno": pid, "cntyname": "Rutherford", "ownname": "EXAMPLE CHURCH INC",
                              "siteadd": "250 N SAMPLE ST", "scity": "RUTHERFORDTON", "szip": "28139",
                              "parval": 1250400, "gisacres": 3.41},
           "owner_mailing": {"owner": "EXAMPLE CHURCH INC", "mailing": "PO BOX 9 RUTHERFORDTON NC 28139",
                             "situs": "250 N SAMPLE ST", "parcel_id": pid, "source": "county_gis"}}
    raw.update(kw.pop("raw", {}))
    return _li(parcel_id=pid, latitude=lat, longitude=lng, owner_name="DOE, JANE Q", raw=raw, **kw)


# ------------------------------------------------------------------------- 1. fallback points
def test_county_seat_parcel_withdrawn_with_what_was_copied_from_it():
    li = _seat_row(market_value=1250400.0, acreage=3.41, living_sqft=1161.0)
    a = pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({}))
    assert a["reason"] == "county_seat_point" and a["parcel_id"] == "5550001111"
    assert li.parcel_id is None
    # the parcel's own value and acreage go; the source's owner and a size the parcel never had stay
    assert li.market_value is None and li.acreage is None
    assert li.owner_name == "DOE, JANE Q" and li.living_sqft == 1161.0
    assert "gis_attrs_full" not in li.raw and "owner_mailing" not in li.raw and "parcel_from_geo" not in li.raw
    assert li.raw["rutherford_tax"]["parcel"] == "400001"           # the source's block is never touched
    audit = li.raw[pc.FALLBACK_KEY]
    assert audit["cleared"] == {"market_value": 1250400.0, "acreage": 3.41}
    assert set(audit["raw_removed"]) == {"gis_attrs_full", "owner_mailing"}
    assert audit["parcel_from_geo"]["source"] == "nc_onemap_point"


def test_copied_situs_and_values_of_a_seat_parcel_are_cleared_by_the_cache_record():
    # sc_public_index (Anderson): the street and three values were copied from the county-seat
    # parcel (a county office building); the row's defendant name is the source's own
    lat, lng = ANDERSON_SEAT
    li = _li(source="counties_sc.sc_public_index", state="SC", county="Anderson", parcel_id="7770002222",
             latitude=lat, longitude=lng, street_address="105 S SAMPLE ST", owner_name="Roe  Richard",
             market_value=5100000.0, tax_value=5100000.0, assessed_value=5100000.0,
             raw={"parcel_from_geo": {"source": "native_point:Anderson", "lat": lat, "lng": lng},
                  "situs_address_source": "parcel_cache:exact", "geo_imprecise": "centroid_snap",
                  "owner_mailing": {"owner": "ANDERSON COUNTY", "mailing": "PO BOX 1000, ANDERSON SC, 29621",
                                    "situs": "105 S SAMPLE ST", "parcel_id": "7770002222", "source": "sc_assessor_roll"}})
    cache = FakeCache({("Anderson", "7770002222"): {"owner": "ANDERSON COUNTY", "address": "105 S SAMPLE ST",
                                                    "owner_mailing": "PO BOX 1000 ANDERSON SC 29621",
                                                    "market_value": 5100000.0}})
    a = pc.withdraw_fallback_parcel(li, pc.Counter(), 8, cache)
    assert a and li.parcel_id is None
    assert li.street_address is None and "situs_address_source" not in li.raw
    assert li.market_value is li.tax_value is li.assessed_value is None
    assert li.owner_name == "Roe  Richard"
    assert a["cleared"]["street_address"] == "105 S SAMPLE ST"
    assert a["cleared"]["situs_address_source"] == "parcel_cache:exact"


def test_shared_point_needs_eight_rows():
    def row(i, street=None):
        return _li(source="counties_nc.lincoln_vacant", county="Lincoln", parcel_id="3600000001",
                   latitude=TOWN_CENTRE[0], longitude=TOWN_CENTRE[1], street_address=street,
                   raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": TOWN_CENTRE[0], "lng": TOWN_CENTRE[1]},
                        "lincoln_vacant": {"PARCELID": str(10000 + i), "PIN": f"26000000{i:02d}"}})
    rows = [row(i, None if i % 2 else f"{100 + i} SAMPLE FARM RD") for i in range(8)]
    stats = pc.correct_prior_rows(list(rows), cache=FakeCache({}))
    assert stats["fallback_by_reason"] == {"shared_point": 8}
    assert all(r.parcel_id is None for r in rows)
    seven = [row(i) for i in range(7)]
    stats = pc.correct_prior_rows(seven, cache=FakeCache({}))
    assert stats["fallback_withdrawn"] == 0 and all(r.parcel_id == "3600000001" for r in seven)


def test_parcel_the_source_names_is_kept():
    # nc_dam_safety writes the dam's NID id as parcel_id; an older copy carried a resolver stamp
    li = _seat_row(pid="NC09999", source="counties_generic.state_contamination.nc_dam_safety",
                   raw={"state_contamination": {"registry": "nc_dam_safety", "NID_ID": "NC09999"}})
    assert pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({})) == {"exempt": "source_parcel"}
    assert li.parcel_id == "NC09999" and "gis_attrs_full" in li.raw


def test_own_street_at_the_parcel_situs_keeps_it():
    # a condo unit at its master parcel's address, geocoded to a point many units share
    li = _seat_row(street_address="250 N SAMPLE ST UNIT 4")
    assert pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({})) == {"exempt": "own_street_is_parcel_situs"}
    assert li.parcel_id == "5550001111"


def test_id_swap_and_address_stamps_are_not_point_attachments():
    li = _seat_row(raw={"parcel_from_geo": {"source": "ptscloud_pts_to_pin", "verified": "owner_name_agrees",
                                            "pts_number": "9900001"}})
    assert pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({})) is None
    li = _seat_row(raw={"parcel_from_geo": {"source": "burke_cache_situs_address", "verified": "address_exact"}})
    assert pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({})) is None


def test_stale_imprecise_flag_on_a_measured_point_is_not_a_fallback():
    lat, lng = 35.512345678901, -81.351234567890        # a code-violation layer's own point, unique
    li = _li(source="counties_generic.arcgis_distress.lincoln_code_violations", county="Lincoln",
             parcel_id="2695800000", latitude=lat, longitude=lng, street_address="1200 SAMPLE HILL RD",
             raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": lat, "lng": lng},
                  "geo_imprecise": "centroid_snap"})
    stats = pc.correct_prior_rows([li], cache=FakeCache({}))
    assert stats["fallback_withdrawn"] == 0 and li.parcel_id == "2695800000"


def test_photo_and_cluster_entries_of_the_parcel_go():
    li = _seat_row(raw={"images": {"real": ["parcel_photos/rutherford_5550001111.jpg"],
                                   "primary": "parcel_photos/rutherford_5550001111.jpg"},
                        "zillow": {"photo": "parcel_photos/rutherford_5550001111.jpg"},
                        "owner_cluster": {"cluster_id": "DOE|JANE|RUTHERFORD|NC", "cluster_size": 3,
                                          "parcel_ids": ["1600000002", "5550001111"]},
                        "gis": {"owner": "EXAMPLE CHURCH INC", "mailing": "PO BOX 9 RUTHERFORDTON NC 28139",
                                "zoning_src": "county"}})
    a = pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({}))
    assert "images" not in li.raw and "zillow" not in li.raw
    assert li.raw["owner_cluster"]["parcel_ids"] == ["1600000002"]
    assert li.raw["gis"] == {"zoning_src": "county"}
    assert {"images", "zillow", "owner_cluster.parcel_ids", "gis.owner", "gis.mailing"} <= set(a["raw_removed"])


def test_resolver_does_not_reattach_at_the_same_point():
    from foreclosure_scraper.enrichment_parcel_from_geo import _withdrawn
    li = _seat_row()
    pc.withdraw_fallback_parcel(li, pc.Counter(), 8, FakeCache({}))
    assert _withdrawn(li)
    li.latitude, li.longitude = 35.36001234, -81.95998765        # a real point later: may resolve
    assert not _withdrawn(li)


# -------------------------------------------------------------- 2. owner mailing as the address
BUNCOMBE = {("Buncombe", "9686540826"): {"owner": "DOE JOHN", "address": "40 SAMPLE RIDGE RD",
                                         "owner_mailing": "18 SAMPLE RIDGE RD FAIRVIEW NC 28730"},
            ("Buncombe", "9634707498"): {"owner": "ROE MARY", "address": "38 EXAMPLE LN",
                                         "owner_mailing": "38 EXAMPLE LN ARDEN NC 28704"},
            ("Transylvania", "8597705450"): {"owner": "ROE RICHARD", "address": "U32 L053 SAMPLE CT",
                                             "owner_mailing": "17 Example Ct Sampleton NV 89000"},
            ("Spartanburg", "6120000100"): {"owner": "DOE JANE", "address": "S SAMPLE ST EXT SPARTANBURG",
                                            "owner_mailing": "77 HARBOR VIEW CT MOORE SC 29369"},
            ("Lincoln", "3600000777"): {"owner": "ROE JOHN", "address": None,
                                        "owner_mailing": "316 EXAMPLE DR LINCOLNTON NC 28092"}}


def _unpaid(pid="9686540826", street="18 SAMPLE RIDGE RD", **kw) -> Listing:
    base = {"source": "counties_generic.arcgis_distress.buncombe_unpaid_bills", "county": "Buncombe",
            "parcel_id": pid, "street_address": street, "city": "FAIRVIEW", "zip_code": "28730"}
    base.update(kw)
    return _li(**base)


def test_mailing_on_the_same_street_is_replaced_by_the_situs():
    li = _unpaid(raw={})
    a = pc.restore_situs(li, FakeCache(BUNCOMBE))
    assert a["class"] == "likely"
    assert (li.street_address, li.city, li.zip_code) == ("40 SAMPLE RIDGE RD", None, None)
    assert li.raw["situs_address_source"] == "parcel_cache:exact"
    assert li.raw[pc.MAILING_KEY]["street_address"] == "18 SAMPLE RIDGE RD"
    assert li.raw[pc.MAILING_KEY]["city"] == "FAIRVIEW"


def test_out_of_state_mailing_with_no_numbered_situs_is_nulled():
    # transylvania_delinquent_tax: the bill shows only the owner's (out-of-state) mailing address
    li = _li(source="counties_nc.transylvania_delinquent_tax", county="Transylvania", parcel_id="8597705450",
             street_address="17 Example Ct", city="Sampleton", zip_code="89000")
    a = pc.restore_situs(li, FakeCache(BUNCOMBE))
    assert a["class"] == "definite" and a["nulled"] == "situs_without_house_number"
    assert li.street_address is None and li.city is None and li.zip_code is None
    assert "situs_address_source" not in li.raw


def test_mailing_on_another_street_is_definite_even_when_stamped_as_a_parcel_situs():
    # spartanburg_vacant: gis_attrs wrote the mailing street and stamped it gis_parcel_situs
    li = _li(source="counties_sc.spartanburg_vacant", state="SC", county="Spartanburg", parcel_id="6120000100",
             street_address="77 HARBOR VIEW CT", city="Spartanburg", zip_code="29306",
             raw={"situs_address_source": "gis_parcel_situs"})
    a = pc.restore_situs(li, FakeCache(BUNCOMBE))
    assert a["class"] == "definite" and li.street_address is None
    assert a["situs_address_source"] == "gis_parcel_situs"


def test_owner_occupied_unverifiable_and_found_from_street_rows_are_left():
    cache = FakeCache(BUNCOMBE)
    occ = _li(source="counties_nc.buncombe_elderly", county="Buncombe", parcel_id="9634707498",
              street_address="38 EXAMPLE LN", city="Arden")
    assert pc.restore_situs(occ, cache) is None and occ.street_address == "38 EXAMPLE LN"
    unv = _li(source="counties_nc.nc_county_pdf_delinquent_tax", county="Lincoln", parcel_id="3600000777",
              street_address="316 EXAMPLE DR")
    assert pc.restore_situs(unv, cache) is None and unv.street_address == "316 EXAMPLE DR"
    # hud_reac_inspection: HUD's own property address; the parcel came from its geocoded point
    hud = _unpaid(source="national.hud_reac_inspection",
                  raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.6, "lng": -82.5}})
    assert pc.restore_situs(hud, cache) == {"skip": "parcel_found_from_street"}
    assert hud.street_address == "18 SAMPLE RIDGE RD"


def test_county_without_a_cache_is_skipped_and_reported():
    cache = FakeCache(BUNCOMBE, have=())
    li = _unpaid()
    assert pc.restore_situs(li, cache) == {"skip": "no_cache"}
    assert li.street_address == "18 SAMPLE RIDGE RD"
    stats = pc.correct_prior_rows([_unpaid()], cache=FakeCache(BUNCOMBE, have=()))
    assert stats["mailing_corrected"] == 0 and stats["cache_missing_counties"] == {"NC|Buncombe": 1}


def test_real_parcel_cache_file(tmp_path, monkeypatch):
    from foreclosure_scraper import parcel_cache
    monkeypatch.setattr(parcel_cache, "CACHE_DIR", Path(tmp_path))
    con = sqlite3.connect(tmp_path / "buncombe.sqlite")
    con.execute("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, market_value REAL, "
                "tax_value REAL, acreage REAL, living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT)")
    con.execute("INSERT INTO parcels(id, owner, address, owner_mailing) VALUES (?,?,?,?)",
                ("9686540826", "DOE JOHN", "000040 SAMPLE RIDGE RD", "18 SAMPLE RIDGE RD FAIRVIEW NC 28730"))
    con.commit()
    con.close()
    parcel_cache._CONN.pop("buncombe.sqlite", None)
    li = _unpaid(pid="9686-54-0826-00000")
    a = pc.restore_situs(li, pc.CacheReader())
    parcel_cache._CONN.pop("buncombe.sqlite", None)
    assert a["class"] == "likely" and li.street_address == "40 SAMPLE RIDGE RD"
    assert pc.restore_situs(_li(county="Haywood", parcel_id="1", street_address="1 X RD"), pc.CacheReader()) == {"skip": "no_cache"}


# ---------------------------------------------------------------- 3. superseded mailing copies
def test_aged_mailing_copy_with_a_live_situs_row_is_dropped():
    old = datetime(2026, 8, 2)
    prior = _unpaid(first_seen=old, raw={"pulled_sale": {"consecutive_misses": 1, "presumed_withdrawn": True}},
                    auction_status="presumed_withdrawn")
    fresh = _unpaid(street="40 SAMPLE RIDGE RD", city=None, zip_code=None, first_seen=datetime(2026, 10, 6))
    other = _li(parcel_id="1111111111", street_address="9 OTHER RD")
    rows = [prior, other, fresh]
    stats = pc.correct_prior_rows(rows, cache=FakeCache(BUNCOMBE))
    assert stats["superseded_dropped"] == 1 and rows == [other, fresh]
    assert fresh.first_seen == old
    assert fresh.raw[pc.SUPERSEDED_KEY][0]["street_address"] == "18 SAMPLE RIDGE RD"


def test_aged_mailing_copy_without_a_live_row_is_corrected_and_kept():
    prior = _unpaid(raw={"pulled_sale": {"consecutive_misses": 2, "presumed_withdrawn": True}})
    other_source = _unpaid(source="counties_nc.buncombe_elderly", street="40 SAMPLE RIDGE RD")
    rows = [prior, other_source]
    stats = pc.correct_prior_rows(rows, cache=FakeCache(BUNCOMBE))
    assert stats["superseded_dropped"] == 0 and len(rows) == 2
    assert prior.street_address == "40 SAMPLE RIDGE RD" and prior.raw["pulled_sale"]["presumed_withdrawn"]


# ------------------------------------------------------------------------------- the step
def test_known_good_rows_are_untouched():
    cache = FakeCache(BUNCOMBE)
    rows = [
        _li(source="counties_nc.buncombe_elderly", county="Buncombe", parcel_id="9634707498",
            street_address="38 EXAMPLE LN", city="Arden", market_value=250000.0),       # owner-occupied
        _li(county="Buncombe", parcel_id="9686540826", street_address="40 SAMPLE RIDGE RD"),  # the situs
        _li(county="Rutherford", parcel_id="1600000001", street_address="12 SAMPLE RD",          # precise point
            latitude=35.33719, longitude=-81.86523,
            raw={"parcel_from_geo": {"source": "nc_onemap_point", "lat": 35.33719, "lng": -81.86523}}),
        _li(county="Haywood", parcel_id="8600000001", street_address="5 SAMPLE CV"),              # no cache
    ]
    before = [r.model_dump() for r in rows]
    stats = pc.correct_prior_rows(rows, cache=cache)
    assert [r.model_dump() for r in rows] == before
    assert stats["fallback_withdrawn"] == 0 and stats["mailing_corrected"] == 0 and stats["superseded_dropped"] == 0


def test_a_malformed_row_never_stops_the_step_and_is_left_whole():
    good = _seat_row()
    bad = _seat_row(pid="5550002222", market_value=1250400.0)
    bad.raw["images"] = {("not", "a str key"): 1}      # json.dumps raises on it
    stats = pc.correct_prior_rows([bad, good], cache=FakeCache({}))
    assert good.parcel_id is None and stats["fallback_withdrawn"] == 1 and stats["row_errors"] == 1
    # planned first, applied last: the failed row was not half-corrected
    assert bad.parcel_id == "5550002222" and bad.market_value == 1250400.0 and "gis_attrs_full" in bad.raw


def test_wired_after_merge_prior_board_and_before_the_enrichers():
    src = (Path(__file__).resolve().parent.parent / "src" / "foreclosure_scraper" / "main.py").read_text()
    merge = src.index("deduped, persist_stats = merge_prior_board(deduped)")
    corr = src.index("correct_prior_rows(deduped")
    assert merge < corr < src.index("validate(deduped, workers=") < src.index("enriched = dedupe(enriched)")


def test_audit_keys_survive_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    for k in (pc.FALLBACK_KEY, pc.MAILING_KEY, pc.SUPERSEDED_KEY):
        assert RAW_KEEP.get(k) == "*"


@pytest.mark.parametrize("street,situs,mailing,state,want", [
    ("28 SAMPLE RD", "42 SAMPLE RD", "28 SAMPLE RD FAIRVIEW NC 28730", "NC", "likely"),
    ("900 OTHER DR", "650 SAMPLE RD", "900 OTHER DR APT 12 SAMPLE BEACH FL 33000", "NC", "definite"),
    ("PO BOX 12", "5 SAMPLE RD", "PO BOX 12 ASHEVILLE NC 28801", "NC", "definite"),
    ("38 SAMPLE LN", "38 SAMPLE LANE", "38 SAMPLE LN ARDEN NC 28704", "NC", "situs"),
    ("516 SAMPLE DR", None, "516 SAMPLE DR DARLINGTON SC", "SC", "unverifiable"),
    ("12 SAMPLE RD", "0 SAMPLE RD", "12 SAMPLE RD CANDLER NC 28715", "NC", "same_street_no_number"),
    ("9 ELSEWHERE ST", "42 SAMPLE RD", "77 OTHER RD ASHEVILLE NC 28801", "NC", "other"),
])
def test_classifier(street, situs, mailing, state, want):
    assert pc.classify_street(street, situs, mailing, state) == want

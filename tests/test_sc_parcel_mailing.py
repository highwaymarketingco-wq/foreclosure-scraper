"""Unit tests for sc_parcel_mailing — the cached SC bulk assessor-roll backfill
(Spartanburg Assessor_Extract CSV + Anderson County_Parcels FeatureServer).

Fixtures are REAL rows saved from both live sources (tests/fixtures/
sc_roll_spartanburg.csv, sc_roll_anderson_page.json), so the parsers are
exercised against the actual column shapes — fixed-width subdivision prefixes,
'CITY  ST' packing, mailing-vs-situs divergence and all. No network.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper import sc_parcel_mailing as pm

FIX = Path(__file__).parent / "fixtures"


def _spart_rows() -> list[dict]:
    with open(FIX / "sc_roll_spartanburg.csv", newline="") as f:
        return list(csv.DictReader(f))


def _anderson_rows() -> list[dict]:
    d = json.loads((FIX / "sc_roll_anderson_page.json").read_text())
    return [f["attributes"] for f in d["features"]]


# ---- key + text normalization ---------------------------------------------------

def test_norm_key_strips_every_separator_form():
    # The same Spartanburg parcel arrives dashed, dotted or bare on the board.
    assert pm.norm_key("7-17-02-041.00") == "7170204100"
    assert pm.norm_key("7170204100") == "7170204100"
    assert pm.norm_key("7133-20-3623.91") == "713320362391"
    assert pm.norm_key(None) == ""


def test_clean_situs_strips_anderson_subdivision_prefix():
    assert pm.clean_situs("SPRINGSIDE        300 SPRINGSIDE CIR       ") == "300 SPRINGSIDE CIR"
    assert pm.clean_situs("NEVITT WOODS      807 EASTWOOD ST          ") == "807 EASTWOOD ST"


def test_clean_situs_keeps_plain_address_and_nameless_road():
    assert pm.clean_situs("3701 OLD DOBBINS BRIDGE  ") == "3701 OLD DOBBINS BRIDGE"
    # No house number anywhere -> keep the whole collapsed string, don't drop it.
    assert pm.clean_situs("HUNTERS RIDGE     WHITEHALL RD") == "HUNTERS RIDGE WHITEHALL RD"
    assert pm.clean_situs("") == ""
    assert pm.clean_situs(None) == ""


def test_strip_city_tail_removes_the_appended_community():
    assert pm.strip_city_tail("1101 PARTRIDGE RD SPARTANBURG", "SPARTANBURG") == "1101 PARTRIDGE RD"
    assert pm.strip_city_tail("120 FOWLER ST DUNCAN", "DUNCAN") == "120 FOWLER ST"
    # City not at the tail -> untouched.
    assert pm.strip_city_tail("251 NEAL RD", "SPARTANBURG") == "251 NEAL RD"


def test_split_city_state_unpacks_anderson_city_column():
    assert pm._split_city_state("ANDERSON  SC") == ("ANDERSON", "SC")
    assert pm._split_city_state("FAIR PLAY  SC") == ("FAIR PLAY", "SC")
    assert pm._split_city_state("ANDERSON") == ("ANDERSON", "")


# ---- Spartanburg parsing --------------------------------------------------------

def test_spart_record_keys_on_mapnumber_not_gis_parcel_number():
    """GISParcelNumber is NOT unique (163,047 MAPNUMBERs vs 138,582 GIS numbers on
    the live layer — condos share a polygon), so it must be the alt_key only."""
    rec = pm._spart_record(_spart_rows()[0])
    assert rec["parcel_key"] == "7170204100"          # MAPNUMBER 7-17-02-041.00
    assert rec["alt_key"] == "713320362391"           # GISParcelNumber 7133-20-3623.91
    assert rec["parcel_raw"] == "7-17-02-041.00"      # dashed form for qPublic


def test_spart_record_separates_mailing_from_situs():
    """StreetAddress is the owner's MAILING address, PropertyLocation the situs.
    Row 2 of the roll is an absentee owner mailing from Prosperity SC."""
    rec = pm._spart_record(_spart_rows()[1])
    assert rec["mail_addr"] == "194 WATERFRONT ROW"
    assert rec["mail_city"] == "PROSPERITY"
    assert rec["mail_state"] == "SC"
    assert rec["situs_street"] == "251 NEAL RD"
    assert rec["situs_norm"] == "251 NEAL RD"
    assert rec["mail_addr"] != rec["situs_street"]


def test_spart_record_value_is_land_plus_building():
    rec = pm._spart_record(_spart_rows()[0])
    assert rec["market_value"] == pytest.approx(146000.0 + 238600.0)
    assert rec["year_built"] == 1956
    assert rec["prev_owner"] == "HALLIDAY Q STANFORD III"


def test_spart_record_rejects_rows_with_no_parcel_number():
    assert pm._spart_record({"MAPNUMBER": "", "GISParcelNumber": ""}) is None


def test_spart_records_all_produce_a_situs_and_owner():
    recs = [pm._spart_record(r) for r in _spart_rows()]
    assert all(r is not None for r in recs)
    assert sum(1 for r in recs if r["situs_norm"]) == len(recs)
    assert sum(1 for r in recs if r["mail_addr"]) == len(recs)


# ---- Anderson parsing -----------------------------------------------------------

def test_anderson_record_pads_tms_and_keeps_unpadded_alt():
    rec = pm._anderson_record({"TMS": "60501002", "OWNER": "GLENN BETTY",
                               "OWNER_ADDR": "3701 OLD DOBBINS BRIDGE RD",
                               "CITY": "FAIR PLAY  SC", "ZIPCODE": "29643",
                               "PHYS_ADDR": "3701 OLD DOBBINS BRIDGE  ",
                               "MRKT_VALUE": 75930})
    assert rec["parcel_key"] == "0060501002"   # board ids arrive 9 or 10 digits
    assert rec["alt_key"] == "60501002"
    assert rec["parcel_raw"] == "60501002"
    assert rec["mail_city"] == "FAIR PLAY"
    assert rec["mail_state"] == "SC"
    assert rec["market_value"] == 75930


def test_anderson_records_from_live_fixture_carry_owner_and_mailing():
    recs = [pm._anderson_record(r) for r in _anderson_rows()]
    assert recs and all(r is not None for r in recs)
    assert all(r["owner"] for r in recs)
    assert all(r["mail_addr"] for r in recs)


def test_anderson_sale_year_becomes_a_date_and_bad_years_are_dropped():
    assert pm._anderson_record({"TMS": "1", "SALE_YEAR": 2014})["sale_date"] == "2014-01-01"
    assert pm._anderson_record({"TMS": "1", "SALE_YEAR": 0})["sale_date"] is None


# ---- card collapse --------------------------------------------------------------

def test_keep_prefers_card_one_then_highest_building_value():
    best: dict = {}
    pm._keep(best, {"parcel_key": "K", "_card": 2, "_bldg": 900_000.0})
    pm._keep(best, {"parcel_key": "K", "_card": 1, "_bldg": 10.0})
    assert best["K"]["_card"] == 1          # primary card wins outright
    pm._keep(best, {"parcel_key": "K", "_card": 1, "_bldg": 50.0})
    assert best["K"]["_bldg"] == 50.0       # then the biggest structure


# ---- cache / TTL logic ----------------------------------------------------------

def test_unchanged_matches_on_etag_then_last_modified_then_length():
    prev = {"etag": '"abc"', "last_modified": "Wed, 27 May 2026 14:41:55 GMT",
            "content_length": 122907117}
    assert pm._unchanged(prev, {"etag": '"abc"'}) is True
    assert pm._unchanged(prev, {"etag": '"zzz"'}) is False
    assert pm._unchanged(prev, {"etag": None,
                                "last_modified": "Wed, 27 May 2026 14:41:55 GMT"}) is True
    assert pm._unchanged(prev, {"etag": None, "last_modified": None,
                                "content_length": 122907117}) is True
    assert pm._unchanged(prev, {"etag": None, "last_modified": None,
                                "content_length": 999}) is False


def test_unchanged_is_false_without_a_prior_fetch_or_any_validator():
    assert pm._unchanged(None, {"etag": '"abc"'}) is False
    assert pm._unchanged({"etag": None}, {"etag": None}) is False


def test_fresh_respects_the_ttl_window():
    now = datetime.utcnow()
    assert pm._fresh({"fetched_at": now.isoformat(), "rows": 10}, 7) is True
    old = (now - timedelta(days=9)).isoformat()
    assert pm._fresh({"fetched_at": old, "rows": 10}, 7) is False
    # A meta row with no parsed rows is never "fresh" — nothing to serve.
    assert pm._fresh({"fetched_at": now.isoformat(), "rows": 0}, 7) is False
    assert pm._fresh(None, 7) is False


# ---- end-to-end against a temp DB -----------------------------------------------

@pytest.fixture()
def roll_db(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "roll.db")
    best: dict = {}
    for row in _spart_rows():
        pm._keep(best, pm._spart_record(row))
    pm._store("SC", "Spartanburg", pm._strip_scratch(best), {"url": "x", "etag": '"e1"'})
    best2: dict = {}
    for row in _anderson_rows():
        pm._keep(best2, pm._anderson_record(row))
    pm._store("SC", "Anderson", pm._strip_scratch(best2), {"url": "y", "etag": None})
    return tmp_path


def test_has_data_and_covered_counties(roll_db):
    assert pm.has_data("SC", "Spartanburg") is True
    assert pm.has_data("SC", "Anderson") is True
    assert pm.has_data("SC", "Greenville") is False
    assert pm.covered_counties() == {("SC", "Spartanburg"), ("SC", "Anderson")}


def test_lookup_by_dashed_and_stripped_map_number(roll_db):
    a = pm.lookup("SC", "Spartanburg", parcel_id="7-17-02-041.00")
    b = pm.lookup("SC", "Spartanburg", parcel_id="7170204100")
    assert a and b and a["parcel_key"] == b["parcel_key"] == "7170204100"
    assert a["mailing"] == "1101 PARTRIDGE RD, SPARTANBURG SC, 29302"


def test_lookup_by_gis_parcel_number_alt_key(roll_db):
    rec = pm.lookup("SC", "Spartanburg", parcel_id="713320362391")
    assert rec and rec["parcel_key"] == "7170204100"


def test_lookup_by_situs_address_returns_the_mailing(roll_db):
    rec = pm.lookup("SC", "Spartanburg", street_address="251 Neal Road")
    assert rec is not None
    assert rec["mail_addr"] == "194 WATERFRONT ROW"      # absentee owner
    assert rec["situs_street"] == "251 NEAL RD"


def test_lookup_misses_return_none(roll_db):
    assert pm.lookup("SC", "Spartanburg", parcel_id="9-99-99-999.99") is None
    assert pm.lookup("SC", "Spartanburg", street_address="1 NOWHERE LN") is None
    assert pm.lookup("SC", "Greenville", parcel_id="7170204100") is None


def test_anderson_lookup_by_padded_and_unpadded_tms(roll_db):
    row = _anderson_rows()[0]
    digits = pm.norm_key(row["TMS"])
    for cand in (digits, digits.zfill(10), digits.lstrip("0")):
        rec = pm.lookup("SC", "Anderson", parcel_id=cand)
        assert rec is not None and rec["owner"]


def test_disambiguate_refuses_a_tie_with_conflicting_mailings():
    rows = [
        ("k1", "a1", "r1", "OWNER A", None, None, "1 MAIN ST", None, None, None,
         None, None, None, None, None, None, None, None, None, None, None, None,
         None, None, 0),
        ("k2", "a1", "r2", "OWNER B", None, None, "2 OTHER ST", None, None, None,
         None, None, None, None, None, None, None, None, None, None, None, None,
         None, None, 0),
    ]
    assert pm._disambiguate(rows, street_address=None, zip_code=None) is None
    # Same mailing on every candidate (one condo owner, many units) is safe.
    same = [rows[0], tuple(["k2", "a1", "r2", "OWNER A"] + list(rows[0][4:]))]
    assert pm._disambiguate(same, street_address=None, zip_code=None) is not None


def test_resolve_parcel_key_returns_the_raw_county_key(roll_db):
    """The assessor-card adapters query with the county's own format — the dashed
    MAPNUMBER for Spartanburg, not the digits-only join key."""
    assert pm.resolve_parcel_key("SC", "Spartanburg",
                                 street_address="251 Neal Rd") == "3-22-00-019.04"


def test_lookup_by_owner_matches_surname_first_rolls(roll_db):
    hits = pm.lookup_by_owner("SC", "Spartanburg", "Brent F Macintosh")
    assert hits and hits[0]["owner"].startswith("MACINTOSH BRENT")
    assert hits[0]["owner_match"] in ("exact", "strong")


def test_lookup_by_owner_rejects_a_different_person(roll_db):
    assert pm.lookup_by_owner("SC", "Spartanburg", "Kevin Michael Macintosh") == []
    assert pm.lookup_by_owner("SC", "Spartanburg", "Zzz") == []


def test_build_is_skipped_while_the_local_copy_is_fresh(roll_db, monkeypatch):
    """The 123 MB CSV must not move on every run: inside the TTL the builder
    returns the cached row count without touching the network at all."""
    def _boom(*a, **k):  # any network call is a test failure
        raise AssertionError("network touched while cache was fresh")
    monkeypatch.setattr(pm, "_probe", _boom)
    monkeypatch.setattr(pm, "_build_from_csv", _boom)
    monkeypatch.setattr(pm, "_build_from_arcgis", _boom)
    assert pm.build_mailing_table("SC", "Spartanburg", ttl_days=7) == 40


def test_build_is_skipped_when_the_etag_is_unchanged(roll_db, monkeypatch):
    monkeypatch.setattr(pm, "_probe", lambda url: {"url": url, "etag": '"e1"',
                                                   "last_modified": None,
                                                   "content_length": None})
    def _boom(*a, **k):
        raise AssertionError("downloaded despite an unchanged ETag")
    monkeypatch.setattr(pm, "_build_from_csv", _boom)
    monkeypatch.setattr(pm, "_build_from_arcgis", _boom)
    # ttl_days=0 forces the validator path rather than the TTL short-circuit.
    assert pm.build_mailing_table("SC", "Spartanburg", ttl_days=0) == 40


def test_build_redownloads_when_the_etag_moves(roll_db, monkeypatch):
    monkeypatch.setattr(pm, "_probe", lambda url: {"url": url, "etag": '"e2-NEW"',
                                                   "last_modified": None,
                                                   "content_length": None})
    calls: list = []

    def _fake_csv(state, county, spec, *, max_rows):
        calls.append((state, county))
        best: dict = {}
        pm._keep(best, pm._spart_record(_spart_rows()[0]))
        return pm._strip_scratch(best)

    monkeypatch.setattr(pm, "_build_from_csv", _fake_csv)
    assert pm.build_mailing_table("SC", "Spartanburg", ttl_days=0) == 1
    assert calls == [("SC", "Spartanburg")]


def test_arcgis_paging_stops_on_exceeded_transfer_limit_false(monkeypatch):
    pages = [
        {"features": [{"attributes": {"OBJECTID": i, "TMS": str(i)}} for i in range(3)],
         "exceededTransferLimit": True},
        {"features": [{"attributes": {"OBJECTID": 9, "TMS": "9"}}],
         "exceededTransferLimit": False},
    ]
    seen: list[str] = []

    def _fake(url, **kw):
        seen.append(url)
        return pages[len(seen) - 1]

    monkeypatch.setattr(pm, "_fetch_json", _fake)
    out = list(pm.arcgis_pages("http://x/0", "1=1", ["OBJECTID", "TMS"], page=3))
    assert len(out) == 4
    assert len(seen) == 2                     # stopped, did not ask for a 3rd page
    assert "resultOffset=3" in seen[1]        # offset advanced by the page it got
    assert "outFields=OBJECTID%2CTMS" in seen[0]   # explicit fields, never `*`


def test_arcgis_paging_never_requests_star_outfields(monkeypatch):
    """Privacy rule: outFields is always an explicit allow-list."""
    monkeypatch.setattr(pm, "_fetch_json",
                        lambda url, **kw: {"features": [], "exceededTransferLimit": False})
    for spec in pm.SC_ROLLS.values():
        assert "*" not in spec["fields"]


# ---- stored-flag coercion -------------------------------------------------------

def test_truthy_flag_never_trusts_a_string_zero():
    """Regression: condition_distressed was declared TEXT, so a stored 0 came
    back as "0" and bool("0") flagged EVERY parcel as distressed."""
    for falsey in (None, "", 0, 0.0, "0", "0.0", "false", "No"):
        assert pm._truthy_flag(falsey) is False
    for truthy in (1, 1.0, "1", "true", "Y"):
        assert pm._truthy_flag(truthy) is True


def test_flag_and_year_columns_are_not_text_affinity():
    assert pm._col_decl("condition_distressed") == "condition_distressed INTEGER"
    assert pm._col_decl("year_built") == "year_built INTEGER"
    assert pm._col_decl("market_value") == "market_value REAL"
    assert pm._col_decl("owner") == "owner TEXT"


def test_good_condition_round_trips_as_not_distressed(roll_db):
    rec = pm.lookup("SC", "Spartanburg", parcel_id="7-17-02-041.00")
    assert rec["condition_code"] == "GD"
    assert rec["condition_distressed"] is False
    assert rec["year_built"] == 1956


def test_poor_condition_codes_still_flag():
    assert pm._condition_flag("PR") == 1
    assert pm._condition_flag("VP") == 1
    assert pm._condition_flag("DL") == 1
    assert pm._condition_flag("GD") == 0
    assert pm._condition_flag("AV") == 0
    assert pm._condition_flag("") == 0

"""scripts/gap_matrix.py: the pure pieces, on hand-made rows (no board, no network)."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "gap_matrix.py"
_SPEC = importlib.util.spec_from_file_location("gap_matrix", _PATH)
gm = importlib.util.module_from_spec(_SPEC)
sys.modules["gap_matrix"] = gm          # dataclasses resolve string annotations through sys.modules
_SPEC.loader.exec_module(gm)

TODAY = date(2026, 10, 7)


def row(**kw):
    base = {"source": "test.src", "source_url": "https://example.test/x", "listing_type": "tax_lien",
            "property_kind": "single_family", "state": "NC", "county": "Buncombe", "raw": {}}
    base.update(kw)
    return base


# ---------------------------------------------------------------- the 73 columns (10/1 rules)

def test_column_counts():
    assert len(gm.OWNER_COLUMNS) == 73
    assert len(gm.ATTY_COLUMNS) == 9
    assert set(gm.SPECS) == set(gm.ALL_COLUMNS)


def test_owner_columns_fields_and_types():
    r = row(street_address="1 A ST", parcel_id="9648-12-3456", owner_name="DOE JOHN ET AL",
            living_sqft=1200, bedrooms=3, bathrooms=2, acreage=0.3, tax_value=100000,
            raw={"owner_phone": {"phone": "8285550100"}, "owner_email": {"best_email": "x@y.test"},
                 "comps": [{"match_quality": "zip+kind+sqft+beds"}]})
    got = gm.owner_columns(r)
    assert {"address", "parcel_id", "owner_name", "phone", "email", "sqft", "beds_baths", "lot_size",
            "assessed_value", "comps", "comps_tight", "lt_tax_lien", "name_et_al"} <= got
    assert "lt_tax_sale" not in got


def test_owner_columns_wrappers_follow_10_01():
    raw = {"divorce": {"case_count": 0, "cases": []},           # checked, nothing found: not a hit
           "probate": {"personal_representative": "x"},          # no decedent / case number: not a hit
           "two_year_delinquent": {"is_two_year_plus": False},
           "tax_aging_surfaced": {"status": "current", "years_delinquent": 0},
           "marriage_license": {"status": "no_match"},           # 10/1 counts bare presence
           "code_enforcement": {"has_open": False, "severe": False},
           "deed_chain": {"transfers": [], "summary": {"chain_breaks": 1}},
           "column": {"is_quiet_title": True}}
    got = gm.owner_columns(row(raw=raw))
    assert "divorce" not in got and "probate" not in got
    assert "two_year_delinquent" not in got and "tax_aging_surfaced" not in got
    assert "code_enforcement" not in got
    assert "marriage_license" in got                      # the 10/1 ambiguity, kept for comparability
    assert {"deed_chain_has_history", "deed_chain_break", "quiet_title"} <= got
    raw2 = {"divorce": {"case_count": 2}, "probate": {"es_case_number": "26E001"}, "code_enforcement": True}
    assert {"divorce", "probate", "code_enforcement"} <= gm.owner_columns(row(raw=raw2))


def test_presence_zero_is_empty_like_10_01():
    assert "liens" not in gm.owner_columns(row(raw={"liens": []}))
    assert "condemned" not in gm.owner_columns(row(raw={"condemned": False}))
    assert "condemned" in gm.owner_columns(row(raw={"condemned": True}))


# ---------------------------------------------------------------- second view

def test_positive_drops_marriage_no_match_and_adds_attorney():
    r = row(owner_name="DOE JANE", legal_description="LOT 4 BLK B",
            raw={"marriage_license": {"status": "no_match"},
                 "deed_chain": {"transfers": [{"date": "2001-01-01", "book": "123", "page": "45"}]},
                 "gis": {"owner": "DOE JANE"},
                 "rod": {"instrument_count": 3},
                 "heir_estate": {"owner_of_record": "x", "heir_names": ["a"]},
                 "probate": {"es_case_number": "26E001"}})
    owner = gm.owner_columns(r)
    pos = gm.positive_columns(r, owner, {"tax_lien": "confirmed"})
    assert "marriage_license" not in pos
    assert {"atty_legal_description", "atty_deed_ref", "atty_taxpayer_of_record", "atty_heir_candidates",
            "atty_rod_lien_checked", "atty_deed_chain_fetched", "atty_probate_case",
            "atty_tax_verified_confirmed"} <= pos


def test_checked_columns_from_wrappers_and_inputs():
    r = row(owner_name="DOE JOHN", defendant="DOE JOHN",
            raw={"tax_owed": {"balance": 10}, "divorce": {"case_count": 0}, "owner_email": {"best_email": None},
                 "incarceration_check": {"result": "no_match"}, "deed_chain": {"transfers": []}})
    owner = gm.owner_columns(r)
    pos = gm.positive_columns(r, owner, {})
    chk = gm.checked_columns(r, pos, {"tax_lien": "refuted"})
    assert {"multi_year_delinquent_tax", "two_year_delinquent", "divorce", "email", "incarceration",
            "deed_chain_break", "name_heirs", "owner_cluster", "owner_mismatch",
            "atty_tax_verified_confirmed"} <= chk
    assert "bop_federal" not in chk
    assert "atty_tax_verified_confirmed" not in gm.checked_columns(r, pos, {"tax_lien": "unconfirmed"})


def test_tax_status_known_ignores_state_income_lien():
    assert gm.tax_status_known({"nc_ptscloud_delinquent_tax": {"x": 1}})
    assert gm.tax_status_known({"rutherford_tax": {"x": 1}})
    assert not gm.tax_status_known({"sc_state_tax_lien": {"owner": "x"}})
    assert not gm.tax_status_known({"bankruptcy_tax_combo": {"x": 1}, "amount_owed": {"value": 1}})


def test_applicability_rules():
    land_sc = row(state="SC", county="Greenville", property_kind="land", raw={"entity_type": "government"})
    rules = gm.row_rules(land_sc, land_sc["raw"], set())
    app = gm.applicable_columns(land_sc, rules)
    assert "beds_baths" not in app and "sqft" not in app and "comps" not in app
    assert "phone" not in app and "divorce" not in app            # government owner
    assert "sc_state_tax_lien" in app and "liensnc_related" not in app
    nc = row(owner_name="SMITH MARY HEIRS", raw={"entity_type": "individual"})
    rules = gm.row_rules(nc, nc["raw"], gm.owner_columns(nc))
    assert "deceased" in rules
    app = gm.applicable_columns(nc, rules)
    assert {"atty_heir_candidates", "atty_probate_case", "liensnc_related", "phone"} <= app
    assert "sc_state_tax_lien" not in app
    assert "atty_tax_verified_confirmed" in app                   # a tax_lien row claims delinquent tax


# ---------------------------------------------------------------- verdicts

def test_row_verdicts_prefers_board_then_ledger():
    idx = {"tax_lien": {"parcel:NC:buncombe:123": "stale"}, "jail_booking": {"parcel:NC:buncombe:123": "confirmed"}}
    r = row(raw={"verification": [{"signal": "tax_lien", "verdict": "confirmed"}]})
    got = gm.row_verdicts(r, idx, ["parcel:NC:buncombe:123"])
    assert got == {"tax_lien": "confirmed", "jail_booking": "confirmed"}
    assert gm.row_verdicts(row(), idx, ["addr:NC:buncombe:1 a st"]) == {}


def test_load_ledger_index_case_scoped_keys(tmp_path):
    (tmp_path / "jail_booking.json").write_text(
        '{"signal": "jail_booking", "rows": {"jail:x@parcel:NC:cleveland:9": {"keys": ["jail:x@parcel:NC:cleveland:9"],'
        ' "row": {"state": "NC", "county": "cleveland"}, "latest": {"verdict": "confirmed"}}}}')
    (tmp_path / "broken.json").write_text("{not json")
    idx, counts = gm.load_ledger_index(tmp_path)
    assert idx["jail_booking"]["parcel:NC:cleveland:9"] == "confirmed"
    assert counts["jail_booking"] == {"NC|Cleveland|confirmed": 1}


# ---------------------------------------------------------------- sources and classes

MATRIX_REC = {"state": "NC", "county": "wake",
              "rod": {"access": "captcha", "free_name_search": "yes", "legal_description_in_index": "yes",
                      "url": "https://rod.example.test/search"},
              "probate": {"access": "captcha", "free_search": "yes", "url": "https://portal.example.test"},
              "tax": {"access": "open", "free_by_parcel": "yes", "url": "https://tax.example.test"},
              "gis": {"url": "https://gis.example.test", "legal_description_field": "no", "deed_book_page_field": "yes",
                      "owner_field": "yes"},
              "manual_lane": "a person ticks the reCAPTCHA"}


def test_source_status_paths():
    S = gm.SPECS
    assert gm.source_status(S["atty_rod_lien_checked"], "NC", MATRIX_REC)[:2] == ("walled", "CAPTCHA")
    assert gm.source_status(S["atty_probate_case"], "NC", MATRIX_REC)[0] == "walled"
    assert gm.source_status(S["sqft"], "NC", MATRIX_REC)[0] == "free"
    assert gm.source_status(S["atty_legal_description"], "NC", MATRIX_REC)[:2] == ("walled", "CAPTCHA")
    assert gm.source_status(S["deed_chain_has_history"], "NC", MATRIX_REC)[0] == "free"
    assert gm.source_status(S["phone"], "NC", None)[0] == "free"                     # statewide voter file
    assert gm.source_status(S["phone"], "SC", None)[0] == "walled"
    assert gm.source_status(S["atty_deed_ref"], "NC", None)[2].startswith("statewide (not read yet)")
    assert gm.source_status(S["liens"], "SC", None)[2] == \
        "county missing from the county records matrix"
    assert gm.source_status(S["jail_booking"], "NC", MATRIX_REC)[0] == "unknown"
    blocked = dict(MATRIX_REC, rod={"access": "open", "terms_forbid_automation": "yes"})
    assert gm.source_status(S["liens"], "NC", blocked)[:2] == ("walled", "terms forbid automation")


@pytest.mark.parametrize("app,target,ran,built,src,want", [
    (0, 0, False, "no", ("free", "", ""), "not applicable"),
    (10, 10, True, "ran", ("free", "", ""), None),
    (10, 3, True, "ran", ("walled", "CAPTCHA", ""), "built-but-low-yield"),
    (10, 0, False, "code", ("free", "", ""), "built-but-low-yield"),
    (10, 0, False, "code", ("walled", "login", ""), "walled (login)"),
    (10, 0, False, "no", ("walled", "CAPTCHA", ""), "walled (CAPTCHA)"),
    (10, 0, False, "no", ("free", "", ""), "sourced-not-built"),
    (10, 0, False, "no", ("unknown", "", ""), "no source known"),
])
def test_classify_cell(app, target, ran, built, src, want):
    assert gm.classify_cell(gm.SPECS["liens"], app, target, ran, built, src) == want


def test_next_action_walled_uses_manual_lane():
    act = gm.next_action("walled (CAPTCHA)", "liens", gm.SPECS["liens"], "", "CAPTCHA", MATRIX_REC, 5)
    assert act.startswith("manual lane: a person ticks")
    assert "no free owner-email source" in gm.next_action("built-but-low-yield", "email", gm.SPECS["email"], "", "", None, 3)


# ---------------------------------------------------------------- correctness invariants

def test_parcel_and_phone_helpers():
    assert gm.parcel_shape("9648-12-3456") == "9999-99-9999"
    assert gm.parcel_shape("R12A") == "A99A"
    assert gm.parcel_junk("000000") and gm.parcel_junk("N/A") and gm.parcel_junk("12")
    assert not gm.parcel_junk("9648-12-3456")
    assert gm.phone_problem("(828) 555-0100") == "fictional_555"
    assert gm.phone_problem("1-828-253-1234") is None
    assert gm.phone_problem("12345") == "not_10_digits"
    assert gm.phone_problem("0285551234") == "bad_area_or_exchange"


def test_row_invariants():
    bad = row(state="NC", county="greenville", zip_code="29601", latitude=32.5, longitude=-82.4,
              owner_name="123 MAIN ST", sale_date="1970-01-01", first_seen="2026-10-05", last_seen="2026-10-01",
              year_built=1600, tax_value=100000, living_sqft=1000,
              raw={"calc": {"arv_expected": 900000}, "owner_phone": {"phone": "123"},
                   "last_sale": {"date": "2030-01-01"}})
    got = gm.row_invariants(bad, TODAY)
    assert {"county_not_in_state", "zip_not_in_state", "latlon_outside_state", "owner_name_looks_like_address",
            "sale_date_impossible", "first_seen_after_last_seen", "year_built_impossible", "arv_over_5x_assessed",
            "last_sale_in_future", "phone_not_10_digits"} <= got
    ok = row(state="NC", county="Buncombe", zip_code="28801", latitude=35.6, longitude=-82.5, owner_name="DOE JOHN",
             raw={"owner_mailing": {"mailing": "PO BOX 1 ASHEVILLE NC"}, "calc": {"arv_expected": 250000}},
             tax_value=200000, living_sqft=1500)
    assert gm.row_invariants(ok, TODAY) == set()
    assert "county_noncanonical_spelling" in gm.row_invariants(row(county="buncombe"), TODAY)
    assert "county_blank" in gm.row_invariants(row(county=""), TODAY)
    same = row(owner_name="1 A ST ASHEVILLE", raw={"owner_mailing": {"mailing": "1 A ST, ASHEVILLE"}})
    assert "owner_name_equals_mailing" in gm.row_invariants(same, TODAY)


def test_county_key():
    assert gm.county_key(row(county="mcdowell")) == ("NC", "McDowell")
    assert gm.county_key(row(county=None)) == ("NC", "UNKNOWN")
    assert gm.county_key(row(state=" sc ", county="Greenville County")) == ("SC", "Greenville")


def test_counties_named_in(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('LAYERS = {"buncombe": 1}\n# Polk County roster\nslug = "henderson_vacant"\nunion_all = 1\n')
    got = gm.counties_named_in([f])
    assert {("NC", "Buncombe"), ("NC", "Polk"), ("NC", "Henderson")} <= got
    assert ("NC", "Union") not in got and ("SC", "Union") not in got


def test_read_baseline_maps_unknown(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text("State,County,Rows,address\nNC,UNKNOWN,5,1.0\nNC,Mcdowell,3,2.0\n")
    b = gm.read_baseline(p)
    assert ("NC", "UNKNOWN") in b and ("NC", "McDowell") in b


# ---------------------------------------------------------------- the roll-up, end to end on four rows

def test_cube_roll_up_classes():
    cube = gm.Cube(today=TODAY)
    a = row(county="Buncombe", owner_name="DOE JOHN", raw={"jail_booking": {"county": "Buncombe"},
                                                           "entity_type": "individual"})
    b = row(county="Buncombe", owner_name="ROE JANE", raw={"entity_type": "individual"})
    c = row(county="Polk", owner_name="POE JIM", raw={"entity_type": "individual"})
    d = row(county=None, owner_name="X Y", raw={})
    for r in (a, b, c, d):
        cube.add(r)
    matrix = {("NC", "Polk"): dict(MATRIX_REC, county="polk")}
    roll = gm.roll_up(cube, matrix, {"jail_booking": set()})
    jail_b = roll["cells"][("NC", "Buncombe", "jail_booking")]
    assert jail_b["ran"] and jail_b["target"] == jail_b["app"] == 2      # roster ran: both screened
    jail_p = roll["cells"][("NC", "Polk", "jail_booking")]
    assert not jail_p["ran"] and jail_p["class"] == "no source known"
    rod_p = roll["cells"][("NC", "Polk", "atty_rod_lien_checked")]
    assert rod_p["class"] == "walled (CAPTCHA)"
    unk = [g for g in roll["gaps"] if g["county"] == "UNKNOWN" and g["column"] == "address"]
    assert unk and unk[0]["next_action"].startswith("resolve the county")
    assert all("DOE" not in str(g) and "ROE" not in str(g) for g in roll["gaps"])
    corr = gm.correctness(cube)
    assert corr["invariants"]["county_blank"]["total"] == 1

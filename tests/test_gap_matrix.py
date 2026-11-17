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


def test_vacant_recognizes_the_gis_vacant_key_its_real_producers_actually_write():
    """2026-10-16: enrichment_arcgis.py and nc_lincoln_bulk.py both write the
    vacant-structure signal to raw["gis"]["vacant"], never the bare top-level
    raw["vacant"] this column used to check alone -- invisible to the gap list for
    every county either one covers (confirmed live: Gaston 107 rows, Lincoln 1,095
    rows). spartanburg_vacant.py's own raw["vacant"] top-level write must still work."""
    assert "vacant" in gm.owner_columns(row(raw={"gis": {"vacant": True}}))
    assert "vacant" not in gm.owner_columns(row(raw={"gis": {"vacant": False}}))
    assert "vacant" not in gm.owner_columns(row(raw={"gis": {}}))
    assert "vacant" in gm.owner_columns(row(raw={"vacant": {"source": "spartanburg_city_registry"}}))


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
    # owner_email carries a still-live source (liensnc_filing) so "email" counts as checked here;
    # see test_email_phone_checked_only_from_a_still_live_source for the retired-module case.
    r = row(owner_name="DOE JOHN", defendant="DOE JOHN",
            raw={"tax_owed": {"balance": 10}, "divorce": {"case_count": 0},
                 "owner_email": {"best_email": None, "source": "liensnc_filing"},
                 "incarceration_check": {"result": "no_match"}, "deed_chain": {"transfers": []}})
    owner = gm.owner_columns(r)
    pos = gm.positive_columns(r, owner, {})
    chk = gm.checked_columns(r, pos, {"tax_lien": "refuted"})
    # 2026-10-16: multi_year_delinquent_tax AND two_year_delinquent both split out of the
    # shared broad tax check -- tax_owed alone (unrelated to either one's own real
    # producer) no longer marks either checked.
    assert {"divorce", "email", "incarceration",
            "deed_chain_break", "name_heirs", "owner_cluster", "owner_mismatch",
            "atty_tax_verified_confirmed"} <= chk
    assert "multi_year_delinquent_tax" not in chk
    assert "two_year_delinquent" not in chk
    assert "bop_federal" not in chk
    assert "atty_tax_verified_confirmed" not in gm.checked_columns(r, pos, {"tax_lien": "unconfirmed"})


def test_email_phone_checked_only_from_a_still_live_source():
    """Audit 2026-10-19: a non-empty owner_email/owner_phone dict used to mark "checked" on its
    own (any dict at all, via SCORER_GATES' generic not-empty test plus a redundant explicit
    owner_email check) -- even when that dict is nothing but frozen scan exhaust from a module
    RETIRED 2026-10-09 (enrichment_email_extract.py, enrichment_surface_contacts.py,
    enrichment_sc_voter_xref.py, enrichment_ocr.py; deploy/oracle/run_profile.json's own
    unwired_allowlist documents the retirement) that will never run again on this row. Live-measured
    19 (county, column) cells, all SC, all literal 0.0% yield, inflated by exactly this. A row
    whose only touch is dead-scanner exhaust (no recognizable live source, and no genuine fill)
    must not count as checked."""
    retired_email = row(raw={"owner_email": {"best_email": None, "best_classification": "other"}})
    retired_phone = row(raw={"owner_phone": {"source": "surface_contacts", "checked_at": "2026-01-01"}})
    live_email = row(raw={"owner_email": {"best_email": None, "source": "liensnc_filing"}})
    live_phone = row(raw={"owner_phone": {"source": "ncsbe_voter", "checked_at": "2026-01-01"}})

    for r in (retired_email, retired_phone, live_email, live_phone):
        owner = gm.owner_columns(r)
        pos = gm.positive_columns(r, owner, {})
        chk = gm.checked_columns(r, pos, {})
        if r is retired_email or r is retired_phone:
            assert "email" not in chk and "phone" not in chk, r["raw"]
        else:
            assert ("email" in chk) or ("phone" in chk), r["raw"]


def test_multi_year_delinquent_tax_checked_only_by_its_own_key():
    """Its real producer (scrapers/counties_generic/multi_year_delinquent_tax.py) covers
    exactly 3 counties (Buncombe NC, Oconee SC, Pickens SC); the generic tax_status_known()
    predicate used to mark it checked from any unrelated tax key board-wide -- live-measured
    150,198 false-"checked" rows outside those 3 counties (audit 2026-10-16)."""
    hit = row(raw={"multi_year_delinquent_tax": {"years": [2023, 2024]}})
    assert "multi_year_delinquent_tax" in gm.checked_columns(hit, set(), {})
    miss = row(raw={"tax_owed": {"balance": 10}, "nc_ptscloud_delinquent_tax": {"years": 3}})
    assert "multi_year_delinquent_tax" not in gm.checked_columns(miss, set(), {})
    assert "two_year_delinquent" not in gm.checked_columns(miss, set(), {})
    assert "tax_aging_surfaced" not in gm.checked_columns(miss, set(), {})
    # the other 2 columns on the shared broad line are unaffected by any of the 3 splits
    assert {"repeat_tax_loss", "bankruptcy_tax_combo"} <= gm.checked_columns(miss, set(), {})


def test_tax_aging_surfaced_checked_only_by_its_own_key_and_never_by_the_dead_default_stamp():
    """enrichment_tax_aging.py IS genuinely board-wide and growing (unlike
    multi_year_delinquent_tax/two_year_delinquent's narrow producers) -- but the shared
    tax_status_known() predicate still overcounted it by 37,566 rows (audit 2026-10-16,
    wave-4 gap-sweep) against keys unrelated to its own precondition. "default" is the
    dead one-shot-script stamp (scripts/surface_tax_aging.py); the live producer only
    ever writes source="nc_ptscloud" or "tax_owed"."""
    hit = row(raw={"tax_aging_surfaced": {"years_delinquent": 2, "source": "tax_owed"}})
    assert "tax_aging_surfaced" in gm.checked_columns(hit, set(), {})
    stale = row(raw={"tax_aging_surfaced": {"years_delinquent": 2, "source": "default"}})
    assert "tax_aging_surfaced" not in gm.checked_columns(stale, set(), {})
    miss = row(raw={"tax_owed": {"balance": 10}, "catalis_roll": {"years": 3}})
    assert "tax_aging_surfaced" not in gm.checked_columns(miss, set(), {})


def test_two_year_delinquent_checked_only_by_its_own_key():
    """Its 3 real producers (albemarle_observer_tax_lists.py, nc_its_public_tax.py,
    sc_catalis_delinquent_roll.py) all write raw['two_year_delinquent'] directly; the
    shared tax_status_known() predicate used to mark it checked from any unrelated tax
    key board-wide -- live-measured 122,976 false-"checked" rows (audit 2026-10-16)."""
    hit = row(raw={"two_year_delinquent": {"is_two_year_plus": False, "years": 1}})
    assert "two_year_delinquent" in gm.checked_columns(hit, set(), {})
    miss = row(raw={"tax_owed": {"balance": 10}, "qpaybill_roll": {"years": 3}})
    assert "two_year_delinquent" not in gm.checked_columns(miss, set(), {})


def test_sos_screen_counts_as_checked_but_never_as_a_positive_hit():
    """Found 2026-10-16 (gap-sweep wave 3): enrichment_sos_dissolution.py wrote nothing for
    a completed "active"/"unknown" lookup, so a clean screen looked unchecked forever (the
    code_enforcement anti-pattern). Fixed by writing raw.sos_screen -- a SEPARATE key from
    raw.sos_dissolution, because sos_dissolution has no SCORER_GATES gate: owner_columns()'s
    bare presence check on that key is what decides the POSITIVE hit too, so a negative
    result written to the same key would wrongly mark a clean entity as dissolved."""
    screened = row(raw={"sos_screen": {"checked": True, "status": "active", "checked_at": "2026-10-16T00:00:00"}})
    owner = gm.owner_columns(screened)
    pos = gm.positive_columns(screened, owner, {})
    assert "sos_dissolution" not in owner       # a clean screen is never a positive hit
    assert "sos_dissolution" not in pos
    assert "sos_dissolution" in gm.checked_columns(screened, pos, {})   # but it was screened

    dissolved = row(raw={"sos_dissolution": {"checked": True, "status": "dissolved"}})
    owner2 = gm.owner_columns(dissolved)
    pos2 = gm.positive_columns(dissolved, owner2, {})
    assert "sos_dissolution" in owner2          # a real hit still counts as positive
    assert "sos_dissolution" in pos2
    assert "sos_dissolution" in gm.checked_columns(dissolved, pos2, {})


def test_jail_booking_screen_counts_as_checked_but_never_as_a_positive_hit():
    """Found 2026-10-16 (gap-sweep wave 3): match_rosters()'s bulk-roster lane wrote
    nothing at all when a healthy roster matched nobody, so a county-scope "ran" check
    (pos>0 or chk>0 on ANY row in the county) could never flip -- Transylvania/Polk NC
    fetched a clean, healthy roster for 2+ months with zero rows ever credited as
    checked. Fixed by writing raw.jail_booking_screen -- a SEPARATE key from
    raw.jail_booking, because _gate_jail treats ANY non-empty jail_booking dict without
    a release marker as a currently-active booking, so a no-match wrapper written to
    that same key would wrongly read as a hit."""
    screened = row(raw={"jail_booking_screen": {"county": "Transylvania", "state": "NC", "result": "no_match"}})
    owner = gm.owner_columns(screened)
    pos = gm.positive_columns(screened, owner, {})
    assert "jail_booking" not in owner          # a clean screen is never a positive hit
    assert "jail_booking" not in pos
    assert "jail_booking" in gm.checked_columns(screened, pos, {})   # but it was screened

    hit = row(raw={"jail_booking": {"release_status": "in_custody"}})
    owner2 = gm.owner_columns(hit)
    pos2 = gm.positive_columns(hit, owner2, {})
    assert "jail_booking" in owner2             # a real hit still counts as positive
    assert "jail_booking" in pos2
    assert "jail_booking" in gm.checked_columns(hit, pos2, {})


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
        '{"kind": "verification_ledger", "signal": "jail_booking", "rows": {"jail:x@parcel:NC:cleveland:9": {"keys": ["jail:x@parcel:NC:cleveland:9"],'
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
    assert {("NC", "Buncombe"), ("NC", "Henderson")} <= got
    assert ("NC", "Union") not in got and ("SC", "Union") not in got
    # "# Polk County roster" is a COMMENT, not real producer code -- see
    # test_counties_named_in_ignores_comments_and_docstrings below for why this no longer counts.
    assert ("NC", "Polk") not in got


def test_counties_named_in_ignores_comments_and_docstrings(tmp_path):
    """2026-10-19: a live audit of built_in_code()'s real output found 47 (county, column) credit
    pairs across 21 columns whose ONLY textual evidence anywhere in the producer file was a
    comment or docstring -- never real code -- e.g. a rejection note ("Gaston Blight Problems:
    live, 0 rows"), a name-parsing docstring example ('MICHAEL LEE ABSHER' -> 'LEE'), or an aside
    comparing one file's style to another's ("same spirit as nc_rowan_cott.py's"). None of the 47
    were legitimate; stripping comments/docstrings before matching removes exactly those 47 and
    adds zero new matches anywhere in the real codebase (verified against the live SPECS/producer
    set, not just this synthetic file)."""
    f = tmp_path / "y.py"
    f.write_text(
        '"""Module docstring mentioning Transylvania County as an example, not real coverage."""\n'
        '# Catawba County: rejected, 0 rows ever returned\n'
        'def helper():\n'
        '    """'"'"'JOHN LEE SMITH'"'"' -> '"'"'LEE'"'"' (a middle-name docstring example).\n'
        '    Also mentions Wake in prose, not code."""\n'
        '    return 1\n'
        'COUNTIES = {"mecklenburg": True}  # a real, active registry entry\n'
    )
    got = gm.counties_named_in([f])
    assert ("NC", "Mecklenburg") in got, "a real code entry (not a comment) must still match"
    for st, n in [("NC", "Transylvania"), ("NC", "Catawba"), ("NC", "Lee"), ("SC", "Lee"), ("NC", "Wake")]:
        assert (st, n) not in got, f"{(st, n)} only ever appeared in a comment/docstring"


def test_strip_comments_and_docstrings_keeps_real_string_literals():
    """The blanking must only ever remove COMMENT tokens and bare/docstring STRING statements --
    never a string literal that is actually part of the running code (a tuple/set/dict element,
    a function argument, an f-string), since those are exactly the real-coverage signal this
    function must keep matching."""
    src = (
        '# a comment naming Rowan\n'
        '"""module docstring naming Transylvania"""\n'
        'TOWNS = ("Moore", "Woodruff")  # Spartanburg-metro towns, not the real Moore County\n'
        'def f(county="Gaston"):\n'
        '    return county\n'
    )
    stripped = gm._strip_comments_and_docstrings(src)
    assert "Rowan" not in stripped
    assert "Transylvania" not in stripped
    assert '"Moore"' in stripped and '"Gaston"' in stripped  # real code, must survive


def test_built_in_code_known_false_positives_not_silently_fixed():
    """2026-10-19 audit of built_in_code()'s real output against the actual producer files:
    comment-stripping (the two tests above) fixes the jail_booking Lee NC/SC false positive (a
    name-parsing docstring example in scrapers/national/jail_bookings.py) and, as a bonus, a
    previously-known Gaston/condemned rejection-comment false positive. It does NOT fix three
    other confirmed false positives below, because each is a match inside REAL CODE (a string
    literal in a collection of place names that happens to share a name with an unrelated county),
    which would need per-file semantic knowledge of what the collection represents -- something
    this text-grep approach has no way to determine without a fragile, unvalidated per-file
    allowlist. This test pins down the exact mechanism so it can't silently regress further or get
    "fixed" by accident without the fix being deliberate and re-validated against the 1,676 other
    (county, column) pairs that currently rely on this same function:
      - condemned still credits ('NC', 'Moore') via scrapers/counties_sc/spartanburg_condemned.py's
        `_local` set of Spartanburg-metro SC town names (includes the real town "Moore, SC",
        zero relation to Moore County, NC).
      - condemned still credits ('NC', 'Davidson') via
        scrapers/city_websites/charlotte_open_data.py's `_MUNICIPALITIES` tuple of
        Mecklenburg-metro town names (includes the town of Davidson, NC, zero relation to
        Davidson County, NC).
      - jail_booking still credits ('NC', 'Cherokee') via scrapers/national/jail_bookings.py's own,
        genuinely real `("SC", "Cherokee", "zuercher", "cherokee-so-sc")` adapter-registry entry --
        a real SC Cherokee producer exists, but the regex is state-blind (it only checks whether
        the literal word "Cherokee" appears, not which state tuple it's paired with), so it also
        credits NC's unrelated Cherokee County with the same real entry.
      - jail_booking also credits ('SC', 'Lee') -- the mirror of the Cherokee case above, same
        state-blind mechanism, opposite direction: a real NC Lee producer (see 2026-11-16 UPDATE
        below) makes the bare word "Lee" true in the stripped text, and counties_named_in()'s own
        docstring says plainly a name shared by both states "counts for both: a grep cannot tell
        them apart." No SC Lee producer exists in any of these 3 files; this is permanent, not
        fixable by comment-stripping once real NC/Lee code exists, same as Cherokee.

    2026-11-10 UPDATE: the "previously-known Gaston/condemned rejection-comment false positive"
    this docstring used to also pin down is GONE, not regressed -- gastonia_code_enforcement.py
    (a real raw["condemned"]=True producer, confirmed by reading its code, missing from this
    tuple until the vacant/condemned coverage-gap research pass that day) was added to
    SPECS["condemned"].producers, and `county="Gaston"` is real code in that file, not a comment
    or docstring example. ('NC', 'Gaston') crediting 'condemned' now is a true positive, the
    opposite of the Moore/Davidson/Cherokee cases above, and belongs in
    test_built_in_code_drops_arcgis_distress_layers_false_credit_for_condemned_and_code_enforcement
    -style end-to-end assertions, not here.

    2026-11-16 UPDATE: the "jail_booking Lee NC/SC false positive" this docstring's opening line
    claims comment-stripping fixes is GONE for NC, same evolution as Gaston above, not a
    regression -- but it brought SC/Lee back as a DIFFERENT, Cherokee-shaped false positive (see
    the new bullet above), not a clean fix. scrapers/national/jail_bookings.py gained a real
    `("NC", "Lee", "dcn_export", "https://dcn.leecountync.gov/DCN/Inmates")` adapter-registry
    entry on 2026-11-10 (commit afae3501, an unrelated sos_agent hand-off batch) plus a real
    `elif state == "NC" and county == "Lee":` branch; enrichment_jail_bookings.py's own ROSTERS
    prose docstring independently names "Lee NC" too (2026-11-05 ROSTER SYNC). Both are literal
    code/real-data text, not a comment or docstring example, so counties_named_in()'s grep now
    correctly credits ('NC', 'Lee') -- a true positive -- but the same bare "Lee" text, being a
    county name shared with SC, mechanically also satisfies SC's pattern (the function's own
    docstring: "a grep cannot tell them apart"), reviving ('SC', 'Lee') as a live false positive.

    2026-11-17 UPDATE (round 15): the ('NC', 'Davidson')/charlotte_open_data.py false positive
    documented below for 'condemned' now ALSO reaches the 'vacant' and 'vacancy' columns --
    charlotte_open_data.py was added to both producers tuples this round (a real, separate fix;
    see the Spec's own 2026-11-17 note in gap_matrix.py and the dedicated test in
    test_built_in_code_drops_vacant_cohort_false_credit), which mechanically carries its
    pre-existing town-name false positive along with it. Not tracked by a THIRD assertion here --
    this test only reads SPECS["condemned"].producers; the 'vacant' version lives in its own
    sibling test, which is the right place for an end-to-end built_in_code() check anyway."""
    condemned_files = [gm.PKG / f for f in gm.SPECS["condemned"].producers if (gm.PKG / f).exists()]
    jail_files = [gm.PKG / f for f in gm.SPECS["jail_booking"].producers if (gm.PKG / f).exists()]
    condemned_counties = gm.counties_named_in(condemned_files)
    jail_counties = gm.counties_named_in(jail_files)

    assert ("NC", "Moore") in condemned_counties, (
        "known-unfixed: 'MOORE' the Spartanburg SC town, in spartanburg_condemned.py's town set"
    )
    assert ("NC", "Davidson") in condemned_counties, (
        "known-unfixed: 'DAVIDSON' the Mecklenburg-metro town, in charlotte_open_data.py's town tuple"
    )
    assert ("NC", "Cherokee") in jail_counties, (
        "known-unfixed: cross-state leak from jail_bookings.py's real SC Cherokee registry entry"
    )
    assert ("SC", "Lee") in jail_counties, (
        "known-unfixed: cross-state leak from jail_bookings.py's real NC Lee dcn_export entry "
        "(mirror of the Cherokee case -- see 2026-11-16 UPDATE above)"
    )
    # NC/Lee is now a TRUE positive here (see 2026-11-16 UPDATE above) -- a real dcn_export
    # adapter entry, not a stale docstring example.
    assert ("NC", "Lee") in jail_counties
    # Gaston is now a TRUE positive here (see 2026-11-10 UPDATE above) -- a real producer, not a
    # stale rejection comment.
    assert ("NC", "Gaston") in condemned_counties


def test_condemned_and_code_enforcement_producers_include_gastonia_kinston_rocky_mount():
    """2026-11-10 vacant/condemned coverage-gap research pass: three real raw["condemned"]/
    raw["vacancy"]/raw["code_enforcement"] writers were missing from these producer tuples
    entirely (confirmed by reading each file's own code, not its docstring) -- Gaston/Lenoir/
    Nash/Edgecombe read as unbuilt despite real, already-running code. Same bug class, same fix
    shape, as test_vacancy_producers_cover_all_three_real_writers above (that one was wave 5;
    this is the same omission recurring in two more tuples plus a fourth writer vacancy itself
    had not yet picked up)."""
    condemned = gm.SPECS["condemned"].producers
    vacancy = gm.SPECS["vacancy"].producers
    code_enf = gm.SPECS["code_enforcement"].producers
    assert any("gastonia_code_enforcement" in p for p in condemned)
    assert any("kinston_proposed_demolition" in p for p in condemned)
    assert any("rocky_mount_blight_survey" in p for p in condemned)
    assert any("gastonia_code_enforcement" in p for p in vacancy)
    assert any("gastonia_code_enforcement" in p for p in code_enf)


def test_arcgis_distress_layers_credit_respects_process_and_condemned_fields():
    """2026-10-19 follow-up to the Richland/condemned investigation (gap-matrix mislabel sweep):
    arcgis_distress_layers.py is a single multi-county, multi-PROCESS module (tax/storm_damage/
    flood_zone/demolition_permit/buyout_applicant/poor_condition/code_enforcement all share its one
    LAYERS registry) listed as a producer for both 'condemned' and 'code_enforcement'. The blanket
    counties_named_in() text match cannot see WHICH process a county's own Layer entry belongs to,
    so (before this fix) it credited a county for either column merely for being named anywhere in
    the file -- live-confirmed: Transylvania is named only on a storm_damage entry (zero
    code_enforcement/condemned=True entries at all) yet was credited 'built' for both columns;
    Lincoln/Guilford/Durham/Richland each have a real process='code_enforcement' entry but, same as
    Richland's own already-investigated case, ZERO condemned=True entry, yet were also credited
    'built' for condemned. _arcgis_distress_layers_credit() reads the LAYERS registry's own fields
    directly instead.

    2026-11-10 UPDATE: Guilford dropped out of code_enforcement's expected set. greensboro_code_
    housing (this test's 5th layer, Guilford's only process='code_enforcement' entry in this file)
    was REMOVED 2026-10-28 -- the file's own dated comment explains why (a 665-row "active" set
    whose newest case number was 2+ years stale, the sync had simply stopped) -- so this test went
    stale against that change rather than being updated alongside it. Guilford is correctly absent
    now; it has no other code_enforcement producer anywhere in the codebase.

    2026-11-16 UPDATE (round 9): Durham now ALSO sets condemned=True (and vacancy=True, checked by
    the sibling vacancy test below) via the new durham_unsafe_building entry -- its own Topic='Unsafe
    Building' subset of the SAME durham_open_code_violations service/sub-layer, peeled into a
    mutually-exclusive where-filtered entry (46 live cases, 2026-11-16). Not a mislabel fix like the
    others above; this is new real evidence for a genuinely condemnation-equivalent NC Minimum
    Housing Code action (see that Layer's own docstring).

    2026-11-17 UPDATE (round 14, vacant_structure "no source known" breadth pass): Richland now ALSO
    sets condemned=True, via the new columbia_code_demolition entry -- the same peel-a-sub-category
    technique as durham_unsafe_building, applied to columbia_code_vacant_boarded's own Problem field
    (126 live 'Residential Demolition'/'Commercial Demolition' cases, mutually exclusive with the
    sibling entry's narrowed where=). Same reasoning as Durham: a city demolition order is as strong
    "condemned" evidence as rockhill_code_demolition's own precedent, not a mislabel fix."""
    credit = gm._arcgis_distress_layers_credit()
    # York's rockhill_code_demolition + Durham's durham_unsafe_building + Richland's new
    # columbia_code_demolition (2026-11-17) are the only three entries setting condemned=True
    # in this entire file.
    assert credit["condemned"] == {("SC", "York"), ("NC", "Durham"), ("SC", "Richland")}
    # the 4 real process="code_enforcement" layers left after greensboro_code_housing's 2026-10-28
    # removal (columbia_code_vacant_boarded, durham_open_code_violations, lincoln_code_violations,
    # rockhill_code_housing/_exterior_major) -- durham_unsafe_building shares Durham's existing
    # membership in this SET, so it adds no new county here. lancaster_code_violations (round
    # 15/16, 2026-11-16) adds SC/Lancaster as a 5th real county.
    assert credit["code_enforcement"] == {
        ("SC", "Richland"), ("NC", "Durham"), ("NC", "Lincoln"), ("SC", "York"),
        ("SC", "Lancaster"),
    }


def test_built_in_code_drops_arcgis_distress_layers_false_credit_for_condemned_and_code_enforcement():
    """End-to-end: built_in_code()'s real output for 'condemned' no longer credits a county whose
    only textual evidence in arcgis_distress_layers.py is an entry tagged a different process (the
    exact mislabel mechanism the test above pins down), while counties with a genuine producer --
    in this file or another -- keep their credit.

    2026-11-10 UPDATE: Guilford moved from "has code_enforcement" to "has neither" -- its only
    code_enforcement producer, greensboro_code_housing, was REMOVED 2026-10-28 as stale (see
    test_arcgis_distress_layers_credit_respects_process_and_condemned_fields's dated note above).
    Gaston also joined this test's world: gastonia_code_enforcement.py (missing from the condemned/
    code_enforcement producer tuples until the 2026-11-10 coverage-gap pass) now genuinely credits
    it for both.

    2026-11-16 UPDATE (round 9): Durham moved from "code_enforcement only, no condemned" to "both",
    via the new durham_unsafe_building entry (real evidence, not a mislabel fix -- see the sibling
    test above).

    2026-11-17 UPDATE (round 14): Richland moved from "code_enforcement only, no condemned" to
    "both" too, via the new columbia_code_demolition entry (same mechanism as Durham's -- see the
    sibling test's 2026-11-17 note).

    2026-11-17 UPDATE (round 15): Mecklenburg's charlotte_open_data.py was added to the 'vacant'/
    'vacancy' producers tuples (previously only in 'condemned') -- a producers-tuple-symmetry check
    across all 11 named producer files, same bug class as round 14's Richland/Henderson fixes,
    found by re-running that round's own "diff a producer's condemned/vacancy/vacant coverage
    against itself" check. See that test function below."""
    built = gm.built_in_code()
    # false positives removed: named in the file, but on an unrelated-process entry only
    for st, co in (("NC", "Transylvania"), ("NC", "Buncombe"), ("NC", "Burke"), ("NC", "New Hanover"),
                   ("SC", "Greenville"), ("SC", "Greenwood"), ("SC", "Laurens"), ("SC", "Pickens")):
        assert (st, co) not in built["condemned"], f"{st}/{co} has no condemned=True entry anywhere"
    for st, co in (("NC", "Transylvania"), ("NC", "Burke"), ("SC", "Greenville"), ("SC", "Greenwood"),
                   ("SC", "Laurens"), ("SC", "Pickens")):
        assert (st, co) not in built["code_enforcement"], f"{st}/{co} has no code_enforcement entry anywhere"
    # Guilford has neither signal now -- its only producer is gone, not merely mislabeled.
    assert ("NC", "Guilford") not in built["condemned"] and ("NC", "Guilford") not in built["code_enforcement"]
    # real producers (in this file, via condemned=True / process='code_enforcement', or via another
    # file entirely) keep their credit
    assert ("SC", "York") in built["condemned"] and ("SC", "York") in built["code_enforcement"]
    assert ("SC", "Spartanburg") in built["condemned"]            # spartanburg_condemned.py
    assert ("NC", "Henderson") in built["condemned"]              # hendersonville_vacant_structures.py
    assert ("NC", "Mecklenburg") in built["condemned"]            # charlotte_open_data.py
    assert ("NC", "Gaston") in built["condemned"]                 # gastonia_code_enforcement.py (added 2026-11-10)
    assert ("NC", "Gaston") in built["code_enforcement"]          # gastonia_code_enforcement.py (added 2026-11-10)
    assert ("NC", "Lincoln") in built["code_enforcement"]         # lincoln_code_violations (this file)
    assert ("NC", "Durham") in built["code_enforcement"]          # durham_open_code_violations (this file)
    assert ("NC", "Durham") in built["condemned"]                 # durham_unsafe_building (added 2026-11-16)
    assert ("SC", "Richland") in built["condemned"]               # columbia_code_demolition (added 2026-11-17)
    assert ("NC", "Buncombe") in built["code_enforcement"]        # asheville_code_enforcement.py (a DIFFERENT file)
    # Lincoln DOES have a real code_enforcement producer but no condemned=True entry -- the
    # narrower, opposite-direction half of the same mislabel. Durham and Richland both dropped out
    # of this set (2026-11-16/2026-11-17, see above): each now has a real condemned entry too.
    for st, co in (("NC", "Lincoln"),):
        assert (st, co) not in built["condemned"], f"{st}/{co} has a code_enforcement entry, not a condemned one"


def test_charlotte_open_data_vacant_vacancy_producers_tuple_symmetry_round15():
    """2026-11-17 (round 15, producers-tuple symmetry re-check): charlotte_open_data.py's
    fof_ordered branch has written a real raw["vacancy"] wrapper AND raw["gis"]["vacant"] mirror
    since its own 2026-10-20 docstring note (same shape as hendersonville_vacant_structures.py's
    dual-key convention), but the file was only ever in the 'condemned' Spec's producers tuple --
    never 'vacant' or 'vacancy'. Pins the fix: Mecklenburg now reads built for all three sibling
    columns via built_in_code()'s plain counties_named_in() text match over this one file (no
    arcgis_distress_layers.py-style LAYERS registry involved here, so no precise-credit override
    needed). This does NOT move any cell on the current gap_list -- Mecklenburg is not in the
    "no source known" bucket (its board already carries real rows, so classify_cell() reads
    `ran=True` before ever reaching the static producers-tuple check this test covers) -- it is a
    correctness fix for what the static credit itself says, verified here so it is caught before
    it does matter (e.g. after a from-scratch board rebuild)."""
    built = gm.built_in_code()
    assert ("NC", "Mecklenburg") in built["condemned"]  # pre-existing, unchanged by this fix
    assert ("NC", "Mecklenburg") in built["vacant"]      # NEW this round
    assert ("NC", "Mecklenburg") in built["vacancy"]     # NEW this round


def test_vacant_cohort_credit_reads_real_registries_not_text():
    """2026-10-19 vacant-sweep follow-up, same bug class as the condemned/code_enforcement fix
    above: enrichment_arcgis.py is a producer of 'vacant', but it also carries NC_GIS/SC_GIS --
    per-county parcel/address/owner/deed-lookup registries used for a dozen unrelated columns --
    so a blanket counties_named_in() text match over this one file alone credits 69 counties
    'built' for vacant (live-measured) when the real vacant-cohort flag (_cohort_flags()'s
    VacantImpro read) is only ever populated for a county in the module's own
    `_COHORT_FLAG_COUNTIES` -- today just Gaston. _vacant_cohort_credit() reads that frozenset
    directly, plus spartanburg_vacant.py's own hardcoded single-county literal, instead of
    trusting the blanket file-level name match either file's many unrelated registries/mentions
    would otherwise manufacture."""
    credit = gm._vacant_cohort_credit()
    assert credit == {("NC", "Gaston"), ("SC", "Spartanburg")}


def test_built_in_code_drops_vacant_cohort_false_credit():
    """End-to-end: built_in_code()'s real output for 'vacant' no longer credits a county whose
    only textual evidence is co-location in enrichment_arcgis.py's NC_GIS/SC_GIS registries
    (used for unrelated columns, not the vacant cohort flag), while the two counties with a
    genuine vacant producer, and nc_lincoln_bulk.py's own untouched single-county credit, keep
    theirs.

    2026-11-11 UPDATE (same shape as the 2026-11-10 UPDATE on
    test_built_in_code_known_false_positives_not_silently_fixed above, for 'condemned'/Gaston):
    SC/Richland and SC/York move from "known false positive, must stay absent" to "true positive,
    must stay present" -- NOT a regression. The vacant/vacancy breadth pass that day gave
    arcgis_distress_layers.py a real, precise Layer.vacancy=True opt-in for exactly two of its
    ~26 entries (columbia_code_vacant_boarded -- Richland SC, where= pre-filtered to Boarded
    Building/Demolition/Vacant Building cases; rockhill_code_demolition -- York SC, a dedicated
    demolition sub-layer), read back here via _arcgis_distress_layers_credit()'s new 'vacant' key
    (see its own and _ARCGIS_DISTRESS_LAYERS_REL's docstrings) -- not the blanket file-name match
    this test originally guarded against. The same pass also gave three more real, single/few-
    county NC producers (gastonia_code_enforcement.py/Gaston, kinston_proposed_demolition.py/
    Lenoir, rocky_mount_blight_survey.py/Nash+Edgecombe) a raw['gis']['vacant'] mirror of the
    raw['vacancy'] wrapper each already wrote -- their blanket text-match credit was already
    correct (each file only ever names its own real county/counties), so they are new true
    positives here too, not a refinement like Richland/York's.

    2026-11-16 UPDATE (round 9): Durham joins the real-producer list via the new
    durham_unsafe_building entry's vacancy=True opt-in (same mechanism as Richland/York, not a
    text-match refinement -- see test_arcgis_distress_layers_credit_respects_process_and_condemned_
    fields's own 2026-11-16 note). Wake also joins -- unlike Durham, this one IS the ordinary
    blanket-text-match path (wake_code_cases.py literally names "Wake", same mechanism as
    nc_lincoln_bulk.py/Lincoln already in this same `other_files` list), now a true positive since
    wake_code_cases.py's own fix this round made it a real (if currently thin) writer of
    raw["gis"]["vacant"].

    2026-11-17 UPDATE (round 15): Mecklenburg moves from this test's own "false positive, must stay
    absent" list to a true positive, same Wake/Durham shape -- charlotte_open_data.py was added to
    the 'vacant' producers tuple this round (it was already a real, correctly-wired writer of
    raw["gis"]["vacant"] via its fof_ordered branch, just missing from this one tuple; see that
    Spec's own 2026-11-17 note in gap_matrix.py), so the ordinary blanket-text-match path now picks
    up its own real county correctly. Not a refinement like Richland/York's precise-credit path --
    an ordinary single-county file genuinely naming its own county, same as Wake/Lincoln above.

    Also 2026-11-17 (round 15): found this test's own Henderson assertion was ALREADY stale before
    this round even started -- round 14 (commit 3f10661a, the same day) added
    hendersonville_vacant_structures.py to the 'vacant' producers tuple (see that Spec's own
    2026-11-16/17 notes in gap_matrix.py: Henderson's hendersonville_vacant_structures.py was
    always a correct 'condemned'/'vacancy' producer, just missing from 'vacant' alone), but never
    updated this negative-assertion list to match, so this test was silently broken on arrival --
    caught only now by this round's own full-suite run, not by round 14's targeted one. Moved
    Henderson out of the false-positive list below alongside Mecklenburg, since both are the exact
    same stale-test shape and this test already belongs to this round's scope.

    One more 2026-11-17 (round 15) consequence of the same charlotte_open_data.py addition: this
    file ALSO carries the pre-existing, deliberately-"known-unfixed" ('NC', 'Davidson') false
    positive that test_built_in_code_known_false_positives_not_silently_fixed already documents for
    the 'condemned' column -- its `_MUNICIPALITIES` tuple of Mecklenburg-metro town names includes
    the town of Davidson, NC, zero relation to Davidson County, NC, and that mismatch is in real
    code (a place-name collection), not a comment or docstring example, so comment-stripping cannot
    fix it (same reasoning that test's own docstring already gives for why this class of false
    positive is accepted rather than chased with a fragile per-file allowlist). Adding the file to
    'vacant'/'vacancy' mechanically carries the SAME false positive into these two sibling columns
    -- not a new bug, the same accepted one now reachable from two more columns. Real-world blast
    radius stays the same low-stakes shape it already has for 'condemned': Davidson County's own
    'vacant'/'vacancy' cells (5,469 est_rows, already built-but-low-yield via OTHER real producers'
    blanket credit before this round, not a 'no source known' cell either column was ever counted
    in) read "code covers this county but nothing landed here, screen and stamp it" -- never a
    false CONFIRMED-clean claim. Acknowledged below rather than silently tolerated or papered over
    with a bespoke precise-credit filter that would be exactly the "fragile, unvalidated per-file
    allowlist" the sibling test's own docstring already argues against building."""
    built = gm.built_in_code()
    # false positives removed: named only via enrichment_arcgis.py's unrelated GIS registries
    for st, co in (("NC", "Buncombe"), ("NC", "Burke"),
                   ("NC", "Cleveland"), ("SC", "Greenville")):
        assert (st, co) not in built["vacant"], f"{st}/{co} has no real vacant-cohort producer"
    # real producers keep their credit
    assert ("NC", "Gaston") in built["vacant"]           # gastonia_code_enforcement.py (condemned branch)
    assert ("NC", "Lenoir") in built["vacant"]            # kinston_proposed_demolition.py (utility-cutoff basis)
    assert ("NC", "Nash") in built["vacant"]              # rocky_mount_blight_survey.py (vacant_boarded class)
    assert ("NC", "Edgecombe") in built["vacant"]         # rocky_mount_blight_survey.py (vacant_boarded class)
    assert ("SC", "Spartanburg") in built["vacant"]      # spartanburg_vacant.py (single-county, correct as-is)
    assert ("SC", "Richland") in built["vacant"]          # arcgis_distress_layers.py: columbia_code_vacant_boarded
    assert ("SC", "York") in built["vacant"]              # arcgis_distress_layers.py: rockhill_code_demolition
    assert ("NC", "Durham") in built["vacant"]            # arcgis_distress_layers.py: durham_unsafe_building (2026-11-16)
    assert ("NC", "Lincoln") in built["vacant"]           # nc_lincoln_bulk.py -- untouched, not part of this bug
    assert ("NC", "Wake") in built["vacant"]              # wake_code_cases.py -- blanket text match (2026-11-16)
    assert ("NC", "Mecklenburg") in built["vacant"]       # charlotte_open_data.py -- blanket text match (2026-11-17)
    assert ("NC", "Henderson") in built["vacant"]         # hendersonville_vacant_structures.py -- added round 14, test was stale
    assert ("NC", "Davidson") in built["vacant"], (
        "known-unfixed: 'DAVIDSON' the Mecklenburg-metro town, in charlotte_open_data.py's town "
        "tuple -- same pre-existing false positive test_built_in_code_known_false_positives_"
        "not_silently_fixed already pins for 'condemned', now also reachable via 'vacant' "
        "(round 15 added charlotte_open_data.py to this producers tuple)"
    )
    assert len(built["vacant"]) == 13


def test_sc_heir_estate_parcel_cache_credit_reads_real_registry_not_text():
    """2026-10-19 wave3 follow-up, same bug class as the condemned/code_enforcement and vacant
    fixes above: sc_heir_estate_parcel_cache.py is a real producer of 'heir_estate' for ~18-20 SC
    counties, but that list is resolved entirely at RUNTIME inside its own _candidate_counties()
    (from parcel_cache's PARCEL_LAYERS/SC_DUAL_LAYERS registries), never written as literal
    county-name text in the file -- the few county names that DO appear there (Greenville,
    Dorchester) live only in its module docstring, which counties_named_in()'s own
    _strip_comments_and_docstrings() removes before matching. Live-measured: the blanket grep over
    this file alone credits ZERO counties. _sc_heir_estate_parcel_cache_credit() calls the
    scraper's own _candidate_counties() directly instead."""
    credit = gm._sc_heir_estate_parcel_cache_credit()
    # the three counties nc_heir_estate_parcels.py already covers live are excluded by the
    # scraper's own _ALREADY_LIVE_COVERED, never double-sourced
    for st, co in (("SC", "York"), ("SC", "Charleston"), ("SC", "Beaufort")):
        assert (st, co) not in credit
    # the 6 counties this bug was hiding as "sourced-not-built"
    for co in ("Greenville", "Orangeburg", "Dorchester", "Jasper", "Aiken", "Greenwood"):
        assert ("SC", co) in credit
    assert all(st == "SC" for st, _co in credit)


def test_built_in_code_adds_sc_heir_estate_parcel_cache_credit():
    """End-to-end: built_in_code()'s real output for 'heir_estate' now credits the 6 SC counties
    this bug hid (already fully served by the shipped sc_heir_estate_parcel_cache.py producer).
    henderson_foreclosure_parcels.py's own (genuine, untouched) text-grep credit for NC/Henderson
    survives too. nc_heir_estate_parcels.py's real coverage was flagged here, at the time, as "a
    SEPARATE pre-existing instance of this same dynamic-list blind spot in a DIFFERENT producer
    file -- out of scope here" -- the 2026-10-19 systematic sweep this comment called for found
    it (its "NC:Cleveland"-style literals are colon-prefixed, which counties_named_in()'s own
    pattern does not match) and fixed it with _nc_heir_estate_parcels_credit(), reading its own
    COUNTY_GIS keys directly. SC/Beaufort, SC/Charleston and SC/York -- the 3 counties that bug
    USED to reach by the wrong mechanism (a false match on sc_heir_estate_parcel_cache.py's own
    _ALREADY_LIVE_COVERED exclusion-list literal, which this fix's own sc_heir_estate_parcel_cache
    credit already corrected to exclude) -- are now legitimately credited again, through the
    REAL mechanism: they are 3 of nc_heir_estate_parcels.py's own 9 real SC COUNTY_GIS entries,
    exactly the "stay on nc_heir_estate_parcels.py's live producer instead" the exclusion-list's
    own comment always said. NC/Beaufort is NOT one of COUNTY_GIS's 20 real keys (there is no
    "NC:Beaufort" entry, only "SC:Beaufort"), so it correctly stays uncredited."""
    built = gm.built_in_code()
    for co in ("Greenville", "Orangeburg", "Dorchester", "Jasper", "Aiken", "Greenwood"):
        assert ("SC", co) in built["heir_estate"], f"SC/{co} should be credited by the parcel-cache producer"
    assert ("NC", "Henderson") in built["heir_estate"]  # henderson_foreclosure_parcels.py, untouched
    # now legitimately credited via nc_heir_estate_parcels.py's own real COUNTY_GIS entries
    for st, co in (("SC", "Beaufort"), ("SC", "Charleston"), ("SC", "York")):
        assert (st, co) in built["heir_estate"], f"{st}/{co} is a real nc_heir_estate_parcels.py COUNTY_GIS entry"
    # NC/Beaufort is not: COUNTY_GIS has no "NC:Beaufort" key, only "SC:Beaufort"
    assert ("NC", "Beaufort") not in built["heir_estate"]


def test_county_lien_sweep_marriage_credit_reads_real_registry_not_text():
    """2026-10-19 wave3 follow-up, same bug class again: enrichment_county_lien_sweep.py's
    SWEEP_COUNTIES registry (and the shared rod/county_sweeps.py constants it draws on, e.g.
    HOSTED_CCHS) names 24 counties in plain code text, but only ONE of them (NC/Beaufort) carries
    a kind=='marriage' Job -- every other name (Orange/Stanly/Surry NC, Sumter/Oconee SC, the 17
    HOSTED_CCHS tenants) is there for the unrelated 'lien' job only. A blanket counties_named_in()
    grep over this file pair can't tell the difference; _county_lien_sweep_marriage_credit() reads
    SWEEP_COUNTIES' own Job.kind field directly instead. (Watauga joined Beaufort as a second real
    marriage job 2026-10-19, same wave3 follow-up, task 3's near-zero-cost LRSearch win; Johnston
    joined as a third, 2026-10-21, via the Tyler EagleWeb BookTypeID='M' sweep.)"""
    credit = gm._county_lien_sweep_marriage_credit()
    assert credit == {("NC", "Beaufort"), ("NC", "Watauga"), ("NC", "Johnston")}


def test_built_in_code_drops_county_lien_sweep_false_marriage_credit():
    """End-to-end: built_in_code()'s real output for 'marriage_license' now credits NC/Beaufort
    (enrichment_county_lien_sweep.py's real, if dormant, marriage sweep) but none of the 23 other
    counties a blanket grep over enrichment_county_lien_sweep.py/rod/county_sweeps.py would
    otherwise manufacture from the unrelated 'lien' job, while enrichment_register_checks.py's/
    rod/register_checks.py's own text-grep credit for this column keeps its credit."""
    built = gm.built_in_code()
    assert ("NC", "Beaufort") in built["marriage_license"]
    # false positives that a naive blanket grep over the lien-sweep file pair would have added
    for st, co in (("NC", "Orange"), ("NC", "Stanly"), ("NC", "Surry"), ("NC", "Burke"),
                   ("NC", "Lincoln"), ("NC", "Henderson"), ("SC", "Sumter"), ("SC", "Oconee")):
        assert (st, co) not in built["marriage_license"], f"{st}/{co} has no marriage job, lien job only"
    # real register_checks.py text-grep credit (the Cott v4 family) keeps its credit
    assert ("NC", "Rowan") in built["marriage_license"]


def test_county_lien_sweep_lien_credit_reads_real_registry_not_text():
    """2026-11-17 ('no source known' probate/liens research round): the SAME SWEEP_COUNTIES
    registry's 'lien' job half (every entry except NC/Beaufort+Watauga's marriage-only rows and
    NC/Johnston's marriage-only row) was never credited to atty_rod_lien_checked/liens at all --
    this is the mirror image of _county_lien_sweep_marriage_credit() just above, filtering on
    kind=='lien' instead of kind=='marriage'."""
    credit = gm._county_lien_sweep_lien_credit()
    assert ("NC", "Johnston") not in credit, "Johnston has a marriage job only, no lien job"
    assert len(credit) == 32
    for st, co in (("NC", "Orange"), ("NC", "Stanly"), ("NC", "Surry"), ("NC", "Beaufort"),
                   ("NC", "Watauga"), ("NC", "Burke"), ("NC", "Lincoln"), ("NC", "Henderson"),
                   ("SC", "Sumter"), ("SC", "Oconee")):
        assert (st, co) in credit, f"{st}/{co} has a real lien job in SWEEP_COUNTIES"


def test_built_in_code_adds_county_lien_sweep_lien_credit():
    """End-to-end: built_in_code()'s real output for atty_rod_lien_checked/liens now credits
    enrichment_county_lien_sweep.py's real 'lien' job counties (raw['rod_lien_sweep'] with
    status+checked_at, the exact shape rod_checked() already recognizes above). NC/Johnston is
    deliberately NOT asserted absent here: it has a real, unrelated, pre-existing credit of its own
    (enrichment_generic_rod.py's literal VENDORS-style entry for nc_tyler, flag-gated off by
    FORECLOSURE_NC_TYLER_ROD -- a flag-off hold, not missing code, same shape as the NC Harris
    marriage credit below), so it is not a clean negative case for THIS credit specifically; see
    test_county_lien_sweep_lien_credit_reads_real_registry_not_text for the one that is (reading
    _county_lien_sweep_lien_credit()'s own output directly)."""
    built = gm.built_in_code()
    for col in ("atty_rod_lien_checked", "liens"):
        assert ("NC", "Orange") in built[col] and ("SC", "Oconee") in built[col]
        assert ("NC", "Wake") not in built[col], "Wake is in neither SWEEP_COUNTIES job nor any other producer here"


def test_rod_chain_contributes_no_blanket_county_credit():
    """2026-11-17 over-crediting audit: 'liens' Spec lists enrichment_rod_chain.py as a producer
    and that module only ever writes raw['rod_chain'] (never raw['rod']/raw['liens'] -- confirmed
    by reading src/foreclosure_scraper/enrichment_rod_chain.py line 287), so round17's own
    follow-up note worried this was a blanket-text over-credit (the opposite-direction bug from
    everything else that round fixed): any county the file's text happens to NAME would get
    'built=code' credit for a signal the file itself never stamps on a row.

    It isn't. enrichment_rod_chain.py carries NO per-county registry of its own at all -- it
    imports ROD_CONFIG/RENDER_ROD_CONFIG/CHAIN_ONLY_CONFIG from enrichment_generic_rod.py and
    dispatches purely off chain_registry()'s keys (no county literal anywhere in real code). The
    only county NAMES anywhere in the file live inside its module docstring's prose run-log
    example ("the sixth county (Alamance, Alexander, Avery, Bertie, Buncombe, Clay)") -- a
    comma-separated list with no quoting and no 'County' suffix, so it fails
    _county_patterns()'s own match shape (quoted/path-like, or 'X County') even BEFORE
    _strip_comments_and_docstrings() removes it. counties_named_in() on this file alone, against
    both the raw and the stripped text, returns the empty set."""
    hits_stripped = gm.counties_named_in([gm.PKG / "enrichment_rod_chain.py"])
    assert hits_stripped == set()
    pats = gm._county_patterns()
    raw_text = (gm.PKG / "enrichment_rod_chain.py").read_text()
    hits_raw = {(st, n) for st, n, rx in pats if rx.search(raw_text)}
    assert hits_raw == set(), "no county name matches even unstripped -- not a stripping artifact"


def test_built_in_code_liens_credit_unaffected_by_removing_rod_chain_producer():
    """End-to-end companion to the test above: since enrichment_rod_chain.py contributes the empty
    set on its own, it cannot change ANY union it is added to -- confirmed directly rather than
    trusting that set-theory argument alone. The blanket counties_named_in() portion of
    built_in_code()['liens']/['atty_rod_lien_checked'] (the part before |-ing in
    _county_lien_sweep_lien_credit()) is byte-identical whether or not enrichment_rod_chain.py is
    in the producers tuple. Verdict: NOT an over-crediting bug -- no fix made. (The real source of
    'built=code' for counties like NC/Mecklenburg -- 39,871 rows, confirmed live 2026-11-17 via
    iter_board_rows() to carry zero raw.rod/raw.rod_chain/raw.liens/raw.rod_lien_sweep anywhere on
    the board today -- is enrichment_generic_rod.py's OWN text: that file is a real, correctly-
    declared producer for both columns, but its source also carries RENDER_ROD_CONFIG and
    CHAIN_ONLY_CONFIG literal county entries that enrich_generic_rod() itself never acts on, read
    instead by other modules (enrichment_nc_rod_render.py, enrichment_rod_chain.py). That is the
    same 'flag-off hold, not missing code' shape this file already credits on purpose elsewhere
    (NC/Mecklenburg+Carteret's own nc_harris marriage_license credit just below; NC/Johnston's
    nc_tyler credit in the test above) and already reads correctly against the project's own
    Bucket-C rod-adapter audit -- a documentation note, not a second bug, and out of scope to
    'fix' here since it changes no cell's classification.)"""
    pats = gm._county_patterns()
    liens_spec = gm.SPECS["liens"]
    base_files = [gm.PKG / f for f in liens_spec.producers if f not in gm._COUNTY_LIEN_SWEEP_REL]
    with_chain = gm.counties_named_in([f for f in base_files if f.exists()], pats)
    without_chain = gm.counties_named_in(
        [f for f in base_files if f.exists() and f.name != "enrichment_rod_chain.py"], pats)
    assert with_chain == without_chain
    assert ("NC", "Mecklenburg") in with_chain, "sanity: Mecklenburg IS credited (via generic_rod.py's text)"


def test_built_in_code_adds_nc_harris_marriage_credit():
    """End-to-end: built_in_code()'s real output for 'marriage_license' now credits NC/Mecklenburg
    and NC/Carteret (rod/nc_harris.marriage_search, wired live in main.py via
    enrichment_nc_rod_render.enrich_marriage_render -- OFF today only by the FORECLOSURE_NC_HARRIS_
    ROD/MARRIAGE flags defaulting to 0, a cost hold per HANDOFF item 82, not missing code). Live-
    reconfirmed 2026-10-20: meckrod.manatron.com/RealEstate + /Marriage answers a real
    marriage_search('Mecklenburg', ...) with no login and no CAPTCHA (108 rows for a common name) --
    a SEPARATE app on that host from the curl_cffi rod/aumentum.py /External/LandRecords path, which
    is still broken (county-side ASP.NET 'Session state is not available in this context')."""
    built = gm.built_in_code()
    assert ("NC", "Mecklenburg") in built["marriage_license"]
    assert ("NC", "Carteret") in built["marriage_license"]


def test_built_in_code_adds_ustaxdata_tax_aging_credit():
    """End-to-end: built_in_code()'s real output for 'tax_aging_surfaced' now credits NC/Robeson,
    NC/Alexander and NC/Rockingham (enrichment_ustaxdata_tax_search.py's TENANTS/NAME_SEARCH_TENANTS
    -- its raw['ustaxdata_delinquent_tax'] block is in enrichment_tax_owed.py's _LIVE_ROLL_BLOCKS,
    so Pass B there folds it into raw['tax_owed'], and enrichment_tax_aging.py -- tax_aging_
    surfaced's only producer, wired every run, no county restriction -- derives raw[
    'tax_aging_surfaced'] from that). Found chasing a 2026-10-20 Rockingham "sourced-not-built" ask;
    live-reconfirmed the same day: a real enrich_ustaxdata() name-search call against live
    Rockingham board rows returned real, address-confirmed, multi-year (2019-2026) bill histories
    for 2 of several real owners tried. Not found by the blanket counties_named_in() grep because
    neither real producer (enrichment_tax_owed.py, enrichment_tax_aging.py) names a county at all."""
    built = gm.built_in_code()
    assert ("NC", "Robeson") in built["tax_aging_surfaced"]
    assert ("NC", "Alexander") in built["tax_aging_surfaced"]
    assert ("NC", "Rockingham") in built["tax_aging_surfaced"]


def test_built_in_code_leaves_ustaxdata_two_year_and_multiyear_uncredited():
    """The SAME vendor's two OTHER gap-list columns (two_year_delinquent,
    multi_year_delinquent_tax) must NOT gain a false credit from this fix: no code path writes
    either column's own literal raw key (raw['two_year_delinquent'], raw[
    'multi_year_delinquent_tax']) from ustaxdata_delinquent_tax/tax_owed data -- only
    tax_aging_surfaced is a real, derived chain. This is the same vendor-attribution imprecision
    already documented for rollback_exposure against this exact vendor (enrichment_ustaxdata_
    tax_search.py's own docstring), a real separate gap, not a credit bug for THIS fix to close."""
    built = gm.built_in_code()
    assert ("NC", "Rockingham") not in built.get("two_year_delinquent", set())
    assert ("NC", "Rockingham") not in built.get("multi_year_delinquent_tax", set())


def test_built_in_code_drops_retired_probate_search_false_credit():
    """2026-10-19 systematic producers-tuple sweep (the follow-up this session's own 5 one-at-a-
    time catches called for): enrichment_probate_search.py was RETIRED 2026-10-09 (main.py never
    runs it; the one script that still imports it, scripts/enrich_board.py, is itself one of the
    ad-hoc scripts main.py's own enrich_deed_chain comment says were never wired into the real
    run) but was still listed as a 'probate' producer, and its own SC_PROBATE_COUNTY_CODES literal
    is real code text (not a comment), so a blanket grep over it credited 10 counties that never
    actually get probate-searched by any code that runs. 3 of them (SC Bamberg, SC Greenville, SC
    York) had no other 'probate' producer at all.

    2026-11-15 UPDATE: SC York is now a TRUE positive, not a false one -- a fresh gap_matrix run
    found York "sourced-not-built" for this column with 80,242 estimated affected rows (the single
    biggest gap on the whole board), and the real live site (scpublicnotices.com) covers all 46 SC
    counties, not just the 11 sc_public_notices.py's _COUNTIES/_IN_SCOPE had been scoped to --
    live-confirmed (2026-11-15: all 46 county checkbox labels present, including York, exact
    title-case match). Added York (plus Sumter/Barnwell/Richland/Calhoun/Lancaster/Newberry/
    Greenwood/Aiken, the same gap's other 8 counties) to those tuples, so York now has a real,
    running probate producer -- same evolution as Gaston/condemned's own 2026-11-10 UPDATE just
    above test_built_in_code_known_false_positives_not_silently_fixed. Bamberg and Greenville were
    untouched at that point and remained genuine false positives THERE (from
    enrichment_probate_search.py's retired credit specifically).

    2026-11-17 UPDATE: both are now ALSO true positives, from two different real producers added
    this round (see 'probate' Spec's own 2026-11-17 comment) -- Greenville via
    column_legal_notices.py's verified-live SC_PROBATE_EXTRA_COUNTIES (3 real notices/year,
    live-checked 2026-10-23), Bamberg via sc_probate_notices.py/publicnoticesc_estates.py's
    genuinely statewide (all 46 SC counties) Notice-to-Creditors coverage
    (_sc_probate_notice_statewide_credit()). The right thing this test still protects -- the
    retired module itself never comes back -- is checked directly below instead of via two
    counties that happen to have no OTHER producer; that coincidence no longer holds for any SC
    county today."""
    built = gm.built_in_code()
    assert "enrichment_probate_search.py" not in gm.SPECS["probate"].producers, \
        "the retired module (main.py never runs it) must never be re-added as a producer"
    # Bamberg and Greenville are genuine true positives now, each via a real, still-running
    # producer added 2026-11-17 -- not the retired module's stale SC_PROBATE_COUNTY_CODES credit
    assert ("SC", "Bamberg") in built["probate"] and ("SC", "Greenville") in built["probate"]
    # sc_public_notices.py's own real text-grep credit (this column's original live producer) stays
    assert ("SC", "Anderson") in built["probate"] and ("NC", "Beaufort") in built["probate"]
    # York is a TRUE positive (2026-11-15 UPDATE above) -- a real producer, not stale credit
    assert ("SC", "York") in built["probate"]


def test_column_probate_credit_reads_real_registries_not_text():
    """2026-11-17 ('no source known' probate/liens research round): column_legal_notices.py's own
    verified-live SC/NC estate-lane county lists (SC_PROBATE_EXTRA_COUNTIES,
    SC_PROBATE_COVERED_COUNTIES, NC_ESTATE_EXTRA_COUNTIES) were never credited to the 'probate'
    column, even though quiet_title's own statewide_except already reads the SC pair's complement.
    A blanket producers-tuple text match over the whole file would over-credit: it also carries the
    separately-scoped foreclosure/tax/quiet-title county lists."""
    from foreclosure_scraper.scrapers.newspapers import column_legal_notices as cln
    credit = gm._column_probate_credit()
    assert credit == ({("SC", c) for c in cln.SC_PROBATE_EXTRA_COUNTIES}
                       | {("SC", c) for c in cln.SC_PROBATE_COVERED_COUNTIES}
                       | {("NC", c) for c in cln.NC_ESTATE_EXTRA_COUNTIES})
    assert ("SC", "Chesterfield") in credit and ("SC", "Greenville") in credit


def test_sc_probate_notice_statewide_credit_is_all_46_sc_counties():
    """sc_probate_notices.py (own docstring: 'all 46, not only the 7-county footprint') and
    publicnoticesc_estates.py (own docstring: 'statewide list of estates being opened, all 46
    counties') are each genuinely statewide, but derive county from the estate case number's own
    embedded code via a SHARED import (sc_case_county.SC_COUNTY_BY_CODE) that neither file's own
    text repeats -- a blanket producers-tuple text match finds zero of the real 46."""
    credit = gm._sc_probate_notice_statewide_credit()
    assert len(credit) == 46
    for co in ("Williamsburg", "Jasper", "Clarendon", "Dillon", "Edgefield", "Abbeville", "Bamberg",
               "Allendale", "Lee", "Saluda", "McCormick", "Hampton", "Fairfield"):
        assert ("SC", co) in credit, f"SC/{co} missing from the statewide 46-county credit"


def test_built_in_code_adds_column_probate_and_statewide_notice_credit():
    """End-to-end: built_in_code()'s real output for 'probate' now credits every one of the 14 SC
    counties the 2026-11-16 gap list's own 'no source known' bucket named for this column (none of
    them had any live probate producer before this round), via the two new precise credits added
    above, while the column's original real producer (sc_public_notices.py) keeps its own credit."""
    built = gm.built_in_code()
    for co in ("Williamsburg", "Jasper", "Clarendon", "Dillon", "Edgefield", "Chesterfield",
               "Abbeville", "Bamberg", "Allendale", "Lee", "Saluda", "McCormick", "Hampton",
               "Fairfield"):
        assert ("SC", co) in built["probate"], f"SC/{co} was the 2026-11-16 gap list's own no-source-known cell"
    assert ("SC", "Anderson") in built["probate"] and ("NC", "Beaufort") in built["probate"]


def test_nc_heir_estate_parcels_credit_reads_county_gis_keys_not_text():
    """2026-10-19 systematic sweep: nc_heir_estate_parcels.py's COUNTY_GIS dict is keyed by
    literal 'ST:County' strings ('NC:Cleveland', 'SC:York', ...), but counties_named_in()'s own
    regex needs a quote/slash/underscore immediately before the name (or a trailing 'County'
    suffix) -- a colon satisfies neither, so its blanket text match is empty despite 20 real
    entries. _nc_heir_estate_parcels_credit() reads COUNTY_GIS's own keys directly instead.

    2026-11-15: the Greene-County parno-collision fix added a real code comparison,
    `county.strip().lower() == "greene"`, whose quoted literal DOES satisfy the blanket
    regex's quote-before-name rule -- so counties_named_in() now also finds ('NC', 'Greene')
    via this one incidental string, unlike every other county here (which only the COUNTY_GIS
    keys name). This is harmless in practice: built_in_code()'s real 'heir_estate' column
    (see the heir_spec block a few hundred lines up) explicitly drops this file from the
    files it runs counties_named_in() over and replaces that contribution with
    _nc_heir_estate_parcels_credit() alone, so this isolated call's result never reaches the
    real crediting path. Asserting the new, narrower truth instead of rewriting a working,
    clear comparison just to dodge a diagnostic regex.

    2026-11-16: the NC Hoke fix (commit 41da6190, this same session) added a real, dedicated
    `COUNTY_GIS["NC:Hoke"]` entry (its own live-GIS layer, not a stale statewide-mirror timeout) --
    20 real entries is now 21, a legitimate growth of the same registry this test already reads
    directly, not a regression."""
    assert gm.counties_named_in([gm.PKG / gm._NC_HEIR_ESTATE_PARCELS_REL]) == {("NC", "Greene")}
    credit = gm._nc_heir_estate_parcels_credit()
    assert ("NC", "Cleveland") in credit and ("SC", "York") in credit
    assert ("NC", "Hoke") in credit
    assert len(credit) == 21


def test_built_in_code_adds_nc_heir_estate_parcels_credit():
    """End-to-end: built_in_code()'s real output for 'heir_estate' now credits every NC county
    nc_heir_estate_parcels.py's own COUNTY_GIS actually covers (not just Henderson, the one
    henderson_foreclosure_parcels.py's own text-grep credit already caught)."""
    built = gm.built_in_code()
    for co in ("Buncombe", "Burke", "Cleveland", "Gaston", "Lincoln", "McDowell", "Mitchell",
               "Polk", "Rutherford", "Transylvania"):
        assert ("NC", co) in built["heir_estate"], f"NC/{co} is a real COUNTY_GIS entry"
    assert ("NC", "Henderson") in built["heir_estate"]  # henderson_foreclosure_parcels.py, untouched


def test_rod_enrich_lien_priority_credit_reads_vendors_not_text():
    """2026-10-19 systematic sweep: 'lien_priority''s only producer, rod/enrich.py, carries no
    literal county-name text at all -- its VENDORS dict is built entirely at import time from
    rod/cchs.py, rod/aumentum.py, rod/cott.py and rod/kofile.py's own constants. A blanket grep
    over this one file finds nothing; _rod_enrich_lien_priority_credit() reads VENDORS' own keys
    directly instead."""
    assert gm.counties_named_in([gm.PKG / "rod/enrich.py"]) == set()
    credit = gm._rod_enrich_lien_priority_credit()
    assert ("NC", "Buncombe") in credit and ("SC", "Oconee") in credit
    assert len(credit) == 11


def test_built_in_code_adds_lien_priority_credit():
    """End-to-end: built_in_code()'s real output for 'lien_priority' is no longer empty -- it now
    credits every (state, county) pair rod/enrich.py's own VENDORS registry actually drives."""
    built = gm.built_in_code()
    assert built["lien_priority"] == gm._rod_enrich_lien_priority_credit()
    assert ("NC", "Mecklenburg") in built["lien_priority"]


def test_repeat_tax_loss_credit_is_the_full_state_county_universe():
    """2026-10-19 systematic sweep: enrichment_repeat_tax_loss.py's own enrich_repeat_tax_loss()
    loop takes li.county/li.state straight off whatever row it is handed, with no per-county
    registry, allowlist or skip-list anywhere in the file -- the same cross-parcel deed-chain join
    runs for every county, NC or SC. A blanket grep over this file finds zero literal county text;
    _repeat_tax_loss_credit() returns the full STATE_COUNTIES universe instead, since that is
    genuinely what the code already covers."""
    assert gm.counties_named_in([gm.PKG / "enrichment_repeat_tax_loss.py"]) == set()
    credit = gm._repeat_tax_loss_credit()
    assert ("NC", "Buncombe") in credit and ("SC", "Charleston") in credit
    assert len(credit) == len(gm.NC_COUNTIES) + len(gm.SC_COUNTIES)


def test_built_in_code_fills_repeat_tax_loss_credit():
    """End-to-end: built_in_code()'s real output for 'repeat_tax_loss' is no longer empty."""
    built = gm.built_in_code()
    assert built["repeat_tax_loss"] == gm._repeat_tax_loss_credit()


def test_nc_case_status_tyler_credit_is_every_nc_county():
    """2026-10-19 systematic sweep: enrichment_nc_case_status_tyler.py's own is_target() gates
    only on li.state == 'NC' plus a case number already on the row, never a county -- so its real
    coverage is every NC county, but a blanket grep over the file finds zero literal county text."""
    assert gm.counties_named_in([gm.PKG / "enrichment_nc_case_status_tyler.py"]) == set()
    credit = gm._nc_case_status_tyler_credit()
    assert credit == {("NC", c) for c in gm.NC_COUNTIES}


def test_built_in_code_adds_nc_case_status_tyler_credit_keeps_case_detail():
    """End-to-end: built_in_code()'s real output for 'child_support' now credits every NC county
    (enrichment_nc_case_status_tyler.py's own state-wide reach) on top of
    enrichment_case_detail.py's own (already-correct) SC_COUNTY_BY_CODE text-grep credit, which
    keeps its credit untouched."""
    built = gm.built_in_code()
    assert ("NC", "Alleghany") in built["child_support"]   # only via the Tyler state-wide fix
    assert ("SC", "Anderson") in built["child_support"]    # enrichment_case_detail.py, untouched


def test_deed_chain_credit_is_the_full_state_county_universe():
    """2026-10-19 systematic sweep: enrichment_deed_chain.py is the sole producer of all 4 of
    deed_chain_has_history/deed_chain_break/deed_chain_distress_transfer/atty_deed_chain_fetched,
    applies to every row with no per-county registry, allowlist or skip-list of any kind, and
    names zero literal county text. _deed_chain_credit() returns the full STATE_COUNTIES universe
    instead of the (correctly empty) blanket grep."""
    assert gm.counties_named_in([gm.PKG / "enrichment_deed_chain.py"]) == set()
    credit = gm._deed_chain_credit()
    assert ("SC", "Fairfield") in credit
    assert len(credit) == len(gm.NC_COUNTIES) + len(gm.SC_COUNTIES)


def test_built_in_code_fills_deed_chain_credit_for_all_four_columns():
    """End-to-end: built_in_code()'s real output for all 4 deed_chain-driven columns is no longer
    empty. SC/Fairfield (208 applicable rows, previously 'no source known' on all 4 with code_counties
    empty) is the one county where this has real, measured impact today -- every other county with
    an applicable row already shows ran=True on the live board, independent of code_counties."""
    built = gm.built_in_code()
    for col in ("deed_chain_has_history", "deed_chain_break", "deed_chain_distress_transfer",
                "atty_deed_chain_fetched"):
        assert ("SC", "Fairfield") in built[col], col
        assert built[col] == gm._deed_chain_credit()


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


# ---------------------------------------------------------------- 2026-10-09 remeasure: flip scope, SC-only quiet title, screens

def test_flip_feed_columns_apply_only_in_flip_scope():
    # Buncombe is a footprint county; Alamance is not (and not oceanfront); Dare is oceanfront
    assert gm.in_flip_scope("NC", "Buncombe")
    assert not gm.in_flip_scope("NC", "Alamance")
    assert gm.in_flip_scope("NC", "Dare")
    assert gm.in_flip_scope("NC", None)                 # no county: cannot be ruled out
    out = row(county="Alamance", listing_type="tax_lien")
    rules = gm.row_rules(out, out["raw"], set())
    app = gm.applicable_columns(out, rules)
    assert not (set(gm.FLIP_FEED_COLS) & app)
    assert "lt_tax_lien" in app and "lt_divorce_notice" in app   # distressed types apply everywhere
    inn = row(county="Buncombe")
    assert set(gm.FLIP_FEED_COLS) <= gm.applicable_columns(inn, gm.row_rules(inn, inn["raw"], set()))


def test_nc_quiet_title_is_read_by_nc_heir_notices():
    # top-80 item: NC notices are now parsed (scrapers/public_notices/nc_heir_notices.py). A county
    # with a Column paper is a read source; one without is a wall verdict (ncnotices.com bodies are
    # CAPTCHA-walled), not a gap
    m = gm.load_matrix(gm.REPO / "docs" / "county_records" / "county_records_matrix.json")
    for col in ("quiet_title", "heir_naming_publication"):
        spec = gm.SPECS[col]
        assert spec.sources == () and any("nc_heir_notices" in p for p in spec.producers)
        johnston = gm.source_status(spec, "NC", m[("NC", "Johnston")])
        assert johnston[0] == "free" and "Column" in johnston[2]
        alleghany = gm.source_status(spec, "NC", m[("NC", "Alleghany")])
        assert alleghany[0] == "walled" and "Column" in alleghany[1]
        # 25 NC counties with no Column paper, plus 25 SC counties outside column_legal_notices's
        # active 21-county SC estate-lane coverage (19 by exact county match + Orangeburg/Calhoun
        # recovered from the "Orangeburg, Bamberg and Calhoun" newspaper-region tag, 2026-11-16 --
        # grew from 18 after the 2026-10-23 re-probe added Aiken, then from 19-exact-match/27-gap
        # after the 2026-11-16 region-tag fix moved Orangeburg/Calhoun to covered; gap-sweep wave 2,
        # 2026-10-16)
        assert len(spec.statewide_except) == 25 + 25
    assert gm.source_status(gm.SPECS["heir_naming_publication"], "SC", None)[2].startswith("statewide: SC estate")


def test_sc_quiet_title_only_reaches_column_legal_notices_18_county_footprint():
    # column_legal_notices's SC estate lane queries SC_FOOTPRINT + SC_DISTRESSED_ONLY +
    # SC_PROBATE_EXTRA_COUNTIES by exact county match (18 of 46 originally, 19 after the
    # 2026-10-23 re-probe added Aiken), PLUS -- since 2026-11-16 -- Orangeburg and Calhoun,
    # recovered from the "Orangeburg, Bamberg and Calhoun" combined newspaper-coverage-region
    # tag (the same "county is a region, not a county" quirk already handled for the SC
    # foreclosure lane, extended here to the estate/probate lane): 21 of 46 total. A 3rd
    # re-probe of the rest (2026-11-16) reconfirmed them empty, York/Lexington included
    # (checked via the server's own total_results over a 10-year window). Before the
    # original fix, gap_matrix.py claimed blanket SC statewide coverage with no exception, so
    # those excluded counties showed an unsatisfiable "run it for this county" built-but-low-
    # yield gap forever (gap-sweep wave 2, 2026-10-16).
    m = gm.load_matrix(gm.REPO / "docs" / "county_records" / "county_records_matrix.json")
    for col in ("quiet_title", "heir_naming_publication"):
        spec = gm.SPECS[col]
        greenville = gm.source_status(spec, "SC", m[("SC", "Greenville")])  # SC_PROBATE_EXTRA_COUNTIES
        assert greenville[0] == "free" and "SC estate" in greenville[2]
        orangeburg = gm.source_status(spec, "SC", m[("SC", "Orangeburg")])  # region-tag recovered
        assert orangeburg[0] == "free" and "SC estate" in orangeburg[2]
        abbeville = gm.source_status(spec, "SC", m[("SC", "Abbeville")])  # not in the active 21
        assert abbeville[0] == "walled" and "21 of 46" in abbeville[1]


def test_ledger_signals_accepts_several_verifier_signals():
    assert gm.ledger_signals(gm.SPECS["lt_divorce_notice"]) == ("nc_ecourts_case", "divorce")
    assert gm.ledger_signals(gm.SPECS["lt_lis_pendens"]) == ("foreclosure_rod", "nc_ecourts_case", "court_wall")
    assert gm.ledger_signals(gm.SPECS["heir_estate"]) == ("probate_heir", "heir_roll")
    assert gm.ledger_signals(gm.SPECS["address"]) == ()


def _ledger(screens):
    return {"schema": "screen-ledger-v1", "run_at": "2026-10-07T00:00:00Z", "screens": screens}


def test_screen_ledger_closes_county_and_tax_roster_cells():
    cube = gm.Cube(today=TODAY)
    for name in ("DOE JOHN", "ROE JANE"):
        cube.add(row(county="Polk", owner_name=name, raw={"entity_type": "individual"}))
    matrix = {("NC", "Polk"): dict(MATRIX_REC, county="polk")}
    plain = gm.roll_up(cube, matrix, {})
    assert plain["cells"][("NC", "Polk", "jail_booking")]["class"] == "no source known"
    assert plain["cells"][("NC", "Polk", "two_year_delinquent")]["target"] == 0
    led = _ledger({"jail_booking": {"NC|Polk": {"sources": ["national.jail_bookings"]}},
                   "two_year_delinquent": {"NC|Polk": {"sources": ["counties_nc.polk_delinquent_tax"]}}})
    roll = gm.roll_up(cube, matrix, {}, led)
    jail = roll["cells"][("NC", "Polk", "jail_booking")]
    assert jail["ran"] and jail["screened"] and jail["class"] is None and jail["target"] == jail["app"] == 2
    tax = roll["cells"][("NC", "Polk", "two_year_delinquent")]
    assert tax["class"] is None and tax["target"] == tax["app"]
    # a screen never fills a FIELD
    assert roll["cells"][("NC", "Polk", "phone")]["target"] == 0


def test_screen_ledger_ignored_for_unknown_county():
    cube = gm.Cube(today=TODAY)
    cube.add(row(county=None, owner_name="X Y", raw={"entity_type": "individual"}))
    led = _ledger({"jail_booking": {"NC|UNKNOWN": {"sources": ["x"]}}})
    roll = gm.roll_up(cube, {}, {}, led)
    assert not roll["cells"][("NC", "UNKNOWN", "jail_booking")]["screened"]


# ---------------------------------------------------------------- 2026-11-16 heir_estate sweep: roll_up()'s
# 'verify' layer must not reuse 'check' layer's "sourced-not-built" text for a different situation

def test_verify_layer_distinguishes_built_not_verified_from_sourced_not_built():
    """Root-cause fix for the round-3 2026-11-16 heir_estate sweep (see memory:
    project_heir_estate_systematic_sweep_2026-11-16.md). 20 SC counties (Colleton 1,817 real
    published rows, Sumter 1,339, Berkeley 716, ...) were already fully built and ran (ran=True,
    built="ran", the layer 'check' cell for the SAME (state, county, column) is None -- not a gap
    at all) yet gap_matrix still printed a gap_class=="sourced-not-built" row for every one of
    them, with est_rows_affected matching the real published row count almost exactly. That row
    was never the build-layer gap (there isn't one: ran=True makes target==app, so classify_cell
    returns None and layer 'check' never emits a row) -- it is roll_up()'s SEPARATE 'verify' layer
    (hit rows of a ledger-backed column without a decisive verdict), which used to fall back to
    the exact same "sourced-not-built" string whenever no verifier applied and the source read
    free. The real reason no verifier applies: heir_roll.py's own HEIR_SOURCE allowlist names only
    counties_nc.nc_heir_estate_parcels, never the later (2026-10-19) counties_sc.
    sc_heir_estate_parcel_cache -- the SAME "stale producer/source list" bug class already fixed
    3 times this session in the BUILD layer's own credit functions, just in the VERIFY layer
    instead. The fix renames that fallback (and its unknown-source sibling) to `built-not-verified`,
    so the class string itself can never again be read as "nothing built here" when a real hit row
    is the only way this loop reaches the cell at all (its own guard: c["pos"] == 0: continue)."""
    cube = gm.Cube(today=TODAY)
    # the exact raw shape counties_sc.sc_heir_estate_parcel_cache.py writes (confirmed live against
    # the real published board, 2026-11-16: a real Colleton SC row carries this shape verbatim)
    hit = row(state="SC", county="Colleton", listing_type="estate_lead", property_kind="unknown",
              source="counties_sc.sc_heir_estate_parcel_cache", defendant="SIMMONS CAROL R (ESTATE)",
              raw={"heir_estate": {"owner_of_record": "SIMMONS CAROL R (ESTATE)",
                                   "heir_names": [{"raw": "SIMMONS CAROL R (ESTATE)", "role": "estate"}],
                                   "mailing": None, "match": "estate", "life_estate": False,
                                   "source": "parcel_cache"},
                   "relationship_signal": {"kind": "probate", "keyword": "heir_estate_owner_of_record",
                                            "source": "counties_sc.sc_heir_estate_parcel_cache"}})
    cube.add(hit)
    matrix = {("SC", "Colleton"): dict(MATRIX_REC, state="SC", county="colleton")}
    roll = gm.roll_up(cube, matrix, gm.built_in_code())
    check_cell = roll["cells"][("SC", "Colleton", "heir_estate")]
    assert check_cell["ran"] is True and check_cell["built"] == "ran"
    assert check_cell["class"] is None                      # layer 'check': 100% built, not a gap at all
    verify_gaps = [g for g in roll["gaps"] if g["column"] == "heir_estate" and g["county"] == "Colleton"
                   and g["layer"] == "verify"]
    assert len(verify_gaps) == 1, verify_gaps
    vg = verify_gaps[0]
    assert vg["gap_class"] == "built-not-verified"
    assert vg["gap_class"] != "sourced-not-built"
    assert vg["built"] == "ran" and vg["ran"] is True       # carries the real build state, not "no"/False
    assert vg["est_rows_affected"] == 1
    assert vg["next_action"] == "write a probate_heir|heir_roll verifier for this county (county GIS: gis.example.test)"


def test_verify_layer_unknown_source_also_not_labelled_sourced_not_built_or_no_source_known():
    """Sibling fallback branch of the same fix: no county_records_matrix entry at all (vsrc[0] is
    "unknown", not "free"). Was 'no source known'; a real hit row still makes "nothing sourced"
    false, so this reads 'built-not-verified (source status unknown)' -- the by-column summary's
    re.sub(r" \\(.*", "", ...) still buckets it with the plain 'built-not-verified' class."""
    cube = gm.Cube(today=TODAY)
    hit = row(state="SC", county="Colleton", listing_type="estate_lead", property_kind="unknown",
              source="counties_sc.sc_heir_estate_parcel_cache", defendant="DOE JOHN (HEIRS)",
              raw={"heir_estate": {"owner_of_record": "DOE JOHN (HEIRS)", "heir_names": ["DOE JOHN"],
                                   "mailing": None, "match": "heirs", "life_estate": False,
                                   "source": "parcel_cache"}})
    cube.add(hit)
    roll = gm.roll_up(cube, {}, {})                         # no county_records_matrix entry at all
    verify_gaps = [g for g in roll["gaps"] if g["column"] == "heir_estate" and g["layer"] == "verify"]
    assert len(verify_gaps) == 1, verify_gaps
    assert verify_gaps[0]["gap_class"] == "built-not-verified (source status unknown)"
    assert "sourced-not-built" not in verify_gaps[0]["gap_class"]
    assert "no source known" not in verify_gaps[0]["gap_class"]


def test_check_layer_genuinely_unbuilt_county_still_reads_sourced_not_built():
    """Regression guard for the fix above: a county with no real hit at all (and no code credit
    either) must still read the ordinary layer 'check' sourced-not-built, and must never spawn a
    layer 'verify' row (its own guard: c["pos"] == 0 skips it) -- the rename only touches layer
    'verify' output, never layer 'check', and never fires without a real hit to justify it."""
    cube = gm.Cube(today=TODAY)
    cube.add(row(state="SC", county="Cherokee", listing_type="tax_lien", owner_name="SMITH ANN",
                 raw={"entity_type": "individual"}))
    matrix = {("SC", "Cherokee"): dict(MATRIX_REC, state="SC", county="cherokee")}
    roll = gm.roll_up(cube, matrix, {})
    cell = roll["cells"][("SC", "Cherokee", "heir_estate")]
    assert cell["ran"] is False and cell["built"] == "no"
    assert cell["class"] == "sourced-not-built"
    assert not any(g["column"] == "heir_estate" and g["layer"] == "verify" for g in roll["gaps"])


# ---------------------------------------------------------------- 2026-10-17 gap-sweep wave 5

def test_storm_damage_applies_only_in_the_real_fema_helene_footprint():
    """Was applies="all" (default): every one of 437,170 rows statewide counted as a gap
    even though the real producer (enrichment_helene_damage.py) is permanently scoped to 3
    counties and Helene structural damage cannot occur where the storm never reached --
    a 392,412-row false gap (wave 5, verified not refuted)."""
    assert gm.in_storm_scope("NC", "Buncombe")          # wired producer county
    assert gm.in_storm_scope("NC", "Mecklenburg")       # real FEMA IA registrations exist here too
    assert not gm.in_storm_scope("NC", "Wake")          # outside the declared footprint entirely
    assert gm.in_storm_scope("NC", None)                # no county: cannot be ruled out
    out = row(county="Wake", listing_type="tax_lien")
    assert "storm_damage" not in gm.applicable_columns(out, gm.row_rules(out, out["raw"], set()))
    inn = row(county="Buncombe")
    assert "storm_damage" in gm.applicable_columns(inn, gm.row_rules(inn, inn["raw"], set()))


def test_bankruptcy_stay_applies_only_to_a_foreclosure_class_row_with_a_bankruptcy_match():
    """Was applies="bankrupt" (shared with lt_bankruptcy): matched any listing_type=='bankruptcy'
    row too, even though the real producer (enrichment_bankruptcy_stay.py) always skips those --
    only a FORECLOSURE-class lead gets stayed. Inflated the published gap ~70x (wave 5, verified
    not refuted)."""
    bk_lead = row(listing_type="bankruptcy", raw={"bankruptcy": {"chapter": "13"}})
    assert "bankruptcy_stay" not in gm.applicable_columns(bk_lead, gm.row_rules(bk_lead, bk_lead["raw"], set()))
    stayed = row(listing_type="lis_pendens", raw={"bankruptcy": {"chapter": "13"}})
    assert "bankruptcy_stay" in gm.applicable_columns(stayed, gm.row_rules(stayed, stayed["raw"], set()))
    no_bk = row(listing_type="lis_pendens", raw={})
    assert "bankruptcy_stay" not in gm.applicable_columns(no_bk, gm.row_rules(no_bk, no_bk["raw"], set()))


def test_divorce_no_subsequent_deed_is_nc_only():
    """enrichment_divorce_no_subsequent_deed.py hard-skips every SC row; the Spec had no
    states= override, so SC rows counted as a gap for a signal that can never close there
    (wave 5, verified not refuted)."""
    assert gm.SPECS["divorce_no_subsequent_deed"].states == ("NC",)
    sc = row(state="SC", county="Spartanburg", raw={"divorce": {"case_count": 1}})
    assert "divorce_no_subsequent_deed" not in gm.applicable_columns(sc, gm.row_rules(sc, sc["raw"], set()))


def test_notice_service_defect_is_nc_only():
    """SC's delinquent-tax process is purely administrative -- no lawsuit/docket/service event
    exists to have a defect in (producer's own live-verified SC note); the Spec claimed a
    working SC statewide source anyway (wave 5, verified not refuted)."""
    assert gm.SPECS["notice_service_defect"].states == ("NC",)
    sc = row(state="SC", county="Charleston", listing_type="tax_lien")
    assert "notice_service_defect" not in gm.applicable_columns(sc, gm.row_rules(sc, sc["raw"], set()))


def test_divorce_no_subsequent_deed_checked_by_resolved_from_name_not_deed_chain():
    """checked_columns() credited this column off raw.deed_chain, a key the producer never
    reads (its real gate is raw.resolved_from_name) -- wrong/unrelated-key bug class, same
    shape fixed repeatedly tonight for the tax columns (wave 5, verified not refuted)."""
    wrong_key = row(raw={"deed_chain": {"transfers": []}})
    assert "divorce_no_subsequent_deed" not in gm.checked_columns(wrong_key, set(), {})
    assert "deed_chain_break" in gm.checked_columns(wrong_key, set(), {})     # unaffected sibling credit
    right_key = row(raw={"resolved_from_name": {"matched": False}})
    assert "divorce_no_subsequent_deed" in gm.checked_columns(right_key, set(), {})


def test_title_risk_checked_only_via_plaintiff_never_defendant():
    """checked_columns() also credited title_risk off rec['defendant'], a field
    enrichment_title_risk.py's _party_text() never reads -- silent over-crediting (wave 5,
    verified: the code defect is real even though the verifier corrected the claimed
    impact's magnitude)."""
    defendant_only = row(defendant="DOE JOHN")
    assert "title_risk" not in gm.checked_columns(defendant_only, set(), {})
    plaintiff = row(plaintiff="ABC BANK")
    assert "title_risk" in gm.checked_columns(plaintiff, set(), {})


def test_vacancy_producers_cover_all_three_real_writers():
    """Was missing 2 of 3 real writers of raw['vacancy'] (rocky_mount_blight_survey.py,
    kinston_proposed_demolition.py), so built_in_code() couldn't see Lenoir County as
    code-covered and mislabeled its cell 'no source known' (wave 5, correctly_classified_non_bug
    for the headline gap, but this narrow metadata fix is real)."""
    producers = gm.SPECS["vacancy"].producers
    assert any("rocky_mount_blight_survey" in p for p in producers)
    assert any("kinston_proposed_demolition" in p for p in producers)


def test_board_rows_reads_a_checkpoint(tmp_path):
    import gzip
    import json as _json
    d = tmp_path / "ckpt"
    d.mkdir()
    (d / "manifest.json").write_text("{}")
    with gzip.open(d / "board.json.gz", "wt") as f:
        _json.dump([{"source": "t.s", "source_url": "https://example.test/1", "listing_type": "tax_lien",
                     "state": "NC", "county": "Buncombe", "raw": {}}], f)
    assert gm.is_checkpoint(d) and gm.is_checkpoint(d / "board.json.gz")
    rows = list(gm.board_rows(d))
    assert len(rows) == 1 and rows[0]["county"] == "Buncombe"


# ---------------------------------------------------------------- 2026-11-16 storm_damage dead-end sweep

def test_storm_damage_declined_for_confirmed_no_qualifying_event_counties():
    """storm_damage's own applicability rule (in_storm_scope) is the real ~71-county FEMA
    Helene IA footprint -- deliberately broader than the 3 counties the producer
    (enrichment_helene_damage.py) covers today, so an in-footprint-but-unbuilt county still
    reads as a real gap (see test_storm_damage_applies_only_in_the_real_fema_helene_footprint
    above). That is correct for most of the footprint, but Mecklenburg/Gaston/Lincoln were
    live-confirmed (2026-10-29 session: NOAA tornado EF-ratings + the state's Helene damage
    briefing; re-confirmed 2026-11-16: FEMA OpenFEMA per-household inspected-damage data) to
    have had NO qualifying structural-damage event at all -- a county the storm's real
    footprint touched only glancingly can never grow a parcel-level damage-assessment dataset
    for this column's producer to read, no matter how long the gap sweep waits. The 2026-10-29
    session recommended reclassifying these in gap_matrix but never implemented it, so they
    kept re-surfacing as 'no source known' on every regeneration (confirmed still broken in the
    2026-11-16 gap list before this fix). Fixed by POPULATING the existing declined_registry.json
    override (not by changing classify_cell/in_storm_scope, which stay correct for the rest of
    the footprint) -- Forsyth/Cabarrus/Union added the same pass from the same FEMA cross-check."""
    for county in ("Mecklenburg", "Gaston", "Lincoln", "Forsyth", "Cabarrus", "Union"):
        assert gm.in_storm_scope("NC", county)      # still "applicable" -- the override is the fix, not app==0
        got = gm.declined_override("NC", county, "storm_damage", "no source known")
        assert got is not None and got.startswith("declined ("), (county, got)
    # a DIFFERENT column for the same county is untouched (the override is column-scoped, not blanket)
    assert gm.declined_override("NC", "Mecklenburg", "condemned", "no source known") == "no source known"


def test_storm_damage_not_declined_for_york_and_lexington_sc():
    """York SC and Lexington SC also show storm_damage as 'no source known' on the board (the
    2026-10-29 session never checked them -- it covered only 3 NC counties) but 2026-11-16
    live FEMA per-household data shows their damage severity (avg FEMA-inspected damage per
    inspected home: York $1,112, Lexington $1,384) at or above Spartanburg SC's (avg $1,224 --
    a county with a CONFIRMED real, built damage-assessment layer per
    enrichment_helene_damage.py's own module docstring), unlike Mecklenburg/Gaston/Lincoln's
    $674-810 tier. These stay genuinely open gaps -- deliberately NOT added to
    declined_registry.json this pass."""
    for state, county in (("SC", "York"), ("SC", "Lexington")):
        got = gm.declined_override(state, county, "storm_damage", "no source known")
        assert got == "no source known", (state, county, got)


def test_declined_override_never_fires_on_not_applicable_or_at_target():
    """Guard for the new storm_damage registry rows specifically: declined_override must still
    refuse to touch a cell that is already correctly 'not applicable' (app == 0) or already at
    target (None), even for a (state, county, column) tuple the registry now has a real entry
    for -- a future narrowing of in_storm_scope must never be silently overridden back to
    'declined' by this registry."""
    assert gm.declined_override("NC", "Mecklenburg", "storm_damage", "not applicable") == "not applicable"


# ---------------------------------------------------------------- 2026-11-16 divorce_no_subsequent_deed sweep

def test_divorce_no_subsequent_deed_credited_for_every_nc_county():
    """enrichment_divorce_no_subsequent_deed.py (this column's only producer) has zero
    per-county registry, allowlist or skip-list -- it gates only on listing_type ==
    DIVORCE_NOTICE and state == 'NC' -- so the real 'built' set is every NC county, not
    whatever a blanket counties_named_in() text match over the file happens to find. That
    blanket match found exactly one ('NC', 'Person'), an accident of the English word "PERSON"
    inside the module's own docstring, not real per-county code (confirmed
    project_divorce_no_subsequent_deed_false_gap_2026-11-12.md, re-confirmed live 2026-11-16:
    Person's board rows show zero resolved/tagged, identical to every other NC county). Before
    this fix, 63 real NC counties (the 2026-11-16 gap list's single highest-cell-count
    'sourced-not-built' cluster, 4,043 est_rows) plus 3 more ('no source known': New Hanover,
    Lee, Hoke) read as a code gap purely because code_counties had nothing for them -- same
    bug-class shape as repeat_tax_loss/deed_chain_*/child_support above, not a per-county dead
    end (contrast test_storm_damage_declined_for_confirmed_no_qualifying_event_counties, which
    IS one)."""
    credit = gm.built_in_code()["divorce_no_subsequent_deed"]
    assert all(("NC", c) in credit for c in
               ("Mecklenburg", "Guilford", "Forsyth", "Johnston", "Cabarrus", "Durham",
                "Davidson", "Jones", "New Hanover", "Lee", "Hoke", "Person"))
    assert credit == {("NC", c) for c in gm.NC_COUNTIES}
    assert not any(st == "SC" for st, co in credit)      # the producer hard-skips every SC row


@pytest.mark.parametrize("src,before,after", [
    (("free", "", "register: some county portal"), "sourced-not-built", "built-but-low-yield"),
    (("unknown", "", ""), "no source known", "built-but-low-yield"),
])
def test_divorce_no_subsequent_deed_reclassifies_once_credited(src, before, after):
    """The exact (app, target, ran, src) shape the 2026-11-16 board read for the 66 affected
    cells (63 'sourced-not-built' + 3 'no source known'): app > target, never ran (0% of this
    column's divorce_notice rows in these counties have been through the shared name resolver
    yet). With the old, empty code_counties credit (built='no') classify_cell read the gap as a
    missing-source problem; with this fix's credit (built='code') it reads built-but-low-yield
    -- which next_action's own spec.scope == 'derived' branch already states correctly ("rows
    lack the inputs ... fill the inputs, then recompute"), matching the real cause (the shared
    resolver backlog, not missing code)."""
    spec = gm.SPECS["divorce_no_subsequent_deed"]
    assert gm.classify_cell(spec, 100, 0, False, "no", src) == before
    assert gm.classify_cell(spec, 100, 0, False, "code", src) == after


def test_divorce_no_subsequent_deed_walled_counties_stay_walled():
    """The 16 counties the 2026-11-16 gap list reads as 'walled' for this column (7 CAPTCHA + 9
    bot-check/Cloudflare) read that from the unrelated 'rod' family's OWN register-portal wall
    for that county (source_status(), family == 'rod') -- a county_records_matrix
    family-assignment imprecision this derived, resolver-only module never actually touches,
    same shape repeat_tax_loss's own docstring flags and explicitly leaves alone. Guard: the
    new built='code' credit must never override an already-walled cell -- classify_cell()
    checks a declared wall before it ever looks at `built`, by design (the explicit
    `status != "walled"` guard on the built == "code" branch)."""
    spec = gm.SPECS["divorce_no_subsequent_deed"]
    walled_src = ("walled", "CAPTCHA", "register: some county portal")
    assert gm.classify_cell(spec, 100, 0, False, "no", walled_src) == "walled (CAPTCHA)"
    assert gm.classify_cell(spec, 100, 0, False, "code", walled_src) == "walled (CAPTCHA)"
    assert gm.declined_override("NC", "Mecklenburg", "storm_damage", None) is None


# ---------------------------------------------------------------- 2026-11-16 email (SC) no-free-source sweep

def test_email_declined_statewide_for_sc():
    """email's only live, owner-sourced producer is liensnc_handoff.py, reading a filed LiensNC
    lien-agent-designation record -- a NC-only mechanism that exists because NC Gen. Stat.
    44A-11.1/44A-11.2 uniquely requires owners of qualifying construction projects to designate a
    lien agent and record that designation. South Carolina's mechanics-lien law (Title 29 Ch.5)
    has no equivalent lien-agent-designation-with-public-registry requirement, and every other
    raw e-mail source in this codebase (notice_contact.email -- the filing attorney/trustee from
    Column legal notices, which IS live for SC; distressed/homeharvest agent_email; sc_sos_entity's
    registered_agent, which carries a name only, never an address or email) is correctly excluded
    from owner_email_of() by design (not the owner, and outreach-useless even if included). Fixed
    via the existing declined_registry.json override (county=None, statewide) -- the SAME
    mechanism and shape as the SC marriage_license and NC lt_tax_sale_overage statewide entries,
    not a change to classify_cell/SPECS. All 46 SC counties showing email as 'no source known' on
    the 2026-11-16 gap list flip to 'declined (...)' on the next regeneration."""
    for county in gm.SC_COUNTIES:
        got = gm.declined_override("SC", county, "email", "no source known")
        assert got is not None and got.startswith("declined ("), (county, got)
    # a DIFFERENT column for the same SC county is untouched (column-scoped, not blanket)
    assert gm.declined_override("SC", "York", "phone", "no source known") == "no source known"


def test_email_not_declined_for_nc():
    """NC keeps its real LiensNC-sourced email producer -- the SC registry entry must never
    bleed across the state line (declined_override's own (state, county, column) key is
    state-scoped, but this guards the actual registry content, not just the lookup mechanics)."""
    for county in ("Mecklenburg", "Wake", "Forsyth"):
        got = gm.declined_override("NC", county, "email", "no source known")
        assert got == "no source known", (county, got)


# ---------------------------------------------------------------- 2026-11-16 round 9: vacant_structure continued

def test_vacancy_producers_also_cover_spartanburg_vacant():
    """spartanburg_vacant.py has written a real raw['vacancy'] = {'vacant': True, 'boarded_up':
    None, 'utility_status': None, 'source': 'spartanburg_city_registry'} on every one of its
    ~5,000 rows since its own 2026-11-11 docstring note, the exact dict shape _gate_vacancy()
    checks -- but was only ever in the sibling 'vacant' column's producers tuple, never this
    one. Same bug class as the 2026-11-16 arcgis_distress_layers.py/lincoln_code_violations.py
    fixes just above in this same producers tuple, found a third time in the same column.
    Unlike 'vacant' (which needs _VACANT_COHORT_REL's precise-credit swap because this same
    file's blanket grep would otherwise need disambiguating from enrichment_arcgis.py's
    unrelated 69-county over-match), 'vacancy' has no such refinement and needs none: this file
    alone, text-grepped, already resolves to exactly {('SC','Spartanburg')}."""
    producers = gm.SPECS["vacancy"].producers
    assert any("spartanburg_vacant" in p for p in producers)


def test_spartanburg_vacant_credited_for_vacancy_column():
    """Live built_in_code() check: Spartanburg SC must flip to built for 'vacancy' (the fix),
    while 'vacant' (already correct before this round) and an unrelated county stay exactly as
    they were -- this is a producers-tuple addition, not a change to how either column is
    computed."""
    built = gm.built_in_code()
    assert ("SC", "Spartanburg") in built["vacancy"]
    assert ("SC", "Spartanburg") in built["vacant"]        # unchanged, still correct
    # an unrelated county (no vacancy producer of its own -- declined this same round, see
    # declined_registry.json) stays absent; NOT Wake, which separately joins built["vacancy"]
    # this round via its own wake_code_cases.py fix (see the dedicated test below)
    assert ("SC", "Horry") not in built["vacancy"]          # no blanket over-credit introduced


def test_wake_code_cases_credited_for_vacancy_and_vacant_not_condemned():
    """Live built_in_code() check for the wake_code_cases.py fix: Wake flips to built for
    'vacancy'/'vacant' (the mirror added this round) but stays absent from 'condemned' (declined
    separately -- see the registry entry)."""
    built = gm.built_in_code()
    assert ("NC", "Wake") in built["vacancy"]
    assert ("NC", "Wake") in built["vacant"]
    assert ("NC", "Wake") not in built["condemned"]


def test_durham_unsafe_building_credited_for_all_three_vacant_structure_columns():
    """Live built_in_code() check for the new durham_unsafe_building Layer entry: Durham flips to
    built for condemned/vacancy/vacant together, the one new source this round that earns all
    three at once (same shape rockhill_code_demolition already does for York SC)."""
    built = gm.built_in_code()
    assert ("NC", "Durham") in built["condemned"]
    assert ("NC", "Durham") in built["vacancy"]
    assert ("NC", "Durham") in built["vacant"]


def test_round9_declined_entries_cover_every_researched_county_and_column():
    """2026-11-16 round 9: 12 more vacant_structure counties researched live (round 8 did 10 the
    same day). 11 came back genuine dead ends across all three columns (condemned/vacancy/vacant)
    -- Horry/New Hanover/Randolph/Cumberland/Rowan/Pitt NC+SC and Greenville/Pickens SC plus Onslow/
    Orangeburg/Beaufort (lighter, web-search-only evidence, same bar as round 8's Lexington/
    Transylvania) -- plus Wake's condemned column specifically (its vacancy/vacant columns got a
    real fix instead, see the test above) and Lincoln's condemned column (vacancy/vacant already
    fixed round 8; condemned stays correctly open for the same reason that round's own fix didn't
    claim it). Each entry needs its own evidence -- this just pins that none were missed or
    mis-keyed."""
    three_col = ("condemned", "vacancy", "vacant")
    for state, county in (
        ("SC", "Horry"), ("NC", "New Hanover"), ("NC", "Randolph"), ("NC", "Cumberland"),
        ("NC", "Rowan"), ("NC", "Pitt"), ("SC", "Greenville"), ("SC", "Pickens"),
        ("NC", "Onslow"), ("SC", "Orangeburg"), ("NC", "Beaufort"),
    ):
        for col in three_col:
            got = gm.declined_override(state, county, col, "no source known")
            assert got is not None and got.startswith("declined ("), (state, county, col, got)
    assert gm.declined_override("NC", "Wake", "condemned", "no source known").startswith("declined (")
    assert gm.declined_override("NC", "Lincoln", "condemned", "no source known").startswith("declined (")
    # a column NOT researched/declined for one of these counties is untouched (column-scoped)
    assert gm.declined_override("SC", "Horry", "probate", "no source known") == "no source known"


# ---------------------------------------------------------------- 2026-11-16 jail_booking_new "ran" detector fix:
# match_cross_county() (enrichment_jail_bookings.py) never lets a hit land in the SAME county as
# the roster that produced it ("same-county lane's job", its own skip) -- so roll_up()'s plain
# "ran = pos > 0 or chk > 0" (keyed on the HIT ROW's own county) could never be satisfied by a
# county's own roster, no matter how many real cross-county hits it produced. Confirmed live
# 2026-11-16: of 91 real jail_booking_new hits on the board across 29 distinct roster counties
# (York SC and Stokes NC among them, 4 and 6 respectively), ZERO had home county == roster
# county -- a board-wide undercount, not a York/Stokes- or first-fetch-specific quirk (round 9's
# own diagnosis named roster health/no_history as the mechanism; live tracing here shows the
# real cause is this home-vs-roster attribution mismatch, which persists even after any number
# of fetches). Fixed by Cube.add() also attributing each hit to the ROSTER's own embedded
# identity (raw.jail_booking_new["state"]/["county"], never the hit row's own county_key) in a
# new jbn_roster_hits counter, which roll_up() consults only for jail_booking_new.

def test_jail_booking_new_ran_true_on_first_ever_fetch_with_real_cross_county_hits():
    """A county whose roster has NEVER run before (no jail_booking_screen, no code credit, no
    screen-ledger entry -- the genuine 'first-ever fetch' case) but whose roster already produced
    a real, middle-corroborated cross-county hit on some OTHER county's row must read ran=True:
    the hit is real evidence this roster ran and found something, even though -- by
    match_cross_county()'s own design -- it can never land back in the roster's own county."""
    cube = gm.Cube(today=TODAY)
    # York's own row: never gets jail_booking_new (match_cross_county skips its own county) and
    # never got a same-county jail_booking hit either -- exactly what a brand-new roster's OWN
    # rows look like the very first time it is ever fetched.
    cube.add(row(state="SC", county="York", owner_name="OWNER ONE", raw={"entity_type": "individual"}))
    # The real cross-county hit: an unrelated owner's Lexington SC property, flagged because that
    # same owner's name is a brand-new booking on York's roster (home_county != roster county, as
    # match_cross_county always writes it).
    cube.add(row(state="SC", county="Lexington", owner_name="OWNER TWO", raw={
        "entity_type": "individual",
        "jail_booking_new": {"county": "York", "state": "SC", "home_county": "Lexington",
                             "matched_name": "TWO OWNER", "confidence": "middle_corroborated_cross_county"},
    }))
    assert cube.jbn_roster_hits[("SC", "York")] == 1       # white-box: attributed to the ROSTER county
    roll = gm.roll_up(cube, {}, {})                        # {} code_counties, {} screens: no history at all
    york = roll["cells"][("SC", "York", "jail_booking_new")]
    assert york["ran"] is True
    assert york["target"] == york["app"] == 1              # "ran" closes the WHOLE county, same as any
                                                            # other county-scope roster (SCOPES["county"])
    lex = roll["cells"][("SC", "Lexington", "jail_booking_new")]
    assert lex["ran"] is True and lex["pos"] == 1           # the landing county's own cell is unaffected,
                                                            # still true via the pre-existing pos>0 path


def test_jail_booking_new_first_ever_fetch_with_no_hits_stays_ran_false():
    """A brand-new roster that genuinely found zero corroborated cross-county hits leaves no
    on-board trace at all for this lane (unlike the same-county lane's jail_booking_screen
    sentinel) -- ran=False here is honest (indistinguishable from never-attempted), not a
    regression. The fix must not invent evidence that does not exist."""
    cube = gm.Cube(today=TODAY)
    cube.add(row(state="NC", county="Stokes", owner_name="OWNER THREE", raw={"entity_type": "individual"}))
    assert cube.jbn_roster_hits.get(("NC", "Stokes"), 0) == 0
    roll = gm.roll_up(cube, {}, {})
    stokes = roll["cells"][("NC", "Stokes", "jail_booking_new")]
    assert stokes["ran"] is False
    assert stokes["target"] == 0


def test_jail_booking_new_fix_does_not_disturb_established_jail_booking_screen_county():
    """An established county with real screen history on the SIBLING jail_booking column (the
    2026-10-16 fix this one is modeled on) must be completely unaffected: the new jbn_roster_hits
    branch is gated on col == 'jail_booking_new' and touches nothing else. Also pins that a
    jail_booking_new cell with no roster-hit evidence at all for a county that DOES have
    jail_booking history still reads ran=False -- the two columns are independent, by design
    (jail_booking's own same-county screen says nothing about this county's cross-county lane)."""
    cube = gm.Cube(today=TODAY)
    cube.add(row(state="NC", county="Transylvania", owner_name="OWNER FOUR", raw={
        "entity_type": "individual",
        "jail_booking_screen": {"county": "Transylvania", "state": "NC", "result": "no_match",
                                "checked_at": "2026-11-16"},
    }))
    roll = gm.roll_up(cube, {}, {})
    jb = roll["cells"][("NC", "Transylvania", "jail_booking")]
    assert jb["ran"] is True and jb["target"] == jb["app"] == 1     # unchanged: the pre-existing fix
    jbn = roll["cells"][("NC", "Transylvania", "jail_booking_new")]
    assert jbn["ran"] is False and jbn["target"] == 0               # independent column, no bleed-through

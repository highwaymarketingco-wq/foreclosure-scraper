"""Audit 2026-10-09, drops_lineage: rules that removed or nulled good data, each pinned with made-up
rows in the real shapes (docs/audit_2026-10-09/drops_lineage.md)."""
from __future__ import annotations

from foreclosure_scraper.drop_audit import all_filtered_sources
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.situs_sanity import situs_is_junk
from foreclosure_scraper.validation import county_native_short_parcel, validate


# --------------------------------------------------------------------------- situs sanity
def test_road_locations_the_old_rule_nulled_are_kept():
    # each shape was nulled on the 2026-10-08 run (street names here are made up)
    for a in ("PINEVIEW ACADEMY RD 4021",       # Dorchester shape: house number after the street
              "OAKVIEW CHAPEL RD 9087",
              "MAPLEWOOD GOLF COURSE DR S",     # direction after the suffix
              "EXAMPLE CLUB DR E",
              "EXAMPLE CHURCH RD     .33",      # acreage after the suffix (vacant registers)
              "TR-A EXAMPLE CLUB DR    2.11",
              "EXAMPLE CHURCH RD/HWY 99",       # intersections / routes (UST registries)
              "CHURCH ST & HWY 99",
              "US 301 & EXAMPLE COLLEGE",
              "S Church Street Extension lot: 1"):
        assert situs_is_junk(a) is False, a


def test_entity_names_and_placeholders_stay_withheld():
    for a in ("Vacant parcel — Delinquent Property Tax 168 46 Owed For 1 Year S 2025 Example Hill",
              "Parcel — EXAMPLE LAND COMPANY INC (THE) — Catawba NC delinquent tax $45 owed (66412)",
              "Lis Pendens 26M000001-590 — Example Church Street Townhomes, LLC",
              "EXAMPLE DRIVE PROPERTIES INC",      # a road word inside a company name
              "EXAMPLE ROAD LLC",
              "Example Road Golf, LLC",          # the corporate form in a later comma part
              "The Retreat on Example Road Owners Assc., Inc.",
              "ST EXAMPLE CHURCH OF GOD",           # a saint, not a street
              "Example Baptist Church",
              "Midtown Example Inn, 210, South Example Street, Gastonia, NC"):
        assert situs_is_junk(a) is True, a


def test_the_old_rule_cases_are_unchanged():
    from foreclosure_scraper import situs_sanity
    assert situs_sanity.situs_is_junk("Glassy Mountain Church Road") is False
    assert situs_sanity.situs_is_junk("123 Main St") is False
    assert situs_sanity.situs_is_junk("STARRWOOD GOLF CO 139 STARRWOOD DR") is False
    assert situs_sanity.situs_is_junk("Oconee Senior Center") is True
    assert situs_sanity.situs_is_junk(None) is False


# --------------------------------------------------------------------------- short parcel ids
def _li(**kw) -> Listing:
    base = dict(source="counties_generic.liensnc", source_url="https://example.invalid/x",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Cleveland")
    base.update(kw)
    return Listing(**base)


def test_county_native_shapes():
    assert county_native_short_parcel("NC", "Cleveland", "12345")
    assert county_native_short_parcel("NC", "Cleveland", "1234")
    assert county_native_short_parcel("NC", "Onslow", "312-96")
    assert county_native_short_parcel("NC", "Onslow", "43E-34")
    assert county_native_short_parcel("NC", "Onslow", "28-9.1")
    assert county_native_short_parcel("NC", "Onslow", "123456")
    assert county_native_short_parcel("nc", "nash", "123456")
    assert county_native_short_parcel("NC", "Rowan", "123456")
    # measured NOT to be the county's parcel number
    assert not county_native_short_parcel("NC", "Catawba", "65771")       # a tax account
    assert not county_native_short_parcel("NC", "Guilford", "183753")     # PTS id, 0% in the layer
    assert not county_native_short_parcel("NC", "Cleveland", "123")       # too short for the shape
    assert not county_native_short_parcel("NC", "Rutherford", "418758")   # owner chose PIN + alias
    assert not county_native_short_parcel("SC", "Cleveland", "12345")


def test_a_county_native_short_id_is_kept():
    li = _li(parcel_id="12345")
    stats = validate([li])
    assert li.parcel_id == "12345"
    assert stats["parcel_kept_county_native"] == 1
    assert stats["parcel_nulled_too_short"] == 0
    assert "parcel_id_nulled" not in li.raw


def test_other_short_ids_are_still_nulled_and_recorded():
    li = _li(county="Catawba", parcel_id="65771")
    stats = validate([li])
    assert li.parcel_id is None
    assert li.raw["parcel_id_nulled"] == {"value": "65771", "reason": "too_short"}
    assert stats["parcel_nulled_too_short"] == 1


def test_a_carried_row_gets_its_county_native_id_back():
    li = _li(parcel_id=None, raw={"parcel_id_nulled": {"value": "312-96", "reason": "too_short"}},
             county="Onslow")
    stats = validate([li])
    assert li.parcel_id == "312-96"
    assert "parcel_id_nulled" not in li.raw
    assert stats["parcel_restored_county_native"] == 1


def test_a_stale_nulled_record_of_the_same_id_is_dropped():
    # fresh row (keeps the id) merged with its prior copy (which carried the nulled record)
    li = _li(parcel_id="54321", raw={"parcel_id_nulled": {"value": "54321", "reason": "too_short"}})
    validate([li])
    assert li.parcel_id == "54321" and "parcel_id_nulled" not in li.raw


def test_a_nulled_record_of_a_different_id_is_left():
    li = _li(parcel_id="54321", raw={"parcel_id_nulled": {"value": "99999", "reason": "too_short"}})
    validate([li])
    assert li.raw["parcel_id_nulled"]["value"] == "99999"


# --------------------------------------------------------------------------- all-filtered warning
class _Row:
    def __init__(self, source):
        self.source = source


def test_all_filtered_counts_by_row_identity_not_slug():
    layer = [_Row("counties_generic.arcgis_distress.example_layer") for _ in range(3)]
    handoff = [_Row("counties_sc.example_index"), _Row("national.example_ucc")]
    dead = [_Row("counties_nc.example_tax_foreclosures") for _ in range(4)]
    results = [("counties_generic.arcgis_distress_layers", layer),
               ("national.stealth_handoff", handoff),
               ("counties_nc.example_tax_foreclosures", dead),
               ("counties_sc.example_zeroed", [])]
    by_source = {"counties_generic.arcgis_distress_layers": 3, "national.stealth_handoff": 2,
                 "counties_nc.example_tax_foreclosures": 4,
                 "counties_sc.example_zeroed": 5,            # 0 scraped + 5 carryover replays
                 "counties_sc.example_probate": 2}           # discovery-style slug, prefixed rows
    carried = [_Row("counties_sc.example_zeroed") for _ in range(5)]
    survivors = layer[:1] + handoff[1:] + [_Row("counties_sc.example_probate.somepaper")]
    out = dict(all_filtered_sources(results, by_source, survivors))
    # the old slug test warned about the layer scraper and the hand-off; neither lost every row
    assert "counties_generic.arcgis_distress_layers" not in out
    assert "national.stealth_handoff" not in out
    assert "counties_sc.example_probate" not in out
    assert out["counties_nc.example_tax_foreclosures"] == 4
    assert out["counties_sc.example_zeroed"] == 5          # every carryover replay filtered
    assert all_filtered_sources(results, by_source, survivors + carried[:1]).count(
        ("counties_sc.example_zeroed", 5)) == 0


# --------------------------------------------------------------------------- column lineage
import importlib.util as _ilu  # noqa: E402
import sys as _sys  # noqa: E402
from datetime import date as _date  # noqa: E402
from pathlib import Path as _P  # noqa: E402

_GM_PATH = _P(__file__).resolve().parents[1] / "scripts" / "gap_matrix.py"
_GM_SPEC = _ilu.spec_from_file_location("gap_matrix_dl", _GM_PATH)
gm = _ilu.module_from_spec(_GM_SPEC)
_sys.modules["gap_matrix_dl"] = gm
_GM_SPEC.loader.exec_module(gm)
TODAY = _date(2026, 10, 9)


def _row(**kw):
    base = {"source": "test.src", "source_url": "https://example.test/x", "listing_type": "distressed",
            "property_kind": "single_family", "state": "NC", "county": "Buncombe", "raw": {}}
    base.update(kw)
    return base


def _second_view(rec):
    owner = gm.owner_columns(rec)
    return owner, gm.positive_columns(rec, owner, {}, TODAY), gm.checked_columns(
        rec, gm.positive_columns(rec, owner, {}, TODAY), {})


def test_negative_wrappers_count_in_the_10_1_view_but_not_as_hits():
    cases = [
        ("bankruptcy_stay", {"bankruptcy_stay": {"status": "lapsed"}}),
        ("storm_damage", {"storm_damage": {"damage_level": "unaffected"}}),
        ("title_risk", {"title_risk": {"kind": "senior", "surviving_senior_debt_risk": False}}),
        ("bop_federal", {"bop_federal": {"in_custody": False, "facility_name": "X"}}),
        ("usps_vacancy", {"usps_vacancy": {"vacancy_level": "low"}}),
        ("lien_priority", {"lien_priority": {"senior_liens": [], "junior_liens": [],
                                             "super_priority_warnings": [], "docs_examined": 3}}),
        ("vacancy", {"vacancy": {"utility_status": "power on"}}),
        ("code_enforcement", {"code_enforcement": {"has_open": True, "vacancy_adjacent": False}}),
        ("divorce", {"divorce": {"case_count": 1, "cases": [{"parties": ["DOE, JANE"]}]}}),
        ("probate", {"probate": {"date_of_death": "2026-01-01"}}),
        ("incarceration", {"incarceration": {"source": "Example County jail roster"}}),
    ]
    for col, raw in cases:
        owner, pos, chk = _second_view(_row(raw=raw))
        if col in ("probate",):
            assert col not in owner      # the 10/1 probate rule already needs a decedent
        else:
            assert col in owner, col     # the 10/1 presence rule counted it
        assert col not in pos, col       # the scorer would not
        assert col in chk, col           # but the row WAS checked


def test_scorer_hits_stay_hits():
    raw = {"bankruptcy_stay": {"status": "stayed", "date_filed": "2026-09-01", "chapter": "13"},
           "storm_damage": {"damage_level": "major"},
           "title_risk": [{"surviving_senior_debt_risk": True}],
           "bop_federal": {"in_custody": True},
           "usps_vacancy": {"vacancy_level": "high"},
           "lien_priority": {"senior_liens": [{"type": "dot"}]},
           "vacancy": {"vacant": True},
           "code_enforcement": [{"status": "open"}],          # list shape: the 10/1 rule missed it
           "probate": {"decedent": "EXAMPLE DECEDENT"}}
    owner, pos, _ = _second_view(_row(raw=raw))
    assert "code_enforcement" not in owner
    for col in ("bankruptcy_stay", "storm_damage", "title_risk", "bop_federal", "usps_vacancy",
                "lien_priority", "vacancy", "code_enforcement", "probate"):
        assert col in pos, col


def test_liensnc_lien_agent_rows_are_not_tax_lien_hits():
    owner, pos, _ = _second_view(_row(source="counties_generic.liensnc", listing_type="tax_lien"))
    assert "lt_tax_lien" in owner and "lt_tax_lien" not in pos
    owner, pos, _ = _second_view(_row(source="counties_nc.example_delinquent_tax", listing_type="tax_lien"))
    assert "lt_tax_lien" in pos


def test_heir_candidates_and_obituary_attorney_columns():
    _, pos, _ = _second_view(_row(raw={"heir_candidates": [{"name": "EXAMPLE PERSON", "relation": "spouse"}]}))
    assert "atty_heir_candidates" in pos
    _, pos, _ = _second_view(_row(raw={"life_event": "death"}))     # a probate notice's stamp
    assert "atty_obituary_match" not in pos
    _, pos, _ = _second_view(_row(raw={"obituary": {"decedent": "EXAMPLE"}}))
    assert "atty_obituary_match" in pos


def test_every_gate_column_is_a_real_column():
    assert set(gm.SCORER_GATES) <= set(gm.ALL_COLUMNS)


def test_owner_email_of_every_shape():
    from foreclosure_scraper.enrichment_email_extract import owner_email_of
    assert owner_email_of({"owner_email": {"best_email": "law@example.test",
                                           "best_classification": "attorney"}}) is None
    assert owner_email_of({"owner_email": {"best_email": "o@example.test",
                                           "best_classification": "owner"}}) == "o@example.test"
    assert owner_email_of({"owner_email": {"best_email": "law@example.test", "best_classification": "attorney",
                                           "emails": [{"email": "law@example.test", "classification": "attorney"},
                                                      {"email": "o2@example.test", "classification": "owner"}]}}
                          ) == "o2@example.test"
    assert owner_email_of({"owner_email": {"email": "l@example.test", "source": "liensnc_filing"}}) == "l@example.test"
    assert owner_email_of({"skip_trace": {"email_addresses": ["s@example.test"]}}) == "s@example.test"
    assert owner_email_of({"skip_trace": {"owner_email": "never@example.test"}}) is None
    assert owner_email_of(None) is None


def test_email_column_counts_owner_emails_only():
    owner, pos, chk = _second_view(_row(raw={"owner_email": {"best_email": "law@example.test",
                                                             "best_classification": "attorney"}}))
    assert "email" in owner and "email" not in pos and "email" in chk
    owner, pos, _ = _second_view(_row(raw={"owner_email": {"email": "l@example.test", "source": "liensnc_filing"}}))
    assert "email" not in owner and "email" in pos


def test_campaign_export_reads_the_owner_email(tmp_path):
    from foreclosure_scraper import campaign_export
    li = Listing(source="counties_generic.liensnc", source_url="https://example.invalid/x",
                 listing_type=ListingType.TAX_LIEN, state="NC", county="Cleveland", owner_name="EXAMPLE OWNER",
                 raw={"skip_trace": {"owner_name": "EXAMPLE OWNER", "email_addresses": ["s@example.test"]}})
    path, n = campaign_export._export_email([li], tmp_path / "e.csv")
    assert n == 1 and "s@example.test" in path.read_text()


def test_countyless_national_rows_get_the_gazetteer_county_before_the_drop():
    from foreclosure_scraper.drop_audit import count_by_source, fill_county_from_city, is_countyless_national
    known = Listing(source="national.landandfarm", source_url="https://example.invalid/1",
                    listing_type=ListingType.UNKNOWN, state="NC", city="Shelby")
    unknown = Listing(source="national.landandfarm", source_url="https://example.invalid/2",
                      listing_type=ListingType.UNKNOWN, state="NC", city="Nowhere Example")
    has_county = Listing(source="national.xome", source_url="https://example.invalid/3",
                         listing_type=ListingType.REO, state="NC", city="Shelby", county="Rutherford")
    local = Listing(source="counties_nc.example", source_url="https://example.invalid/4",
                    listing_type=ListingType.TAX_LIEN, state="NC", city="Shelby")
    rows = [known, unknown, has_county, local]
    assert count_by_source(rows, is_countyless_national) == {"national.landandfarm": 2}
    st = fill_county_from_city(rows)
    assert st["filled"] == 1 and st["left"] == 1
    assert known.county == "Cleveland" and known.raw["county_backfill"]["evidence"] == "city"
    assert has_county.county == "Rutherford"           # never overwritten
    assert local.county is None                        # not a national row
    assert count_by_source(rows, is_countyless_national) == {"national.landandfarm": 1}


def test_liensnc_owner_email_is_the_owner_block_not_the_claimant():
    from foreclosure_scraper.enrichment_email_extract import liensnc_owner_email, owner_email_of
    from foreclosure_scraper.enrichment_surface_contacts import _surface_emails_from_raw
    raw = {"liensnc": {"filed_by": "Example Contractor, contractor@example.test",
                       "owner_text": "EXAMPLE OWNER, 1 Example Rd, owner@example.test, 555"},
           "liensnc_related": {"notices": [{"claimant": "supplier@example.test"}]}}
    assert liensnc_owner_email(raw) == "owner@example.test"
    assert owner_email_of(raw) == "owner@example.test"
    # a row surfaced before the fix: best_email 'other' (the raw scan's first find)
    raw["owner_email"] = {"emails": [{"email": "contractor@example.test", "classification": "other"}],
                          "best_email": "contractor@example.test", "best_classification": "other"}
    assert owner_email_of(raw) == "owner@example.test"
    raw.pop("owner_email")
    found = _surface_emails_from_raw(raw)
    assert found[0] == {"email": "owner@example.test", "source": "liensnc.owner", "classification": "owner"}
    assert {e["email"] for e in found} == {"owner@example.test", "contractor@example.test",
                                            "supplier@example.test"}
    raw2 = {"liensnc_related": {"owner_contact": {"email": "OC@Example.test"}}}
    assert liensnc_owner_email(raw2) == "oc@example.test"
    assert liensnc_owner_email({"liensnc": {"filed_by": "x@example.test"}}) is None


def test_attorney_columns_read_what_the_writers_write():
    # the register scrapers write raw.rod.instrument, not instrument_no
    _, pos, _ = _second_view(_row(raw={"rod": {"instrument": "202600001234", "doc_type": "DEED"}}))
    assert "atty_deed_ref" in pos
    # probate.case_number is a case
    _, pos, _ = _second_view(_row(raw={"probate": {"decedent": "EXAMPLE", "case_number": "26E000123"}}))
    assert "atty_probate_case" in pos
    # a LiensNC lien-agent filing names the project owner, not the tax roll's taxpayer
    liens = _row(source="counties_generic.liensnc", listing_type="tax_lien", owner_name="EXAMPLE OWNER",
                 raw={"owner_mailing": {"owner": "EXAMPLE OWNER", "mailing": "1 EXAMPLE RD",
                                        "source": "liensnc_filing"}})
    _, pos, _ = _second_view(liens)
    assert "atty_taxpayer_of_record" not in pos
    roll = _row(source="counties_nc.example_delinquent_tax", listing_type="tax_lien", owner_name="EXAMPLE OWNER")
    _, pos, _ = _second_view(roll)
    assert "atty_taxpayer_of_record" in pos
    # a probate notice's personal representative (owner_mailing.addressee) is not the taxpayer
    pr = _row(source="counties_sc.example_probate", listing_type="probate_notice",
              raw={"owner_mailing": {"addressee": "EXAMPLE REPRESENTATIVE", "mailing": "1 EXAMPLE RD"}})
    _, pos, _ = _second_view(pr)
    assert "atty_taxpayer_of_record" not in pos


# --------------------------------------------------------------------------- the invariants
_DL_SPEC = _ilu.spec_from_file_location(
    "drops_lineage_checks", _P(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "drops_lineage.py")
dl = _ilu.module_from_spec(_DL_SPEC)
_DL_SPEC.loader.exec_module(dl)


def _run(rows):
    checks = dl.make_checks()
    for r in rows:
        for c in checks:
            c.feed(r)
    return {res["name"]: res for res in (c.finish() for c in checks)}


def test_the_checks_follow_the_interface_and_pass_a_clean_row():
    res = _run([_row(parcel_id="1234567890", raw={"gis": {"owner": "X", "absentee": True}})])
    assert len(res) == 9
    for r in res.values():
        assert set(r) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
        assert r["ok"], r


def test_the_checks_catch_each_defect():
    rows = [
        _row(county="Cleveland", parcel_id=None,
             raw={"parcel_id_nulled": {"value": "12345", "reason": "too_short"}}),
        _row(raw={"situs_nulled": "PINEVIEW ACADEMY RD 4021", "situs_quality": "low"}),
        _row(raw={"gis": {"owner": "X", "unpublished_key": 1}}),
        _row(county="", source="counties_nc.example_new_feed"),
    ]
    res = _run(rows)
    assert res["drops-short-parcel-county-native"]["violations"] == 1
    assert res["drops-situs-road-nulled"]["violations"] == 1
    assert res["lineage-gis-subkeys"]["violations"] == 1
    assert res["drops-county-blank-source"]["violations"] == 1
    assert res["lineage-scorer-gated-columns"]["violations"] == 0


def test_the_age_out_and_marker_bounds_count():
    many = [_row(raw={"pulled_sale": {"consecutive_misses": 4}}) for _ in range(3)]
    res = _run(many)
    assert res["drops-age-out-imminent"]["violations"] == 3
    mb = dl.MarkerBounds()
    for _ in range(dl.MARKER_BOUNDS["county_was_name_derived"] + 1):
        mb.feed({"raw": {"county_was_name_derived": {"county": "X"}}})
    assert mb.finish()["violations"] == 1


# --------------------------------------------------------------------------- low-value parcels
def test_a_low_county_value_is_kept_flagged_and_never_a_house_value():
    from foreclosure_scraper.models import PropertyKind
    from foreclosure_scraper.valuation import calc, grading
    li = _li(county="Greenville", state="SC", source="counties_generic.arcgis_distress.example_layer",
             property_kind=PropertyKind.SINGLE_FAMILY, tax_value=500.0, market_value=500.0)
    stats = validate([li])
    assert stats["tax_value_too_low"] == 1
    assert li.tax_value is None
    assert li.raw["tax_value_low"] == {"value": 500.0, "county": "Greenville",
                                       "source": "counties_generic.arcgis_distress.example_layer",
                                       "reason": "kind_unverified"}
    assert li.raw["low_value_parcel"] is True
    li.opening_bid = 40_000.0       # a bid would otherwise carry a bid-proxy ARV
    c = calc.compute(li)
    assert c.arv_expected is None
    assert "low_value_parcel" in (c.arv_flags or [])
    assert grading.arv_trust(c.arv_flags, c.arv_expected, c.arv_withheld) in grading.ARV_TRUST_BLOCKS_DERIVED


def test_land_and_real_values_are_not_flagged_and_a_stale_flag_clears():
    from foreclosure_scraper.models import PropertyKind
    land = _li(property_kind=PropertyKind.LAND, tax_value=800.0)
    validate([land])
    assert land.tax_value == 800.0 and "low_value_parcel" not in land.raw
    carried = _li(property_kind=PropertyKind.SINGLE_FAMILY, tax_value=150_000.0,
                  raw={"low_value_parcel": True, "tax_value_low": {"value": 900.0}})
    validate([carried])
    assert "low_value_parcel" not in carried.raw and "tax_value_low" not in carried.raw
    kept = _li(property_kind=PropertyKind.SINGLE_FAMILY, tax_value=None,
               raw={"low_value_parcel": True, "tax_value_low": {"value": 900.0}})
    validate([kept])
    assert kept.raw["low_value_parcel"] is True       # nothing new to contradict it


def test_the_low_value_check():
    ok = _row(raw={"tax_value_low": {"value": 500.0}, "low_value_parcel": True, "calc": {"arv_expected": None}})
    bad = _row(raw={"tax_value_low": {"value": 500.0}, "low_value_parcel": True,
                    "calc": {"arv_expected": 120000}})
    flag_only = _row(raw={"low_value_parcel": True})
    res = _run([ok, bad, flag_only])["drops-low-value-parcel"]
    assert res["checked"] == 3 and res["violations"] == 2


def test_removed_by_source_counts_what_a_filter_took():
    from foreclosure_scraper.drop_audit import removed_by_source
    a, b, c, d = _Row("s1"), _Row("s1"), _Row("s2"), _Row("s3")
    assert removed_by_source([a, b, c, d], [b]) == {"s1": 1, "s2": 1, "s3": 1}
    assert removed_by_source([a, b, c, d], [b], top=1) in ({"s1": 1}, {"s2": 1}, {"s3": 1})
    assert removed_by_source([a, a, c], [c]) == {"s1": 2}


def test_countyless_rows_are_placed_by_zip_and_a_conflict_is_left():
    from foreclosure_scraper._zip_to_county import ZIP_COUNTY, county_for_zip
    from foreclosure_scraper.drop_audit import fill_county_from_city
    (st, z), cty = next(iter(sorted(ZIP_COUNTY.items())))
    assert county_for_zip(z + "-1234", st.lower()) == cty and county_for_zip("1234", st) is None
    by_zip = Listing(source="national.landandfarm", source_url="https://example.invalid/5",
                     listing_type=ListingType.UNKNOWN, state=st, city="Nowhere Example", zip_code=z)
    other = next(c for c in ("Cleveland", "Wake") if c != cty)
    city = "Shelby" if other == "Cleveland" else "Raleigh"
    clash = Listing(source="national.xome", source_url="https://example.invalid/6",
                    listing_type=ListingType.REO, state=st, city=city, zip_code=z)
    st_ = fill_county_from_city([by_zip, clash])
    assert by_zip.county == cty and by_zip.raw["county_backfill"]["evidence"] == "zip"
    assert clash.county is None and st_["conflicts"] == (1 if st == "NC" else 0)


def test_the_zip_table_module_renders_and_imports(tmp_path):
    spec = _ilu.spec_from_file_location(
        "build_zip_county_table", _P(__file__).resolve().parents[1] / "scripts" / "build_zip_county_table.py")
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from collections import Counter
    text = mod.render({("NC", "28150"): "Cleveland"}, Counter({"cache+board": 1}))
    f = tmp_path / "zt.py"
    f.write_text(text)
    zs = _ilu.spec_from_file_location("zt", f)
    zt = _ilu.module_from_spec(zs)
    zs.loader.exec_module(zt)
    assert zt.county_for_zip("28150", "NC") == "Cleveland" and zt.county_for_zip("28150", "SC") is None

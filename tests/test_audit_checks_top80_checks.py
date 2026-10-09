"""scripts/audit_checks/top80_checks.py on made-up rows, plus the live repo configuration."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("top80_checks", REPO / "scripts" / "audit_checks" / "top80_checks.py")
T = importlib.util.module_from_spec(spec)
sys.modules["top80_checks"] = T
spec.loader.exec_module(T)


def by_name(checks):
    return {c.name: c for c in checks}


def run(name, rows):
    c = by_name(T.make_checks())[name]
    for r in rows:
        c.feed(r)
    return c.finish()


def its_row(county="Anson", years=(2024, 2025), two=True, parcel="7404", street="1 SAMPLE RD", total=100.0, bal=100.0):
    blk = {"county": county, "years": list(years), "is_two_year_plus": two, "total_due": total}
    raw = {"nc_its_public_tax": blk,
           "two_year_delinquent": {"is_two_year_plus": two},
           "tax_owed": {"balance": bal, "source": "counties_nc.nc_its_public_tax"}}
    return {"state": "NC", "county": county, "parcel_id": parcel, "street_address": street, "raw": raw}


def test_the_interface_and_names():
    checks = T.make_checks()
    assert [c.name for c in checks] == [
        "top80-its-roll-shape", "top80-its-county-silent", "top80-onemap-heir-shape",
        "top80-onemap-flag-shape", "top80-onemap-flag-share", "top80-probate-match-shape",
        "top80-vacant-lot-shape", "top80-checks-config"]
    for c in checks:
        r = c.finish()
        assert set(r) == {"name", "checked", "violations", "max_violations", "ok", "detail"}


def test_its_roll_shape_accepts_a_clean_block_and_flags_each_contradiction():
    ok = run("top80-its-roll-shape", [its_row(), its_row(years=(2025,), two=False), its_row(parcel=None)])
    assert ok["ok"] and ok["checked"] == 3
    assert not run("top80-its-roll-shape", [its_row(two=False)])["ok"]            # 2 years but flag False
    assert not run("top80-its-roll-shape", [its_row(years=(2025,), two=True)])["ok"]
    assert not run("top80-its-roll-shape", [its_row(years=(2025, 2024))])["ok"]    # not ascending
    assert not run("top80-its-roll-shape", [its_row(county="Wake")])["ok"]         # not a portal
    assert not run("top80-its-roll-shape", [its_row(parcel=None, street=None)])["ok"]
    assert not run("top80-its-roll-shape", [its_row(bal=5.0)])["ok"]


def test_its_county_silent_needs_enough_rows_and_names_the_missing_county():
    few = run("top80-its-county-silent", [its_row()] * 10)
    assert few["ok"] and "not part of this board" in few["detail"]
    rows = [its_row(county=c) for c in T.ITS_COUNTIES if c != "Duplin" for _ in range(60)]
    got = run("top80-its-county-silent", rows)
    assert not got["ok"] and "Duplin" in got["detail"]
    full = [its_row(county=c) for c in T.ITS_COUNTIES for _ in range(60)]
    assert run("top80-its-county-silent", full)["ok"]


def heir_row(owner, source="nc_onemap_sweep"):
    return {"state": "NC", "county": "Wake", "raw": {"heir_estate": {"owner_of_record": owner, "source": source}}}


def test_heir_shape():
    assert run("top80-onemap-heir-shape", [heir_row("DOE JANE HEIRS"), heir_row("ESTATE OF ROE MARY")])["ok"]
    assert not run("top80-onemap-heir-shape", [heir_row("DOE JANE")])["ok"]
    assert not run("top80-onemap-heir-shape", [heir_row("DOE LIFE ESTATE")])["ok"]
    assert run("top80-onemap-heir-shape", [heir_row("DOE JANE", source="county layer")])["checked"] == 0


def flag_row(county="Alamance", state="NC", **over):
    rb = {"basis": "present_use_flag", "deferred_value": None, "estimated_rollback": None, "state": "NC",
          "source_key": "nc_onemap_presentval"}
    rb.update(over)
    return {"state": state, "county": county, "parcel_id": "1", "raw": {"rollback_exposure": rb}}


def test_flag_shape_forbids_a_dollar_figure_and_other_states():
    assert run("top80-onemap-flag-shape", [flag_row()])["ok"]
    assert not run("top80-onemap-flag-shape", [flag_row(deferred_value=1000.0)])["ok"]
    assert not run("top80-onemap-flag-shape", [flag_row(state="SC")])["ok"]
    assert not run("top80-onemap-flag-shape", [flag_row(source_key=None)])["ok"]


def test_flag_share_catches_a_county_where_the_flag_is_on_everything():
    ok_rows = [flag_row("Alamance")] * 5 + [{"state": "NC", "county": "Alamance", "parcel_id": "9", "raw": {}}] * 60
    assert run("top80-onemap-flag-share", ok_rows)["ok"]
    bad_rows = [flag_row("Johnston")] * 60 + [{"state": "NC", "county": "Johnston", "parcel_id": "9", "raw": {}}] * 2
    got = run("top80-onemap-flag-share", bad_rows)
    assert not got["ok"] and "Johnston" in got["detail"]
    small = [flag_row("Dare")] * 10
    assert run("top80-onemap-flag-share", small)["ok"]       # too few rows to judge


def test_live_repo_configuration_is_consistent():
    got = by_name(T.make_checks())["top80-checks-config"].finish()
    assert got["ok"], got["detail"]


def prow(match=None, probate=None, owner="ESTATE OF DOE JANE", state="SC", county="Greenwood", **raw_extra):
    raw = dict(raw_extra)
    if match is not None:
        raw["probate_index_match"] = match
    if probate is not None:
        raw["probate"] = probate
    return {"state": state, "county": county, "owner_name": owner, "raw": raw}


GOOD = {"case_number": "2020ES2400222", "level": "full", "county": "Greenwood", "party_type": "DEC"}
PR = {"source": "spartan_public_probate", "case_number": "2020ES2400222", "es_case_number": "2020ES2400222"}


def test_probate_match_shape():
    assert run("top80-probate-match-shape", [prow([GOOD], PR), prow([GOOD], owner="DOE JANE")])["ok"]
    assert not run("top80-probate-match-shape", [prow([GOOD, GOOD, GOOD, GOOD])])["ok"]
    assert not run("top80-probate-match-shape", [prow([{**GOOD, "level": "maybe"}])])["ok"]
    assert not run("top80-probate-match-shape", [prow([{**GOOD, "county": "Aiken"}])])["ok"]
    assert not run("top80-probate-match-shape", [prow([GOOD], state="NC")])["ok"]
    assert not run("top80-probate-match-shape", [prow([GOOD], {**PR, "es_case_number": "X"})])["ok"]
    got = run("top80-probate-match-shape", [prow([GOOD], PR, owner="DOE JANE")])
    assert not got["ok"] and "probate_without_death_signal" in got["detail"]


def test_vacant_lot_shape():
    ok = {"state": "SC", "raw": {"vacant_lot": {"land_use": "Vacant Residential", "source": "parcel_cache_landuse"}}}
    bad = {"state": "SC", "raw": {"vacant_lot": {"land_use": "R", "source": "parcel_cache_landuse"}}}
    other = {"state": "SC", "raw": {"vacant_lot": {"land_use": "R", "source": "county"}}}
    assert run("top80-vacant-lot-shape", [ok, other])["ok"]
    assert not run("top80-vacant-lot-shape", [ok, bad])["ok"]

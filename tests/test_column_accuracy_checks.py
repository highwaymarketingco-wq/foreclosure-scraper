"""scripts/audit_checks/column_accuracy.py (audit 2026-10-09). Fixtures are made up."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "audit_checks"))

import column_accuracy as CA  # noqa: E402
from foreclosure_scraper import parcel_cache as P  # noqa: E402


def _run(check, rows):
    for r in rows:
        check.feed(r)
    return check.finish()


def test_email_owner_only():
    good = {"raw": {"owner_email": {"best_email": "pat@x.test", "best_classification": "owner"},
                    "liensnc": {"owner_text": "pat@x.test"}}}
    agent = {"raw": {"owner_email": {"best_email": "a@realty.test", "best_classification": "other"}}}
    artifact = {"raw": {"owner_email": {"best_email": "npat@x.test", "best_classification": "owner"},
                        "liensnc": {"owner_text": "OWNER\npat@x.test"}}}
    r = _run(CA.EmailOwnerOnly(), [good, agent, artifact])
    assert (r["checked"], r["violations"], r["ok"]) == (3, 2, False)


def test_fuzzy_phone_needs_the_new_gate_stamp():
    old = {"raw": {"owner_phone": {"phone": "(828) 555-0101", "source": "ncsbe_voter",
                                   "match": "fuzzy:soundex+county-unique", "identity_check": "corroborated"}}}
    new = {"raw": {"owner_phone": {"phone": "(828) 555-0101", "source": "ncsbe_voter",
                                   "match": "fuzzy:soundex+county-unique", "identity_check": "corroborated",
                                   "identity_basis": "fuzzy_phone_on_owner_named_voter"}}}
    flagged = {"raw": {"owner_phone": {"phone": "(828) 555-0101", "source": "ncsbe_voter",
                                       "match": "fuzzy:soundex+addr", "do_not_dial": True}}}
    r = _run(CA.PhoneFuzzyRechecked(), [old, new, flagged])
    assert (r["checked"], r["violations"]) == (3, 1)


def test_sc_assessed_equal_market_and_glued_numbers():
    r = _run(CA.ScAssessedNotMarket(), [
        {"state": "SC", "assessed_value": 1e5, "market_value": 1e5},
        {"state": "SC", "assessed_value": 6e3, "market_value": 1e5},
        {"state": "NC", "assessed_value": 1e5, "market_value": 1e5}])
    assert (r["checked"], r["violations"]) == (2, 1)
    g = _run(CA.HouseNumberGlued(), [
        {"source": "counties_sc.berkeley_paystar_tax", "raw": {"owner_mailing": {"mailing": "313EXAMPLE DR X SC"}}},
        {"source": "s", "street_address": "100TH ST"}])
    assert g["violations"] == 1 and g["ok"] is False          # a Berkeley row must be 0


def test_layer_map_semantics_catches_component_and_money_fields(monkeypatch):
    assert CA.layer_map_problems() == []
    bad = dict(P.PARCEL_LAYERS)
    bad["Testcounty"] = {"url": "u", "id_fields": ["PIN"],
                         "map": {"market_value": "CurrentAppraisedBuildingValue", "tax_value": "landval",
                                 "living_sqft": "BUILDING_VALUE"}}
    bad["Testtwo"] = {"url": "u", "id_fields": ["PIN"], "map": {"living_sqft": "Dwelling"}}
    monkeypatch.setattr(P, "PARCEL_LAYERS", bad)
    assert sorted(CA.layer_map_problems()) == ["Testcounty.living_sqft=BUILDING_VALUE",
                                               "Testcounty.market_value=CurrentAppraisedBuildingValue",
                                               "Testcounty.tax_value=landval",
                                               "Testtwo.living_sqft=Dwelling"]


def test_placeholder_classes():
    assert CA.placeholder_class("address", "MAIN ST", {}) == "street_only"
    assert CA.placeholder_class("address", "12 MAIN ST", {}) is None
    assert CA.placeholder_class("phone", "(111) 555-0100", {}) == "not_nanp"
    assert CA.placeholder_class("owner_name", "UNKNOWN", {}) == "placeholder_name"
    assert CA.placeholder_class("year_built", 0, {}) == "impossible_year"


def test_fill_report_never_fails():
    r = _run(CA.FillOnCallList(), [{"raw": {"distress_stack": {"tier": "WARM"}}, "street_address": "MAIN ST"}])
    assert r["ok"] and "warm n=1" in r["detail"] and "address 1/1" in r["detail"]

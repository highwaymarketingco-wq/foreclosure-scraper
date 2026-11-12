"""tax_lien_pickens v1: the row's own PIN on Pickens County's current published delinquent-tax
list (the county's ArcGIS publications; its bill API is a CloudFront 403 wall). Confirmed only from
the current list; absence is never stale or refuted. Hand-written layer answers in the ArcGIS
REST shape with made-up PINs, owners and addresses. No network."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover, from_module
from foreclosure_scraper.verification.verifiers import _arcgis_layer as ag
from foreclosure_scraper.verification.verifiers import tax_lien_pickens as P
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as Q

TODAY = date(2026, 10, 8)
REAL_LAYERS = P.layers
EDIT_DELQ = datetime(2026, 9, 18, 19, 46, tzinfo=timezone.utc)
EDIT_WEEK = datetime(2026, 9, 21, 14, 11, tzinfo=timezone.utc)
L21 = P.ListLayer("del_2021", 2021, False, pin="PIN", situs="LOCADD")
L24 = P.ListLayer("dqnt_2024", 2024, False, pin="PIN", situs="LOCADD")
DELQ = P.ListLayer("DELQ_TAX_WEEK1_2026", 2026, True, pin="GISADMIN_P", owner="T_WEEK_1_1",
                   amount="T_WEEK_1_2")
WEEK = P.ListLayer("WeekOne2027", 2026, True, pin="MAP_PARCEL", owner="OWNER__NOW",
                   amount="AMOUNT_DUE")
LAYERS = [L21, L24, DELQ, WEEK]

PIN_A = "9000-00-00-0001"      # on every list: chronic, owes
PIN_B = "9000-00-00-0002"      # on the 2024 list only
PIN_C = "9000-00-00-0003"      # two unit accounts under one PIN
PIN_D = "9000-00-00-0004"      # its county situs is a neighbor's number

HIST = {
    L21: [{"PIN": PIN_A, "LOCADD": "100 TEST RD"}],
    L24: [{"PIN": PIN_A, "LOCADD": "100 TEST RD"}, {"PIN": PIN_B, "LOCADD": "200 TEST RD"},
          {"PIN": PIN_D.replace("-", ""), "LOCADD": "104 SAMPLE LN"}],
    DELQ: [{"GISADMIN_P": PIN_A, "T_WEEK_1_1": "TESTOWNER PAT", "T_WEEK_1_2": 1250.4},
           {"GISADMIN_P": PIN_C, "T_WEEK_1_1": "UNITOWNER ONE", "T_WEEK_1_2": 410.0},
           {"GISADMIN_P": PIN_C, "T_WEEK_1_1": "UNITOWNER TWO", "T_WEEK_1_2": 380.5},
           {"GISADMIN_P": PIN_D, "T_WEEK_1_1": "TESTOWNER PAT", "T_WEEK_1_2": 900.0}],
    WEEK: [{"MAP_PARCEL": PIN_A, "OWNER__NOW": "TESTOWNER PAT", "AMOUNT_DUE": "1250.4"},
           {"MAP_PARCEL": PIN_C, "OWNER__NOW": "UNITOWNER ONE", "AMOUNT_DUE": "790.5"},
           {"MAP_PARCEL": PIN_D, "OWNER__NOW": "TESTOWNER PAT", "AMOUNT_DUE": "900"}],
}


def _ms(dt):
    return int(dt.timestamp() * 1000)


def serve(hist=None, *, services=None, drop=(), extra=None) -> ReplayFetcher:
    hist = HIST if hist is None else hist
    resp: dict = {}
    for L in LAYERS:
        if L in drop:
            continue
        rows = hist.get(L, [])
        edit = EDIT_WEEK if L is WEEK else EDIT_DELQ if L is DELQ else datetime(2024, 10, 1, tzinfo=timezone.utc)
        resp[ag.meta_url(L.url)] = json.dumps({"editingInfo": {"dataLastEditDate": _ms(edit)}})
        resp[ag.count_url(L.url)] = json.dumps({"count": len(rows)})
        resp[ag.page_url(L.url, out_fields=L.out_fields, order_by="FID", offset=0, page=2000)] = \
            json.dumps({"features": [{"attributes": dict(a, FID=i + 1)} for i, a in enumerate(rows)]})
    names = services if services is not None else [L.service for L in LAYERS] + \
        ["Parcels_Pumpkintown_Cleveland_Tornado", "PlumModel_67Degree_New"]
    resp[f"{P.ORG}?f=json"] = json.dumps({"services": [{"name": n} for n in names]})
    resp.update(extra or {})
    return ReplayFetcher(resp)


@pytest.fixture(autouse=True)
def _layers(monkeypatch):
    monkeypatch.setattr(P, "layers", lambda: list(LAYERS))


def row(pin=PIN_A, *, street="100 TEST RD", owner="TESTOWNER PAT", **kw):
    r = {"state": "SC", "county": "Pickens", "parcel_id": pin, "street_address": street,
         "owner_name": owner, "listing_type": "tax_lien",
         "source": "counties_sc.pickens_delinquent_parcels",
         "raw": {"pickens_delinquent": {"cycles": [2024, 2025]}}}
    r.update(kw)
    return r


def run(r, f, today=TODAY):
    return asyncio.run(P.verify(r, f, today=today))


def test_applies_only_to_pickens_tax_claims_and_no_other_tax_verifier_does():
    assert P.applies(row())
    assert not P.applies(row(county="Oconee"))
    assert not P.applies(row(state="NC"))
    assert not P.applies(row(listing_type="flood_damage", source="x", raw={}))
    assert P.applies(row(listing_type="flood_damage", source="x",
                         raw={"two_year_delinquent": {"is_two_year_plus": True}}))
    # a DEW lien typed tax_lien is not a property-tax claim
    assert not P.applies(row(source="counties_sc.sc_dew_lien_registry", raw={}))
    others = [v for v in discover() if v.signal == "tax_lien" and v.name != "tax_lien_pickens"]
    assert not any(v.safe_applies(row()) for v in others)
    assert not Q.applies(row())


def test_on_the_current_list_is_confirmed_with_the_amount_and_the_listing_history():
    f = serve()
    res = run(row(), f)
    ev = res.evidence
    assert res.verdict == "confirmed" and res.verifier == "tax_lien_pickens"
    assert ev["on_current_list"] and ev["amount_due"] == 1250.4 == ev["total_delinquent"]
    assert ev["list_cycles"] == [2021, 2024, 2026] and ev["chronic_claim"] == "confirmed"
    assert ev["list_as_of"] == "2026-09-21" and ev["list_age_days"] == 17
    assert ev["owner_match"] == "same" and ev["address_relation"] == "match"
    assert not ev["under_500"]
    assert "TESTOWNER" not in json.dumps(res.to_dict()) and "TEST RD" not in json.dumps(res.to_dict())
    n = len(f.asked)
    run(row(), f)                                   # every list read once per run
    assert len(f.asked) == n


def test_absence_from_the_current_list_is_never_stale_or_refuted():
    res = run(row(PIN_B, street="200 TEST RD"), serve())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "not_on_current_list"
    assert res.evidence["list_cycles"] == [2024] and res.evidence["on_current_list"] is False
    assert res.evidence["chronic_claim"] == "unknown"


def test_not_listed_and_in_the_tax_sale_results_is_its_own_state():
    r = row(PIN_B, street="200 TEST RD")
    r["raw"]["pickens_tax_sale"] = {"bidder": "150", "item_no": "00002", "parcel": PIN_B}
    assert run(r, serve()).evidence["reason"] == "sold_at_tax_sale"
    r["raw"]["pickens_tax_sale"]["bidder"] = "PBO"          # bought by the owner: not a sale
    assert run(r, serve()).evidence["reason"] == "not_on_current_list"


def test_unit_accounts_under_one_pin_bind_to_the_board_owner_or_stay_unconfirmed():
    res = run(row(PIN_C, street="300 TEST RD", owner="SOMEONE ELSE"), serve())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "shared_pin_accounts"
    assert res.evidence["accounts_on_list"] == 2
    res2 = run(row(PIN_C, street="300 TEST RD", owner="UNITOWNER TWO"), serve())
    assert res2.verdict == "confirmed" and res2.evidence["amount_due"] == 380.5


def test_a_neighbors_house_number_on_the_county_situs_is_not_confirmed():
    res = run(row(PIN_D, street="100 SAMPLE LN"), serve())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "address_parcel_mismatch"
    assert res.evidence["address_relation"] == "conflict"


def test_a_resolver_parcel_with_another_owner_is_not_confirmed():
    r = row(owner="DIFFERENT PERSONNAME")
    r["raw"]["parcel_from_address"] = {"how": "test"}
    res = run(r, serve())
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "address_parcel_mismatch"


def test_a_newer_unread_publication_stops_confirmation():
    week2 = f"{P.ORG}/DELQ_TAX_WEEK2_2026/FeatureServer/0"
    f = serve(services=[L.service for L in LAYERS] + ["DELQ_TAX_WEEK2_2026"],
              extra={ag.meta_url(week2): json.dumps(
                  {"editingInfo": {"dataLastEditDate": _ms(datetime(2026, 10, 1, tzinfo=timezone.utc))}})})
    res = run(row(), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "newer_list_unread"
    assert res.evidence["newer_list_unread"] == ["DELQ_TAX_WEEK2_2026"]


def test_an_old_list_no_longer_confirms():
    res = run(row(), serve(), today=date(2027, 3, 1))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "list_too_old"


def test_a_current_list_that_does_not_load_is_transient():
    res = run(row(), serve(drop=(WEEK,)))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "layer_unavailable"
    v = from_module(P)
    assert v.is_transient(res.to_dict()) and v.transient_retry_days == 0.25
    # an older list that does not load only shortens the history
    res2 = run(row(), serve(drop=(L21,)))
    assert res2.verdict == "confirmed" and res2.evidence["history_layers_missing"] == ["del_2021"]
    assert res2.evidence["list_cycles"] == [2024, 2026]


def test_no_pickens_pin_is_unconfirmed_without_a_request():
    f = serve()
    res = run(row(pin="12-34"), f)
    assert res.evidence["reason"] == "parcel_unresolvable" and f.asked == []


def test_older_lists_are_read_for_pin_and_situs_only():
    olds = [L for L in REAL_LAYERS() if not L.current]
    assert olds and all(L.owner is None and L.amount is None for L in olds)
    assert all(set(L.out_fields.split(",")) <= {"FID", L.pin, L.situs} for L in olds)
    cur = {L.service for L in REAL_LAYERS() if L.current}
    assert cur >= {"DELQ_TAX_WEEK1_2026", "WeekOne2027"}

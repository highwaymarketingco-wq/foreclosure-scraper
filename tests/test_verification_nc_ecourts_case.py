"""nc_ecourts_case: an NC Judgment Search claim re-read at its source (made-up fixtures, no network).

The verifier finds the row's judgment by its county and its own order date (the open index does
not match case numbers in free text), then judges status and whether the judgment's parties are
the row's owner of record.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher, json_key
from foreclosure_scraper.verification.verifiers import nc_ecourts_case as V

TEMPLATE = {"queryString": "*", "from": 0, "size": 10, "parameters": {}, "sorts": [],
            "facets": [{"name": "Location", "buckets": []}],
            "searchResult": {"totalHits": 0, "hits": []}}


@pytest.fixture(autouse=True)
def _fresh_caches():
    V.reset_caches()
    yield
    V.reset_caches()


def _row(**kw) -> dict:
    row = {"state": "NC", "county": "Forsyth", "source": "counties_nc.nc_ecourts_lis_pendens",
           "listing_type": "lis_pendens", "case_number": "26M000777-330",
           "raw": {"nc_ecourts": {"cause": "CV - Claim of Lien", "civilJudgmentStatus": "Active",
                                  "caseID": 111, "judgmentId": 222,
                                  "orderedDate": "2026-09-30T23:00:00-05:00",
                                  "location": "Forsyth Superior Court"}}}
    raw = kw.pop("raw", None)
    row.update(kw)
    if raw:
        row["raw"].update(raw)
    return row


def _hit(case="26M000777-330", status="Active", cause="CV - Claim of Lien", jid=222,
         debtors=("DOE, JOHN Q",), creditors=(), county="Forsyth"):
    return {"caseNumber": case, "location": f"{county} Superior Court", "causeOfActionDesc": cause,
            "civilJudgmentStatus": status, "judgmentId": jid, "caseID": 111,
            "judgmentType": "Recorded", "orderedDate": "2026-09-30T23:00:00-05:00",
            "debtors": [{"name": d} for d in debtors], "creditors": [{"name": c} for c in creditors]}


def _fetcher(row: dict, hits, *, total=None, search_answer=None) -> ReplayFetcher:
    c = V.claim(row)
    w = V.window(c["ordered"])
    so = V.search_object(TEMPLATE, c["county"], w, 0)
    body = search_answer if search_answer is not None else {
        "text": json.dumps({"searchResult": {"totalHits": total if total is not None else len(hits),
                                             "hits": hits}}), "status": 201}
    return ReplayFetcher({json_key(V.SERVICE_URL, None): {"text": json.dumps(TEMPLATE), "status": 201},
                          json_key(V.SERVICE_URL, so): body})


def _run(row, f):
    return asyncio.run(V.verify(row, f))


def test_registered_with_the_contract():
    v = {x.name: x for x in registry.discover()}["nc_ecourts_case"]
    assert v.signal == "nc_ecourts_case" and v.identity == "case" and v.ttl_days == 14
    assert set(v.governs) >= {"lis_pendens", "upset_bid", "judgment_lien", "divorce_notice", "divorce"}
    assert "fetch_failed" in v.transient_reasons


def test_applies_only_to_nc_judgment_claims():
    assert V.applies(_row())
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(source="law_firms.example", listing_type="foreclosure_sale"))
    r = _row()
    r["raw"]["nc_ecourts"].pop("orderedDate")
    assert not V.applies(r)


def test_active_judgment_with_no_property_is_confirmed():
    row = _row()
    r = _run(row, _fetcher(row, [_hit(case="26M000001-330", jid=1), _hit()]))
    assert r.verdict == "confirmed"
    assert r.evidence["status_now"] == "Active"
    assert r.evidence["property_binding"] == "no_property"


def test_cancelled_judgment_is_stale():
    row = _row()
    r = _run(row, _fetcher(row, [_hit(status="Canceled")]))
    assert r.verdict == "stale" and r.evidence["reason"] == "judgment_no_longer_in_force"
    assert V.governs_for(r.to_dict()) == ("lis_pendens", "upset_bid")


def test_party_is_not_the_owner_of_record_is_refuted():
    row = _row(parcel_id="1234567890", street_address="12 EXAMPLE RD", owner_name="ROE RICHARD")
    r = _run(row, _fetcher(row, [_hit(debtors=("DOE, JOHN Q",))]))
    assert r.verdict == "refuted" and r.evidence["property_binding"] == "conflict"
    assert "case_number" not in r.evidence and "judgment_id" not in r.evidence
    # the public evidence names nobody
    assert "DOE" not in json.dumps(r.evidence) and "ROE" not in json.dumps(r.evidence)


def test_party_matching_the_owner_of_record_is_confirmed():
    row = _row(parcel_id="1234567890", street_address="12 EXAMPLE RD", owner_name="DOE JOHN Q")
    r = _run(row, _fetcher(row, [_hit()]))
    assert r.verdict == "confirmed" and r.evidence["property_binding"] == "match"


def test_same_surname_other_first_name_is_unconfirmed():
    row = _row(parcel_id="1234567890", owner_name="DOE MARY")
    r = _run(row, _fetcher(row, [_hit()]))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "surname_only"


def test_divorce_names_both_spouses_and_governs_divorce():
    row = _row(source="counties_nc.nc_ecourts_divorce", listing_type="divorce_notice",
               parcel_id="555", owner_name="ROE RICHARD ETUX",
               raw={"nc_ecourts": {"cause": "FAM - Divorce", "civilJudgmentStatus": "Active",
                                   "judgmentId": 222, "orderedDate": "2026-09-30T23:00:00-05:00"}})
    r = _run(row, _fetcher(row, [_hit(cause="FAM - Divorce", debtors=("Doe, Jane",),
                                      creditors=("Roe, Richard",))]))
    assert r.verdict == "confirmed" and r.evidence["claim_kind"] == "divorce"
    assert V.governs_for(r.to_dict()) == ("divorce_notice", "divorce")


def test_case_not_in_its_window_is_unconfirmed():
    row = _row()
    r = _run(row, _fetcher(row, [_hit(case="26M000001-330", jid=1)]))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_not_in_index"


def test_fused_case_numbers_are_not_checked():
    row = _row()
    row["raw"]["nc_ecourts"]["case_number"] = "26M000999-330"
    f = ReplayFetcher({})
    r = _run(row, f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "case_number_conflict"
    assert f.asked == []


def test_service_error_is_transient():
    row = _row()
    r = _run(row, _fetcher(row, [], search_answer={"text": "busy", "status": 503}))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "service_unhealthy"
    v = {x.name: x for x in registry.discover()}["nc_ecourts_case"]
    assert v.is_transient(r.to_dict())


def test_one_window_request_serves_every_row_of_that_county_and_day():
    a, b = _row(), _row(case_number="26M000778-330")
    b["raw"]["nc_ecourts"]["judgmentId"] = 333
    f = _fetcher(a, [_hit(), _hit(case="26M000778-330", jid=333, status="Satisfied")])
    assert _run(a, f).verdict == "confirmed"
    assert _run(b, f).verdict == "stale"
    assert len(f.asked) == 2          # the template once, the county window once


def test_case_identity_is_per_case_and_county():
    assert V.case_identity(_row()) == V.case_identity(_row(source="nc_ecourts_judgments"))
    assert V.case_identity(_row()) != V.case_identity(_row(county="Wake"))

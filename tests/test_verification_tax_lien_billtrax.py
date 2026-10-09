"""tax_lien_billtrax v1 (Dorchester's delinquent-tax collector on BillTrax).

Synthetic: made-up owners (TESTOWNER ...), map numbers and bill numbers, the shape of the real API
answers (read live 2026-10-09). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_billtrax as bt

TODAY = date(2026, 10, 9)
MAP = "901-00-00-001-000"
TEMPLATE = {"Id": "x", "Name": "Delinquent Tax",
            "NewQuickPayParams": [{"FieldName": n, "FieldValue": ""} for n in
                                  ("AccountNumber", "BillNumber", "PropertyOwner", "PropertyLocation")]}


def bill(m, year, *, owed=0.0, paid_on=None, pending=False, abated=False, owner="TESTOWNER ALPHA", kind="R"):
    return {"Bill": [{"FieldName": "AccountNumber", "FieldValue": m},
                     {"FieldName": "BillNumber", "FieldValue": f"{kind}-{year}-00000001"},
                     {"FieldName": "PropertyOwner", "FieldValue": owner},
                     {"FieldName": "PropertyLocation", "FieldValue": "TEST RD"},
                     {"FieldName": "TotalDueNow", "FieldValue": str(owed)}],
            "Payment": ([{"FieldName": "PaymentDate", "FieldValue": paid_on.isoformat() + "T04:00:00Z"},
                         {"FieldName": "Amount", "FieldValue": "100"}] if paid_on else []),
            "IsPaid": bool(paid_on), "IsPending": pending, "IsBillAbated": abated, "IsDeliquent": True}


class FakeAPI:
    def __init__(self, books, *, status=200):
        self.books, self.status, self.asked = books, status, []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post_form(self, url, data, **_):
        body = json.loads(data["RequestData"])
        self.asked.append((url.rsplit("/", 1)[-1], body))
        if self.status != 200:
            return FormResponse(self.status, url, "Request blocked")
        if url.endswith(bt.TEMPLATE_PATH):
            return FormResponse(200, url, json.dumps(TEMPLATE))
        m = next(p["FieldValue"] for p in body["NewQuickPayParams"] if p["FieldName"] == "AccountNumber")
        rows = [{"BillsAndPayments": self.books.get(m, [])}] if self.books.get(m) else []
        return FormResponse(200, url, json.dumps({"Results": [{"Rows": rows, "PageAttributes": {"TotalRecords": len(rows)}}],
                                                  "HasErrors": False}))


def roll_row(**kw):
    r = {"state": "SC", "county": "Dorchester", "listing_type": "tax_sale",
         "source": "counties_sc.dorchester_billtrax_delinquent_tax", "parcel_id": MAP,
         "street_address": "TEST RD 1", "owner_name": "TESTOWNER ALPHA",
         "raw": {"billtrax_dorchester_delinquent_tax": {"account_number": MAP, "years": [2025]},
                 "tax_owed": {"balance": 900.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def run(row, api):
    return asyncio.run(bt.verify(row, api, today=TODAY))


def test_contract_and_forms():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(bt)
    assert (v.signal, v.version) == ("tax_lien", "v1") and v.governs == tc.GOVERNS
    assert bt.tms("9010000001000") == MAP and bt.tms(MAP) == MAP and bt.tms("901-00") is None
    assert bt.applies(roll_row()) and not bt.applies(roll_row(county="Berkeley"))


def test_an_owed_delinquent_bill_confirms():
    api = FakeAPI({MAP: [bill(MAP, 2025, owed=2584.59)]})
    r = run(roll_row(), api)
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 2584.59}
    # the template is read once per run, the body carries the map number in AccountNumber
    assert [a[0] for a in api.asked] == ["getbyidquickpay", "SearchNewForQuickPayRawBsonExecutorWithRateLimit"]


def test_a_paid_bill_on_the_delinquent_books_is_stale():
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, paid_on=date(2026, 10, 2))]}))
    assert r.verdict == "stale", r.evidence
    assert r.evidence["current_claim_basis"] == "claimed_year_paid_late"
    assert r.evidence["history_complete"] is False and r.evidence["chronic_claim"] == "unknown"
    assert "tax_lien_chronic" not in bt.governs_for(r.to_dict())


def test_never_refuted_absence_is_not_proof():
    r = run(roll_row(), FakeAPI({}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "not_on_delinquent_list")
    # an older delinquent bill paid, the claimed levy not on the books: still not decided
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2023, paid_on=date(2024, 6, 1))]}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "not_on_delinquent_list")


def test_pending_abated_and_personal_property():
    assert run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, owed=10.0, pending=True)]})).verdict == "confirmed"
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, pending=True)]}))
    assert r.evidence["reason"] == "payment_pending"
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, abated=True)]}))
    assert r.evidence["reason"] == "abated"
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, owed=50.0, kind="V")]}))     # a vehicle bill
    assert r.evidence["reason"] == "not_on_delinquent_list"


def test_the_claims_parcel_and_the_boards_disagree():
    other = "902-00-00-002-000"
    row = roll_row(parcel_id=other)
    r = run(row, FakeAPI({MAP: [bill(MAP, 2025, owed=700.0)], other: [bill(other, 2025, paid_on=date(2026, 10, 1))]}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "identity_conflict")


def test_a_refusal_is_a_wall_for_the_run():
    api = FakeAPI({}, status=403)
    r = run(roll_row(), api)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "portal_unhealthy")


def test_public_evidence_names_nobody():
    blob = json.dumps(run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, owed=1.0e3)]})).to_dict())
    assert "TESTOWNER" not in blob and "00000001" not in blob


def test_the_gate_sees_a_check_of_the_rows_own_parcel():
    from foreclosure_scraper.tax_binding import verified_checks_row
    r = run(roll_row(), FakeAPI({MAP: [bill(MAP, 2025, owed=900.0)]}))
    assert r.evidence["tax_parcel"] == MAP and verified_checks_row(roll_row(), r.evidence)

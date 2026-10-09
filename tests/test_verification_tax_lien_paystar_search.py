"""tax_lien_paystar_search v1 (Berkeley's per-county PayStar portal, the unified /api/search).

Synthetic: made-up owners (TESTOWNER ...), map numbers, invoice numbers and streets, the shape of
the real API answers (read live 2026-10-09). No network.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import date

from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_paystar_search as ps

TODAY = date(2026, 10, 9)
TMS = "901-01-01-001"
HOST = ps.TENANTS["berkeley"][1]


def inv(number, year, *, status="Unpaid", cents=100000, paid=None, tms=TMS, situs="12 TEST BLOSSOM ST",
        owner="TESTOWNER ALPHA"):
    meta = {"SiteAddress": situs, "BillName": owner, "ActualPaymentDate": "0"}
    return {"number": number, "year": year, "data": {
        "taxYear": year, "paymentStatus": status, "paymentDate": paid.isoformat() + "T00:00:00Z" if paid else None,
        "invoiceAmountMinor": cents, "delinquent": year < 2026 and status == "Unpaid",
        "assetIdentifierDisplay": tms, "assetType": "Real Property", "invoiceeName": owner,
        "assetMetaJson": json.dumps(meta)}}


class FakePortal:
    def __init__(self, invoices, *, listed=None):
        self.inv = {base64.b64encode(i["number"].encode()).decode(): i for i in invoices}
        self.listed = listed if listed is not None else [i["number"] for i in invoices]
        self.asked = []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post_json(self, url, payload, **_):
        self.asked.append(("search", payload["searchTerm"]))
        rows = [{"invoiceNumber": i["number"], "invoiceNumberHash": h, "taxYear": i["year"],
                 "paymentStatus": i["data"]["paymentStatus"]}
                for h, i in self.inv.items() if i["number"] in self.listed and i["data"]["assetIdentifierDisplay"] == payload["searchTerm"]]
        return FormResponse(200, url, json.dumps({"data": {"results": rows, "totalCount": len(rows)}}))

    async def get(self, url, **_):
        h = url.rsplit("/", 1)[-1]
        self.asked.append(("detail", h))
        if h not in self.inv:
            return FormResponse(400, url, json.dumps({"hasErrors": True}))
        return FormResponse(200, url, json.dumps({"hasErrors": False, "data": self.inv[h]["data"]}))


def roll_row(**kw):
    r = {"state": "SC", "county": "Berkeley", "listing_type": "tax_sale", "source": "counties_sc.berkeley_paystar_tax",
         "parcel_id": TMS, "street_address": "12 TEST BLOSSOM ST", "owner_name": "TESTOWNER ALPHA",
         "raw": {"berkeley_paystar_tax": {"invoice_number": "2025-0000001", "tax_year": 2025, "total_due": 1000.0},
                 "tax_owed": {"balance": 1000.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def run(row, portal):
    return asyncio.run(ps.verify(row, portal, today=TODAY))


def test_contract_and_forms():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(ps)
    assert (v.signal, v.version) == ("tax_lien", "v1") and v.governs == tc.GOVERNS
    assert ps.tms("9010101001") == TMS and ps.tms(TMS) == TMS and ps.tms("901-01-01-001A") == "901-01-01-001A"
    assert ps.tms("") is None and ps.invoice_hash("2025-0000001") == base64.b64encode(b"2025-0000001").decode()
    assert ps.applies(roll_row()) and not ps.applies(roll_row(county="Abbeville"))


def test_an_unpaid_late_levy_confirms():
    p = FakePortal([inv("2025-0000001", 2025, cents=154291), inv("2026-0000009", 2026, cents=99000)])
    r = run(roll_row(), p)
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 1542.91}
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 990.0}
    assert r.evidence["claim_bill"] == "on_portal" and r.evidence["address_relation"] == "match"


def test_the_claimed_bill_gone_from_the_portal_is_not_a_verdict():
    p = FakePortal([inv("2026-0000009", 2026, cents=99000)])           # only the current bill left
    r = run(roll_row(), p)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "claimed_bill_not_on_portal"), r.evidence
    assert r.evidence["claim_bill"] == "not_on_portal"


def test_a_paid_bill_still_on_the_portal_decides():
    late = FakePortal([inv("2025-0000001", 2025, status="Paid", paid=date(2026, 9, 30))])
    r = run(roll_row(), late)
    assert r.verdict == "stale" and r.evidence["current_claim_basis"] == "claimed_year_paid_late", r.evidence
    on_time = FakePortal([inv("2025-0000001", 2025, status="Paid", paid=date(2026, 1, 10))])
    assert run(roll_row(), on_time).verdict == "refuted"


def test_another_house_number_never_gives_a_harmful_answer():
    p = FakePortal([inv("2025-0000001", 2025, status="Paid", paid=date(2026, 9, 30), situs="14 TEST BLOSSOM ST")])
    r = run(roll_row(), p)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_parcel_mismatch")


def test_pending_and_a_resolver_parcel():
    p = FakePortal([inv("2025-0000001", 2025, status="Pending")])
    assert run(roll_row(), p).evidence["reason"] == "payment_pending"
    row = roll_row(source="x", owner_name="SOMEONE ELSE ENTIRELY",
                   raw={"parcel_from_address": True, "tax_owed": {"balance": 5.0, "kind": "delinquent_tax"}})
    p = FakePortal([inv("2025-0000001", 2025)])
    assert run(row, p).evidence["reason"] == "parcel_resolved_unbound"


def test_the_claims_invoice_on_another_parcel_is_an_identity_conflict():
    p = FakePortal([inv("2025-0000001", 2025, tms="902-02-02-002"), inv("2025-0000005", 2025, status="Paid",
                                                                       paid=date(2025, 12, 1))])
    r = run(roll_row(), p)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "identity_conflict")


def test_public_evidence_names_nobody():
    blob = json.dumps(run(roll_row(), FakePortal([inv("2025-0000001", 2025)])).to_dict())
    assert "TESTOWNER" not in blob and "BLOSSOM" not in blob and "2025-0000001" not in blob


def test_the_gate_sees_a_check_of_the_rows_own_parcel():
    from foreclosure_scraper.tax_binding import verified_checks_row
    r = run(roll_row(), FakePortal([inv("2025-0000001", 2025)]))
    assert r.evidence["tax_parcel"] == TMS and verified_checks_row(roll_row(), r.evidence)

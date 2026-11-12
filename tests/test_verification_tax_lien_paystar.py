"""tax_lien_paystar v1 (Abbeville SC, whose qPayBill tenant went off line; 2026-10-08). The
PayStar JSON API answers rebuilt by hand in the shape read live (search list, bill detail), with
made-up map numbers, owners and hashes. No network."""
from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover, from_module
from foreclosure_scraper.verification.verifiers import tax_lien_paystar as P
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as Q

TODAY = date(2026, 10, 8)
SLUG = "abbeville-county-taxes"
IDS = {"bu": 17, "cfg": 40, "field": 55}
MAP = "900-00-00-001"
OTHER = "900-00-00-001.A"


def item(year, status, h, desc=MAP, asset="Real Property"):
    return {"invoiceNumberHash": h, "invoiceNumber": h.upper(), "taxYear": year, "assetType": asset,
            "paymentStatus": status, "invoiceeName": "TESTOWNER PAT", "assetOwner": "TESTOWNER PAT",
            "assetDescription": desc, "assetIdentifier": f"0{year}-3", "externalLookup": "x",
            "payable": status == "Unpaid", "invoiceStreetAddress1": "1 MAILING WAY",
            "groupingKey": None, "payOnOrAfterDate": f"{year}-03-17T00:00:00+00:00",
            "payBeforeDate": f"{year + 1}-03-17T00:00:00+00:00"}


def det(status, paid=None, cents=0):
    return {"data": {"paymentStatus": status, "paymentDate": f"{paid}T00:00:00+00:00" if paid else None,
                     "invoiceAmountMinor": cents, "delinquent": True}, "hasErrors": False, "errors": []}


def serve(searches: dict, details: dict, extra=None) -> ReplayFetcher:
    resp = {P.context_url(SLUG): json.dumps({"data": {"id": 17, "slug": SLUG, "assetConfigurations": [
                {"id": 59, "key": "property-taxes"}]}, "hasErrors": False}),
            P.config_url(SLUG): json.dumps({"data": {"id": 40, "searchFields": [{"id": 55, "key": "search1"}]},
                                            "hasErrors": False})}
    for value, items in searches.items():
        resp[P.search_url(SLUG, IDS, value)] = json.dumps(
            {"data": {"page": 1, "pageSize": 100, "pageCount": 1, "totalItemCount": len(items),
                      "items": items}, "hasErrors": False, "errors": []})
    for h, d in details.items():
        resp[P.detail_url(SLUG, h)] = json.dumps(d)
    resp.update(extra or {})
    return ReplayFetcher(resp)


def row(ident=MAP, *, parcel=None, owner="TESTOWNER PAT", years=("2025",), **kw):
    r = {"state": "SC", "county": "Abbeville", "listing_type": "tax_sale",
         "source": "counties_sc.qpaybill_delinquent_roll", "parcel_id": parcel or ident,
         "street_address": "100 TEST RD", "owner_name": owner,
         "raw": {"qpaybill_roll": {"identification_no": ident, "county": "Abbeville",
                                   "years_unpaid": list(years)}}}
    r.update(kw)
    return r


def run(r, f, today=TODAY):
    return asyncio.run(P.verify(r, f, today=today))


def test_applies_to_abbeville_only_and_qpaybill_no_longer_does():
    assert P.applies(row())
    assert not Q.applies(row())
    assert not P.applies(row(state="NC"))
    assert not P.applies(dict(row(), county="Allendale"))
    assert not P.applies(row(listing_type="tax_lien", source="counties_sc.sc_dew_lien_registry", raw={}))
    owners = [v.name for v in discover() if v.signal == "tax_lien" and v.safe_applies(row())]
    assert owners == ["tax_lien_paystar"]


def test_confirmed_reads_only_the_unpaid_late_bills_of_its_own_map_number():
    f = serve({MAP: [item(2026, "Unpaid", "h26"), item(2025, "Unpaid", "h25"), item(2024, "Unpaid", "h24"),
                     item(2023, "Paid", "h23"), item(2025, "Unpaid", "hx", desc=OTHER)]},
              {"h25": det("Unpaid", cents=81240), "h24": det("Unpaid", cents=79010)})
    res = run(row(), f)
    ev = res.evidence
    assert res.verdict == "confirmed" and res.verifier == "tax_lien_paystar"
    assert ev["delinquent_by_year"] == {"2025": 812.4, "2024": 790.1} and ev["years_delinquent"] == 2
    assert ev["total_delinquent"] == 1602.5 and not ev["under_500"]
    assert ev["not_yet_delinquent_years"] == [2026] and ev["owner_match"] == "same"
    assert ev["searched"] == [{"map_number": MAP, "role": "claim", "found": True, "rows": 4,
                               "latest_levy_year": 2026}]
    assert len(f.asked) == 2 + 1 + 2          # tenant ids, the search, two bill details
    blob = json.dumps(res.to_dict())
    assert "TESTOWNER" not in blob and "MAILING" not in blob and "100 TEST RD" not in blob
    assert set(ev) <= set(P._KEYS)


def test_stale_when_the_claimed_year_was_paid_after_january_15():
    f = serve({MAP: [item(2026, "Unpaid", "h26"), item(2025, "Paid", "h25"), item(2024, "Paid", "h24")]},
              {"h25": det("Paid", "2026-03-02")})
    res = run(row(), f)
    assert res.verdict == "stale"
    assert res.evidence["bills_checked"] == [{"year": 2025, "status": "Paid", "paid_on": "2026-03-02",
                                              "deadline": "2026-01-15", "paid_late": True}]
    assert res.evidence["current_claim_basis"] == "claimed_year_paid_late"


def test_refuted_when_paid_on_time():
    f = serve({MAP: [item(2025, "Paid", "h25"), item(2024, "Paid", "h24")]},
              {"h25": det("Paid", "2026-01-15"), "h24": det("Paid", "2025-01-10")})
    res = run(row(), f)
    assert res.verdict == "refuted"
    assert [c["paid_late"] for c in res.evidence["bills_checked"]] == [False, False]


def test_tax_sale_is_its_own_state():
    f = serve({MAP: [item(2025, "Paid", "h25"), item(2024, "Tax Sale", "h24")]},
              {"h24": det("Tax Sale", "2025-10-06", 0), "h25": det("Paid", "2026-01-12")})
    res = run(row(), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "sold_at_tax_sale"
    assert res.evidence["sold_at_tax_sale_years"] == [2024]
    f2 = serve({MAP: [item(2025, "Unpaid", "h25"), item(2024, "Tax Sale", "h24")]},
               {"h24": det("Tax Sale", None, 31000), "h25": det("Unpaid", cents=29000)})
    res2 = run(row(), f2)
    assert res2.verdict == "confirmed" and res2.evidence["reason"] == "sold_at_tax_sale"


def test_a_pending_payment_decides_nothing():
    f = serve({MAP: [item(2025, "Pending", "h25"), item(2024, "Paid", "h24")]}, {})
    res = run(row(), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "payment_pending"


def test_a_resolver_parcel_with_another_owner_never_confirms_and_never_refutes():
    r = row(parcel=MAP, owner="DIFFERENT PERSONNAME")
    r["raw"] = {"parcel_from_address": {"how": "test"}, "two_year_delinquent": {"is_two_year_plus": True}}
    f = serve({MAP: [item(2025, "Unpaid", "h25")]}, {"h25": det("Unpaid", cents=50000)})
    res = run(r, f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "parcel_resolved_unbound"
    f2 = serve({MAP: [item(2025, "Paid", "h25")]}, {"h25": det("Paid", "2026-01-02")})
    assert run(r, f2).evidence["reason"] == "parcel_resolved_unbound"


def test_identity_conflict_between_the_claim_and_the_board_parcel():
    f = serve({MAP: [item(2025, "Unpaid", "h25")], OTHER: [item(2025, "Paid", "o25", desc=OTHER)]},
              {"h25": det("Unpaid", cents=40000)})
    res = run(row(parcel=OTHER), f)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "identity_conflict"


def _http_error(url, code):
    req = httpx.Request("GET", url)
    return httpx.HTTPStatusError(f"{code}", request=req, response=httpx.Response(code, request=req))


def test_a_503_names_its_status_and_opens_the_circuit():
    url = P.context_url(SLUG)
    f = ReplayFetcher({url: _http_error(url, 503)})
    r1 = run(row(), f)
    assert r1.evidence["reason"] == "fetch_failed" and r1.evidence["http_status"] == 503
    r2 = run(row("900-00-00-002"), f)
    assert r2.evidence["reason"] == "portal_unhealthy" and r2.evidence["tenant_state"] == "open"
    n = len(f.asked)
    r3 = run(row("900-00-00-003"), f)
    assert r3.evidence["reason"] == "portal_unhealthy" and len(f.asked) == n
    v = from_module(P)
    assert v.is_transient(r1.to_dict()) and v.is_transient(r3.to_dict())


def test_a_403_is_a_wall_for_the_run():
    url = P.context_url(SLUG)
    f = ReplayFetcher({url: _http_error(url, 403)})
    r = run(row(), f)
    assert r.evidence["reason"] == "portal_unhealthy" and r.evidence["tenant_state"] == "blocked"
    assert r.evidence["http_status"] == 403
    run(row("900-00-00-004"), f)
    assert len(f.asked) == 1


def test_not_on_the_portal():
    f = serve({MAP: []}, {})
    assert run(row(), f).evidence["reason"] == "parcel_not_found"


@pytest.mark.parametrize("status,kind", [("Paid", "paid"), ("Unpaid", "owed"), ("Tax Sale", "sold"),
                                         ("Pending", "pending"), ("Something", "other")])
def test_status_kinds(status, kind):
    assert P._kind(status) == kind

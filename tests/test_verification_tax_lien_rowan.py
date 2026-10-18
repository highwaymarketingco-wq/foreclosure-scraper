"""tax_lien_rowan v1: Rowan County NC's iasWorld tax-bill search (tax.rowancountync.gov).

Everything here is synthetic: made-up parcels/owners (TEST...), but the markup shapes (the
WebForms hidden fields, the results-grid row's onclick/column layout, the Datalet TAX_BILLS_INT
table) mirror the real site's own HTML, live-read 2026-10-18. No network.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.registry import discover, from_module
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_rowan as p

TODAY = date(2026, 10, 18)


def _hidden_html(tag: str = "a") -> str:
    return (f"<input type='hidden' name='__VIEWSTATE' id='__VIEWSTATE' value='VS-{tag}' />"
           f"<input type='hidden' name='__VIEWSTATEGENERATOR' id='__VIEWSTATEGENERATOR' value='G1' />"
           f"<input type='hidden' name='__EVENTVALIDATION' id='__EVENTVALIDATION' value='EV-{tag}' />")


def _row_html(sIndex: int, idx: int, parcel: str, owner: str, account: str, address: str,
              tax_year: str = "2026") -> str:
    return (f"<tr onclick=\"javascript:selectSearchRow('../Datalets/Datalet.aspx?sIndex={sIndex}&idx={idx}')\""
           f" onkeyup=\"javascript:if(event.code == 'Space'){{selectSearchRow('../Datalets/Datalet.aspx?sIndex={sIndex}&idx={idx}')}}\">"
           f"<td><div style='margin-left:2px;'><input name='chkPin'></div></td>"
           f"<td><div style='margin-left:3px;'>{parcel}</div></td>"
           f"<td><div style='margin-left:3px;'>{owner}</div></td>"
           f"<td><div style='margin-left:3px;'>{account}</div></td>"
           f"<td><div style='margin-left:3px;'>{address}</div></td>"
           f"<td><div style='margin-left:3px;'>{tax_year}</div></td></tr>")


def _results_html(rows: list[dict], tag: str = "b") -> str:
    body = "".join(_row_html(r["sIndex"], r["idx"], r["parcel_id"], r["owner"], r["account"],
                             r["address"], r.get("tax_year", "2026")) for r in rows)
    return f"<html>{_hidden_html(tag)}<table>{body}</table></html>"


def _bill_row(year: int, original: float, adjustment: float, paid: float, discount: float,
             interest: float, due: float) -> str:
    cells = [str(year), f"{original:.2f}", f"{adjustment:.2f}", f"{paid:.2f}", f"{discount:.2f}",
             f"{interest:.2f}", f"{due:.2f}", "", ""]
    return "<tr>" + "".join(f"<td class='DataletData'>{c}</td>" for c in cells) + "</tr>"


def bills_html(rows: list[tuple]) -> str:
    """rows: [(year, original, adjustment, paid, discount, interest, due)], newest first, as the
    live page prints them. Always followed by the table's own "Total:" row and, past that, a
    DIFFERENT widget's DataletData cells further down the same page (both confirmed live,
    2026-10-18) -- a real regression case: parse_bills() must stop at "Total:", not keep
    chunking into unrelated page furniture."""
    body = "".join(_bill_row(*r) for r in rows)
    total = ("<tr>" + "".join(f"<td class='DataletData'>{c}</td>"
                              for c in ["Total:", "", "", "", "", "", "0.00", "", ""]) + "</tr>")
    other_widget = ("<div id='datalet_div_1' name='OTHER_WIDGET'><table>"
                   + "".join(f"<td class='DataletData'>{c}</td>" for c in ["2099", "1.00"])
                   + "</table></div>")
    return (f"<html>{_hidden_html('d')}<div id='datalet_div_0' name='TAX_BILLS_INT'>"
           f"<table>{body}{total}</table></div>{other_widget}</html>")


class FakeSite:
    """Stands in for the whole client: form_session() returns self, like the real curl_cffi
    session the module uses. `parcels` maps parcel_id -> {"owner","account","address","bills"};
    each is assigned a fixed (sIndex=0, idx=N) position, as the real grid does for one search."""

    def __init__(self, parcels: dict[str, dict], *, search_status: int = 200,
                detail_status: int = 200, no_bills_table: bool = False):
        self.parcels = parcels
        self._order = list(parcels)
        self.search_status = search_status
        self.detail_status = detail_status
        self.no_bills_table = no_bills_table
        self.asked: list[tuple] = []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        self.asked.append(("GET", url))
        if "Datalet.aspx" in url:
            idx = int(url.split("idx=")[1].split("&")[0])
            parcel = self._order[idx - 1]
            if self.detail_status != 200:
                return FormResponse(self.detail_status, url, "")
            if self.no_bills_table:
                return FormResponse(200, url, f"<html>{_hidden_html('nb')}</html>")
            return FormResponse(200, url, bills_html(self.parcels[parcel]["bills"]))
        return FormResponse(200, url, f"<html>{_hidden_html('a')}</html>")

    async def post_form(self, url, data, **_):
        self.asked.append(("POST", url, dict(data)))
        if self.search_status != 200:
            return FormResponse(self.search_status, url, "")
        parid = str(data.get("inpParid") or "")
        want = tc.alnum(parid)
        rows = []
        for i, pid in enumerate(self._order, start=1):
            if want and want in tc.alnum(pid):
                v = self.parcels[pid]
                rows.append({"sIndex": "0", "idx": str(i), "parcel_id": pid, "owner": v["owner"],
                            "account": v["account"], "address": v["address"]})
        return FormResponse(200, url, _results_html(rows))


def row(parcel="TEST001", owner="TESTOWNER ALPHA", claimed_year=2025, **kw):
    r = {"state": "NC", "county": "Rowan", "listing_type": "tax_lien", "source": p.SOURCE_SLUG,
         "parcel_id": parcel, "owner_name": owner,
         "raw": {"rowan_delinquent_tax": {"tax_year": str(claimed_year), "years_unpaid": [claimed_year]},
                 "tax_owed": {"balance": 100.0, "year": claimed_year, "kind": "delinquent_tax",
                             "source": p.SOURCE_SLUG}}}
    r.update(kw)
    return r


def run(r, site, today=TODAY):
    return asyncio.run(p.verify(r, site, today=today))


def test_contract_and_registration():
    v = from_module(p)
    assert (v.signal, v.version, v.ttl_days) == ("tax_lien", "v1", 30.0)
    assert v.governs == tc.GOVERNS
    others = [v for v in discover() if v.signal == "tax_lien" and v.name != "tax_lien_rowan"]
    assert not any(o.source == p.SOURCE for o in others)


def test_applies_to_rowan_tax_claim_rows_only():
    assert p.applies(row())
    assert not p.applies(row(county="Davidson"))
    assert not p.applies(row(state="SC"))
    assert not p.applies(row(source="counties_nc.other_source"))
    assert not p.applies({"state": "NC", "county": "Rowan", "listing_type": "foreclosure",
                          "source": p.SOURCE_SLUG, "parcel_id": "1", "raw": {}})


def test_confirmed_on_a_real_late_balance():
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "900001",
                                 "address": "1 TEST LN",
                                 "bills": [(2026, 500.0, 0, 0, 0, 0, 500.0),
                                          (2025, 480.0, 0, -200.0, 0, 40.0, 320.0),
                                          (2024, 460.0, 0, -460.0, 0, 0, 0.0)]}})
    r = run(row(), site)
    assert r.verdict == "confirmed", r.evidence
    assert r.evidence["delinquent_by_year"] == {"2025": 320.0}
    assert r.evidence["total_delinquent"] == 320.0
    assert r.evidence["owner_match"] == "same"
    assert r.evidence["not_yet_delinquent_due"] == {"2026": 500.0}


def test_stale_when_the_claimed_year_is_now_fully_paid():
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "900001",
                                 "address": "1 TEST LN",
                                 "bills": [(2026, 500.0, 0, 0, 0, 0, 500.0),
                                          (2025, 480.0, 0, -480.0, 0, 0, 0.0)]}})
    r = run(row(claimed_year=2025), site)
    assert r.verdict == "stale", r.evidence
    assert r.evidence["resolved_claimed_years"] == [2025]
    assert "delinquent_by_year" not in r.evidence


def test_unconfirmed_when_nothing_late_and_the_claimed_year_is_not_in_the_table():
    """The claimed year predates the live table's own history window: nothing to confirm it
    resolved, so this must not guess "stale"."""
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "900001",
                                 "address": "1 TEST LN",
                                 "bills": [(2026, 500.0, 0, 0, 0, 0, 500.0)]}})
    r = run(row(claimed_year=2018), site)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "claimed_year_not_in_bill_history"


def test_parcel_not_found_is_unconfirmed_with_zero_results():
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "900001",
                                 "address": "1 TEST LN", "bills": [(2026, 1, 0, 0, 0, 0, 1)]}})
    r = run(row(parcel="NOPE999"), site)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_not_found"
    assert r.evidence["searched"] == [{"by": "inpParid", "results": 0}]


def test_a_prefix_match_is_filtered_down_to_the_exact_parcel():
    """inpParid matches by prefix live (confirmed: a 3-char search returned 32 rows) -- the
    verifier must keep only the row whose own Parcel ID column is an exact alnum match."""
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "1",
                                 "address": "1 TEST LN", "bills": [(2025, 1, 0, 0, 0, 0, 50.0)]},
                     "TEST0019": {"owner": "TESTOWNER BETA", "account": "2",
                                 "address": "2 TEST LN", "bills": [(2025, 1, 0, 0, 0, 0, 99.0)]}})
    r = run(row(parcel="TEST001"), site)
    assert r.verdict == "confirmed" and r.evidence["delinquent_by_year"] == {"2025": 50.0}


def test_no_parcel_id_is_unconfirmed_without_a_request():
    site = FakeSite({})
    r = run(row(parcel=None), site)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_parcel"
    assert site.asked == []


def test_a_failing_search_is_unconfirmed_fetch_failed():
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "1", "address": "1 TEST LN",
                                 "bills": []}}, search_status=500)
    r = run(row(), site)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"


def test_no_bills_table_on_the_detail_page_is_unconfirmed():
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "1", "address": "1 TEST LN",
                                 "bills": []}}, no_bills_table=True)
    r = run(row(), site)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_bills"


def test_portal_goes_unhealthy_after_repeated_failures_then_recovers():
    """MAX_FAILURES=2: the circuit trips open only after 2 failures in a row, so the 3rd call is
    the first one refused outright (never even attempted) -- mirrors tax_lien_itspublic's own
    test convention for this exact circuit-breaker shape."""
    site = FakeSite({"TEST001": {"owner": "TESTOWNER ALPHA", "account": "1", "address": "1 TEST LN",
                                 "bills": [(2025, 1, 0, 0, 0, 0, 1)]}}, search_status=500)
    r1 = run(row(parcel="A"), site)
    assert (r1.verdict, r1.evidence["reason"]) == ("unconfirmed", "fetch_failed")
    r2 = run(row(parcel="B"), site)
    assert r2.verdict == "unconfirmed" and r2.evidence["reason"] in ("fetch_failed", "portal_unhealthy")
    r3 = run(row(parcel="C"), site)
    assert (r3.verdict, r3.evidence["reason"]) == ("unconfirmed", "portal_unhealthy")
    site.search_status = 200
    r4 = run(row(), site)
    assert r4.evidence["reason"] == "portal_unhealthy", r4.evidence


def test_parse_results_reads_the_live_markup_shape():
    html = _results_html([{"sIndex": "0", "idx": "1", "parcel_id": "379D104",
                           "owner": "AMECA HEBELYN", "account": "717609",
                           "address": "130 MIDDLE BROOK DR", "tax_year": "2026"}])
    rows = p.parse_results(html)
    assert rows == [{"sIndex": "0", "idx": "1", "parcel_id": "379D104", "owner": "AMECA HEBELYN",
                     "account": "717609", "address": "130 MIDDLE BROOK DR", "tax_year": "2026"}]


def test_parse_bills_reads_the_live_table_shape():
    html = bills_html([(2026, 567.84, 0.0, 0.0, 0.0, 0.0, 567.84),
                       (2025, 567.84, 37.14, -425.36, 0.0, 48.32, 227.94)])
    bills = p.parse_bills(html)
    assert len(bills) == 2, bills   # stops at "Total:" -- never picks up OTHER_WIDGET's "2099" row
    assert bills[0] == {"year": 2026, "original_bill": 567.84, "bill_adjustment": 0.0,
                        "total_paid": 0.0, "discount": 0.0, "interest": 0.0, "amount_due": 567.84}
    assert bills[1]["amount_due"] == 227.94 and bills[1]["total_paid"] == -425.36


def test_parse_bills_returns_none_when_the_datalet_is_absent():
    assert p.parse_bills(f"<html>{_hidden_html('x')}</html>") is None

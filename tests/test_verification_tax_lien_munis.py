"""tax_lien_munis v1: Tyler Munis Citizen Self Service (New Hanover).

Everything here is synthetic: made-up owners (TESTOWNER ...), parcels (R9xxxx ...) and streets
(TEST ...), in the shape of the real WebForms pages (live-read 2026-10-08). The portal keeps the
search and the selected bill in the session, so a small in-memory portal stands in for it. No
network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_munis as p

TODAY = date(2026, 10, 8)
BASE = p.PORTALS["New Hanover"].base
CSV = "counties_nc.nc_county_csv_delinquent_tax"


def bill(parcel, year, *, due=0.0, payments=(), pay_by=None, owner="TESTOWNER ALPHA",
         address="12 TEST OAK ST", btype="REGULAR/ORIGINAL - REAL ESTATE"):
    return {"parcel": parcel, "year": year, "due": due, "payments": list(payments), "owner": owner,
            "address": address, "type": btype, "pay_by": pay_by or f"1/5/{year + 1}"}


class FakeMunis:
    def __init__(self, bills, *, fail=0):
        self.bills = bills
        self.shown: list[dict] = []
        self.selected = None
        self.fail = fail
        self.asked = []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        self.asked.append(("GET", url))
        if url.endswith(p.FORM):
            return FormResponse(200, url, self._form())
        if url.endswith(p.PAYMENTS):
            return FormResponse(200, url, self._payments(self.selected))
        return FormResponse(404, url, "")

    async def post_form(self, url, data, **_):
        self.asked.append(("POST", url, data.get(p.PARCEL_FIELD) or data.get("__EVENTTARGET")))
        if self.fail:
            self.fail -= 1
            return FormResponse(500, url, "<html>500 - Internal server error.</html>")
        if url.endswith(p.FORM):
            want = data[p.PARCEL_FIELD].upper()
            self.shown = sorted((b for b in self.bills if b["parcel"].upper().startswith(want)),
                                key=lambda b: (b["parcel"], b["year"]))
            return FormResponse(200, BASE + p.BROWSE, self._browse())
        if url.endswith(p.BROWSE):
            i = int(data["__EVENTTARGET"].split("$ctl")[-1].split("$")[0]) - 2
            self.selected = self.shown[i]
            return FormResponse(200, BASE + "/citizens/RealEstate/ViewBill.aspx", self._bill(self.selected))
        return FormResponse(404, url, "")

    # pages -----------------------------------------------------------------------------
    @staticmethod
    def _form():
        return ('<form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs1" />'
                f'<input name="{p.PARCEL_FIELD}" type="text" maxlength="30" /></form>')

    def _browse(self):
        rows = ['<tr><th scope="col">Property Address</th><th>Unit</th><th>Owner</th><th>Parcel ID</th>'
                '<th>Tax Year</th><th>Bill Type</th><th>&nbsp;</th><th>&nbsp;</th></tr>']
        for i, b in enumerate(self.shown):
            tgt = f"ctl00$ctl00$PrimaryPlaceHolder$ContentPlaceHolderMain$BillsGridView$ctl{i + 2:02d}$ViewBillLinkButton"
            rows.append(f"<tr><td>{b['address']}</td><td>&nbsp;</td><td>{b['owner']}</td><td>{b['parcel']}</td>"
                        f"<td>{b['year']}</td><td>{b['type']}</td><td><a href=\"javascript:__doPostBack(&#39;"
                        f"{tgt}&#39;,&#39;&#39;)\">View Bill</a></td><td></td></tr>")
        return ('<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs2" />'
                '<table id="ctl00_ctl00_PrimaryPlaceHolder_ContentPlaceHolderMain_BillsGridView">'
                + "".join(rows) + "</table>")

    def _bill(self, b):
        same = [x for x in self.shown if x["parcel"] == b["parcel"] and x is not b and x["due"] > 0]
        prior = any(x["year"] < b["year"] for x in same)
        newer = any(x["year"] > b["year"] for x in same)
        msg = ("Prior and newer unpaid bills exist" if prior and newer else "Prior unpaid bill(s) exist"
               if prior else "Newer unpaid bill(s) exist" if newer else "")
        paid = round(sum(a for _, a in b["payments"]), 2)
        amount = round(b["due"] + paid, 2)

        def span(sfx, v):
            return f'<span id="ctl00_ctl00_PrimaryPlaceHolder_ContentPlaceHolderMain_ViewBill1_{sfx}">{v}</span>'
        return (f'<p id="x_PaymentBlockMessage_BlockageMessageParagraph" class="instruction">'
                f'<span><a href="allbills.aspx?c=1">{msg}</a> for this parcel. </span></p>' if msg else "") + (
            "<table>" + span("FiscalYearLabel", b["year"]) + span("BillNumberLabel", f"{b['year'] % 100}000001")
            + span("OwnerLabel", b["owner"]) + span("CategoryLabel", b["parcel"]) + "</table>"
            '<div id="ctl00_ctl00_PrimaryPlaceHolder_ContentPlaceHolderMain_ViewBill1_BillDetailsUpdatePanel">'
            '<table class="datatable nocaption"><tr><th>Installment</th><th>Pay By</th><th>Amount</th>'
            '<th>Payments/Credits</th><th>Balance</th><th>Interest</th><th>Due</th></tr>'
            f'<tr><td>1</td><td>{b["pay_by"]}</td><td>${amount:,.2f}</td><td>${paid:,.2f}</td>'
            f'<td>${b["due"]:,.2f}</td><td>$0.00</td><td>${b["due"]:,.2f}</td></tr>'
            f'<tr><td colspan="2" class="strong">TOTAL</td><td>${amount:,.2f}</td><td>${paid:,.2f}</td>'
            f'<td>${b["due"]:,.2f}</td><td>$0.00</td><td>${b["due"]:,.2f}</td></tr></table></div>')

    @staticmethod
    def _payments(b):
        rows = "".join(f"<tr><td>Payment</td><td>{d.month}/{d.day}/{d.year}</td><td>{d.month}/{d.day}/{d.year}</td>"
                       f"<td>1</td><td>TESTPAYER BANK</td><td>${a:,.2f}</td></tr>" for d, a in (b or {}).get("payments", []))
        return ('<table class="datatable nomargin"><tr><th scope="col" class="width1">Activity</th><th>Posted</th>'
                '<th>Entered</th><th>Reference #</th><th>Paid By/Reference</th><th>Amount</th></tr>' + rows + "</table>")


def run(row, portal):
    return asyncio.run(p.verify(row, portal, today=TODAY))


def row_of(parcel="R90000-001-001-000", *, block_parcel=None, **kw):
    """A New Hanover roll row; block_parcel names the parcel its roll block is about."""
    r = {"state": "NC", "county": "New Hanover", "listing_type": "tax_lien", "source": CSV,
         "parcel_id": parcel, "street_address": "12 TEST OAK ST", "owner_name": "TESTOWNER ALPHA",
         "first_seen": "2026-08-16T00:00:00",
         "raw": {p.ROLL_KEY: {"county": "New Hanover", "county_id": block_parcel or parcel,
                              "principal_tax_due": 4100.0, "bill_years": ["2016", "2017"]},
                 "tax_owed": {"balance": 4100.0, "year": 2016, "source": CSV},
                 "tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 10, "tax_year": 2016}}}
    r.update(kw)
    return r


def history(parcel, *, late2025=False, late2024=False, address="12 TEST OAK ST", owner="TESTOWNER ALPHA"):
    on = {y: date(y, 11, 20) for y in range(2016, 2026)}
    if late2025:
        on[2025] = date(2026, 3, 24)
    if late2024:
        on[2024] = date(2025, 2, 2)
    out = [bill(parcel, y, payments=[(on[y], 1000.0)], address=address, owner=owner) for y in range(2016, 2026)]
    out.append(bill(parcel, 2026, due=1100.0, address=address, owner=owner))    # not late until 2027-01-06
    return out


# ---------------------------------------------------------------------------
# which rows, parsing
# ---------------------------------------------------------------------------

def test_contract_and_version():
    from foreclosure_scraper.verification.registry import from_module
    v = from_module(p)
    assert (v.signal, v.version, v.ttl_days) == ("tax_lien", "v1", 30.0)
    assert v.governs == tc.GOVERNS


def test_applies():
    assert p.applies(row_of())
    assert not p.applies(row_of(county="Onslow"))
    assert not p.applies(row_of(state="SC"))
    assert not p.applies(row_of(source="counties_nc.nc_ptscloud_delinquent_tax"))
    assert not p.applies({"state": "NC", "county": "New Hanover", "listing_type": "foreclosure",
                          "source": "x", "parcel_id": "R1", "raw": {}})


def test_a_block_of_another_parcel_names_no_claimed_year():
    """The 2026-10-07 board copied one parcel's roll block onto 1,198 New Hanover rows: its years
    are not a claim about the row's parcel."""
    assert p.claimed_years(row_of(block_parcel="R99999-009-009-000")) == []
    assert p.claimed_years(row_of()) == [2017, 2016]


def test_an_undashed_parcel_id_is_dashed_for_the_search():
    assert p.search_id("R09999001002000") == "R09999-001-002-000"
    assert p.search_id("R09999-001-002-000") == "R09999-001-002-000"
    assert p.search_id("9999-46-0001.000") == "9999-46-0001.000"        # a PIN is passed as it is
    r = run(row_of(parcel="R90000001001000"), FakeMunis(history("R90000-001-001-000")))
    assert r.verdict == "refuted" and r.evidence["tax_parcel"] == "R90000-001-001-000"


def test_payment_check_honours_a_later_county_pay_by():
    on_monday = [{"type": "Payment", "posted": "2025-01-06", "amount": 1.0}]
    assert p.payment_check(2024, "New Hanover", on_monday, "2025-01-06")["paid_late"] is False
    assert p.payment_check(2024, "New Hanover", on_monday)["paid_late"] is True        # statute alone
    early = p.payment_check(2025, "New Hanover", [{"type": "Payment", "posted": "2026-01-05", "amount": 1.0}],
                            "2026-01-04")                                               # earlier Pay By ignored
    assert early["paid_late"] is False and early["delinquent_from"] == "2026-01-06"
    fee_only = p.payment_check(2018, "New Hanover", [{"type": "Fee", "posted": "2018-04-06", "amount": 2.0}])
    assert fee_only["no_payment_on_bill"] is True and fee_only["paid_late"] is False


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

def test_confirmed_with_the_older_unpaid_bills_summed():
    bills = history("R90000-001-001-000")
    for b in bills:
        if b["year"] in (2024, 2025):
            b["due"], b["payments"] = 900.0 + b["year"] - 2024, []
    r = run(row_of(), FakeMunis(bills))
    assert r.verdict == "confirmed", r.evidence
    ev = r.evidence
    assert ev["delinquent_by_year"] == {"2025": 901.0, "2024": 900.0} and ev["years_delinquent"] == 2
    assert ev["total_delinquent"] == 1801.0 and ev["address_binding"] == "parcel_number"
    assert ev["bills_viewed"] == 2                        # 2024's page says no older bill is unpaid


def test_refuted_on_the_rows_own_parcel_when_the_block_is_another_parcels():
    """The flag came from another parcel's block; the row's own parcel paid every year on time."""
    r = run(row_of(block_parcel="R99999-009-009-000"), FakeMunis(history("R90000-001-001-000")))
    assert r.verdict == "refuted", r.evidence
    ev = r.evidence
    assert ev["claim_block_other_parcel"] is True and ev["claimed_years"] == []
    assert ev["current_claim_basis"] == "latest_year_on_time" and ev["address_binding"] == "bill_address"
    assert ev["note"].startswith("a newer bill is unpaid")


def test_stale_when_the_latest_late_year_was_paid_late():
    r = run(row_of(block_parcel="R99999-009-009-000"),
            FakeMunis(history("R90000-001-001-000", late2025=True)))
    assert r.verdict == "stale", r.evidence
    assert r.evidence["current_claim_basis"] == "latest_year_paid_late"
    assert r.evidence["late_levy_years"] == [2025]


def test_the_partial_id_match_of_another_parcel_is_never_read():
    """The portal lists every parcel that STARTS with the id typed: another parcel's unpaid bills
    in the same answer are not the row's."""
    other = [bill("R90000-001-001-0001", y, due=500.0, address="14 TEST OAK ST", owner="TESTOWNER BRAVO")
             for y in (2024, 2025)]
    r = run(row_of(), FakeMunis(other + history("R90000-001-001-000")))
    assert r.verdict == "refuted", r.evidence
    assert not r.evidence["delinquent_by_year"]


def test_an_address_of_another_property_never_refutes():
    r = run(row_of(), FakeMunis(history("R90000-001-001-000", address="400 TEST ELM DR")))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_parcel_mismatch")
    assert r.evidence["address_relation"] == "conflict"


def test_a_resolver_parcel_owing_with_another_owner_is_not_confirmed():
    bills = history("R90000-001-001-000", owner="SOMEBODY ELSE")
    bills[-2]["due"], bills[-2]["payments"] = 700.0, []
    row = row_of(raw={"parcel_from_address": True,
                      "tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 2, "tax_year": 2025}})
    r = run(row, FakeMunis(bills))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "bill_owner_differs")


def test_parcel_not_found():
    r = run(row_of(), FakeMunis([]))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_not_found")


def test_a_failing_portal_is_unconfirmed_then_skipped():
    m = FakeMunis(history("R90000-001-001-000"), fail=5)
    assert run(row_of(), m).evidence["reason"] == "fetch_failed"
    assert run(row_of(parcel="R90000-001-002-000"), m).evidence["reason"] == "fetch_failed"
    assert run(row_of(parcel="R90000-001-003-000"), m).evidence["reason"] == "portal_unhealthy"


def test_the_public_evidence_names_nobody():
    bills = history("R90000-001-001-000", late2025=True)
    r = run(row_of(), FakeMunis(bills))
    blob = json.dumps(r.to_dict())
    assert "TESTOWNER" not in blob and "TESTPAYER" not in blob

"""enrichment_nash_multiyear_tax: Nash County NC multi-year delinquent-tax history, read live
from the county's own Tyler Munis "Citizen Self Service" tax-bill search (a NEW TENANT of the
SAME vendor verification/verifiers/tax_lien_munis.py already drives for New Hanover/Hoke/Lee --
its hidden_fields/search_form/view_form/parse_grid/parse_bill functions are reused verbatim, not
reimplemented).

Everything here is synthetic (made-up parcel 305400-shaped PARIDs, owners, streets) in the shape
of the real pages, live-read against taxdata/Munis 2026-10-21 (see the module's own docstring for
the real canary: PARID 305400, "ROCKY MOUNT GOLF CLUB WEH LP", a genuine multi-year delinquency).
No network.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind, _normalize_parcel
from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import tax_lien_munis as munis
from foreclosure_scraper import enrichment_nash_multiyear_tax as mod
from foreclosure_scraper.enrichment_nash_multiyear_tax import (
    build_two_year_block, build_multiyear_block, enrich_with_nash_multiyear_tax, _fetch, _open_form,
)

TODAY = date(2026, 10, 21)
PARID = "305400"


def bill(year, due, *, owner="TESTOWNER ALPHA", parcel=PARID, pay_by=None):
    return {"year": year, "bill": f"{year % 100}00001", "owner": owner, "parcel": parcel,
            "amount": round(due + 100, 2), "credits": 100.0, "balance": due, "interest": 0.0,
            "due": due, "pay_by": pay_by or f"{year}-09-01", "prior_unpaid": False, "newer_unpaid": False}


def _li(parcel=PARID, county="Nash", state="NC", raw=None) -> Listing:
    return Listing(source="counties_generic.liensnc", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_two_year_block / build_multiyear_block -- pure
# ---------------------------------------------------------------------------

def test_real_shaped_old_year_paid_but_newer_unpaid_still_counts_due_only():
    """Mirrors the real 2026-10-21 canary shape (PARID 305400): oldest year paid (due 0), latest
    years carry a real due amount -- only years with due > 0 count toward the gate."""
    bills = [bill(y, 0.0) for y in range(2015, 2024)]
    bills += [bill(2024, 291.74), bill(2025, 266.90), bill(2026, 6340.45)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year["is_two_year_plus"] is True
    assert two_year["oldest_year"] == 2024
    block = build_multiyear_block(PARID, bills, today=TODAY)
    assert block is not None
    assert block["matured_years"] == [2024, 2025]
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["total_due"] == round(291.74 + 266.90 + 6340.45, 2)
    assert block["matured_owed"] == round(291.74 + 266.90, 2)
    assert block["parcel_key"] == _normalize_parcel(PARID)
    assert block["source_url"] == mod.FORM_URL
    assert block["amount_basis"] == "annual_bill"


def test_current_year_unpaid_but_not_yet_late_does_not_qualify():
    bills = [bill(2025, 0.0), bill(2026, 3310.47)]
    assert build_two_year_block(bills, today=TODAY) == {
        "is_two_year_plus": False, "years": 0, "oldest_year": None,
        "source": "verification.verifiers.tax_lien_munis"}
    assert build_multiyear_block(PARID, bills, today=TODAY) is None


def test_single_matured_year_fails_multiyear_gate_but_two_year_block_still_honest():
    bills = [bill(2024, 50.0)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year["is_two_year_plus"] is False and two_year["years"] == 1 and two_year["oldest_year"] == 2024
    assert build_multiyear_block(PARID, bills, today=TODAY) is None


def test_all_paid_yields_nothing():
    bills = [bill(y, 0.0) for y in range(2015, 2027)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                        "source": "verification.verifiers.tax_lien_munis"}
    assert build_multiyear_block(PARID, bills, today=TODAY) is None


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_enrich_eligible_only_nash_nc_with_parcel():
    eligible = _li()
    wrong_county = _li(county="Rowan")
    wrong_state = _li(state="SC", county="Nash")
    no_parcel = _li(parcel="")
    already = _li(raw={"_nash_mydt_checked": "fetch_failed:TimeoutError"})
    already_block = _li(raw={"two_year_delinquent": {"is_two_year_plus": False}})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already, already_block]
    targets = [li for li in rows if mod._eligible(li)]
    assert targets == [eligible]


def test_eligible_does_not_require_the_6digit_shape_upfront():
    """Nash's board carries 12-digit NC PIN shapes and 'NC#####' dam-safety IDs too (the module
    docstring's live-measured 612/282/58 split) -- _eligible only checks alnum-truthy, same as
    every sibling restater; a wrong-shaped parcel sentinels via _fetch()'s own parcel_not_found
    path, not a pre-filter here."""
    pin_shaped = _li(parcel="385208991720")
    assert mod._eligible(pin_shaped) is True


# ---------------------------------------------------------------------------
# fake Munis client (the older "css"-skin tenant: one cookie-warmup bounce, then the real form)
# ---------------------------------------------------------------------------

class FakeNashMunis:
    def __init__(self, bills_by_parid, *, warm=True):
        self.bills_by_parid = bills_by_parid
        self.warm = warm          # False => first GET of the form bounces (cookie warm-up)
        self._get_calls = 0
        self.shown: list[dict] = []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        assert url == mod.FORM_URL
        self._get_calls += 1
        if not self.warm and self._get_calls == 1:
            return FormResponse(200, "https://x/css/common/Upgrade.aspx", "<html>enable cookies</html>")
        return FormResponse(200, url, self._form())

    async def post_form(self, url, data, **_):
        if url == mod.FORM_URL:
            parid = data[munis.PARCEL_FIELD]
            self.shown = sorted(self.bills_by_parid.get(parid, []), key=lambda b: b["year"])
            return FormResponse(200, mod.NASH_BASE + munis.BROWSE, self._browse())
        # a view-bill postback on the browse page
        target = data["__EVENTTARGET"]
        idx = int(target.split("$ctl")[-1].split("$")[0]) - 2
        b = self.shown[idx]
        return FormResponse(200, "https://x/css/citizens/RealEstate/ViewBill.aspx", self._bill(b))

    @staticmethod
    def _form():
        return ('<form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs1" />'
                f'<input name="{munis.PARCEL_FIELD}" type="text" maxlength="30" /></form>')

    def _browse(self):
        rows = ['<tr><th>Property Address</th><th>Unit</th><th>Owner</th><th>Parcel ID</th>'
                '<th>Tax Year</th><th>Bill Type</th></tr>']
        for i, b in enumerate(self.shown):
            tgt = f"ctl00$ctl00$PrimaryPlaceHolder$ContentPlaceHolderMain$BillsGridView$ctl{i + 2:02d}$ViewBillLinkButton"
            rows.append(f"<tr><td>{b.get('address', '1 TEST DR')}</td><td>&nbsp;</td><td>{b['owner']}</td>"
                        f"<td>{b['parcel']}</td><td>{b['year']}</td><td>REGULAR/ORIGINAL - REAL ESTATE</td>"
                        f"<td><a href=\"javascript:__doPostBack(&#39;{tgt}&#39;,&#39;&#39;)\">View Bill</a></td></tr>")
        return ('<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs2" />'
                '<table id="ctl00_ctl00_PrimaryPlaceHolder_ContentPlaceHolderMain_BillsGridView">'
                + "".join(rows) + "</table>")

    @staticmethod
    def _bill(b):
        def span(sfx, v):
            return f'<span id="ctl00_ctl00_PrimaryPlaceHolder_ContentPlaceHolderMain_ViewBill1_{sfx}">{v}</span>'
        due, amount = b["due"], b["amount"]
        paid = round(amount - due, 2)
        return ("<table>" + span("FiscalYearLabel", b["year"]) + span("BillNumberLabel", b["bill"])
                + span("OwnerLabel", b["owner"]) + span("CategoryLabel", b["parcel"]) + "</table>"
                '<div id="x_ViewBill1_BillDetailsUpdatePanel">'
                '<table class="datatable"><tr><th>Installment</th><th>Pay By</th><th>Amount</th>'
                '<th>Payments/Credits</th><th>Balance</th><th>Interest</th><th>Due</th></tr>'
                f'<tr><td>1</td><td>{b["pay_by"]}</td><td>${amount:,.2f}</td><td>${paid:,.2f}</td>'
                f'<td>${due:,.2f}</td><td>$0.00</td><td>${due:,.2f}</td></tr>'
                f'<tr><td colspan="2" class="strong">TOTAL</td><td>${amount:,.2f}</td><td>${paid:,.2f}</td>'
                f'<td>${due:,.2f}</td><td>$0.00</td><td>${due:,.2f}</td></tr></table></div>')


# ---------------------------------------------------------------------------
# _open_form -- the cookie warm-up bounce
# ---------------------------------------------------------------------------

def test_open_form_succeeds_first_try_when_session_already_warm():
    client = FakeNashMunis({}, warm=True)
    async def go():
        async with client.form_session() as s:
            return await _open_form(s)
    html = run(go())
    assert munis.PARCEL_FIELD in html
    assert client._get_calls == 1


def test_open_form_retries_once_past_the_cookie_bounce():
    client = FakeNashMunis({}, warm=False)
    async def go():
        async with client.form_session() as s:
            return await _open_form(s)
    html = run(go())
    assert munis.PARCEL_FIELD in html
    assert client._get_calls == 2


# ---------------------------------------------------------------------------
# _fetch / enrich_with_nash_multiyear_tax -- the live chain, faked
# ---------------------------------------------------------------------------

def test_fetch_ok_path_reuses_tax_lien_munis_parsing_verbatim():
    bills = [bill(2024, 30.0), bill(2025, 32.0)]
    client = FakeNashMunis({PARID: bills})
    got, status = run(_fetch(client, PARID))
    assert status == "ok"
    assert {b["year"] for b in got} == {2024, 2025}
    assert got[0]["due"] in (30.0, 32.0)


def test_fetch_parcel_not_found():
    client = FakeNashMunis({PARID: [bill(2024, 10.0, parcel="999999")]})
    got, status = run(_fetch(client, PARID))
    assert (got, status) == (None, "parcel_not_found")


def test_fetch_survives_the_cookie_warmup_bounce():
    bills = [bill(2024, 30.0)]
    client = FakeNashMunis({PARID: bills}, warm=False)
    got, status = run(_fetch(client, PARID))
    assert status == "ok"
    assert client._get_calls == 2


def test_enrich_end_to_end_qualifies_both_blocks():
    bills = [bill(2024, 52.0), bill(2025, 50.0), bill(2026, 10.0)]
    li = _li()
    client = FakeNashMunis({PARID: bills})
    stats = run(enrich_with_nash_multiyear_tax([li], client=client))
    assert stats["eligible"] == 1 and stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]


def test_enrich_zero_matured_years_still_writes_two_year_block_not_multiyear():
    bills = [bill(2026, 10.0)]  # current, not yet late
    li = _li()
    stats = run(enrich_with_nash_multiyear_tax([li], client=FakeNashMunis({PARID: bills})))
    assert stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 0
    assert stats["multiyear_insufficient_years"] == 1
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_unresolvable_parcel_stamps_checked_sentinel_not_block():
    li = _li(parcel="NC00902")
    stats = run(enrich_with_nash_multiyear_tax([li], client=FakeNashMunis({})))
    assert stats["fetch_errors"] == 1
    assert "two_year_delinquent" not in li.raw
    assert li.raw["_nash_mydt_checked"] == "parcel_not_found"


def test_enrich_does_not_overwrite_existing_two_year_block():
    sentinel = {"is_two_year_plus": True, "manual": True}
    li = _li(raw={"two_year_delinquent": sentinel})
    stats = run(enrich_with_nash_multiyear_tax([li], client=FakeNashMunis({})))
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel

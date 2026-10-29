"""enrichment_pender_multiyear_tax: Pender County NC multi-year delinquent-tax history, read
live from the county's own Tyler Munis "Citizen Self Service" tax-bill search (tax_lien_munis's
own PORTALS dict, added 2026-10-29) -- search()/view()/parse_grid()/parse_bill() are reused
verbatim, not reimplemented, since Pender is already a registered Portal (unlike Nash's
differently-pathed tenant, enrichment_nash_multiyear_tax.py's own sibling module).

Everything here is synthetic (made-up parcel/owner/street, in the real 4202-82-6152-0000-shaped
board parcel format) in the shape of the real WebForms pages, live-read 2026-10-29 (see
tax_lien_munis.py's own PORTALS note for the real canary: owner DINKEL, parcel
42028261520000). No network.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind, _normalize_parcel
from foreclosure_scraper.verification.fetch import FormResponse
from foreclosure_scraper.verification.verifiers import tax_lien_munis as munis
from foreclosure_scraper import enrichment_pender_multiyear_tax as mod
from foreclosure_scraper.enrichment_pender_multiyear_tax import (
    build_two_year_block, build_multiyear_block, enrich_with_pender_multiyear_tax, _fetch,
)

TODAY = date(2026, 10, 29)
BOARD_PARCEL = "4202-82-6152-0000"
PARID = "42028261520000"          # what Pender's Munis actually wants (dashes stripped)


def bill(year, due, *, owner="TESTOWNER ALPHA", parcel=PARID, pay_by=None):
    return {"year": year, "bill": f"{year % 100}00001", "owner": owner, "parcel": parcel,
            "amount": round(due + 100, 2), "credits": 100.0, "balance": due, "interest": 0.0,
            "due": due, "pay_by": pay_by or f"{year}-09-01", "prior_unpaid": False, "newer_unpaid": False}


def _li(parcel=BOARD_PARCEL, county="Pender", state="NC", raw=None) -> Listing:
    return Listing(source="counties_generic.liensnc", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_two_year_block / build_multiyear_block -- pure (identical gate logic to Nash's sibling)
# ---------------------------------------------------------------------------

def test_two_matured_years_with_a_real_due_amount_qualifies_both_blocks():
    bills = [bill(2024, 291.74), bill(2025, 266.90), bill(2026, 6340.45)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year["is_two_year_plus"] is True
    assert two_year["oldest_year"] == 2024
    block = build_multiyear_block(BOARD_PARCEL, bills, today=TODAY)
    assert block is not None
    assert block["matured_years"] == [2024, 2025]
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["total_due"] == round(291.74 + 266.90 + 6340.45, 2)
    assert block["matured_owed"] == round(291.74 + 266.90, 2)
    assert block["parcel_key"] == _normalize_parcel(BOARD_PARCEL)
    assert block["source_url"] == mod.PORTAL.base + munis.FORM.split("?")[0]
    assert block["amount_basis"] == "annual_bill"


def test_current_year_unpaid_but_not_yet_late_does_not_qualify():
    bills = [bill(2025, 0.0), bill(2026, 3310.47)]
    assert build_two_year_block(bills, today=TODAY) == {
        "is_two_year_plus": False, "years": 0, "oldest_year": None,
        "source": "verification.verifiers.tax_lien_munis"}
    assert build_multiyear_block(BOARD_PARCEL, bills, today=TODAY) is None


def test_single_matured_year_fails_multiyear_gate_but_two_year_block_still_honest():
    """Matches the real DINKEL/GREET live canary shape (2026-10-29): a single real delinquent
    year is reported honestly in two_year_delinquent, but does not clear the MIN_YEARS=2 gate."""
    bills = [bill(2025, 929.17)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year["is_two_year_plus"] is False and two_year["years"] == 1 and two_year["oldest_year"] == 2025
    assert build_multiyear_block(BOARD_PARCEL, bills, today=TODAY) is None


def test_all_paid_yields_nothing():
    bills = [bill(y, 0.0) for y in range(2023, 2027)]
    two_year = build_two_year_block(bills, today=TODAY)
    assert two_year == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                        "source": "verification.verifiers.tax_lien_munis"}
    assert build_multiyear_block(BOARD_PARCEL, bills, today=TODAY) is None


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_enrich_eligible_only_pender_nc_with_parcel():
    eligible = _li()
    wrong_county = _li(county="New Hanover")
    wrong_state = _li(state="SC", county="Pender")
    no_parcel = _li(parcel="")
    already = _li(raw={"_pender_mydt_checked": "fetch_failed:TimeoutError"})
    already_block = _li(raw={"two_year_delinquent": {"is_two_year_plus": False}})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already, already_block]
    targets = [li for li in rows if mod._eligible(li)]
    assert targets == [eligible]


# ---------------------------------------------------------------------------
# fake Munis client -- drives tax_lien_munis.search()/view() directly, the way the real
# Fetcher.form_session() does, so this module's OWN reuse of those functions is exercised,
# not a re-implementation of them (contrast enrichment_nash_multiyear_tax's FakeNashMunis,
# which fakes its own standalone _fetch/_open_form instead)
# ---------------------------------------------------------------------------

class FakePenderMunis:
    def __init__(self, bills_by_parid):
        self.bills_by_parid = bills_by_parid
        self.shown: list[dict] = []

    def form_session(self, **_):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url, **_):
        return FormResponse(200, url, self._form())

    async def post_form(self, url, data, **_):
        if url == mod.PORTAL.base + munis.FORM:
            parid = data[munis.PARCEL_FIELD]
            self.shown = sorted(self.bills_by_parid.get(parid, []), key=lambda b: b["year"])
            return FormResponse(200, mod.PORTAL.base + munis.BROWSE, self._browse())
        target = data["__EVENTTARGET"]
        idx = int(target.split("$ctl")[-1].split("$")[0]) - 2
        b = self.shown[idx]
        return FormResponse(200, mod.PORTAL.base + "/citizens/RealEstate/ViewBill.aspx", self._bill(b))

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
# _fetch / enrich_with_pender_multiyear_tax -- the live chain, faked
# ---------------------------------------------------------------------------

def test_fetch_ok_path_reuses_tax_lien_munis_search_and_view_verbatim():
    bills = [bill(2024, 30.0), bill(2025, 32.0)]
    client = FakePenderMunis({PARID: bills})
    got, status = run(_fetch(client, BOARD_PARCEL))
    assert status == "ok"
    assert {b["year"] for b in got} == {2024, 2025}
    assert got[0]["due"] in (30.0, 32.0)


def test_fetch_undashes_the_board_parcel_before_searching():
    """The fake only knows bills under the UNDASHED PARID -- a search for the dashed board id
    must still find them, proving search_id()'s Pender branch actually ran before search()."""
    bills = [bill(2026, 10.0)]
    client = FakePenderMunis({PARID: bills})
    got, status = run(_fetch(client, BOARD_PARCEL))
    assert status == "ok" and len(got) == 1


def test_fetch_parcel_not_found():
    client = FakePenderMunis({PARID: [bill(2024, 10.0, parcel="99999999999999")]})
    got, status = run(_fetch(client, BOARD_PARCEL))
    assert (got, status) == (None, "parcel_not_found")


def test_enrich_end_to_end_qualifies_both_blocks():
    bills = [bill(2024, 52.0), bill(2025, 50.0), bill(2026, 10.0)]
    li = _li()
    client = FakePenderMunis({PARID: bills})
    stats = run(enrich_with_pender_multiyear_tax([li], client=client))
    assert stats["eligible"] == 1 and stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]


def test_enrich_zero_matured_years_still_writes_two_year_block_not_multiyear():
    bills = [bill(2026, 10.0)]  # current, not yet late
    li = _li()
    stats = run(enrich_with_pender_multiyear_tax([li], client=FakePenderMunis({PARID: bills})))
    assert stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 0
    assert stats["multiyear_insufficient_years"] == 1
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_unresolvable_parcel_stamps_checked_sentinel_not_block():
    li = _li(parcel="9999-99-9999-9999")
    stats = run(enrich_with_pender_multiyear_tax([li], client=FakePenderMunis({})))
    assert stats["fetch_errors"] == 1
    assert "two_year_delinquent" not in li.raw
    assert li.raw["_pender_mydt_checked"] == "parcel_not_found"


def test_enrich_does_not_overwrite_existing_two_year_block():
    sentinel = {"is_two_year_plus": True, "manual": True}
    li = _li(raw={"two_year_delinquent": sentinel})
    stats = run(enrich_with_pender_multiyear_tax([li], client=FakePenderMunis({})))
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel


def test_enrich_runs_one_row_at_a_time_by_default():
    """2026-10-29: CONCURRENCY>1 raced two parcels on tax_lien_munis's one shared
    per-portal session and the real portal answered search HTTP 500 for both -- see the
    module docstring. The default must stay 1."""
    assert mod.CONCURRENCY == 1

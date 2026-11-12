"""enrichment_cabarrus_multiyear_tax: Cabarrus County NC multi-year delinquent-tax history, read
live via verification/verifiers/tax_lien_itsnet.py's own live-proven session/search/parse chain,
reused verbatim (not re-implemented). Bill fixtures below use the exact dict shape
tax_lien_itsnet.parse_grid() produces: year/bill/account/owners/levy/balance/ids/address.

The fixtures mirror real shapes live-read against the real portal 2026-10-20 (see the module's
own docstring): PIN 56221770270000 (22 years, all paid current, correctly yields nothing) and a
constructed 2-matured-year case shaped like it (real multi-year delinquency is rare in a 5-PIN
canary, so this exercises the gate with the same dollar shapes the live recon found elsewhere).
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_itsnet as itsnet
from foreclosure_scraper import enrichment_cabarrus_multiyear_tax as mod
from foreclosure_scraper.enrichment_cabarrus_multiyear_tax import (
    build_two_year_block, build_multiyear_block, enrich_with_cabarrus_multiyear_tax, _fetch,
)

TODAY = date(2026, 10, 20)
PORTAL = itsnet.PORTALS["Cabarrus"]
PIN = "56221770270000"
FORM_PAGE = """<html><form>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs123" />
<input type="hidden" name="__EVENTVALIDATION" value="ev456" />
<input name="ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$ctrlParcelNumber$txtSheet" type="text" maxlength="4" />
<select name="ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$dropdownlistTaxYear">
<option selected="selected" value="-1">All Years</option><option value="2025">2025</option></select>
</form></html>"""


def bill(year, billno, owner, balance, pid, addr, *, account="15772"):
    """One tax_lien_itsnet.parse_grid()-shaped bill dict."""
    return {"year": year, "bill": billno, "account": account, "owners": [owner],
            "levy": max(balance, 1.0), "balance": balance, "ids": [pid, "04077 0129.000000"],
            "address": addr}


def _grid(*bills_):
    rows = ""
    for b in bills_:
        rows += (f'<tr class="RowStyleDefaultGridViewSkin"><td class="HyperLinkField"><a href="javascript:x">'
                 f'{b["year"]}  {b["bill"]}</a></td><td>{b["account"]}</td><td>{b["owners"][0]}</td><td></td>'
                 f'<td>{b["levy"]:.2f}</td><td>{b["balance"]:.2f}</td><td> </td>'
                 f'<td>{b["ids"][0]}<br />{b["ids"][1]}</td><td>{b["address"]}</td></tr>')
    return ('<html><input type="hidden" name="__VIEWSTATE" value="vs2" /><table id="x_gridviewSearchResults">'
            '<tr><th>Year Bill#</th><th>Account#</th><th>Owner Name</th><th>Owner Name2</th><th>Orig Levy</th>'
            '<th>Balance</th><th>Disc Year</th><th>Property ID</th><th>Property Address</th></tr>'
            + rows + "</table></html>")


def _li(parcel=PIN, county="Cabarrus", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_county_pdf_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def _replay(bills_):
    fields = itsnet.search_fields(PORTAL, PIN)
    page = _grid(*bills_) if bills_ else _grid()
    return ReplayFetcher({PORTAL.url: FORM_PAGE,
                          form_key(PORTAL.url, itsnet.build_form(FORM_PAGE, fields)): page})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_two_year_block / build_multiyear_block -- pure
# ---------------------------------------------------------------------------

def test_real_shaped_all_paid_parcel_yields_nothing():
    """Real board PIN 56221770270000, live-verified 2026-10-20: 22 years, every one paid
    $0.00 (SECHLER/METTS-WAKELAND owners) -- correctly zero matured delinquent years."""
    bills = [bill(y, str(1000 + y), "SECHLER SHELIA", 0.0, PIN, "2401 FLORIDA AVE") for y in range(2005, 2027)]
    two_year = build_two_year_block(PIN, bills, today=TODAY)
    assert two_year == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                        "source": "verification.verifiers.tax_lien_itsnet"}
    assert build_multiyear_block(PIN, bills, today=TODAY) is None


def test_current_year_unpaid_but_not_yet_late_does_not_qualify():
    """Real board PIN 56301830170000 shape, live-verified 2026-10-20: 2025 paid, 2026 unpaid
    $13,944.50 but NOT YET LATE (NC's Jan-6-of-next-year rule) -- a current bill, not a
    multi-year delinquency."""
    bills = [bill(2025, "053046", "HARWARDS REALTY", 0.0, PIN, "178 WILKINSON CT SE"),
            bill(2026, "053338", "HARWARDS REALTY", 13944.50, PIN, "178 WILKINSON CT SE")]
    assert build_two_year_block(PIN, bills, today=TODAY) == {
        "is_two_year_plus": False, "years": 0, "oldest_year": None,
        "source": "verification.verifiers.tax_lien_itsnet"}
    assert build_multiyear_block(PIN, bills, today=TODAY) is None


def test_two_matured_years_qualifies_both_blocks():
    bills = [bill(2026, "1", "X", 100.0, PIN, "1 TEST DR"),      # current, not yet late
            bill(2025, "2", "X", 266.90, PIN, "1 TEST DR"),      # matured, unpaid
            bill(2024, "3", "X", 291.74, PIN, "1 TEST DR"),      # matured, unpaid
            bill(2023, "4", "X", 0.0, PIN, "1 TEST DR")]         # matured, paid
    two_year = build_two_year_block(PIN, bills, today=TODAY)
    assert two_year["is_two_year_plus"] is True and two_year["years"] == 2 and two_year["oldest_year"] == 2024
    block = build_multiyear_block(PIN, bills, today=TODAY)
    assert block is not None
    assert block["years"] == [2024, 2025, 2026] and block["matured_years"] == [2024, 2025]
    assert block["years_delinquent"] == 2
    assert block["total_due"] == round(266.90 + 291.74 + 100.0, 2)
    assert block["matured_owed"] == round(266.90 + 291.74, 2)
    assert block["in_current_levy"] is True and block["current_levy_year"] == 2026
    assert block["amount_basis"] == "annual_bill"
    # _normalize_parcel collapses a 10+-digit PIN whose tail past the 10th char is all zeros
    # (models._normalize_parcel's own "county GIS zero-padding" rule) -- "56221770270000" ->
    # "5622177027", same rule any other 14-digit-with-trailing-zeros Cabarrus PIN hits.
    assert block["parcel_key"] == "5622177027"
    assert block["source_url"] == PORTAL.url


def test_single_matured_year_fails_multiyear_gate_but_two_year_block_still_honest():
    bills = [bill(2024, "1", "X", 50.0, PIN, "1 TEST DR")]
    two_year = build_two_year_block(PIN, bills, today=TODAY)
    assert two_year["is_two_year_plus"] is False and two_year["years"] == 1 and two_year["oldest_year"] == 2024
    assert build_multiyear_block(PIN, bills, today=TODAY) is None


def test_ignores_bills_for_a_different_parcel():
    other = bill(2023, "9", "X", 999.0, "99999999999999", "9 OTHER ST")
    bills = [bill(2024, "1", "X", 30.0, PIN, "1 TEST DR"), bill(2023, "2", "X", 32.0, PIN, "1 TEST DR"), other]
    block = build_multiyear_block(PIN, bills, today=TODAY)
    assert block["years"] == [2023, 2024]
    assert block["total_due"] == 62.0


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_enrich_eligible_only_cabarrus_nc_with_parcel():
    eligible = _li()
    wrong_county = _li(county="Iredell")
    wrong_state = _li(state="SC", county="Cabarrus")
    no_parcel = _li(parcel="")
    already = _li(raw={"_cabarrus_mydt_checked": "fetch_failed:TimeoutError"})
    already_block = _li(raw={"two_year_delinquent": {"is_two_year_plus": False}})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already, already_block]
    targets = [li for li in rows if mod._eligible(li)]
    assert targets == [eligible]


# ---------------------------------------------------------------------------
# _fetch / enrich_with_cabarrus_multiyear_tax -- the live chain, replayed
# ---------------------------------------------------------------------------

def test_fetch_ok_path_reuses_tax_lien_itsnet_verbatim():
    bills = [bill(2024, "1", "X", 30.0, PIN, "1 TEST DR"), bill(2023, "2", "X", 32.0, PIN, "1 TEST DR")]
    f = _replay(bills)
    got, status = run(_fetch(f, PIN))
    assert status == "ok"
    assert {b["year"] for b in got} == {2023, 2024}


def test_fetch_zero_bills_is_ok_not_an_error():
    """A parcel with no bills on file answers an empty-but-real grid (the __VIEWSTATE is still
    present) -- a genuine zero, not a fetch failure."""
    f = _replay([])
    got, status = run(_fetch(f, PIN))
    assert (got, status) == ([], "ok")


def test_fetch_unresolvable_parcel():
    f = ReplayFetcher({})
    got, status = run(_fetch(f, "12-34"))
    assert (got, status) == (None, "parcel_unresolvable")


def test_enrich_end_to_end_qualifies_both_blocks():
    bills = [bill(2026, "1", "X", 10.0, PIN, "1 TEST DR"), bill(2025, "2", "X", 50.0, PIN, "1 TEST DR"),
            bill(2024, "3", "X", 52.0, PIN, "1 TEST DR")]
    li = _li()
    stats = run(enrich_with_cabarrus_multiyear_tax([li], client=_replay(bills)))
    assert stats["eligible"] == 1 and stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]


def test_enrich_zero_matured_years_still_writes_two_year_block_not_multiyear():
    bills = [bill(2026, "1", "X", 10.0, PIN, "1 TEST DR")]  # current, not yet late
    li = _li()
    stats = run(enrich_with_cabarrus_multiyear_tax([li], client=_replay(bills)))
    assert stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 0
    assert stats["multiyear_insufficient_years"] == 1
    assert li.raw["two_year_delinquent"] == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                                             "source": "verification.verifiers.tax_lien_itsnet"}
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_no_bills_on_file_still_writes_an_honest_zero():
    li = _li()
    stats = run(enrich_with_cabarrus_multiyear_tax([li], client=_replay([])))
    assert stats["two_year_written"] == 1
    assert li.raw["two_year_delinquent"]["years"] == 0


def test_enrich_unresolvable_parcel_stamps_checked_sentinel_not_block():
    li = _li(parcel="bad")
    stats = run(enrich_with_cabarrus_multiyear_tax([li], client=ReplayFetcher({})))
    assert stats["fetch_errors"] == 1
    assert "two_year_delinquent" not in li.raw
    assert li.raw["_cabarrus_mydt_checked"] == "parcel_unresolvable"


def test_enrich_does_not_overwrite_existing_two_year_block():
    sentinel = {"is_two_year_plus": True, "manual": True}
    li = _li(raw={"two_year_delinquent": sentinel})
    stats = run(enrich_with_cabarrus_multiyear_tax([li], client=ReplayFetcher({})))
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel

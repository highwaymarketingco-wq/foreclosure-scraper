"""tax_lien_itsnet: the classic ITS.NET bill search (Iredell, Chowan) with hand-written pages."""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_itsnet as V

TODAY = date(2026, 10, 9)
FORM_PAGE = """<html><form>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs123" />
<input type="hidden" name="__EVENTVALIDATION" value="ev456" />
<input name="ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$textboxLastName" type="text" />
<input name="ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$ctrlParcelNumber$txtMAP" type="text" maxlength="4" />
<select name="ctl00$contentplaceholdertaxBillSearch$UsercontrolTaxbillSearch$dropdownlistTaxYear">
<option selected="selected" value="-1">All Years</option><option value="2025">2025</option></select>
</form></html>"""


def _grid(*bills):
    rows = ""
    for year, bill, owner, bal, pid, addr in bills:
        rows += (f'<tr class="RowStyleDefaultGridViewSkin"><td class="HyperLinkField"><a href="javascript:x">'
                 f'{year}  {bill}</a></td><td>900001</td><td>{owner}</td><td></td><td>100.00</td>'
                 f'<td>{bal:.2f}</td><td> </td><td>{pid}<br />ALT-9</td><td>{addr}</td></tr>')
    return ('<html><input type="hidden" name="__VIEWSTATE" value="vs2" /><table id="x_gridviewSearchResults">'
            '<tr><th>Year Bill#</th><th>Account#</th><th>Owner Name</th><th>Owner Name2</th><th>Orig Levy</th>'
            '<th>Balance</th><th>Disc Year</th><th>Property ID</th><th>Property Address</th></tr>'
            + rows + "</table></html>")


def _row(county="Iredell", parcel="1234567890.000", owner="EXAMPLE TESTER", **kw):
    r = {"state": "NC", "county": county, "parcel_id": parcel, "owner_name": owner,
         "street_address": "10 TEST ST", "listing_type": "tax_lien",
         "source": "counties_nc.iredell_delinquent_tax",
         "raw": {"iredell_delinquent_tax": {"years_unpaid": [2025]},
                 "tax_owed": {"balance": 400, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def _fetcher(row, results_page, county="Iredell"):
    portal = V.PORTALS[county]
    fields = V.search_fields(portal, row["parcel_id"])
    if fields is None:
        return ReplayFetcher({})
    return ReplayFetcher({portal.url: FORM_PAGE,
                          form_key(portal.url, V.build_form(FORM_PAGE, fields)): results_page})


def _run(row, results_page, county="Iredell"):
    f = _fetcher(row, results_page, county)
    return asyncio.run(V.verify(row, f, today=TODAY)), f


def test_registered_with_the_shared_tax_lien_contract():
    v = {x.name: x for x in registry.discover()}["tax_lien_itsnet"]
    assert v.signal == "tax_lien" and v.governs and not v.wall


def test_applies_to_the_two_counties_and_not_to_a_non_tax_listing():
    assert V.applies(_row())
    assert V.applies(_row(county="Chowan", parcel="123456789012", source="counties_nc.albemarle_observer_tax_lists",
                          raw={"albemarle_observer_tax_list": {"county": "Chowan"}}))
    assert not V.applies(_row(county="Wake"))
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(listing_type="lis_pendens", raw={}))


def test_parcel_fields_by_county_kind():
    ire, cho = V.PORTALS["Iredell"], V.PORTALS["Chowan"]
    f = V.search_fields(ire, "1234567890.000")
    assert list(f.values()) == ["1234", "56", "7890"]
    assert V.search_fields(ire, "12345") is None and V.search_fields(ire, "") is None
    assert V.search_fields(cho, "6970-0779-2923") == {V.P + "ctrlParcelNumber$txtParcel": "697007792923"}


def test_cabarrus_portal_registered_and_untouched_siblings():
    """Added 2026-10-20: a new tenant of the same vendor. Iredell/Chowan's own kind/url/blocks
    are unchanged by this addition."""
    cab = V.PORTALS["Cabarrus"]
    assert cab.kind == "sheet_block_parcel" and cab.blocks == ()
    assert cab.url == "https://tax.cabarruscounty.us/TaxBill.aspx"
    assert V.PORTALS["Iredell"].kind == "map_blk_pin" and V.PORTALS["Chowan"].kind == "single"


def test_cabarrus_parcel_fields_sheet_block_parcel_interest():
    cab = V.PORTALS["Cabarrus"]
    f = V.search_fields(cab, "56221770270000")
    assert f == {V.P + "ctrlParcelNumber$txtSheet": "5622", V.P + "ctrlParcelNumber$txtBlock": "17",
                V.P + "ctrlParcelNumber$txtParcel": "7027", V.P + "ctrlParcelNumber$txtInterest": "0000"}
    assert V.search_fields(cab, "123") is None and V.search_fields(cab, "") is None


def test_cabarrus_not_in_applies_without_an_upstream_claim():
    """No scraper claims a Cabarrus property-tax delinquency yet (blocks=()), so the shared
    tax_lien verifier correctly stays silent on an ordinary distressed-listing row (real
    Cabarrus board rows carry listing_type "distressed", not "tax_lien") until some upstream
    source claims one -- enrichment_cabarrus_multiyear_tax reads the live portal directly
    instead."""
    assert not V.applies(_row(county="Cabarrus", parcel="56221770270000", listing_type="distressed",
                              source="some.other.scraper", raw={}))


def test_fetch_grid_public_wrapper_matches_cabarrus_live_shape():
    """fetch_grid() is the public reuse seam enrichment_cabarrus_multiyear_tax.py calls; proves
    it round-trips a Cabarrus-shaped search the same way _search() does internally for verify()."""
    cab = V.PORTALS["Cabarrus"]
    fields = V.search_fields(cab, "56221770270000")
    page = _grid((2025, "077858", "SECHLER SHELIA", 0.0, "56221770270000", "2401 FLORIDA AVE"),
                 (2026, "079760", "SECHLER SHELIA", 13944.50, "56221770270000", "2401 FLORIDA AVE"))
    f = ReplayFetcher({cab.url: FORM_PAGE, form_key(cab.url, V.build_form(FORM_PAGE, fields)): page})
    grid = asyncio.run(V.fetch_grid(f, cab, fields))
    assert grid["paged"] is False
    assert {b["year"] for b in grid["bills"]} == {2025, 2026}


def test_build_form_keeps_the_pages_fields_and_picks_all_years():
    d = V.build_form(FORM_PAGE, {V.P + "ctrlParcelNumber$txtMAP": "1234"})
    assert d["__VIEWSTATE"] == "vs123" and d["__EVENTVALIDATION"] == "ev456"
    assert d[V.P + "dropdownlistTaxYear"] == "-1" and d[V.P + "ctrlParcelNumber$txtMAP"] == "1234"
    assert d[V.P + "buttonSearch"] == "Search" and V.P + "textboxLastName" in d


def test_parse_grid_reads_bills_and_ids():
    g = V.parse_grid(_grid((2025, "000001", "EXAMPLE TESTER", 250.5, "1234567890.000", "10 TEST ST")))
    assert g["paged"] is False and len(g["bills"]) == 1
    b = g["bills"][0]
    assert b["year"] == 2025 and b["balance"] == 250.5 and b["ids"] == ["1234567890.000", "ALT-9"]
    assert V.parse_grid("<html>no grid</html>") is None


def test_confirmed_when_a_late_year_bill_has_a_balance():
    page = _grid((2024, "1", "EXAMPLE TESTER", 0.0, "1234567890.000", "10 TEST ST"),
                 (2025, "2", "EXAMPLE TESTER", 250.5, "1234567890.000", "10 TEST ST"),
                 (2026, "3", "EXAMPLE TESTER", 999.0, "1234567890.000", "10 TEST ST"),   # not late yet
                 (2025, "9", "OTHER PARCEL OWNER", 77.0, "1111111111.000", "9 OTHER ST"))
    r, f = _run(_row(), page)
    assert r.verdict == "confirmed" and r.evidence["late_years_owed"] == {"2025": 250.5}
    assert r.evidence["total_late_balance"] == 250.5 and r.evidence["bills_on_parcel"] == 3
    assert "EXAMPLE" not in str(r.evidence)                  # public ledger: no names
    assert len(f.asked) == 2                                  # the form page and one search


def test_stale_when_the_decision_year_is_billed_and_paid():
    page = _grid((2025, "2", "EXAMPLE TESTER", 0.0, "1234567890.000", "10 TEST ST"))
    r, _ = _run(_row(), page)
    assert r.verdict == "stale" and r.evidence["reason"] == "paid_since_list"
    assert r.evidence["paid_decision_years"] == [2025]


def test_a_county_address_that_is_another_house_on_the_street_is_unconfirmed():
    page = _grid((2025, "2", "EXAMPLE TESTER", 0.0, "1234567890.000", "12 TEST ST"))
    r, _ = _run(_row(), page)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "address_parcel_mismatch"


def test_unconfirmed_outcomes():
    r, _ = _run(_row(), _grid((2025, "9", "X", 5.0, "1111111111.000", "9 OTHER ST")))
    assert r.evidence["reason"] == "parcel_not_found"
    r, _ = _run(_row(), _grid((2020, "9", "EXAMPLE TESTER", 0.0, "1234567890.000", "10 TEST ST")))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "decision_year_not_billed"
    r, _ = _run(_row(), _grid((2025, "2", "EXAMPLE TESTER", 5.0, "1234567890.000", "10 TEST ST")).replace(
        "</table>", "<tr><td>Page$2</td></tr></table>"))
    assert r.evidence["reason"] == "results_paged"
    r, f = _run(_row(parcel="12-34"), "x")
    assert r.evidence["reason"] == "parcel_unresolvable" and f.asked == []
    r, _ = _run(_row(), "<html>nothing</html>")
    assert r.evidence["reason"] == "fetch_failed"        # not the form: unreadable answer is an error
    assert "fetch_failed" in V.TRANSIENT_REASONS


def test_a_resolver_attached_parcel_with_another_owners_bills_is_unconfirmed():
    page = _grid((2025, "2", "STRANGER PERSON", 250.5, "1234567890.000", "10 TEST ST"))
    row = _row()
    row["raw"]["parcel_from_address"] = "1234567890.000"
    r, _ = _run(row, page)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_differs"


def test_chowan_single_parcel_field():
    row = _row(county="Chowan", parcel="697007792923", source="counties_nc.albemarle_observer_tax_lists",
               raw={"albemarle_observer_tax_list": {"county": "Chowan", "years": [2025]}})
    page = _grid((2025, "13", "EXAMPLE TESTER", 44.8, "697007792923", "100 CHEYENNE TRL"))
    r, f = _run(row, page, county="Chowan")
    assert r.verdict == "confirmed" and r.evidence["county"] == "Chowan"

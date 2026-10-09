"""tax_lien_pwa: PTS Public Web Access bill search (Randolph, Mecklenburg) with hand-written pages."""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_pwa as V

TODAY = date(2026, 10, 9)
FORM_PAGE = """<html><form>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs1" />
<input type="hidden" name="hdnPageNum" value="0" />
<select name="taxYear"><option value="">ALL</option><option value="2026">2026</option><option value="2025">2025</option></select>
<select name="lookupCriterion"><option selected="true" value=""></option><option value="Bill Number">Bill Number</option>
<option value="Parcel Number">Parcel Number</option></select>
<input name="txtStreetNum" type="text" /><input name="txtSearchString" type="text" />
</form></html>"""


def _grid(*bills, pages=1):
    rows = ""
    for i, (year, owner, due, addr, flags, parcel) in enumerate(bills):
        rows += (f"<tr id='dgResults_r_{i}' level='{i}'><td level=\"{i}_0\"><a href='BillDetails.aspx?BillPk={i}'>"
                 f"0000099999-{year}-{year}-0000-00</a></td><td level=\"{i}_1\">&nbsp;</td>"
                 f"<td uV=\"{parcel}\" level=\"{i}_2\"><a href=\"x\">{parcel}</a></td>"
                 f"<td level=\"{i}_3\">{owner}</td><td level=\"{i}_4\">{addr}</td><td level=\"{i}_5\">{flags}</td>"
                 f"<td uV=\"{due:.2f}\" level=\"{i}_7\">${due:,.2f}</td></tr>")
    return (f'<html><input type="hidden" name="__VIEWSTATE" value="vs2" /> [Page 1 of {pages}] '
            f'<table id="dgResults">{rows}</table></html>')


def _row(county="Randolph", parcel="9999999999", owner="EXAMPLE TESTER LLC", **kw):
    r = {"state": "NC", "county": county, "parcel_id": parcel, "owner_name": owner,
         "street_address": "10 TEST ST", "listing_type": "tax_lien", "source": "counties_nc.nc_tax_lien_ads",
         "raw": {"nc_tax_lien_ad": {"county": county, "tax_year": 2025, "years_unpaid": [2025], "amount": 400}}}
    r.update(kw)
    return r


def _run(row, results_page):
    portal = V.PORTALS[row["county"]]
    resp = {portal.form_url: FORM_PAGE}
    if results_page is not None:
        resp[form_key(portal.post_url, V.build_form(FORM_PAGE, row["parcel_id"]))] = results_page
    f = ReplayFetcher(resp)
    return asyncio.run(V.verify(row, f, today=TODAY)), f


def test_registered_with_the_shared_tax_lien_contract():
    v = {x.name: x for x in registry.discover()}["tax_lien_pwa"]
    assert v.signal == "tax_lien" and v.governs and not v.wall


def test_applies_to_the_two_counties():
    assert V.applies(_row())
    assert V.applies(_row(county="Mecklenburg", source="counties_nc.mecklenburg_tax_foreclosure",
                          raw={"mecklenburg_tax_foreclosure": {}}))
    assert not V.applies(_row(county="Wake"))
    assert not V.applies(_row(state="SC"))
    assert not V.applies(_row(listing_type="lis_pendens", raw={}))


def test_build_form_sets_criterion_parcel_and_year():
    d = V.build_form(FORM_PAGE, "123", year="2025")
    assert d["lookupCriterion"] == "Parcel Number" and d["txtSearchString"] == "123"
    assert d["taxYear"] == "2025" and d["btnGo"] == "Go" and d["__VIEWSTATE"] == "vs1"
    assert V.build_form(FORM_PAGE, "123")["taxYear"] == ""


def test_parse_grid_reads_bills_flags_and_pages():
    g = V.parse_grid(_grid((2025, "EXAMPLE TESTER LLC", 231.84, "1 MAIN ST", "DLQ, ADVERTISED, ATT REF IN REM",
                            "9999999999"), pages=3))
    assert g["pages"] == 3 and len(g["bills"]) == 1
    b = g["bills"][0]
    assert b["year"] == 2025 and b["due"] == 231.84 and b["parcel"] == "9999999999"
    assert b["flags"] == ["DLQ", "ADVERTISED", "ATT REF IN REM"]
    assert V.parse_grid("<html>nothing</html>") is None


def test_confirmed_with_the_counties_bill_flags_as_evidence():
    page = _grid((2026, "EXAMPLE TESTER LLC", 900.0, "10 TEST ST", "", "9999999999"),            # not late yet
                 (2025, "EXAMPLE TESTER LLC", 231.84, "10 TEST ST", "DLQ, ATT REF IN REM", "9999999999"),
                 (2024, "EXAMPLE TESTER LLC", 0.0, "10 TEST ST", "", "9999999999"),
                 (2025, "OTHER OWNER", 55.0, "9 OTHER ST", "DLQ", "1111111111"), pages=2)
    r, f = _run(_row(), page)
    assert r.verdict == "confirmed" and r.evidence["late_years_owed"] == {"2025": 231.84}
    assert r.evidence["bill_flags"] == ["DLQ", "ATT REF IN REM"] and r.evidence["pages"] == 2
    assert r.evidence["bills_on_page"] == 3 and "EXAMPLE" not in str(r.evidence)
    assert len(f.asked) == 2


def test_stale_when_the_decision_year_is_billed_with_nothing_due():
    page = _grid((2026, "EXAMPLE TESTER LLC", 900.0, "10 TEST ST", "", "9999999999"),
                 (2025, "EXAMPLE TESTER LLC", 0.0, "10 TEST ST", "", "9999999999"))
    r, _ = _run(_row(), page)
    assert r.verdict == "stale" and r.evidence["reason"] == "paid_since_list"
    assert r.evidence["paid_decision_years"] == [2025] and not r.evidence.get("late_years_owed")


def test_unconfirmed_outcomes():
    other = _grid((2025, "X", 5.0, "9 OTHER ST", "", "1111111111"))
    assert _run(_row(), other)[0].evidence["reason"] == "parcel_not_found"
    only_2026 = _grid((2026, "EXAMPLE TESTER LLC", 0.0, "10 TEST ST", "", "9999999999"))
    assert _run(_row(), only_2026)[0].evidence["reason"] == "decision_year_not_on_page"
    mismatch = _grid((2025, "EXAMPLE TESTER LLC", 0.0, "12 TEST ST", "", "9999999999"))
    assert _run(_row(), mismatch)[0].evidence["reason"] == "address_parcel_mismatch"
    r, f = _run(_row(parcel="0"), None)
    assert r.evidence["reason"] == "parcel_unresolvable" and f.asked == []
    r, _ = _run(_row(), None)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"
    assert "fetch_failed" in V.TRANSIENT_REASONS


def test_resolver_attached_parcel_with_another_owners_bills_is_unconfirmed():
    page = _grid((2025, "STRANGER PERSON", 231.84, "10 TEST ST", "DLQ", "9999999999"))
    row = _row()
    row["raw"]["parcel_from_geo"] = "9999999999"
    r, _ = _run(row, page)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "owner_differs"

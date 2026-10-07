"""tax_lien_qpaybill v4 (2026-10-07): "Sold at Tax Sale" is its own recognised state.

Observed live on Cherokee SC's qPayBill portal (3 requests, 2026-10-07): the land parcel of a
manufactured-home account lists Status "Sold at Tax Sale" with Payment Date 11/04/24 (the SALE date)
for tax years 2023 and 2024, its 2025 bill "Paid" 03/25/26 (after the 01/15/26 deadline), and the
home account (the same map number + ".001") lists "Unpaid" for 2023-2025. The only statuses on that
page were Paid, Unpaid and Sold at Tax Sale. This module rebuilds that shape with made-up owners,
addresses and map numbers (grid markup as the portal writes it). No network.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as q

TODAY = date(2026, 10, 7)
SUB = "cherokeecountysctax"
LAND = "900-00-00-001.010"
HOME = "900-00-00-001.010.001"


def page(rows):
    """The portal's search answer for `rows`: (notice, year, ident, status, paid_on mm/dd/yy, amount)."""
    body = "".join(
        f'<tr class="gvrow"><td>{n}</td><td>TESTOWNER11 PAT<br />100 TEST RD</td><td>{y}</td>'
        f'<td>TEST DESCRIPTION</td><td>{ident}</td><td>RealEstate</td><td>{status}</td>'
        f'<td>{paid or "        "}</td><td>{amt}</td></tr>'
        for n, y, ident, status, paid, amt in rows)
    return ('<html><body><form><input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS" />'
            '<select name="ctl00$MainContent$ddlCriteriaList" id="ctl00_MainContent_ddlCriteriaList"></select>'
            '<table class="gridview" id="ctl00_MainContent_gvSearchResults"><tr class="gvheader"><th>x</th></tr>'
            f'{body}</table></form></body></html>')


FORM = page([])        # a form page: the viewstate and the criteria drop-down, no rows


def served(**searches):
    """A replay of the tenant's session plus the named Map searches {value: page}."""
    url = q.form_url(SUB)
    resp = {url: FORM, form_key(url, q.criteria_data(q.viewstate(FORM), "Map")): FORM}
    for value, html in searches.items():
        resp[form_key(url, q.search_data(q.viewstate(FORM), value, "Map"))] = html
    return ReplayFetcher(resp)


def served_map(pages: dict):
    return served(**pages)


def run(row, fetcher):
    return asyncio.run(q.verify(row, fetcher, today=TODAY))


def row_for(ident, *, years=("2025",), parcel=None, street="100 TEST RD", **kw):
    r = {"state": "SC", "county": "Cherokee", "listing_type": "tax_sale", "street_address": street,
         "source": "counties_sc.qpaybill_delinquent_roll", "parcel_id": parcel or ident,
         "raw": {"qpaybill_roll": {"identification_no": ident, "county": "Cherokee",
                                   "years_unpaid": list(years), "notice_numbers": []}}}
    r.update(kw)
    return r


# the observed land parcel: 2025 paid late (after the 01/15/26 deadline), 2023 and 2024 sold on 11/04/24
LAND_ROWS = [("010147253", 2025, LAND, "Paid", "03/25/26", "$41.27"),
             ("009837243", 2024, LAND, "Sold at Tax Sale", "11/04/24", "$116.93"),
             ("009829233", 2023, LAND, "Sold at Tax Sale", "11/04/24", "$253.93"),
             ("009901223", 2022, LAND, "Paid", "12/02/22", "$110.52"),
             ("009684213", 2021, LAND, "Paid", "12/02/22", "$829.39")]
HOME_ROWS = [("010148253", 2025, HOME, "Unpaid", None, "$290.82"),
             ("009838243", 2024, HOME, "Unpaid", None, "$1,059.28"),
             ("009830233", 2023, HOME, "Unpaid", None, "$1,055.05")]


def test_the_observed_statuses_are_kinds_of_their_own():
    assert [q._kind(s) for s in ("Paid", "Unpaid", "Sold at Tax Sale")] == ["paid", "owed", "sold"]
    rows = q.parse_grid(page(LAND_ROWS))["rows"]
    sold = [r for r in rows if r["status"] == "Sold at Tax Sale"]
    assert [(r["year"], str(r["paid_on"]), r["amount"]) for r in sold] == \
        [(2024, "2024-11-04", 116.93), (2023, "2024-11-04", 253.93)]


# ---------------------------------------------------------------------------
# the land account itself
# ---------------------------------------------------------------------------

def test_a_land_parcel_sold_at_tax_sale_is_confirmed_with_the_machine_reason():
    r = run(row_for(LAND, years=("2023", "2024")), served_map({LAND: page(LAND_ROWS)}))
    assert r.verdict == "confirmed" and r.evidence["reason"] == "sold_at_tax_sale"
    ev = r.evidence
    assert ev["delinquent_by_year"] == {"2024": 116.93, "2023": 253.93} and ev["total_delinquent"] == 370.86
    assert ev["sold_at_tax_sale_years"] == [2024, 2023] and ev["sold_at_tax_sale_on"] == ["2024-11-04"]


def test_a_sold_year_without_an_amount_is_never_read_as_paid_or_stale():
    """The hazard: the sold rows carry no amount, so nothing counts as owed, and the 2025 bill that
    was paid late on the same land parcel made v3 say `stale` (suppressing a tax-sale account)."""
    rows = [(n, y, ident, status, paid, "$0.00" if status.startswith("Sold") else amt)
            for n, y, ident, status, paid, amt in LAND_ROWS]
    r = run(row_for(LAND, years=("2023", "2024")), served_map({LAND: page(rows)}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "sold_at_tax_sale")
    assert r.evidence["sold_at_tax_sale_years"] == [2024, 2023]


def test_a_sold_year_is_skipped_by_the_paid_checks():
    """A year with both a Paid row and a Sold row is not judged on the Paid row."""
    rows = [("1", 2025, LAND, "Paid", "12/01/25", "$40.00"), ("2", 2024, LAND, "Paid", "12/01/24", "$40.00"),
            ("3", 2024, LAND, "Sold at Tax Sale", "11/04/25", "$0.00")]
    r = run(row_for(LAND, years=("2024",)), served_map({LAND: page(rows)}))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "sold_at_tax_sale")


def test_an_old_sale_followed_by_years_paid_on_time_is_still_refuted():
    """A sale of the 2017 levy, every later year paid on time: the sale is history (outside the
    recent levies), the current claim is judged on the later bills as before."""
    rows = [("a", 2025, LAND, "Paid", "12/01/25", "$40.00"), ("b", 2024, LAND, "Paid", "12/01/24", "$40.00"),
            ("c", 2018, LAND, "Paid", "12/01/19", "$40.00"),
            ("d", 2017, LAND, "Sold at Tax Sale", "12/15/18", "$170.97")]
    r = run(row_for(LAND, years=("2025",)), served_map({LAND: page(rows)}))
    assert r.verdict == "refuted" and r.evidence["sold_at_tax_sale_years"] == [2017]
    assert "reason" not in r.evidence


# ---------------------------------------------------------------------------
# the manufactured-home account and its land
# ---------------------------------------------------------------------------

def test_parent_ident():
    assert q.parent_ident(HOME) == LAND
    assert q.parent_ident(LAND) is None and q.parent_ident("072-00-00-052 000") is None
    assert q.parent_ident(None) is None


def test_the_home_account_is_confirmed_and_the_sold_land_is_surfaced():
    """229 Euphra Dr shape: unpaid 2023-2025 on the home account, the land beneath sold at tax sale."""
    f = served_map({HOME: page(HOME_ROWS), LAND: page(LAND_ROWS + HOME_ROWS)})
    r = run(row_for(HOME, years=("2023", "2024", "2025")), f)
    assert r.verdict == "confirmed" and r.evidence["reason"] == "sold_at_tax_sale"
    assert r.evidence["total_delinquent"] == 2405.15 and r.evidence["years_delinquent"] == 3
    rel = r.evidence["related_account"]
    assert rel["map_number"] == LAND and rel["sold_at_tax_sale_years"] == [2024, 2023]
    assert rel["sold_at_tax_sale_on"] == ["2024-11-04"]
    assert rel["delinquent_by_year"] == {"2024": 116.93, "2023": 253.93}


def test_a_home_account_paid_up_beside_a_sold_land_is_unconfirmed_not_refuted():
    paid_home = [("h5", 2025, HOME, "Paid", "01/10/26", "$290.82"), ("h4", 2024, HOME, "Paid", "01/10/25", "$290.82")]
    f = served_map({HOME: page(paid_home), LAND: page(LAND_ROWS + paid_home)})
    r = run(row_for(HOME, years=("2025",)), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "sold_at_tax_sale")
    assert r.evidence["related_account"]["sold_at_tax_sale_years"] == [2024, 2023]


def test_a_home_account_beside_a_land_that_was_not_sold_is_judged_as_before():
    paid_home = [("h5", 2025, HOME, "Paid", "01/10/26", "$290.82"), ("h4", 2024, HOME, "Paid", "01/10/25", "$290.82")]
    land_ok = [("l5", 2025, LAND, "Paid", "01/10/26", "$41.27"), ("l4", 2024, LAND, "Paid", "01/10/25", "$41.27")]
    f = served_map({HOME: page(paid_home), LAND: page(land_ok + paid_home)})
    r = run(row_for(HOME, years=("2025",)), f)
    assert r.verdict == "refuted" and "reason" not in r.evidence
    assert r.evidence["related_account"]["map_number"] == LAND


def test_a_failed_read_of_the_land_account_never_changes_the_verdict():
    f = served_map({HOME: page(HOME_ROWS)})          # no recording for the land search: LookupError
    r = run(row_for(HOME, years=("2025",)), f)
    assert r.verdict == "confirmed" and "related_account" not in r.evidence and "reason" not in r.evidence


def test_the_public_evidence_has_no_names_or_addresses():
    f = served_map({HOME: page(HOME_ROWS), LAND: page(LAND_ROWS + HOME_ROWS)})
    blob = json.dumps(run(row_for(HOME, years=("2025",), owner_name="TESTOWNER11 PAT"), f).to_dict()).upper()
    for tok in ("TESTOWNER", "100 TEST RD"):
        assert tok not in blob


# ---------------------------------------------------------------------------
# Cherokee is reachable: its numeric sub-account parcels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pid,want", [
    ("0520000013010001", "052-00-00-013.010.001"),          # 16 digits: a sub-account (v3 searched the digits)
    ("0520000013010", "052-00-00-013.010"),                  # 13 digits: re-dashed as before
    ("052-00-00-013.010.001", "052-00-00-013.010.001"),      # already dashed
])
def test_cherokee_numeric_parcels_are_redashed(pid, want):
    assert q.board_parcel({"parcel_id": pid}, "Cherokee") == want


def test_a_sixteen_digit_parcel_of_another_county_is_left_alone():
    assert q.board_parcel({"parcel_id": "0520000013010001"}, "Union") == "0520000013010001"


def test_a_cherokee_row_with_only_a_numeric_sub_account_parcel_is_found():
    row = {"state": "SC", "county": "Cherokee", "listing_type": "tax_sale", "parcel_id": "0520000013010001",
           "street_address": "100 TEST RD", "source": "counties_sc.sc_public_index_lis_pendens", "raw": {}}
    r = run(row, served_map({"052-00-00-013.010.001": page(
        [(n, y, "052-00-00-013.010.001", s, p, a) for n, y, _i, s, p, a in HOME_ROWS]),
        "052-00-00-013.010": page([])}))
    assert r.verdict == "confirmed" and r.evidence["board_parcel"] == "052-00-00-013.010.001"

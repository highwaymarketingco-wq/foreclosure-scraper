"""tax_lien_buncombe v6 (2026-10-08): the three defects an independent audit of 160 ledger rows
against the live tax.buncombenc.gov found, each test failing on v5.

Fixtures are HAND-WRITTEN in the site's markup (the shapes of tests/
test_verification_tax_lien_recheck_defects.py): made-up parcel numbers (00000003xx), made-up
addresses, one placeholder owner. No page here is a capture of a real parcel.

  1 A levy year that is not late yet is never a late year, See Legal or not (41 ledger rows said
    "2+ late years" from a See Legal 2026 bill beside one late year).
  2 A See Legal bill whose own Transactions table shows it paid off is paid (See Legal on
    2011-2013 bills, a 2014 payment bringing each to $0: confirmed with 3 late years and $0).
  3 A PIN whose page names a different house number on the row's own street does not bind a
    confirmed answer (915 checked against 909 on the same road).
  + balance_under_25: a marker on a confirmed balance under $25, not a verdict.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from urllib.parse import quote_plus

import pytest

from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tb

TODAY = date(2026, 10, 8)          # the 2026 levy is not late until 2027-01-06
OWNER = "JO EXAMPLE"               # placeholder


# ===========================================================================
# the site's markup, hand-written
# ===========================================================================

def _card(bill: str, amount: str | None, value: str) -> str:
    amt = ('<div class="text-danger fw-semibold">See Legal</div>' if amount is None
           else f'<div class="fw-semibold">{amount}</div>')
    badge = '<span class="badge bg-warning">See Legal</span>' if amount is None else ""
    return f'''<div class="col-12"><div class="card history-card shadow-sm">
<div class="card-header bg-light"><div class="d-flex justify-content-between align-items-center">
<h3 class="h6 mb-0"><a href="/Bill/Details/{bill}">{bill}</a></h3>{badge}</div></div>
<div class="card-body"><div class="row"><div class="col-6"><small class="text-muted d-block">Owner</small>
<div class="fw-semibold"> {OWNER}</div></div><div class="col-6 text-end">
<small class="text-muted d-block">Value</small><div class="fw-semibold">{value}</div></div></div>
<div class="row mt-2"><div class="col-6"><small class="text-muted d-block">PIN</small><div>000000000000000</div></div>
<div class="col-6 text-end"><small class="text-muted d-block">Amount Due</small>{amt}</div></div></div></div></div>'''


def parcel_html(bills, *, situs, value="$90,050") -> str:
    """bills: [(bill number, "$1.00" | None)]; None = Amount Due "See Legal", listed as "Payment
    Unavailable" in Current Bills like the real page."""
    cards = "".join(_card(b, a, value) for b, a in bills)
    cur = "".join(f'<div class="row my-4"><div class="col-6 fw-bold"><div><a href="/Bill/Details/{b}">{b}</a></div></div>'
                  f'<div class="col-6 text-end"><span class="text-danger"><b>Payment Unavailable</b></span></div></div>'
                  for b, a in bills if a is None)
    return (f'<html><body><h1 class="card-title h2 mb-2">{situs}</h1>'
            f'<section class="amount-due my-4"><div class="row"><h2>Current Bills</h2></div>'
            f'<div class="row"><div class="col-12">{cur}</div></div></section>'
            f'<div class="d-block d-md-none"><div class="row g-3">{cards}</div></div></body></html>')


def bill_html(rows, *, legal=False) -> str:
    """rows: [(type, 'm/d/Y', tax, late fee, interest, cost)]. A bill in legal collection shows a
    red bar, no number, in its Total column (on every row, paid or not)."""
    def money(v):
        return f"(${abs(v):,.2f})" if v < 0 else f"${v:,.2f}"

    def total(a):
        return '<div class="bg-danger d-flex flex-fill">&nbsp;</div>' if legal else money(a)
    trs = "".join(f"<tr><td>{t}</td><td>{d}</td><td></td><td>{money(a)}</td><td>{money(b)}</td>"
                  f"<td>{money(c)}</td><td>{money(e)}</td><td>{total(a + b + c + e)}</td></tr>"
                  for t, d, a, b, c, e in rows)
    return (f'<html><body><section class="transactions my-4"><table><thead><tr><th>Type</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></section></body></html>')


def search_html(found) -> str:
    cards = "".join(f'<div class="col"><div class="card shadow mb-3"><div class="card-body">'
                    f'<h6 class="card-subtitle mb-1">\n  {pin}\n</h6>'
                    f'<a href="/Parcel/Details/{pin}?Query=x"><h4 class="card-title text-uppercase">{a}</h4></a>'
                    f'</div></div></div>' for pin, a in found)
    return f'<html><body><div class="search-results row">{cards}</div></body></html>'


def P(acct: str) -> str:
    return f"{tb.BASE}/Parcel/Details/{acct}00000"


def B(acct: str, year: int) -> str:
    return f"{tb.BASE}/Bill/Details/{acct}-{year}-{year}-0000-00"


def bn(acct: str, year: int) -> str:
    return f"{acct}-{year}-{year}-0000-00"


def S(query: str) -> str:
    return tb.SEARCH_URL.format(q=quote_plus(query))


def on_time(year: int, tax: float = 500.0) -> str:
    return bill_html([("BILL", f"7/20/{year}", tax, 0, 0, 0), ("PAYMENT", f"11/1/{year}", -tax, 0, 0, 0)])


def unpaid(year: int, tax: float, interest: float = 0.0) -> str:
    return bill_html([("BILL", f"7/20/{year}", tax, 0, interest, 0)], legal=True)


def row(acct: str, **kw) -> dict:
    r = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "parcel_id": acct,
         "raw": {"tax_owed": {"balance": 1.0, "year": 2025}}}
    r.update(kw)
    return r


def run(r: dict, pages: dict, today: date = TODAY):
    f = ReplayFetcher(pages)
    return asyncio.run(tb.verify(r, f, today=today)), f


# ===========================================================================
# 1. a levy year that is not late yet is never a late year, See Legal or not
# ===========================================================================

A1 = "0000000301"


def _legal_2026_and_2025():
    """The shape of the 41 rows: the parcel is in legal collection, so its CURRENT 2026 bill reads
    See Legal beside the one late year, 2025."""
    return {P(A1): parcel_html([(bn(A1, 2026), None), (bn(A1, 2025), None), (bn(A1, 2024), "$0.00")],
                               situs="31 EXAMPLE RIDGE RD"),
            B(A1, 2026): unpaid(2026, 410.00),
            B(A1, 2025): unpaid(2025, 280.00, 11.23)}


def test_a_see_legal_bill_of_the_current_levy_is_not_a_second_late_year():
    r, _ = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), _legal_2026_and_2025())
    ev = r.evidence
    assert r.verdict == "confirmed"
    assert ev["years_delinquent"] == 1                       # v5: 2
    assert ev["delinquent_by_year"] == {"2025": 291.23}
    assert ev["total_delinquent"] == 291.23 and ev["total_delinquent_is_floor"] is False
    assert ev["not_yet_delinquent_due"] == {"2026": 410.0}   # kept as evidence, not as a late year
    assert ev["see_legal_years"] == [2026, 2025]


def test_the_same_bill_is_a_late_year_from_january_6():
    r, _ = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), _legal_2026_and_2025(),
               today=date(2027, 1, 6))
    assert r.verdict == "confirmed" and r.evidence["years_delinquent"] == 2
    assert r.evidence["delinquent_by_year"] == {"2026": 410.0, "2025": 291.23}
    assert r.evidence["not_yet_delinquent_due"] == {}


def test_a_numeric_current_bill_beside_legal_years_is_kept_apart_too():
    pages = {P(A1): parcel_html([(bn(A1, 2026), "$188.00"), (bn(A1, 2025), None), (bn(A1, 2024), None)],
                                situs="31 EXAMPLE RIDGE RD"),
             B(A1, 2025): unpaid(2025, 300.00), B(A1, 2024): unpaid(2024, 250.00)}
    ev = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), pages)[0].evidence
    assert ev["years_delinquent"] == 2
    assert ev["delinquent_by_year"] == {"2025": 300.0, "2024": 250.0} and ev["total_delinquent"] == 550.0
    assert ev["not_yet_delinquent_due"] == {"2026": 188.0}


def test_a_not_yet_late_see_legal_bill_alone_is_not_a_delinquency():
    """Nothing late: the claimed 2025 levy was paid on time and only the 2026 bill (not late until
    2027-01-06) reads See Legal. v5 confirmed it; the claim is refuted, the amount kept."""
    pages = {P(A1): parcel_html([(bn(A1, 2026), None), (bn(A1, 2025), "$0.00"), (bn(A1, 2024), "$0.00")],
                                situs="31 EXAMPLE RIDGE RD"),
             B(A1, 2026): unpaid(2026, 410.00), B(A1, 2025): on_time(2025), B(A1, 2024): on_time(2024)}
    r, _ = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), pages)
    ev = r.evidence
    assert r.verdict == "refuted"
    assert ev["years_delinquent"] == 0 and ev["delinquent_by_year"] == {} and ev["total_delinquent"] == 0
    assert ev["not_yet_delinquent_due"] == {"2026": 410.0} and ev["see_legal_years"] == [2026]
    assert ev["current_claim_basis"] == "claimed_years_on_time"


# ===========================================================================
# 2. a See Legal bill its own transactions show paid off is paid
# ===========================================================================

A2 = "0000000302"


def _paid_off_in_2014(year: int, tax: float, interest: float) -> str:
    """See Legal on the parcel page; the bill page: the BILL row and one 2014 PAYMENT of the same
    tax, interest and cost (the red bar stays in the Total column)."""
    return bill_html([("BILL", f"8/16/{year}", tax, 0, interest, 2.0),
                      ("PAYMENT", "5/6/2014", -tax, 0, -interest, -2.0)], legal=True)


def _old_legal_pages(acct: str, situs: str, *, y2025: str):
    bills = [(bn(acct, 2026), "$278.59"), (bn(acct, 2025), y2025), (bn(acct, 2024), "$0.00"),
             (bn(acct, 2013), None), (bn(acct, 2012), None), (bn(acct, 2011), None)]
    return {P(acct): parcel_html(bills, situs=situs),
            B(acct, 2013): _paid_off_in_2014(2013, 150.10, 12.40),
            B(acct, 2012): _paid_off_in_2014(2012, 146.00, 21.75),
            B(acct, 2011): _paid_off_in_2014(2011, 141.45, 30.97),
            B(acct, 2025): on_time(2025), B(acct, 2024): on_time(2024)}


def test_see_legal_bills_paid_off_by_a_later_payment_are_not_late_years():
    """v5: confirmed, 3 late years, total $0. Every See Legal bill is paid; the claimed 2025 levy
    was paid on time: refuted."""
    r, f = run(row(A2, street_address="6 EXAMPLE KIDS DR"),
               _old_legal_pages(A2, "6 EXAMPLE KIDS DR", y2025="$0.00"))
    ev = r.evidence
    assert r.verdict == "refuted"
    assert ev["see_legal_paid_years"] == [2013, 2012, 2011] and ev["see_legal_years"] == []
    assert ev["years_delinquent"] == 0 and ev["total_delinquent"] == 0 and ev["delinquent_by_year"] == {}
    assert ev["not_yet_delinquent_due"] == {"2026": 278.59}
    assert all(b["remaining"] == 0.0 and b["paid"] is True for b in ev["see_legal_bills"])
    assert all(B(A2, y) in f.asked for y in (2011, 2012, 2013))


def test_a_paid_off_see_legal_bill_beside_a_real_late_year_counts_only_the_real_one():
    r, _ = run(row(A2, street_address="6 EXAMPLE KIDS DR"),
               _old_legal_pages(A2, "6 EXAMPLE KIDS DR", y2025="$237.65"))
    ev = r.evidence
    assert r.verdict == "confirmed"
    assert ev["years_delinquent"] == 1                        # v5: 4
    assert ev["delinquent_by_year"] == {"2025": 237.65} and ev["total_delinquent"] == 237.65
    assert ev["total_delinquent_is_floor"] is False           # v5: True (a $0 See Legal bill)


def test_legal_bill_paid_reads_the_transactions():
    paid = tb.parse_bill_page(_paid_off_in_2014(2011, 141.45, 30.97))
    assert tb.remaining_balance(paid) == 0.0 and tb.legal_bill_paid(paid) is True
    part = tb.parse_bill_page(bill_html([("BILL", "8/16/2011", 141.45, 0, 30.97, 2.0),
                                         ("PAYMENT", "5/6/2014", -141.45, 0, 0, -2.0)], legal=True))
    assert tb.legal_bill_paid(part) is False                  # the interest is still owed
    nothing_paid = tb.parse_bill_page(bill_html([("BILL", "8/16/2011", 0, 0, 0, 0)], legal=True))
    assert tb.remaining_balance(nothing_paid) == 0.0 and tb.legal_bill_paid(nothing_paid) is False
    released = tb.parse_bill_page(bill_html([("BILL", "7/26/2025", 324.92, 0, 28.57, 4.76),
                                             ("PAYMENT", "10/2/2026", -322.46, 0, -28.57, -4.76),
                                             ("PAYMENTRELEASE", "10/9/2026", -2.46, 0, 0, 0)]))
    assert tb.legal_bill_paid(released) is True


def test_a_see_legal_bill_not_shown_paid_stays_unpaid():
    """Guards (v5 agreed): part-paid, unreadable, or zero with no payment row: still a late year."""
    bills = [(bn(A2, 2026), "$278.59"), (bn(A2, 2025), "$0.00"), (bn(A2, 2013), None),
             (bn(A2, 2012), None), (bn(A2, 2011), None)]
    pages = {P(A2): parcel_html(bills, situs="6 EXAMPLE KIDS DR"),
             B(A2, 2013): bill_html([("BILL", "8/16/2013", 150.10, 0, 12.40, 2.0),
                                     ("PAYMENT", "5/6/2014", -100.00, 0, 0, 0)], legal=True),
             B(A2, 2012): bill_html([("BILL", "8/16/2012", 0, 0, 0, 0)], legal=True)}
    # (the 2011 bill page is not served: unreadable)
    r, _ = run(row(A2, street_address="6 EXAMPLE KIDS DR"), pages)
    ev = r.evidence
    assert r.verdict == "confirmed" and ev["years_delinquent"] == 3
    assert ev["delinquent_by_year"] == {"2013": 64.5} and ev["total_delinquent_is_floor"] is True
    assert "see_legal_paid_years" not in ev and ev["balance_under_25"] is False


# ===========================================================================
# 3. another house number on the row's own street never binds a confirmed answer
# ===========================================================================

OWN, ADDR = "0000000303", "0000000304"          # the row's PIN (909) and the parcel of 915
ROW_ADDR = "915 EXAMPLE HILL RD"


def _neighbors(*, search=None, addr_2025="$0.00"):
    pages = {P(OWN): parcel_html([(bn(OWN, 2026), "$300.00"), (bn(OWN, 2025), "$11.32"),
                                  (bn(OWN, 2024), "$0.00")], situs="909 EXAMPLE HILL RD", value="$30,900"),
             P(ADDR): parcel_html([(bn(ADDR, 2026), "$250.00"), (bn(ADDR, 2025), addr_2025),
                                   (bn(ADDR, 2024), "$0.00")], situs="915 EXAMPLE HILL RD", value="$41,000"),
             B(ADDR, 2025): on_time(2025), B(ADDR, 2024): on_time(2024)}
    found = [(f"{ADDR}00000", "915 EXAMPLE HILL RD, BLACK MOUNTAIN NC 28711")] if search is None else search
    pages[S("915 EXAMPLE HILL")] = search_html(found)
    return pages


def test_without_proof_which_parcel_is_the_rows_the_neighbors_balance_is_ambiguous():
    """v5: confirmed from 909's $11.32. Nothing proves the row's PIN is wrong or right."""
    r, f = run(row(OWN, street_address=ROW_ADDR), _neighbors())
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["address_pins"] == [f"{ADDR}00000"] and r.evidence["address_relation"] == "conflict"
    assert r.evidence["delinquent_by_year"] == {"2025": 11.32}           # the own PIN's balance, kept
    assert S("915 EXAMPLE HILL") in f.asked


def test_a_resolver_attached_pin_is_followed_to_the_parcel_of_the_address():
    """The row's parcel id came from a resolver: the address decides, and 915's own parcel paid its
    2025 levy on time. v5: confirmed from the neighbor's balance."""
    r, _ = run(row(OWN, street_address=ROW_ADDR,
                   raw={"tax_owed": {"balance": 1.0, "year": 2025}, "parcel_from_address": {"pin": OWN}}),
               _neighbors())
    ev = r.evidence
    assert r.verdict == "refuted"
    assert ev["pin"] == f"{ADDR}00000" and ev["followed_from_pin"] == f"{OWN}00000"
    assert ev["address_binding"] == "followed" and ev["followed_because"] == "parcel_resolved"


def test_a_followed_parcel_that_owes_too_is_confirmed_on_its_own_balance():
    r, _ = run(row(OWN, street_address=ROW_ADDR, raw={"parcel_from_address": {"pin": OWN}}),
               _neighbors(addr_2025="$10.22"))
    ev = r.evidence
    assert r.verdict == "confirmed" and ev["pin"] == f"{ADDR}00000"
    assert ev["delinquent_by_year"] == {"2025": 10.22} and ev["followed_from_pin"] == f"{OWN}00000"


def test_the_rows_own_parcel_decides_when_the_boards_value_is_its_county_value():
    r, _ = run(row(OWN, street_address=ROW_ADDR, assessed_value=30900), _neighbors())
    ev = r.evidence
    assert r.verdict == "confirmed" and ev["pin"] == f"{OWN}00000"
    assert ev["address_binding"] == "own_parcel_value_identity" and ev["address_account_pin"] == f"{ADDR}00000"


def test_no_parcel_carries_the_address_is_address_not_found():
    r, _ = run(row(OWN, street_address=ROW_ADDR), _neighbors(search=[]))
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")


def test_the_pin_itself_carrying_the_address_binds():
    r, _ = run(row(OWN, street_address=ROW_ADDR),
               _neighbors(search=[(f"{OWN}00000", "915 EXAMPLE HILL RD, BLACK MOUNTAIN NC 28711")]))
    assert r.verdict == "confirmed" and r.evidence["address_binding"] == "address_search"


@pytest.mark.parametrize("situs", ["12 OTHER LN", "EXAMPLE HILL RD", "915 EXAMPLE HILL RD UNINCORPORATED"])
def test_another_street_or_no_number_or_the_same_number_needs_no_search(situs):
    """Guards (unchanged from v5): only another house number on the row's own street binds."""
    pages = {P(OWN): parcel_html([(bn(OWN, 2025), "$11.32")], situs=situs)}
    r, f = run(row(OWN, street_address=ROW_ADDR), pages)
    assert r.verdict == "confirmed" and len(f.asked) == 1


@pytest.mark.parametrize("a,b,other", [
    ("915 EXAMPLE HILL RD", "909 EXAMPLE HILL RD", True),
    ("915 EXAMPLE HILL ROAD", "909 EXAMPLE HILL RD, BLACK MOUNTAIN NC 28711", True),
    ("915 EXAMPLE HILL RD", "915 EXAMPLE HILL RD UNINCORPORATED", False),
    ("915 EXAMPLE HILL RD", "12 OTHER LN", False),
    ("915 EXAMPLE HILL RD", "EXAMPLE HILL RD", False),
    ("EXAMPLE HILL RD", "909 EXAMPLE HILL RD", False),
    ("915 EXAMPLE HILL RD", "99999 EXAMPLE HILL RD", False),         # a placeholder number
])
def test_other_number_same_street(a, b, other):
    assert tc.other_number_same_street(a, b) is other


# ===========================================================================
# balance_under_25, the version
# ===========================================================================

@pytest.mark.parametrize("amount,under", [("$11.32", True), ("$24.99", True), ("$25.00", False), ("$300.00", False)])
def test_balance_under_25_marks_a_trivial_confirmed_balance(amount, under):
    pages = {P(A1): parcel_html([(bn(A1, 2025), amount)], situs="31 EXAMPLE RIDGE RD")}
    r, _ = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), pages)
    assert r.verdict == "confirmed" and r.evidence["balance_under_25"] is under


def test_balance_under_25_is_never_claimed_for_a_balance_of_unknown_size():
    pages = {P(A1): parcel_html([(bn(A1, 2025), None)], situs="31 EXAMPLE RIDGE RD")}   # bill page unread
    ev = run(row(A1, street_address="31 EXAMPLE RIDGE RD"), pages)[0].evidence
    assert ev["total_delinquent"] == 0 and ev["total_delinquent_is_floor"] is True
    assert ev["balance_under_25"] is False


def test_the_version_bump_makes_every_v5_entry_due_again():
    assert tb.VERSION == "v6"
    v = next(x for x in discover() if x.name == "tax_lien_buncombe")
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    entry = {"latest": {"verifier": "tax_lien_buncombe", "verifier_version": "v5", "verdict": "confirmed",
                        "checked_at": "2026-10-08T11:00:00Z"}}
    assert L.is_due(entry, v, now) == (True, "version")

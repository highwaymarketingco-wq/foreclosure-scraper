"""The tax_lien defects found by the 2026-10-06 live recheck of all 103 `stale` verdicts (91 held,
8 were wrong, 4 weak), each pinned on a REAL shape and each failing on the pre-fix verifiers
(tax_lien_buncombe v3, tax_lien_ptscloud v1, tax_lien_qpaybill v1).

Fixtures (tests/fixtures/verification/, captured live 2026-10-06; owner names replaced by made-up
ones, addresses and parcel ids are public record):
  buncombe_tax_recheck.json.gz     {url: page}: tax.buncombenc.gov parcel pages, bill pages and
                                   address-search pages of the real cases below
  tax_lien_ptscloud_recheck.json.gz  bcpwa.ncptscloud.com (Henderson) search + bill answers
  tax_lien_qpaybill_recheck.json.gz  qPayBill grids (Union, Calhoun): forms, criteria, searches
Pages the real sweep never met (a payment before the interest date with interest charged, an
unpaid rollback bill) are built from the same markup by the helpers below.

DEFECTS (numbers as in the task):
  1 See Legal blind spot   2 address -> parcel binding   3 lateness from payment dates, rollback
  bills   4 evidence: interest counted once, every bill kept, paid_on never None
"""
from __future__ import annotations

import asyncio
import gzip
import json
import re
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import _tax_common as tc
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as tb
from foreclosure_scraper.verification.verifiers import tax_lien_ptscloud as tp
from foreclosure_scraper.verification.verifiers import tax_lien_qpaybill as tq

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 6)


def _gz(name):
    return json.loads(gzip.decompress((FIX / name).read_bytes()))


BUNC = _gz("buncombe_tax_recheck.json.gz")
PTS = _gz("tax_lien_ptscloud_recheck.json.gz")
QPB = _gz("tax_lien_qpaybill_recheck.json.gz")


# ===========================================================================
# Buncombe helpers: the real markup, rebuilt for shapes the sweep did not meet
# ===========================================================================

def _card(bill: str, amount: str | None, legal: bool) -> str:
    badge = '<span class="badge bg-warning">See Legal</span>' if legal else ""
    amt = ('<div class="text-danger fw-semibold">See Legal</div>' if legal
           else f'<div class="fw-semibold">{amount}</div>')
    return f'''<div class="col-12"><div class="card history-card shadow-sm">
<div class="card-header bg-light"><div class="d-flex justify-content-between align-items-center">
<h3 class="h6 mb-0"><a href="/Bill/Details/{bill}">{bill}</a></h3>{badge}</div></div>
<div class="card-body"><div class="row"><div class="col-6"><small class="text-muted d-block">Owner</small>
<div class="fw-semibold"> JO EXAMPLE</div></div><div class="col-6 text-end">
<small class="text-muted d-block">Value</small><div class="fw-semibold">$90,050</div></div></div>
<div class="row mt-2"><div class="col-6"><small class="text-muted d-block">PIN</small><div>000000000000000</div></div>
<div class="col-6 text-end"><small class="text-muted d-block">Amount Due</small>{amt}</div></div></div></div></div>'''


def parcel_html(bills, *, situs="1 EXAMPLE RD", inactive=False) -> str:
    """bills: [(bill number, "$1.00" | None)]; None = Amount Due "See Legal" (and, like the real
    page, "Payment Unavailable" in the Current Bills list)."""
    banner = ('<div class="alert alert-warning"><strong>You are viewing an inactive parcel.</strong></div>'
              if inactive else "")
    cards = "".join(_card(b, a, a is None) for b, a in bills)
    cur = "".join(f'<div class="row my-4"><div class="col-6 fw-bold"><div><a href="/Bill/Details/{b}">{b}</a></div></div>'
                  f'<div class="col-6 text-end"><span class="text-danger"><b>Payment Unavailable</b></span></div></div>'
                  for b, a in bills if a is None)
    return (f'<html><body>{banner}<h1 class="card-title h2 mb-2">{situs}</h1>'
            f'<section class="amount-due my-4"><div class="row"><h2>Current Bills</h2></div>'
            f'<div class="row"><div class="col-12">{cur}</div></div></section>'
            f'<div class="d-block d-md-none"><div class="row g-3">{cards}</div></div></body></html>')


def bill_html(rows) -> str:
    """rows: [(type, 'm/d/Y', tax, late fee, interest, cost)]."""
    def money(v):
        return f"(${abs(v):,.2f})" if v < 0 else f"${v:,.2f}"
    trs = "".join(f"<tr><td>{t}</td><td>{d}</td><td></td><td>{money(a)}</td><td>{money(b)}</td>"
                  f"<td>{money(c)}</td><td>{money(e)}</td><td>{money(a + b + c + e)}</td></tr>"
                  for t, d, a, b, c, e in rows)
    return (f'<html><body><section class="transactions my-4"><table><thead><tr><th>Type</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></section></body></html>')


def search_html(found) -> str:
    """found: [(pin, address)] parcel cards of an address search."""
    cards = "".join(f'<div class="col"><div class="card shadow mb-3"><div class="card-body">'
                    f'<h6 class="card-subtitle mb-1">\n  {pin}\n</h6>'
                    f'<a href="/Parcel/Details/{pin}?Query=x"><h4 class="card-title text-uppercase">{a}</h4></a>'
                    f'</div></div></div>' for pin, a in found)
    return f'<html><body><div class="search-results row">{cards}</div></body></html>'


def brow(parcel, **kw):
    r = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "parcel_id": parcel, "raw": {}}
    r.update(kw)
    return r


def brun(row, pages, today=TODAY):
    f = ReplayFetcher(pages)
    return asyncio.run(tb.verify(row, f, today=today)), f


# ===========================================================================
# 1. See Legal: an unpaid balance of unknown size
# ===========================================================================

def test_the_discovery_bills_of_8792725038_are_all_read_and_see_legal_is_not_dropped():
    """PIN 8792725038 (inactive; 3 Tony Lunsford Dr on the board). Four discovery bills billed
    2025-02-19 for tax years 2021-2024 beside the regular bills: the old parser kept ONE bill per
    levy year (the first of year 2025) and skipped every card whose Amount Due is text."""
    page = tb.parse_parcel_page(BUNC[f"{tb.BASE}/Parcel/Details/879272503800000"])
    bills = {b["bill"]: b for b in page["bills"]}
    assert len(page["bills"]) == len(bills) == 20
    disc = {b["year"]: b for b in page["bills"] if not b["regular"]}
    assert sorted(disc) == [2021, 2022, 2023, 2024]
    assert all(b["levy_year"] == 2025 and b["seq"] == "0070" for b in disc.values())
    assert [y for y, b in disc.items() if b["see_legal"]] == [2024, 2023, 2022]
    assert disc[2021]["see_legal"] is False and disc[2021]["amount_due"] == 0.0     # paid 2025-06-18
    assert page["inactive"] is True and page["situs"] == "242 P GIBBS RD UNINCORPORATED"
    assert [b["year"] for b in page["bills"] if b["see_legal"]] == [2026, 2024, 2023, 2022]


def test_8792725038_is_confirmed_not_stale_and_its_balances_are_read():
    """v3 said stale: it judged from the interest on the paid 2021 discovery bill. Three bills
    are unpaid in legal collection: 89.41 (part-paid 2022), 380.29 (2023), 364.36 (2024)."""
    row = brow("8792725038", street_address="3 TONY LUNSFORD DR")
    r, f = brun(row, BUNC)
    assert r.verdict == "confirmed"
    ev = r.evidence
    assert ev["see_legal_years"] == [2026, 2024, 2023, 2022]
    rem = {b["year"]: b["remaining"] for b in ev["see_legal_bills"]}
    assert rem == {2026: 52.09, 2024: 364.36, 2023: 380.29, 2022: 89.41}
    assert ev["total_delinquent"] == 834.06 and ev["total_delinquent_is_floor"] is False
    assert ev["not_yet_delinquent_due"] == {"2026": 52.09}      # the current levy, owed not delinquent
    assert ev["years_delinquent"] == 4 and ev["under_500"] is False
    assert ev["pin_inactive"] is True and ev["address_relation"] == "conflict"


def test_9686053926_is_confirmed_not_refuted_see_legal_on_2024_and_2015():
    """The wrongly REFUTED one (ledger address 29 Ravenwood Dr, county 3 Eastcrest Dr): the
    verifier looked at the 2025 bill (paid on time) only. The 2024 bill and a 2015 bill are in
    legal collection."""
    pages = {f"{tb.BASE}/Parcel/Details/968605392600000":
             gzip.decompress((FIX / "buncombe_tax_Parcel_Details_968605392600000.html.gz").read_bytes()).decode(),
             f"{tb.BASE}/Bill/Details/0000667232-2025-2025-0000-00":
             gzip.decompress((FIX / "buncombe_tax_Bill_Details_0000667232-2025-2025-0000-00.html.gz").read_bytes()).decode()}
    r, _ = brun(brow("9686053926", street_address="29 RAVENWOOD DR",
                     raw={"tax_owed": {"balance": 900.0, "year": 2025}}), pages)
    assert r.verdict == "confirmed"
    assert r.evidence["see_legal_years"] == [2024, 2015]
    assert r.evidence["total_delinquent_is_floor"] is True     # the bill pages were not served: size unknown


@pytest.mark.parametrize("legal_year", [2015, 2023, 2024])
def test_never_stale_or_refuted_while_a_see_legal_bill_is_unpaid(legal_year):
    """Whatever year the See Legal bill is for, and however clean the claimed year is."""
    bills = [("0000000001-2026-2026-0000-00", "$100.00"), ("0000000001-2025-2025-0000-00", "$0.00"),
             ("0000000001-2024-2024-0000-00", "$0.00"), ("0000000001-2023-2023-0000-00", "$0.00"),
             ("0000000001-2015-2015-0000-00", "$0.00")]
    bills = [(b, None if f"-{legal_year}-{legal_year}-" in b else a) for b, a in bills]
    pages = {f"{tb.BASE}/Parcel/Details/000000000100000": parcel_html(bills),
             f"{tb.BASE}/Bill/Details/0000000001-2025-2025-0000-00":
                 bill_html([("BILL", "7/26/2025", 500, 0, 0, 0), ("PAYMENT", "11/1/2025", -500, 0, 0, 0)])}
    r, _ = brun(brow("0000000001", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)
    assert r.verdict == "confirmed" and r.evidence["see_legal_years"] == [legal_year]


def test_a_card_that_says_payment_unavailable_in_the_current_bills_list_is_legal_even_if_its_field_is_odd():
    html = parcel_html([("0000000002-2025-2025-0000-00", None), ("0000000002-2024-2024-0000-00", "$0.00")])
    html = html.replace('<div class="text-danger fw-semibold">See Legal</div>', '<div class="fw-semibold"></div>')
    page = tb.parse_parcel_page(html)
    assert [b["see_legal"] for b in page["bills"]] == [True, False]


def test_see_legal_text_nobody_parsed_never_decides():
    """A layout change: the words are on the page but no card carries them in a readable shape."""
    html = parcel_html([("0000000003-2025-2025-0000-00", "$0.00"), ("0000000003-2024-2024-0000-00", "$0.00")])
    html = html.replace("</body>", "<p>See Legal</p></body>")
    r, _ = brun(brow("0000000003"), {f"{tb.BASE}/Parcel/Details/000000000300000": html})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "see_legal_unparsed"


def test_remaining_balance_reads_the_transactions_table():
    bp = tb.parse_bill_page(bill_html([("BILL", "2/19/2025", 291.53, 0, 78.43, 4.76),
                                       ("PAYMENT", "6/18/2025", -216.07, 0, -69.24, 0)]))
    assert tb.remaining_balance(bp) == 89.41
    assert tb.remaining_balance({"transactions": []}) is None


# ===========================================================================
# 2. address binding
# ===========================================================================

#: board address, board parcel -> the parcel that carries the address, its levy-2025 verdict
FOLLOWS = [
    # (2614 Old Fort Rd, whose PIN shows 2610 Old Fort Rd, is no longer followed to the neighbor's
    #  parcel: tests/test_verification_tax_lien_address_history.py)
    ("0710406959", "44 SKYLAND CIR", "973045193900000", "refuted"),        # county shows 99999 East St
    ("9605259489", "356 BEAVERDAM LOOP RD", "960525935900000", "stale"),   # inactive PIN
    ("9754697396", "7 ISLAND IN THE SKY TRL", "975469477200000", "refuted"),   # inactive; 78 Island... is another
]


@pytest.mark.parametrize("pid,addr,followed,verdict", FOLLOWS)
def test_a_pin_that_does_not_carry_the_address_is_followed_to_the_one_that_does(pid, addr, followed, verdict):
    """v3 judged the retired / other PIN: stale from ITS late payment. The address's own parcel
    decides (and, for 7 Island in the Sky Trl, the search also lists 78 Island in the Sky Trl,
    which is not the address)."""
    r, f = brun(brow(pid, street_address=addr), BUNC)
    assert r.verdict == verdict, r.evidence
    ev = r.evidence
    assert ev["pin"] == followed and ev["followed_from_pin"] == tb.pin_of(brow(pid))
    assert ev["address_binding"] == "followed"
    assert any("/Search/Results" in u for u in f.asked)


def test_the_followed_stale_counts_interest_once():
    r, _ = brun(brow("9605259489", street_address="356 BEAVERDAM LOOP RD"), BUNC)
    chk = r.evidence["bills_checked"][0]
    assert (chk["paid_late"], chk["interest_and_fees"], chk["paid_on"]) == (True, 36.45, "2026-05-20")


def test_a_page_whose_situs_matches_is_bound_without_a_search():
    pages = dict(BUNC)
    r, f = brun(brow("0646441256", street_address="2610 Old Fort Rd"), pages)
    assert r.verdict == "stale" and r.evidence["address_binding"] == "page_address"
    assert not any("/Search/" in u for u in f.asked)
    assert r.evidence["bills_checked"][0]["paid_on"] == "2026-09-29"


def test_an_inactive_pin_without_a_followable_address_is_unconfirmed_never_judged():
    page = BUNC[f"{tb.BASE}/Parcel/Details/960525948900000"]
    for row in (brow("9605259489"),                                         # no address on the row
                brow("9605259489", street_address="POND RD")):              # a road name is no address
        r, f = brun(row, {f"{tb.BASE}/Parcel/Details/960525948900000": page})
        assert r.verdict == "unconfirmed" and r.evidence["reason"] == "pin_inactive"
        assert not f.asked[1:]


def test_an_address_that_belongs_to_two_other_parcels_or_none_is_unconfirmed():
    url = f"{tb.BASE}/Parcel/Details/064644125600000"
    row = brow("0646441256", street_address="2614 OLD FORT RD")
    two = search_html([("111111111100000", "2614 OLD FORT RD, A NC"), ("222222222200000", "2614 OLD FORT RD, B NC")])
    r, _ = brun(row, {url: BUNC[url], f"{tb.BASE}/Search/Results?QueryType=Address&Query=2614+OLD+FORT": two})
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_parcel_mismatch")
    assert sorted(r.evidence["address_pins"]) == ["111111111100000", "222222222200000"]
    none = search_html([])
    r, _ = brun(row, {url: BUNC[url], f"{tb.BASE}/Search/Results?QueryType=Address&Query=2614+OLD+FORT": none})
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_not_found")    # v5
    r, _ = brun(row, {url: BUNC[url]})                                  # the search page cannot be fetched
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "address_search_failed")


def test_a_confirmed_answer_needs_no_binding_but_records_it():
    r, f = brun(brow("0646441256", street_address="2614 OLD FORT RD",
                     raw={"tax_owed": {"balance": 1.0, "year": 2026}}),
                {f"{tb.BASE}/Parcel/Details/064644125600000":
                 parcel_html([("0000000009-2025-2025-0000-00", "$55.00")], situs="2610 OLD FORT RD")})
    assert r.verdict == "confirmed" and r.evidence["address_relation"] == "conflict"
    assert len(f.asked) == 1


@pytest.mark.parametrize("a,b,rel", [
    ("2614 OLD FORT RD", "2610 OLD FORT RD", "conflict"),
    ("810 ROBINSON TERRACE", "807 ROBINSON TER", "conflict"),
    ("807 ROBINSON TERRACE", "807 ROBINSON TER", "match"),
    ("7 ISLAND IN THE SKY TRL", "78 ISLAND IN THE SKY TRL, WEAVERVILLE NC 28787", "conflict"),
    ("7 ISLAND IN THE SKY TRL", "7 ISLAND IN THE SKY TRL, WEAVERVILLE NC 28787", "match"),
    ("356 BEAVERDAM LOOP RD", "356 BEAVERDAM LOOP RD UNINCORPORATED", "match"),
    ("44 SKYLAND CIR", "99999 EAST ST", "unknown"),                    # a placeholder number
    ("844 RICE AVE EXT", "RICE AVE EXT UNION", "unknown"),            # no number
    ("000123 EXAMPLE DRIVE", "123 EXAMPLE DR", "match"),
    ("804, Trailwinds Drive, Oconee County, South Carolina, 29693, United States", "804 TRAILWINDS DR", "match"),
    ("100 MAIN ST", "100 MAIN AVE", "conflict"),
    ("POND RD", "POND RD", "unknown"),
])
def test_address_relation(a, b, rel):
    assert tc.address_relation(a, b) == rel


def test_address_query_is_the_number_and_the_street_name():
    assert tc.address_query("810 ROBINSON TERRACE") == "810 ROBINSON"
    assert tc.address_query("7 ISLAND IN THE SKY TRL") == "7 ISLAND IN THE SKY"
    assert tc.address_query("100 N MAIN ST") == "100 N MAIN"
    assert tc.address_query("POND RD") is None and tc.address_query("") is None


# ===========================================================================
# 3. lateness is a payment date, never interest alone
# ===========================================================================

def _regular_page(rows2025, *, situs=None):
    bills = [("0000000010-2026-2026-0000-00", "$200.00"), ("0000000010-2025-2025-0000-00", "$0.00"),
             ("0000000010-2024-2024-0000-00", "$0.00")]
    pages = {f"{tb.BASE}/Parcel/Details/000000001000000": parcel_html(bills, situs=situs or "1 EXAMPLE RD"),
             f"{tb.BASE}/Bill/Details/0000000010-2025-2025-0000-00": bill_html(rows2025)}
    return pages


def test_interest_charged_with_every_payment_before_the_interest_date_is_not_lateness():
    """The 8792725038 error's other half: v3 called any bill with interest charged `stale` even
    when the only payment is dated before the January 6 interest date."""
    pages = _regular_page([("BILL", "7/26/2025", 500, 0, 12, 0), ("PAYMENT", "12/1/2025", -500, 0, -12, 0)])
    r, _ = brun(brow("0000000010", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "interest_without_late_payment"
    chk = r.evidence["bills_checked"][0]
    assert chk["paid_late"] is False and chk["paid_on"] == "2025-12-01"
    assert chk["interest_and_fees"] == 12.0 and chk["interest_without_late_payment"] is True


def test_a_payment_on_the_first_interest_day_is_still_late_the_threshold_is_unchanged():
    """The two near-miss cures are a policy question for the owner: what counts as late did not
    change. A payment dated January 6 is on the interest date."""
    pages = _regular_page([("BILL", "7/26/2025", 500, 0, 4.2, 0), ("PAYMENT", "1/6/2026", -504.2, 0, 0, 0)])
    r, _ = brun(brow("0000000010", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)
    assert r.verdict == "stale"
    assert r.evidence["bills_checked"][0]["first_late_payment_on"] == "2026-01-06"
    pages = _regular_page([("BILL", "7/26/2025", 500, 0, 0, 0), ("PAYMENT", "1/5/2026", -500, 0, 0, 0)])
    assert brun(brow("0000000010", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)[0].verdict == "refuted"


def test_a_zero_balance_with_nothing_paid_is_not_on_time():
    pages = _regular_page([("BILL", "7/26/2025", 500, 0, 0, 0)])
    r, _ = brun(brow("0000000010", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "no_payment_on_bill")


def test_a_parcel_record_that_ends_early_is_unconfirmed():
    """Billing stops at the 2024 levy and nothing is in legal collection (the old test for this
    used a page whose 2025 and 2026 bills were See Legal)."""
    pages = {f"{tb.BASE}/Parcel/Details/000000001100000": parcel_html(
        [("0000000011-2024-2024-0000-00", "$0.00"), ("0000000011-2023-2023-0000-00", "$0.00")])}
    r, f = brun(brow("0000000011", raw={"tax_owed": {"balance": 10.0, "year": 2026}}), pages)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "parcel_record_ended")
    assert len(f.asked) == 1


def test_a_discovery_bill_is_late_from_its_own_tax_year():
    """A discovery bill for tax year 2021, billed and paid in 2025, was paid after ITS January
    2022 interest date (the levy year in its number is only when it was billed)."""
    bp = tb.parse_bill_page(bill_html([("BILL", "2/19/2025", 291.53, 0, 95.48, 0),
                                       ("PAYMENT", "6/18/2025", -291.53, 0, -95.48, 0)]))
    assert tb.payment_check(2021, bp)["paid_late"] is True
    assert tb.payment_check(2025, bp)["paid_late"] is False       # judged by the levy year in its number
    assert tb.payment_check(2025, bp)["interest_without_late_payment"] is True


# ===========================================================================
# 4. evidence
# ===========================================================================

def test_interest_and_fees_is_what_the_county_charged_not_double():
    """Real bill 0000739533-2025 (40 Boone St): BILL interest 45.18, three payments of interest
    30.33 + 12.28 + 2.57. v3 summed every row's absolute interest: 90.36 on all 39 Buncombe stale
    records."""
    f = ReplayFetcher({**{f"{tb.BASE}/Parcel/Details/963962247000000":
                          gzip.decompress((FIX / "buncombe_tax_Parcel_Details_963962247000000.html.gz").read_bytes()).decode(),
                          f"{tb.BASE}/Bill/Details/0000739533-2025-2025-0000-00":
                          gzip.decompress((FIX / "buncombe_tax_Bill_Details_0000739533-2025-2025-0000-00.html.gz").read_bytes()).decode()}})
    r = asyncio.run(tb.verify(brow("963962247000000", raw={"buncombe_delinquent_tax": {"tax_year": 2025}}), f, today=TODAY))
    chk = r.evidence["bills_checked"][0]
    assert r.verdict == "stale" and chk["interest_and_fees"] == 45.18
    assert chk["payments"] == 3 and chk["late_payments"] == 3 and chk["paid_on"] == "2026-09-03"


def test_every_2026_bill_of_the_page_is_kept():
    """Parcel 9754697396 has four 2026 bills (3 owing); the old parse kept one per levy year."""
    page = tb.parse_parcel_page(BUNC[f"{tb.BASE}/Parcel/Details/975469739600000"])
    y26 = [b for b in page["bills"] if b["year"] == 2026]
    assert len(y26) == 4 and sorted(b["amount_due"] for b in y26) == [0.0, 169.68, 184.67, 185.46]
    r, _ = brun(brow("9754697396"), BUNC)                  # no address on the row: judged on the PIN...
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "pin_inactive"   # ...which is inactive
    # the three owing 2026 levies are summed per year, not collapsed to one
    ev = brun(brow("9754697396", raw={"tax_owed": {"balance": 1.0, "year": 2026}}),
              BUNC, today=date(2027, 1, 6))[0].evidence
    assert ev["delinquent_by_year"]["2026"] == round(169.68 + 184.67 + 185.46, 2)


def test_paid_on_is_never_none_when_the_page_shows_a_payment():
    pages = _regular_page([("BILL", "7/26/2025", 500, 0, 12, 0), ("PAYMENT", "12/1/2025", -500, 0, -12, 0)])
    r, _ = brun(brow("0000000010", raw={"tax_owed": {"balance": 1.0, "year": 2025}}), pages)
    assert r.evidence["bills_checked"][0]["paid_on"] == "2025-12-01"


def test_a_payment_release_is_not_a_payment():
    bp = tb.parse_bill_page(bill_html([("BILL", "7/26/2025", 324.92, 0, 28.57, 4.76),
                                       ("PAYMENT", "10/2/2026", -322.46, 0, -28.57, -4.76),
                                       ("PAYMENTRELEASE", "10/9/2026", -2.46, 0, 0, 0)]))
    c = tb.payment_check(2025, bp)
    assert c["payments"] == 1 and c["paid_on"] == "2026-10-02" and c["interest_and_fees"] == 28.57


def test_version_bumped_so_every_old_entry_is_due_again():
    # tp v4 / tq v4: 2026-10-07 (confirmed binds to the row's parcel and owner; Sold at Tax Sale)
    assert (tb.VERSION, tp.VERSION, tq.VERSION) == ("v5", "v4", "v4")


# ===========================================================================
# PTS Cloud (Henderson): address binding, interest alone
# ===========================================================================

def prow(parcel, addr, **kw):
    r = {"state": "NC", "county": "Henderson", "listing_type": "tax_lien", "source": tp.ROLL_SLUG,
         "parcel_id": "9569907747", "street_address": addr,
         "raw": {tp.ROLL_KEY: {"tenant": "Henderson", "parcel": parcel, "tax_year": "2025", "bill_number": None}}}
    r.update(kw)
    return r


def prun(row, extra=None):
    f = ReplayFetcher({**PTS, **(extra or {})})
    return asyncio.run(tp.verify(row, f, today=TODAY)), f


def test_henderson_810_robinson_terrace_is_not_the_billing_parcel_807_robinson_ter():
    """Board parcel 9569907747 (810 ROBINSON TERRACE) was bound to billing parcel 106171, which is
    807 ROBINSON TER; v1 judged that parcel and said stale. 810 has no billing record."""
    r, f = prun(prow("106171", "810 ROBINSON TERRACE"))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "address_not_found"      # v3
    assert r.evidence["address_relation"] == "conflict" and r.evidence["address_matches"] == 0
    assert any("query=810%20ROBINSON" in u for u in f.asked)


def test_the_billing_parcel_that_carries_the_address_binds_and_decides():
    r, f = prun(prow("106171", "807 ROBINSON TERRACE"))
    assert r.verdict == "stale" and r.evidence["address_binding"] == "bill_address"
    assert r.evidence["bills_checked"][0]["paid_on"] == "2026-08-03"
    assert not any("807%20ROBINSON" in u for u in f.asked)


def test_a_parcel_with_no_usable_address_follows_the_address_to_its_parcel():
    """Billing parcel 9954207 is '0 PHYSICAL SITUS UNKNOWN': it cannot say it is 807 ROBINSON TER,
    and the address search lists parcel 106171 for it, which is verified instead."""
    r, f = prun(prow("9954207", "807 ROBINSON TERRACE"))
    assert r.verdict == "stale" and r.evidence["followed_from_parcel"] == "9954207"
    assert r.evidence["tax_parcel"] == "106171" and r.evidence["address_binding"] == "followed"


def test_pts_interest_paid_with_every_payment_before_interest_began_is_not_lateness():
    base = json.loads(PTS[tp.DETAIL_URL.format(bill_id=5036232, tenant="Henderson")])
    base["interestBeginDate"] = "2026-01-06T00:00:00"
    base["lastPaymentDate"] = "2025-12-03T00:00:00"
    base["interestPaid"] = 6.5
    base["transactions"] = [t for t in base["transactions"] if t["transactionCreationDate"] < "2025-12-04"]
    served = {tp.DETAIL_URL.format(bill_id=i, tenant="Henderson"): json.dumps(base)
              for i in (5036232, 4926001)}                    # the 2025 and the 2024 bill
    r, _ = prun(prow("106171", None), served)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "interest_without_late_payment"
    d = tp.paid_late(base, 2025)
    assert d["paid_late"] is False and d["interest_without_late_payment"] is True


# ===========================================================================
# qPayBill (SC): address binding, rollback bills
# ===========================================================================

def qserved(*searches):
    resp = {}
    for key in searches:
        sub, crit, value = key.split("|")
        url = tq.form_url(sub)
        form, cp = QPB["forms"][sub], QPB["criteria"][f"{sub}|{crit}"]
        resp[url] = form
        resp[form_key(url, tq.criteria_data(tq.viewstate(form), crit))] = cp
        resp[form_key(url, tq.search_data(tq.viewstate(cp), value, crit))] = QPB["searches"][key]
    return ReplayFetcher(resp)


def qrow(county, ident, parcel, years=("2025",), addr=None, **kw):
    r = {"state": "SC", "county": county, "listing_type": "tax_sale",
         "source": "counties_sc.qpaybill_delinquent_roll", "parcel_id": parcel,
         "raw": {"qpaybill_roll": {"identification_no": ident, "county": county,
                                   "years_unpaid": list(years), "notice_numbers": []}}}
    if addr:
        r["street_address"] = addr
    r.update(kw)
    return r


def qrun(row, fetcher):
    return asyncio.run(tq.verify(row, fetcher, today=TODAY))


UNION_2383 = ["uniontreasurer|Map|036-00-00-066 000", "uniontreasurer|Map|027-00-00-008 000",
              "uniontreasurer|Address|2383 JONESVILLE"]


def test_union_2383_jonesville_hwy_is_ambiguous_between_the_boards_account_and_the_address_account():
    """The claim's map (329 Jonesville Lockhart Hwy, paid 2026-09-29: late) and the board's map (S
    Jonesville Hwy, paid 2026-09-17: late) against the account that carries 2383 JONESVILLE HWY
    (paid 2026-01-07, on time). Two independent checks disagreed about which account the row is;
    v2 followed the address and said refuted. The owner is a different one on both sides, so
    nothing proves the row's own account is the wrong one: unconfirmed, never refuted or stale."""
    f = qserved(*UNION_2383)
    r = qrun(qrow("Union", "036-00-00-066 000", "027-00-00-008 000", addr="2383 Jonesville Hwy"), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    ev = r.evidence
    assert ev["address_relation"] == "conflict" and ev["address_matches"] == 3
    assert "bills_checked" not in ev and "decided_on" in ev        # nothing was judged on the address account


def test_union_844_rice_ave_ext_is_ambiguous_the_claim_account_is_on_the_same_street():
    """Claim map 072-00-00-052 000 shows 'RICE AVE EXT' (no number: the same street): both
    late-paid years belong to it, the account that carries 844 RICE AVENUE EXT paid on time.
    v2 followed the address (refuted); the verifier cannot tell which account is the row's."""
    f = qserved("uniontreasurer|Map|072-00-00-052 000", "uniontreasurer|Address|844 RICE")
    r = qrun(qrow("Union", "072-00-00-052 000", "072-00-00-052 000", addr="844 RICE AVE EXT"), f)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "ambiguous_account")
    assert r.evidence["address_relation"] == "unknown" and r.evidence["address_matches"] == 3


def test_an_account_whose_bills_name_the_row_address_is_bound_without_a_search():
    f = qserved("uniontreasurer|Map|046-00-00-029 000")
    r = qrun(qrow("Union", "046-00-00-029 000", "046-00-00-029 000", addr="2383 JONESVILLE HWY"), f)
    assert r.verdict == "refuted" and r.evidence["address_binding"] == "bill_address"
    assert not any("Address" in str(k) for k in f.asked) and len(f.asked) == 3


def _no_records(sub="uniontreasurer", crit="Address"):
    """qPayBill's answer to a search that matches nothing: the page without a grid."""
    cp = QPB["criteria"][f"{sub}|{crit}"]
    return cp.replace("</form>", "<span>No records matched the search criteria provided. Please try again.</span></form>")


def test_a_conflicting_address_with_no_account_of_its_own_is_unconfirmed():
    f = qserved("uniontreasurer|Map|036-00-00-066 000", "uniontreasurer|Address|2383 JONESVILLE")
    cp = QPB["criteria"]["uniontreasurer|Address"]
    f.responses[form_key(tq.form_url("uniontreasurer"),
                         tq.search_data(tq.viewstate(cp), "2383 JONESVILLE", "Address"))] = _no_records()
    r = qrun(qrow("Union", "036-00-00-066 000", "036-00-00-066 000", addr="2383 JONESVILLE HWY"), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "address_not_found"      # v3
    assert r.evidence["address_matches"] == 0


CALHOUN = "calhountreasurer|Map|053-00-01-112"


def test_calhoun_rollback_bills_are_judged_apart_from_the_regular_2025_bill():
    """The regular 2025 bill (000149253) was paid 2025-12-08, on time; the late dates (2026-09-22)
    belong to three rollback bills billed under 2025. v1 lumped them: stale."""
    g = tq.parse_grid(QPB["searches"][CALHOUN])
    assert [r["rollback"] for r in g["rows"]] == [True, True, True, False]
    assert [r["description"].split()[0] for r in g["rows"][:3]] == ["2024", "2022", "2023"]
    r = qrun(qrow("Calhoun", "053-00-01-112", "053-00-01-112"), qserved(CALHOUN))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "rollback_bills_mixed"
    assert r.evidence["bills_checked"] == [{"year": 2025, "status": "Paid", "paid_on": "2025-12-08",
                                            "deadline": "2026-01-15", "paid_late": False}]
    assert r.evidence["rollback_bills_checked"] == [{"year": 2025, "status": "Paid", "paid_on": "2026-09-22",
                                                     "deadline": "2026-01-15", "paid_late": True}]


def _qcalhoun(html):
    f = qserved(CALHOUN)
    key = [k for k in f.responses if k.startswith("POST") and f.responses[k] == QPB["searches"][CALHOUN]][0]
    f.responses[key] = html
    return qrun(qrow("Calhoun", "053-00-01-112", "053-00-01-112"), f)


def test_calhoun_variants_regular_late_rollback_on_time_unpaid_rollback():
    html = QPB["searches"][CALHOUN]
    late_regular = html.replace("12/08/25", "02/20/26")                 # the regular bill paid late
    assert _qcalhoun(late_regular).verdict == "stale"
    ontime_both = html.replace("09/22/26", "12/10/25")                  # the rollbacks paid on time too
    assert _qcalhoun(ontime_both).verdict == "refuted"
    unpaid_rb = re.sub(r"(<td>1218792[0-9]+</td>.*?<td>Paid</td><td>)09/22/26(</td>)", r"\g<1>        \2", html,
                       count=1, flags=re.S).replace("<td>Paid</td><td>        </td>", "<td>Unpaid</td><td>        </td>", 1)
    r = _qcalhoun(unpaid_rb)
    assert r.verdict == "confirmed" and r.evidence["delinquent_by_year"]       # an unpaid rollback is owed

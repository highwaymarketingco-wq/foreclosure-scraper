"""The reference verifier, against REAL responses captured from tax.buncombenc.gov during the
2026-10-05 live sweep (tests/fixtures/verification/, gzipped as served). No network."""
from __future__ import annotations

import asyncio
import gzip
import re
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import tax_lien_buncombe as t

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 5)


def page(name: str) -> str:
    return gzip.decompress((FIX / f"buncombe_tax_{name}.html.gz").read_bytes()).decode("utf-8")


def served(*paths: str) -> dict:
    return {f"{t.BASE}/{p}": page(p.replace("/", "_")) for p in paths}


def run(row, fetcher, today=TODAY):
    return asyncio.run(t.verify(row, fetcher, today=today))


def _row(**kw):
    base = {"state": "NC", "county": "Buncombe", "listing_type": "tax_lien", "raw": {}}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------

def test_applies_to_flagged_buncombe_nc_rows_only():
    assert t.applies(_row())
    assert not t.applies(_row(county="Henderson"))
    assert not t.applies(_row(state="SC"))
    assert not t.applies(_row(listing_type="foreclosure_sale"))
    assert t.applies(_row(listing_type="elderly_disabled",
                          raw={"tax_aging_surfaced": {"status": "delinquent", "years_delinquent": 1}}))
    assert t.applies(_row(listing_type="unknown", raw={"two_year_delinquent": {"is_two_year_plus": True}}))
    assert not t.applies(_row(listing_type="unknown",
                              raw={"tax_aging_surfaced": {"status": "current", "years_delinquent": 0}}))


@pytest.mark.parametrize("pid,pin", [
    ("968654082600000", "968654082600000"),
    ("9686-54-0826-00000", "968654082600000"),
    ("9686540826", "968654082600000"),
    ("9686540826000", "968654082600000"),
    ("96865408261234", None),
    ("12345", None),
    (None, None),
])
def test_pin_of(pid, pin):
    assert t.pin_of({"parcel_id": pid}) == pin


# ---------------------------------------------------------------------------
# parsing real pages
# ---------------------------------------------------------------------------

def test_parse_parcel_page_reads_every_levy_year():
    p = t.parse_parcel_page(page("Parcel_Details_968654082600000"))
    years = [b["year"] for b in p["bills"]]
    assert years == sorted(years, reverse=True) and years[0] == 2026 and len(years) >= 10
    assert p["owner"] and p["value"] and p["value"] > 0
    assert all(re.fullmatch(r"\d{10}-\d{4}-\d{4}-\d{4}-\d{2}", b["bill"]) for b in p["bills"])


def test_parse_bill_page_reads_the_transactions():
    b = t.parse_bill_page(page("Bill_Details_0000739533-2025-2025-0000-00"))
    assert b["readable"]
    kinds = [x["type"] for x in b["transactions"]]
    assert "BILL" in kinds and any(k.startswith("PAY") for k in kinds)


def test_a_non_parcel_page_parses_to_nothing():
    assert t.parse_parcel_page("<html><body>Not found</body></html>")["bills"] == []
    assert t.parse_bill_page("<html></html>") == {"transactions": [], "readable": False}


@pytest.mark.parametrize("s,v", [("$1,234.56", 1234.56), ("($152.63)", -152.63), ("$0.00", 0.0), ("", None)])
def test_money(s, v):
    assert t.money(s) == v


def test_delinquency_date_rule():
    assert t.delinquent_after(2025) == date(2026, 1, 6)
    assert t.is_delinquent_year(2025, date(2026, 1, 6))
    assert not t.is_delinquent_year(2025, date(2026, 1, 5))
    assert not t.is_delinquent_year(2026, TODAY)


# ---------------------------------------------------------------------------
# verdicts on real captured responses
# ---------------------------------------------------------------------------

def test_confirmed_real_multi_year_balance():
    """28 Dode Whitaker Rd: three delinquent levies on the county record."""
    f = ReplayFetcher(served("Parcel/Details/968654082600000"))
    r = run(_row(parcel_id="9686540826", owner_name="X", assessed_value=100000.0), f)
    assert r.verdict == "confirmed"
    ev = r.evidence
    assert ev["years_delinquent"] == 3 and ev["total_delinquent"] > 7000
    assert all(int(y) < 2026 for y in ev["delinquent_by_year"])
    assert "2026" in ev["not_yet_delinquent_due"] or ev["not_yet_delinquent_due"] == {}
    assert ev["url"].endswith("/Parcel/Details/968654082600000")
    assert ev["value_county"] and ev["value_ratio_board_to_county"]
    assert len(f.asked) == 1                       # no bill page needed
    assert (r.signal, r.verifier, r.verifier_version, r.source) == (
        "tax_lien", "tax_lien_buncombe", t.VERSION, t.SOURCE)


def test_stale_paid_late_since():
    """40 Boone St: nothing owed now, the 2025 levy was paid on 2026-09-03 with interest."""
    f = ReplayFetcher(served("Parcel/Details/963962247000000",
                             "Bill/Details/0000739533-2025-2025-0000-00"))
    r = run(_row(parcel_id="963962247000000", owner_name="REVIS, PATRICIA ANN L",
                 raw={"buncombe_delinquent_tax": {"tax_year": 2025}}), f)
    assert r.verdict == "stale"
    chk = r.evidence["bills_checked"][0]
    assert chk["year"] == 2025 and chk["paid_late"] is True
    assert chk["paid_on"] == "2026-09-03" and chk["interest_and_fees"] > 0
    assert r.evidence["total_delinquent"] == 0
    assert r.evidence["owner_match"] == "same"


def test_refuted_paid_on_time_and_only_the_current_levy_unpaid():
    """3 Eastcrest Dr: the board's claim rests on the 2026 levy, not delinquent until
    2027-01-06; the 2025 levy was paid on time."""
    f = ReplayFetcher(served("Parcel/Details/968605392600000",
                             "Bill/Details/0000667232-2025-2025-0000-00"))
    r = run(_row(parcel_id="9686-05-3926-00000", raw={"tax_owed": {"balance": 900.0, "year": 2026}}), f)
    assert r.verdict == "refuted"
    assert r.evidence["claimed_years"] == [2026]
    assert r.evidence["bills_checked"] == [{
        "year": 2025, "paid_late": False,
        "url": f"{t.BASE}/Bill/Details/0000667232-2025-2025-0000-00"}]


def test_the_same_page_reads_differently_once_the_levy_goes_delinquent():
    """3 Eastcrest Dr on 2027-01-06: its unpaid 2026 levy ($1,421.35) is delinquent now."""
    f = ReplayFetcher(served("Parcel/Details/968605392600000"))
    assert run(_row(parcel_id="9686053926"), f, today=date(2027, 1, 5)).verdict != "confirmed"
    r = run(_row(parcel_id="9686053926"), f, today=date(2027, 1, 6))
    assert r.verdict == "confirmed"
    assert r.evidence["delinquent_by_year"] == {"2026": 1421.35}
    assert r.evidence["not_yet_delinquent_due"] == {}


# ---------------------------------------------------------------------------
# unconfirmed: never a guess
# ---------------------------------------------------------------------------

def test_unresolvable_parcel_is_unconfirmed_without_a_fetch():
    f = ReplayFetcher({})
    r = run(_row(parcel_id="12-34"), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_unresolvable"
    assert f.asked == []


def test_fetch_failure_and_unreadable_page_are_unconfirmed():
    url = t.PARCEL_URL.format(pin="968654082600000")
    r = run(_row(parcel_id="968654082600000"), ReplayFetcher({url: TimeoutError("slow")}))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "fetch_failed"
    r = run(_row(parcel_id="968654082600000"), ReplayFetcher({url: "<html>maintenance</html>"}))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "no_bills_parsed"


def test_unreadable_bill_pages_are_unconfirmed_not_refuted():
    f = ReplayFetcher(served("Parcel/Details/968605392600000"))   # bill page not recorded
    r = run(_row(parcel_id="9686053926"), f)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "bill_pages_unreadable"


def test_owner_match():
    assert t.owner_match("SANDERS JENNIFER", "JENNIFER SANDERS") == "same"
    assert t.owner_match("SMITH JOHN", "JOHN SMITH, MARY JONES") in ("same", "partial")
    assert t.owner_match("SMITH JOHN", "ACME HOLDINGS LLC") == "different"
    assert t.owner_match(None, "X") is None

"""enrichment_mecklenburg_tax: Mecklenburg County NC multi-year delinquent-tax history, read live
via taxbill.co.mecklenburg.nc.us's own "Bill Search" portal (BillSearchResults.aspx?ParcelNum=),
a bare query-string GET with no ASP.NET VIEWSTATE postback needed -- a different vendor product
from the ITS.NET / ITSPublic chains Iredell/Cabarrus/Catawba read, so this module calls httpx
directly rather than reusing a verifier chain, and tests mock at the httpx.MockTransport layer
(the same convention test_albemarle_observer_tax_lists.py and siblings already use for a
bare-httpx module) instead of a verifier-level ReplayFetcher.

Fixtures mirror real shapes. The "all matured years paid, current year billed-not-yet-due" shape
is the module's own 3 build-time canary parcels (17103426, 00507430, 07808409, live-verified
2026-11-05). The genuine multi-year-delinquency shape is parcel 07505317's own real live answer
(read 2026-11-10, sourced read-only from the board's existing mecklenburg_delinquent_tax.py
rows -- a parcel independently already known to be tax-distressed): years [2020, 2021, 2025,
2026], balances 853.28 / 803.77 / 592.15 / 549.99, non-contiguous (2022-2024 paid in between),
confirming the parser and the _longest_run/_trend reuse on a genuinely messy real shape, not just
a clean constructed one.
"""
from __future__ import annotations

import asyncio
from datetime import date

import httpx

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_mecklenburg_tax as mod
from foreclosure_scraper.enrichment_mecklenburg_tax import (
    _candidate_parcel,
    _eligible,
    _fetch_parcel_bills,
    _parse_bill_rows,
    build_multiyear_block,
    build_two_year_block,
    enrich_mecklenburg_tax,
)

TODAY = date(2026, 11, 10)


def bill_row(seq: str, year: int, parcel: str, owner: str, address: str, balance: float, *,
             note: str = "") -> str:
    """One <tr> shaped exactly like a real BillSearchResults.aspx grid row: cell 0 Bill Number
    (embeds the tax year, '<seq>-<year>-<year>-0000-00'), cell 1 blank (secondary/deed number),
    cell 2 Parcel Number, cell 3 Owner Name as of that bill, cell 4 Property Address, cell 5 a
    mailing/status note, cell 6 the dollar balance."""
    return (f"<tr><td>{seq}-{year}-{year}-0000-00</td><td></td><td>{parcel}</td>"
            f"<td>{owner}</td><td>{address}</td><td>{note}</td><td>${balance:,.2f}</td></tr>")


def grid_page(rows_html: str = "") -> str:
    """A full BillSearchResults.aspx answer: 4 filler <table>s (page furniture _parse_bill_rows
    skips) then the real grid as the 5th table (index 4), closed by a 'Total:' footer row whose
    cell 0 never matches the Bill-Number shape -- dropped by the regex check, not by position."""
    footer = "<tr><td>Total:</td><td></td><td></td><td></td><td></td><td></td><td>$0.00</td></tr>"
    return ("<html>" + "<table></table>" * 4 +
            f"<table>{rows_html}{footer}</table></html>")


def _li(parcel="07505317", county="Mecklenburg", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.mecklenburg_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# build_two_year_block / build_multiyear_block -- pure
# ---------------------------------------------------------------------------

def test_real_shaped_all_matured_paid_plus_current_unpaid_yields_nothing():
    """The module's own 3 build-time canary parcels' shape (17103426/00507430/07808409,
    live-verified 2026-11-05): every matured year 2012-2025 paid $0.00, only 2026 (current,
    billed this year, not yet due under NC's Jan-6-of-next-year rule) unpaid -- correctly zero
    matured delinquent years, not a repeat delinquency."""
    rows = [{"year": y, "bill_number": f"1-{y}-{y}-0000-00", "parcel": "17103426",
             "owner": "X", "address": "1 TEST DR", "note": "", "balance": 0.0}
            for y in range(2012, 2026)]
    rows.append({"year": 2026, "bill_number": "1-2026-2026-0000-00", "parcel": "17103426",
                 "owner": "X", "address": "1 TEST DR", "note": "", "balance": 2224.22})
    two_year = build_two_year_block("17103426", rows, today=TODAY)
    assert two_year == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                        "source": "enrichment_mecklenburg_tax"}
    assert build_multiyear_block("17103426", rows, today=TODAY) is None


def test_real_shaped_genuine_multiyear_delinquency_non_contiguous():
    """Parcel 07505317's own real live answer (read 2026-11-10): years [2020, 2021, 2025, 2026]
    with balances 853.28/803.77/592.15/549.99, 2022-2024 paid in between -- a genuinely messy
    real shape (non-contiguous), not a clean constructed one."""
    rows = [
        {"year": 2026, "bill_number": "1-2026-2026-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 549.99},
        {"year": 2025, "bill_number": "2-2025-2025-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 592.15},
        {"year": 2024, "bill_number": "3-2024-2024-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 0.0},
        {"year": 2023, "bill_number": "4-2023-2023-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 0.0},
        {"year": 2022, "bill_number": "5-2022-2022-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 0.0},
        {"year": 2021, "bill_number": "6-2021-2021-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 803.77},
        {"year": 2020, "bill_number": "7-2020-2020-0000-00", "parcel": "07505317", "owner": "X",
         "address": "1 TEST DR", "note": "", "balance": 853.28},
    ]
    two_year = build_two_year_block("07505317", rows, today=TODAY)
    assert two_year["is_two_year_plus"] is True
    assert two_year["years"] == 3 and two_year["oldest_year"] == 2020
    block = build_multiyear_block("07505317", rows, today=TODAY)
    assert block is not None
    assert block["years"] == [2020, 2021, 2025, 2026]
    assert block["matured_years"] == [2020, 2021, 2025]
    assert block["years_delinquent"] == 3
    assert block["total_due"] == round(853.28 + 803.77 + 592.15 + 549.99, 2)
    assert block["matured_owed"] == round(853.28 + 803.77 + 592.15, 2)
    assert block["in_current_levy"] is True and block["current_levy_year"] == 2026
    assert block["parcel_key"] == "07505317"
    assert block["source_url"].endswith("BillSearchResults.aspx?ParcelNum=07505317")


def test_single_matured_year_fails_multiyear_gate_but_two_year_block_still_honest():
    rows = [{"year": 2024, "bill_number": "1-2024-2024-0000-00", "parcel": "X", "owner": "X",
             "address": "1 TEST DR", "note": "", "balance": 50.0}]
    two_year = build_two_year_block("X", rows, today=TODAY)
    assert two_year["is_two_year_plus"] is False and two_year["years"] == 1
    assert build_multiyear_block("X", rows, today=TODAY) is None


def test_ignores_bills_for_a_different_parcel():
    other = {"year": 2023, "bill_number": "9-2023-2023-0000-00", "parcel": "99999999",
             "owner": "X", "address": "9 OTHER ST", "note": "", "balance": 999.0}
    mine = [{"year": 2024, "bill_number": "1-2024-2024-0000-00", "parcel": "07505317",
             "owner": "X", "address": "1 TEST DR", "note": "", "balance": 30.0},
            {"year": 2023, "bill_number": "2-2023-2023-0000-00", "parcel": "07505317",
             "owner": "X", "address": "1 TEST DR", "note": "", "balance": 32.0}, other]
    block = build_multiyear_block("07505317", mine, today=TODAY)
    assert block["years"] == [2023, 2024]
    assert block["total_due"] == 62.0


# ---------------------------------------------------------------------------
# _candidate_parcel -- parcel ID shape (verified live, see module docstring)
# ---------------------------------------------------------------------------

def test_candidate_parcel_zero_pads_short_forms():
    assert _candidate_parcel(_li(parcel="507430")) == "00507430"


def test_candidate_parcel_already_8_digits_unchanged():
    assert _candidate_parcel(_li(parcel="17103426")) == "17103426"


def test_candidate_parcel_13digit_district_prefixed_form_truncates_to_last_8():
    """'3711917103426' = district '37119' + the same 8-digit '17103426' REID (verified live
    against 3 real cache parcels, same owner/address on both the bare and prefixed rows)."""
    assert _candidate_parcel(_li(parcel="3711917103426")) == "17103426"


def test_candidate_parcel_too_short_is_none():
    assert _candidate_parcel(_li(parcel="123")) is None


def test_candidate_parcel_no_digits_is_none():
    assert _candidate_parcel(_li(parcel="")) is None
    assert _candidate_parcel(_li(parcel=None)) is None


# ---------------------------------------------------------------------------
# _eligible
# ---------------------------------------------------------------------------

def test_eligible_only_mecklenburg_nc_with_parcel_not_already_checked():
    eligible = _li()
    wrong_county = _li(county="Cabarrus")
    wrong_state = _li(state="SC", county="Mecklenburg")
    no_parcel = _li(parcel="")
    already_sentinel = _li(raw={"_mecklenburg_mydt_checked": "fetch_failed:TimeoutError"})
    already_block = _li(raw={"two_year_delinquent": {"is_two_year_plus": False}})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already_sentinel, already_block]
    assert [li for li in rows if _eligible(li)] == [eligible]


# ---------------------------------------------------------------------------
# _parse_bill_rows / _fetch_parcel_bills -- real grid HTML, by position
# ---------------------------------------------------------------------------

def test_parse_bill_rows_drops_total_footer_and_reads_by_position():
    html = grid_page(bill_row("1", 2026, "07505317", "COHEN CO REAL ESTATE LLC", "1 TEST DR",
                               549.99) +
                      bill_row("2", 2025, "07505317", "COHEN, ERIC SAMUEL", "1 TEST DR", 592.15))
    rows = _parse_bill_rows(html)
    assert [r["year"] for r in rows] == [2026, 2025]
    assert rows[0]["balance"] == 549.99 and rows[0]["parcel"] == "07505317"
    assert rows[0]["owner"] == "COHEN CO REAL ESTATE LLC"


def test_parse_bill_rows_fewer_than_5_tables_is_empty():
    assert _parse_bill_rows("<html><table></table></html>") == []


def test_fetch_no_data_found_is_a_real_empty_answer_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>NO DATA FOUND</html>")
    rows, status = run(_fetch_parcel_bills(_mock_client(handler), "00000000"))
    assert (rows, status) == ([], "no_results")


def test_fetch_ok_path_parses_the_real_grid():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ParcelNum"] == "07505317"
        return httpx.Response(200, text=grid_page(
            bill_row("1", 2026, "07505317", "X", "1 TEST DR", 549.99)))
    rows, status = run(_fetch_parcel_bills(_mock_client(handler), "07505317"))
    assert status == "ok"
    assert {r["year"] for r in rows} == {2026}


def test_fetch_non_200_is_a_fetch_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")
    rows, status = run(_fetch_parcel_bills(_mock_client(handler), "07505317"))
    assert rows is None and status == "fetch_failed:http_500"


def test_fetch_unreadable_answer_when_grid_shape_doesnt_match():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><table></table><table></table>"
                                        "<table></table><table></table><table>"
                                        "<tr><td>junk</td></tr></table></html>")
    rows, status = run(_fetch_parcel_bills(_mock_client(handler), "07505317"))
    assert rows is None and status == "unreadable_answer"


# ---------------------------------------------------------------------------
# enrich_mecklenburg_tax -- end to end
# ---------------------------------------------------------------------------

def test_enrich_end_to_end_qualifies_both_blocks(monkeypatch):
    monkeypatch.setattr(mod, "_ENABLED", True)
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=grid_page(
            bill_row("1", 2026, "07505317", "X", "1 TEST DR", 10.0) +
            bill_row("2", 2025, "07505317", "X", "1 TEST DR", 50.0) +
            bill_row("3", 2024, "07505317", "X", "1 TEST DR", 52.0)))
    li = _li()
    stats = run(enrich_mecklenburg_tax([li], client=_mock_client(handler)))
    assert stats["eligible"] == 1 and stats["two_year_written"] == 1 and stats["multiyear_qualified"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]


def test_enrich_disabled_by_default_flag_writes_nothing(monkeypatch):
    """With the module's own _ENABLED flag off (its real default when FORECLOSURE_MECKLENBURG_MYDT
    is unset), the whole pass is a documented no-op -- this is the dormant state a fresh pipeline
    run is actually in today, not a bug in the enrichment logic itself."""
    monkeypatch.setattr(mod, "_ENABLED", False)
    li = _li()
    stats = run(enrich_mecklenburg_tax([li]))
    assert stats["eligible"] == 0
    assert "two_year_delinquent" not in li.raw and "multi_year_delinquent_tax" not in li.raw


def test_enrich_no_results_stamps_checked_sentinel_not_a_block(monkeypatch):
    monkeypatch.setattr(mod, "_ENABLED", True)
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>NO DATA FOUND</html>")
    li = _li()
    stats = run(enrich_mecklenburg_tax([li], client=_mock_client(handler)))
    assert stats["no_results"] == 1
    assert "two_year_delinquent" not in li.raw
    assert li.raw["_mecklenburg_mydt_checked"] == "no_results"


def test_enrich_does_not_overwrite_existing_two_year_block(monkeypatch):
    monkeypatch.setattr(mod, "_ENABLED", True)
    sentinel = {"is_two_year_plus": True, "manual": True}
    li = _li(raw={"two_year_delinquent": sentinel})
    stats = run(enrich_mecklenburg_tax([li], client=_mock_client(lambda r: httpx.Response(200))))
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel

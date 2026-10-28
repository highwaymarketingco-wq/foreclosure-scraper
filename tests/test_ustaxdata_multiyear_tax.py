"""enrichment_ustaxdata_multiyear_tax: pure restatement of raw['ustaxdata_delinquent_tax']
bills into multi_year_delinquent_tax / two_year_delinquent. No network -- every test builds its
own synthetic `bills` list in the exact shape enrichment_ustaxdata_tax_search.parse_results()
produces (year, status, total_due), matching that module's own real field names.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_ustaxdata_multiyear_tax import (
    RAW_KEY, TWO_YEAR_KEY, _eligible, build_block, build_two_year_block,
    enrich_ustaxdata_multiyear_tax,
)
from foreclosure_scraper.models import Listing

TODAY = date(2026, 10, 28)


def _bill(year: int, status: str, total_due: float | None = None) -> dict:
    return {"year": year, "status": status, "total_due": total_due}


def _listing(**kw) -> Listing:
    kw.setdefault("source", "test")
    kw.setdefault("source_url", "https://x")
    return Listing(**kw)


def test_build_block_none_below_min_years():
    bills = [_bill(2025, "unpaid", 100.0)]
    assert build_block(bills, "Rockingham", today=TODAY) is None


def test_build_block_none_when_nothing_matured():
    # Two unpaid years but both current-levy (never matured) -- same gate Gaston's sibling uses.
    bills = [_bill(2026, "unpaid", 50.0), _bill(2027, "unpaid", 60.0)]
    assert build_block(bills, "Rockingham", today=TODAY) is None


def test_build_block_qualifies_on_two_matured_unpaid_years():
    bills = [_bill(2023, "unpaid", 100.0), _bill(2024, "partial", 50.0), _bill(2025, "paid", 0.0)]
    block = build_block(bills, "Rockingham", today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024]
    assert block["years_delinquent"] == 2
    assert block["total_due"] == 150.0
    assert block["amount_known"] is True


def test_build_block_amount_known_false_when_total_due_missing():
    # Rockingham's own real gap (enrichment_ustaxdata_tax_search.py's 2026-10-20 finding):
    # status-confirmed unpaid bills can carry no resolved dollar amount at all.
    bills = [_bill(2022, "unpaid", None), _bill(2023, "unpaid", None)]
    block = build_block(bills, "Rockingham", today=TODAY)
    assert block is not None
    assert block["total_due"] is None
    assert block["amount_known"] is False


def test_build_block_ignores_paid_years():
    bills = [_bill(2022, "paid", 0.0), _bill(2023, "paid", 0.0)]
    assert build_block(bills, "Rockingham", today=TODAY) is None


def test_build_two_year_block_unconditional_real_answer():
    bills = [_bill(2022, "paid", 0.0)]
    block = build_two_year_block(bills, "Rockingham", today=TODAY)
    assert block["is_two_year_plus"] is False
    assert block["years"] == 0
    assert block["oldest_year"] is None

    bills2 = [_bill(2021, "unpaid", 10.0), _bill(2022, "unpaid", 10.0)]
    block2 = build_two_year_block(bills2, "Rockingham", today=TODAY)
    assert block2["is_two_year_plus"] is True
    assert block2["years"] == 2
    assert block2["oldest_year"] == 2021


def test_eligible_requires_tenant_county_and_bills_and_not_already_done():
    li = _listing(state="NC", county="Rockingham",
                  raw={"ustaxdata_delinquent_tax": {"bills": [_bill(2023, "unpaid", 10.0)]}})
    assert _eligible(li) is True

    not_a_tenant = _listing(state="NC", county="Wake",
                            raw={"ustaxdata_delinquent_tax": {"bills": []}})
    assert _eligible(not_a_tenant) is False

    no_bills = _listing(state="NC", county="Robeson", raw={"ustaxdata_delinquent_tax": {}})
    assert _eligible(no_bills) is False

    already_done = _listing(state="NC", county="Alexander",
                            raw={"ustaxdata_delinquent_tax": {"bills": [_bill(2023, "unpaid", 10.0)]},
                                 RAW_KEY: {"years": [2023]}})
    assert _eligible(already_done) is False


def test_enrich_writes_both_keys_on_a_qualifying_row():
    li = _listing(state="NC", county="Rockingham",
                  raw={"ustaxdata_delinquent_tax": {
                      "bills": [_bill(2023, "unpaid", 100.0), _bill(2024, "unpaid", 50.0)]}})
    stats = enrich_ustaxdata_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 1
    assert stats["two_year_written"] == 1
    assert isinstance(li.raw[RAW_KEY], dict)
    assert isinstance(li.raw[TWO_YEAR_KEY], dict)


def test_enrich_skips_already_done_rows():
    li = _listing(state="NC", county="Robeson",
                  raw={"ustaxdata_delinquent_tax": {"bills": [_bill(2023, "unpaid", 10.0)]},
                       RAW_KEY: {"years": [2023]}})
    stats = enrich_ustaxdata_multiyear_tax([li])
    assert stats["eligible"] == 0

"""enrichment_transylvania_multiyear_tax: pure, no-network restatement of
raw['transylvania_tax']['bills'] (scrapers/counties_nc/transylvania_delinquent_tax.py's own
build_listing() output -- [{year, bill, balance, original_levy}, ...]) into the shared
raw['multi_year_delinquent_tax'] contract gap_matrix.py reads.

gap-matrix context (docs/gap_matrix/gap_list_2026-11-16.csv): NC/Transylvania
multi_year_delinquent_tax, 12,528 applicable, 0 built -- the 2nd-biggest sourced-not-built item
on the board. Investigation found the scraper and this restatement module both already existed
and were already wired into main.py (commit afae3501, 2026-11-10); the real gap was that most
existing raw['transylvania_tax'] blocks on the board predate the scraper's 2026-10-14 multi-year
fix and carry no `bills` key at all (closed via scripts/refresh_transylvania_delinquent_tax.py's
live re-scrape, not by this module, which cannot restate data that was never fetched)."""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_transylvania_multiyear_tax import (
    RAW_KEY, SOURCE_KEY, build_block, enrich_transylvania_multiyear_tax,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

TODAY = date(2026, 11, 15)


def _bill(year: int, balance: float) -> dict:
    return {"year": year, "bill": f"B-{year}", "balance": balance, "original_levy": balance}


def _source_block(bills: list[dict], *, parcel: str = "8583012326000") -> dict:
    years = [b["year"] for b in bills if isinstance(b, dict) and b.get("year")]
    return {"tax_year": max(years) if years else None,
           "account_number": "70094770", "parcel": parcel, "signal": "delinquent_property_tax",
           "bills": bills}


def _li(parcel="8583012326000", raw=None) -> Listing:
    return Listing(source="counties_nc.transylvania_delinquent_tax",
                  source_url="https://tax.transylvaniacounty.org/TaxBillSearch",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Transylvania", state="NC", parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_block
# ---------------------------------------------------------------------------

def test_build_block_qualifies_multi_year_matured():
    # The task's own live-verified sample parcel (module docstring, 2026-11-05 check).
    src = _source_block([_bill(2023, 90.16), _bill(2024, 83.75), _bill(2025, 110.48)])
    block = build_block(src, today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024, 2025]
    assert block["unpaid_bill_years"] == 3
    assert block["consecutive_years"] == 3
    assert block["total_due"] == 284.39
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"]
    assert block["layers"] == ["enrichment_transylvania_multiyear_tax"]
    # Every year here is well past NC's Jan 6-following-year delinquent date relative to TODAY.
    assert block["matured_years_delinquent"] == 3
    assert block["matured_years"] == [2023, 2024, 2025]


def test_build_block_single_year_fails_gate():
    src = _source_block([_bill(2025, 50.0)])
    assert build_block(src, today=TODAY) is None


def test_build_block_no_bills_key_returns_none():
    # The exact OLD, pre-2026-10-14 single-year snapshot shape still on ~480 board rows at the
    # time this gap was investigated: no `bills` list at all.
    stale = {"tax_year": 2025, "balance_owed": 120.0, "original_levy": 130.0,
             "account_number": "123", "parcel": "999"}
    assert build_block(stale, today=TODAY) is None


def test_build_block_empty_bills_list_returns_none():
    assert build_block({"bills": []}, today=TODAY) is None


def test_build_block_zero_or_invalid_amount_year_still_counts_toward_years():
    # Real behavior, read from the code (not assumed): a bill whose balance is 0/negative/
    # unparseable keeps its YEAR in the history (per_year.setdefault(year, None)) -- the county
    # listed the year as an open bill even when the balance field itself didn't parse to a
    # positive number -- it just contributes nothing to total_due. Differs deliberately from
    # enrichment_its_public_multiyear_tax's build_block(), which drops such a bill entirely;
    # this module's own per-row data has no analogous "the bill just doesn't exist" case to
    # distinguish from "exists but reads as zero", so it is kept as a year, not discarded.
    bills = [_bill(2023, 12.0), _bill(2024, 0.0), {"year": 2022, "balance": None}]
    block = build_block(_source_block(bills), today=TODAY)
    assert block is not None
    assert block["years"] == [2022, 2023, 2024]
    assert block["total_due"] == 12.0


def test_build_block_duplicate_year_keeps_larger_not_sum():
    bills = [_bill(2024, 10.0), _bill(2024, 40.0), _bill(2023, 5.0)]
    block = build_block(_source_block(bills), today=TODAY)
    assert block is not None
    assert block["per_year"]["2024"] == 40.0
    assert block["total_due"] == 45.0


def test_build_block_trend_growing():
    bills = [_bill(2022, 40.0), _bill(2023, 45.0), _bill(2024, 55.0)]
    block = build_block(_source_block(bills), today=TODAY)
    assert block["trend"] == "growing"


def test_build_block_current_unmatured_year_excluded_from_matured():
    # A parcel unpaid only for the current, not-yet-due levy plus one real matured year still
    # qualifies (>=2 years, >=1 matured) but the current year must not count as matured.
    bills = [_bill(2024, 80.0), _bill(TODAY.year, 95.0)]
    block = build_block(_source_block(bills), today=TODAY)
    assert block is not None
    assert TODAY.year not in block["matured_years"]
    assert 2024 in block["matured_years"]


def test_build_block_all_years_unmatured_fails_gate():
    # Two years, both still the current/not-yet-due levy (can't really happen with one tax
    # calendar, but exercises the "no matured year at all" branch directly).
    bills = [_bill(TODAY.year, 10.0), _bill(TODAY.year + 1, 10.0)]
    assert build_block(_source_block(bills), today=TODAY) is None


def test_build_block_non_dict_bill_rows_ignored():
    bills = [_bill(2023, 10.0), "not a dict", _bill(2024, 12.0)]  # type: ignore[list-item]
    block = build_block(_source_block(bills), today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024]


# ---------------------------------------------------------------------------
# enrich_transylvania_multiyear_tax: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats["eligible"] == 0
    assert RAW_KEY not in li.raw


def test_enrich_qualifies_real_shaped_row():
    bills = [_bill(2023, 90.16), _bill(2024, 83.75), _bill(2025, 110.48)]
    li = _li(raw={SOURCE_KEY: _source_block(bills)})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats["eligible"] == 1
    assert stats["qualified"] == 1
    assert li.raw[RAW_KEY]["years"] == [2023, 2024, 2025]


def test_enrich_stale_pre_fix_shape_counted_insufficient_not_qualified():
    # The real board state this gap was closed from: a row carrying raw['transylvania_tax']
    # with no `bills` key at all is ELIGIBLE (the source key is present as a dict) but never
    # qualifies -- confirms the restatement module correctly leaves these alone rather than
    # erroring, and that only a fresh re-scrape (not this module) can upgrade them.
    stale = {"tax_year": 2025, "balance_owed": 120.0, "original_levy": 130.0}
    li = _li(raw={SOURCE_KEY: stale})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats["eligible"] == 1
    assert stats["qualified"] == 0
    assert stats["insufficient_history"] == 1
    assert RAW_KEY not in li.raw


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"years": [1999], "manual": True}
    bills = [_bill(2023, 28.0), _bill(2024, 30.0)]
    li = _li(raw={SOURCE_KEY: _source_block(bills), RAW_KEY: sentinel})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats["eligible"] == 0
    assert li.raw[RAW_KEY] is sentinel


def test_enrich_single_year_row_counted_insufficient_not_qualified():
    li = _li(raw={SOURCE_KEY: _source_block([_bill(2025, 12.0)])})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats["eligible"] == 1
    assert stats["qualified"] == 0
    assert stats["insufficient_history"] == 1
    assert RAW_KEY not in li.raw


def test_enrich_gated_off_by_env(monkeypatch):
    monkeypatch.setattr("foreclosure_scraper.enrichment_transylvania_multiyear_tax.ENABLED", False)
    bills = [_bill(2023, 28.0), _bill(2024, 30.0)]
    li = _li(raw={SOURCE_KEY: _source_block(bills)})
    stats = enrich_transylvania_multiyear_tax([li], today=TODAY)
    assert stats == {"eligible": 0, "qualified": 0, "insufficient_history": 0}
    assert RAW_KEY not in li.raw

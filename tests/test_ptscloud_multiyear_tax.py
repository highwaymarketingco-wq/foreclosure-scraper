"""enrichment_ptscloud_multiyear_tax: pure, no-network restatement of
raw['nc_ptscloud_delinquent_tax']['by_year'] into the shared raw['multi_year_delinquent_tax']
contract. by_year fixtures below use the exact dict shape nc_ptscloud_delinquent_tax._bill_entry
produces (tax_year/bill_amount/bill_due_amt/interest_due/total_due/bill_status/bill_due_date),
not a simplified stand-in.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_ptscloud_multiyear_tax import (
    build_block, enrich_ptscloud_multiyear_tax,
)

TODAY = date(2026, 10, 18)


def _bill(year: str, total_due: float) -> dict:
    return {"tax_year": year, "bill_number": f"B-{year}", "bill_amount": total_due,
            "bill_due_amt": total_due, "interest_due": 0.0, "total_due": total_due,
            "bill_status": "DELINQUENT", "bill_due_date": f"{year}-01-05"}


def _li(parcel="6869430725", county="Forsyth", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_ptscloud_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_block
# ---------------------------------------------------------------------------

def test_build_block_qualifies_multi_year_matured():
    by_year = [_bill("2026", 50.00), _bill("2025", 48.00), _bill("2024", 45.00)]
    block = build_block("6869430725", "NC", "Forsyth", by_year, "Forsyth", today=TODAY)
    assert block is not None
    assert block["years"] == [2024, 2025, 2026]
    assert block["unpaid_bill_years"] == 3
    assert block["consecutive_years"] == 3
    assert block["total_due"] == 143.00
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"]
    assert block["tenant"] == "Forsyth"
    assert "bcpwa.ncptscloud.com" in block["source_url"]
    # 2026 is this year's not-yet-late bill (NC delinquent-after is Jan 6 of the following
    # year); 2024/2025 are matured.
    assert 2026 not in block["matured_years"]
    assert block["years_delinquent"] == 2


def test_build_block_single_year_fails_gate():
    by_year = [_bill("2026", 50.00)]
    assert build_block("p1", "NC", "Forsyth", by_year, "Forsyth", today=TODAY) is None


def test_build_block_current_year_only_two_entries_no_matured_year():
    # Two distinct years but BOTH still current (e.g. a county on a two-year current-levy
    # window) would fail the matured gate -- here we just confirm a genuinely all-current
    # case (both years >= today's levy year) returns None rather than a false positive.
    by_year = [_bill("2026", 50.00), _bill("2027", 10.00)]
    assert build_block("p1", "NC", "Forsyth", by_year, "Forsyth", today=TODAY) is None


def test_build_block_ignores_unparseable_or_zero_amount_rows():
    by_year = [_bill("2024", 10.0), _bill("2025", 0.0), {"tax_year": None, "total_due": 5.0},
               _bill("2023", 12.0)]
    block = build_block("p1", "NC", "Forsyth", by_year, "Forsyth", today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024]  # 2025 ($0) and the yearless row are dropped


def test_build_block_duplicate_year_keeps_larger_not_sum():
    by_year = [_bill("2024", 10.0), _bill("2024", 40.0), _bill("2023", 5.0)]
    block = build_block("p1", "NC", "Forsyth", by_year, "Forsyth", today=TODAY)
    assert block is not None
    assert block["per_year"]["2024"] == 40.0
    assert block["total_due"] == 45.0


def test_build_block_trend_growing():
    by_year = [_bill("2022", 40.0), _bill("2023", 45.0), _bill("2024", 55.0)]
    block = build_block("p1", "NC", "Forsyth", by_year, "Forsyth", today=TODAY)
    assert block["trend"] == "growing"


# ---------------------------------------------------------------------------
# enrich_ptscloud_multiyear_tax: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_ptscloud_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_qualifies_real_shaped_row():
    li = _li(raw={"nc_ptscloud_delinquent_tax": {
        "tenant": "Forsyth", "parcel": "6910782033",
        "by_year": [_bill("2024", 30.0), _bill("2023", 28.0), _bill("2022", 25.0)],
    }})
    stats = enrich_ptscloud_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 1
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2022, 2023, 2024]


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"years": [1999], "manual": True}
    li = _li(raw={
        "nc_ptscloud_delinquent_tax": {
            "tenant": "Forsyth",
            "by_year": [_bill("2024", 30.0), _bill("2023", 28.0)],
        },
        "multi_year_delinquent_tax": sentinel,
    })
    stats = enrich_ptscloud_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel


def test_enrich_single_year_row_counted_insufficient_not_qualified():
    li = _li(raw={"nc_ptscloud_delinquent_tax": {
        "tenant": "Pitt", "by_year": [_bill("2026", 12.0)],
    }})
    stats = enrich_ptscloud_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 0
    assert stats["insufficient_history"] == 1
    assert "multi_year_delinquent_tax" not in li.raw

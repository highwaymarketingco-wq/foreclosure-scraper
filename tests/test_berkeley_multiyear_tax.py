"""enrichment_berkeley_multiyear_tax: pure, no-network restatement of
raw['berkeley_paystar_tax']['bills'] (counties_sc/berkeley_paystar_tax.py's own
_merge_invoices() shape: one {tax_year, total_due, invoice_number, delinquent} dict per
distinct unpaid year) into the shared raw['multi_year_delinquent_tax'] contract. Reuses
enrichment_ptscloud_multiyear_tax.build_block() (already pure-function-tested there) and
checks only the two fields this module restates afterward (source_url/tenant/layers).
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_berkeley_multiyear_tax import (
    build_block, enrich_berkeley_multiyear_tax,
)

TODAY = date(2026, 10, 20)


def _bill(tax_year: int, total_due: float) -> dict:
    return {"tax_year": tax_year, "total_due": total_due, "invoice_number": f"2026-{tax_year}",
            "delinquent": True}


def _li(parcel="081-00-00-141", raw=None) -> Listing:
    return Listing(source="counties_sc.berkeley_paystar_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county="Berkeley", state="SC", parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_block
# ---------------------------------------------------------------------------

def test_build_block_qualifies_multi_year_matured():
    blk = {"bills": [_bill(2024, 300.0), _bill(2023, 285.0), _bill(2022, 270.0)]}
    block = build_block("081-00-00-141", blk, today=TODAY)
    assert block is not None
    assert block["years"] == [2022, 2023, 2024]
    assert block["unpaid_bill_years"] == 3
    assert block["total_due"] == 855.0
    assert block["amount_basis"] == "annual_bill"
    assert block["layers"] == ["berkeley_paystar_tax"]
    assert block["tenant"] is None
    assert block["source_url"] == "https://berkeleycountysc.paystar.io"
    # SC delinquent-after is the day after Jan 15 of year+1; as of 2026-10-20 every one of
    # 2022/2023/2024 has matured.
    assert block["years_delinquent"] == 3


def test_build_block_single_year_fails_gate():
    blk = {"bills": [_bill(2025, 300.0)]}
    assert build_block("p1", blk, today=TODAY) is None


def test_build_block_no_bills_list_is_none():
    assert build_block("p1", {}, today=TODAY) is None
    assert build_block("p1", {"bills": []}, today=TODAY) is None


def test_build_block_all_current_years_no_matured_year():
    blk = {"bills": [_bill(2026, 50.0), _bill(2027, 10.0)]}
    assert build_block("p1", blk, today=TODAY) is None


# ---------------------------------------------------------------------------
# enrich_berkeley_multiyear_tax: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_berkeley_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_writes_for_a_real_multi_year_row():
    blk = {"bills": [_bill(2024, 300.0), _bill(2023, 285.0)]}
    li = _li(raw={"berkeley_paystar_tax": blk})
    stats = enrich_berkeley_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 1
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2023, 2024]


def test_enrich_leaves_single_year_rows_alone():
    li = _li(raw={"berkeley_paystar_tax": {"bills": [_bill(2025, 300.0)]}})
    stats = enrich_berkeley_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["insufficient_history"] == 1
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_does_not_overwrite_an_existing_block():
    sentinel = {"years": [1999], "manual": True}
    blk = {"bills": [_bill(2024, 300.0), _bill(2023, 285.0)]}
    li = _li(raw={"berkeley_paystar_tax": blk, "multi_year_delinquent_tax": sentinel})
    stats = enrich_berkeley_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel


def test_enrich_skips_a_stray_block_on_a_non_berkeley_row():
    """Same cross-contamination guard as enrichment_berkeley_two_year_delinquent.py: the
    source key's presence alone must never be trusted; county is the real gate."""
    blk = {"bills": [_bill(2024, 300.0), _bill(2023, 285.0)], "parent_tms": "0000000000"}
    li = _li(parcel="0000000000", raw={"berkeley_paystar_tax": blk})
    li.county = "Spartanburg"
    stats = enrich_berkeley_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert stats["skipped_wrong_county"] == 1
    assert "multi_year_delinquent_tax" not in li.raw

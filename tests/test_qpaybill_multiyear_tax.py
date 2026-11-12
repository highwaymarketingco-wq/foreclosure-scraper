"""enrichment_qpaybill_multiyear_tax: pure, no-network restatement of
raw['qpaybill_roll'] (counties_sc.qpaybill_delinquent_roll's own already-aggregated shape) into
the two shared contract keys raw['multi_year_delinquent_tax'] / raw['two_year_delinquent'].
Fixtures below use the exact dict shape qpaybill_delinquent_roll._to_listings() produces
(identification_no/is_account_id_not_parcel/balance_owed/years_unpaid/all_unpaid_years/
years_delinquent/is_two_year_plus), not a simplified stand-in.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_qpaybill_multiyear_tax import (
    build_multiyear_block, build_two_year_block, enrich_qpaybill_multiyear_tax,
)


def _qr(ident="44305030067", balance=100.0, years_unpaid=None, all_years=None,
        account_only=False) -> dict:
    years_unpaid = years_unpaid if years_unpaid is not None else ["2025"]
    all_years = all_years if all_years is not None else years_unpaid
    return {
        "identification_no": ident,
        "is_account_id_not_parcel": account_only,
        "county": "Horry",
        "subdomain": "horrycountytreasurer",
        "owner": "SOME OWNER",
        "property_address": None,
        "balance_owed": balance,
        "years_unpaid": years_unpaid,
        "all_unpaid_years": all_years,
        "years_delinquent": len(years_unpaid),
        "is_two_year_plus": len(years_unpaid) >= 2,
        "statuses": ["Unpaid"],
        "notice_numbers": [],
        "prior_owner_description": None,
        "rows": len(all_years),
    }


def _li(parcel="44305030067", county="Horry", state="SC", raw=None) -> Listing:
    return Listing(source="counties_sc.qpaybill_delinquent_roll", source_url="https://x/1",
                  listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_two_year_block
# ---------------------------------------------------------------------------

def test_two_year_block_single_year_not_two_plus():
    blk = build_two_year_block(_qr(years_unpaid=["2025"]))
    assert blk == {"is_two_year_plus": False, "years": 1, "oldest_year": 2025,
                   "source": "counties_sc.qpaybill_delinquent_roll"}


def test_two_year_block_multi_year_is_two_plus():
    blk = build_two_year_block(_qr(years_unpaid=["2023", "2024", "2025"]))
    assert blk["is_two_year_plus"] is True
    assert blk["years"] == 3
    assert blk["oldest_year"] == 2023


# ---------------------------------------------------------------------------
# build_multiyear_block
# ---------------------------------------------------------------------------

def test_multiyear_block_single_year_fails_gate():
    assert build_multiyear_block(_qr(years_unpaid=["2025"])) is None


def test_multiyear_block_qualifies_consecutive():
    blk = build_multiyear_block(_qr(ident="45702030036", balance=2910.57,
                                    years_unpaid=["2023", "2024", "2025"]))
    assert blk is not None
    assert blk["years"] == [2023, 2024, 2025]
    assert blk["consecutive_years"] == 3
    assert blk["total_due"] == 2910.57
    assert blk["amount_basis"] == "aggregate_across_years"
    assert blk["parcel_key"] == "45702030036"
    assert "per_year" not in blk  # honestly scoped: source has no per-year split
    assert "trend" not in blk


def test_multiyear_block_nonconsecutive_run_length():
    blk = build_multiyear_block(_qr(years_unpaid=["2021", "2022", "2023", "2025"]))
    assert blk["consecutive_years"] == 3  # 2021-2023, not the lone 2025


def test_multiyear_block_account_id_county_gets_no_parcel_key():
    # Orangeburg: identification_no is an ACCOUNT number, not a parcel id -- binding tax debt
    # to it as a parcel_key would be the exact class of bug project_tax_binding_bug_2026-10-08.md
    # already found and fixed once (another parcel's debt bound onto a row).
    blk = build_multiyear_block(_qr(ident="993249", account_only=True,
                                    years_unpaid=["2024", "2025"]))
    assert blk is not None
    assert "parcel_key" not in blk


# ---------------------------------------------------------------------------
# enrich_qpaybill_multiyear_tax: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_qpaybill_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert "multi_year_delinquent_tax" not in li.raw
    assert "two_year_delinquent" not in li.raw


def test_enrich_writes_two_year_for_every_row_but_multiyear_only_when_qualified():
    li1 = _li(raw={"qpaybill_roll": _qr(years_unpaid=["2025"])})
    li2 = _li(raw={"qpaybill_roll": _qr(ident="33916040020", balance=4351.37,
                                        years_unpaid=["2023", "2024", "2025"])})
    stats = enrich_qpaybill_multiyear_tax([li1, li2])
    assert stats["eligible"] == 2
    assert stats["two_year_written"] == 2
    assert stats["multiyear_qualified"] == 1
    assert stats["multiyear_insufficient_years"] == 1
    assert "multi_year_delinquent_tax" not in li1.raw
    assert li1.raw["two_year_delinquent"]["is_two_year_plus"] is False
    assert li2.raw["multi_year_delinquent_tax"]["years"] == [2023, 2024, 2025]
    assert li2.raw["two_year_delinquent"]["is_two_year_plus"] is True


def test_enrich_does_not_overwrite_existing_blocks():
    sentinel_mydt = {"years": [1999], "manual": True}
    sentinel_tyd = {"is_two_year_plus": True, "manual": True}
    li = _li(raw={
        "qpaybill_roll": _qr(years_unpaid=["2023", "2024"]),
        "multi_year_delinquent_tax": sentinel_mydt,
        "two_year_delinquent": sentinel_tyd,
    })
    stats = enrich_qpaybill_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel_mydt
    assert li.raw["two_year_delinquent"] is sentinel_tyd


def test_enrich_orangeburg_account_id_row_no_parcel_key_board_shape():
    li = _li(parcel=None, county="Orangeburg",
             raw={"qpaybill_roll": _qr(ident="993249", account_only=True,
                                       balance=2790.33, years_unpaid=["2024", "2025"])})
    stats = enrich_qpaybill_multiyear_tax([li])
    assert stats["multiyear_qualified"] == 1
    assert "parcel_key" not in li.raw["multi_year_delinquent_tax"]

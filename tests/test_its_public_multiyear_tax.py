"""enrichment_its_public_multiyear_tax: pure, no-network restatement of
raw['nc_its_public_tax']['bills'] into the shared raw['multi_year_delinquent_tax'] contract.
Bill fixtures below use the exact dict shape nc_its_public_tax.aggregate() produces (year/bill/
balance/original_levy/status), not a simplified stand-in.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_its_public_multiyear_tax import (
    build_block, enrich_its_public_multiyear_tax,
)

TODAY = date(2026, 10, 18)


def _bill(year: int, balance: float) -> dict:
    return {"year": year, "bill": f"B-{year}", "balance": balance,
            "original_levy": balance, "status": None}


def _source_block(portal: str, bills: list[dict]) -> dict:
    years = sorted({b["year"] for b in bills if b.get("year") is not None})
    return {"county": "Duplin", "portal": portal, "parcel": "DL-1", "account": "0000565",
            "years": years, "years_delinquent": len(years), "is_two_year_plus": len(years) >= 2,
            "total_due": round(sum(b["balance"] for b in bills), 2), "bills": bills}


def _li(parcel="DL-1", county="Duplin", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_its_public_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_block
# ---------------------------------------------------------------------------

def test_build_block_qualifies_multi_year_matured():
    src = _source_block("https://www.bttaxpayerportal.com/ITSPublicDL",
                        [_bill(2023, 219.16), _bill(2024, 203.59), _bill(2025, 248.02)])
    block = build_block("DL-1", "NC", "Duplin", src, today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024, 2025]
    assert block["unpaid_bill_years"] == 3
    assert block["consecutive_years"] == 3
    assert block["total_due"] == 670.77
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"]
    assert "ITSPublicDL" in block["source_url"]
    # nc_its_public_tax.delinquent_years() only ever asks for years already past their
    # delinquent date, so every one of these is matured.
    assert block["years_delinquent"] == 3
    assert block["matured_years"] == [2023, 2024, 2025]


def test_build_block_single_year_fails_gate():
    src = _source_block("https://x", [_bill(2025, 50.0)])
    assert build_block("p1", "NC", "Duplin", src, today=TODAY) is None


def test_build_block_ignores_unparseable_or_zero_amount_rows():
    bills = [_bill(2024, 10.0), _bill(2025, 0.0), {"year": None, "balance": 5.0}, _bill(2023, 12.0)]
    src = _source_block("https://x", bills)
    block = build_block("p1", "NC", "Duplin", src, today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024]  # 2025 ($0) and the yearless row are dropped


def test_build_block_duplicate_year_keeps_larger_not_sum():
    bills = [_bill(2024, 10.0), _bill(2024, 40.0), _bill(2023, 5.0)]
    src = _source_block("https://x", bills)
    block = build_block("p1", "NC", "Duplin", src, today=TODAY)
    assert block is not None
    assert block["per_year"]["2024"] == 40.0
    assert block["total_due"] == 45.0


def test_build_block_trend_growing():
    bills = [_bill(2022, 40.0), _bill(2023, 45.0), _bill(2024, 55.0)]
    src = _source_block("https://x", bills)
    block = build_block("p1", "NC", "Duplin", src, today=TODAY)
    assert block["trend"] == "growing"


# ---------------------------------------------------------------------------
# enrich_its_public_multiyear_tax: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_its_public_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_qualifies_real_shaped_row():
    bills = [_bill(2022, 25.0), _bill(2023, 28.0), _bill(2024, 30.0)]
    li = _li(raw={"nc_its_public_tax": _source_block(
        "https://www.bttaxpayerportal.com/ITSPublicDL", bills)})
    stats = enrich_its_public_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 1
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2022, 2023, 2024]


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"years": [1999], "manual": True}
    bills = [_bill(2023, 28.0), _bill(2024, 30.0)]
    li = _li(raw={
        "nc_its_public_tax": _source_block("https://x", bills),
        "multi_year_delinquent_tax": sentinel,
    })
    stats = enrich_its_public_multiyear_tax([li])
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel


def test_enrich_single_year_row_counted_insufficient_not_qualified():
    li = _li(raw={"nc_its_public_tax": _source_block("https://x", [_bill(2025, 12.0)])})
    stats = enrich_its_public_multiyear_tax([li])
    assert stats["eligible"] == 1
    assert stats["qualified"] == 0
    assert stats["insufficient_history"] == 1
    assert "multi_year_delinquent_tax" not in li.raw


def test_enrich_not_county_restricted_runs_on_any_its_public_portal():
    # Onslow, not Duplin -- the gate is the source block's presence, not an allowlist.
    bills = [_bill(2023, 20.0), _bill(2024, 22.0)]
    li = _li(county="Onslow", raw={"nc_its_public_tax": _source_block(
        "https://tax.onslowcountync.gov/ITSPublicON", bills)})
    stats = enrich_its_public_multiyear_tax([li])
    assert stats["qualified"] == 1

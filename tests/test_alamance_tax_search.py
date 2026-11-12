"""enrichment_alamance_tax_search: pure-function tests (build_block / build_mydt_block /
build_two_year_block / _search_term / _confirm_parid), no network. Bill fixtures match the
exact shape _search/one() builds from a real property.spatialest.com/nc/alamance-tax response
(live-verified 2026-10-28, not invented field names)."""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.enrichment_alamance_tax_search import (
    MYDT_KEY, RAW_KEY, TWO_YEAR_KEY, _confirm_parid, _eligible, _search_term, build_block,
    build_mydt_block, build_two_year_block,
)
from foreclosure_scraper.models import Listing

TODAY = date(2026, 10, 28)


def _bill(year: int, status: str, balance: float | None = None) -> dict:
    return {"year": year, "status": status, "balance": balance, "owner_name": "X",
            "taxable_value": None, "account": "1", "situs": "X"}


def test_search_term_cuts_at_co_owner_joiner():
    assert _search_term("OAKLEY TAYLOR & RAGAN OAKLEY") == "OAKLEY TAYLOR"
    assert _search_term("SMITH JOHN / JANE SMITH") == "SMITH JOHN"
    assert _search_term("GHS PROPERTIES LIMITED PARTNER") == "GHS PROPERTIES LIMITED PARTNER"


def test_confirm_parid_matches_on_address_only():
    rows = [
        {"PropertyType": "R", "PARID": 106711, "AssetDescription": "3949 RURAL RETREAT RD"},
        {"PropertyType": "R", "PARID": 999999, "AssetDescription": "100 OTHER ST"},
        {"PropertyType": "search?", "PARID": None, "AssetDescription": "2002 HD MC"},
    ]
    assert _confirm_parid(rows, "3949 Rural Retreat Road") == (106711, "3949 RURAL RETREAT RD")
    assert _confirm_parid(rows, "999 Nowhere Ave") is None
    assert _confirm_parid([], "3949 Rural Retreat Road") is None


def test_build_block_sums_only_unpaid():
    bills = [_bill(2026, "open", 100.0), _bill(2025, "paid in full", 0.0)]
    block = build_block(bills)
    assert block["years_unpaid"] == [2026]
    assert block["balance"] == 100.0
    assert block["taxpayer_of_record"] == "X"
    assert "situs" not in block  # no confirmed_address given -> no fabricated field


def test_build_block_stamps_confirmed_address_as_situs():
    """situs is load-bearing, not cosmetic: it is the ONLY field tax_binding.bind_block() can
    recognize as evidence for this block (no parcel-id registry entry for this block name, no
    row-source relation) -- see test_alamance_tax_bills_survives_scrub_unbound_tax below."""
    bills = [_bill(2026, "open", 100.0)]
    block = build_block(bills, confirmed_address="3949 RURAL RETREAT RD")
    assert block["situs"] == "3949 RURAL RETREAT RD"


def test_alamance_tax_bills_survives_scrub_unbound_tax():
    """Regression test for the live-confirmed 2026-11-05 finding: without 'situs', tax_binding's
    Pass 0 (scrub_unbound_tax) strips raw['alamance_tax_bills'] as 'no_evidence' -- this vendor's
    PARID is never registered in tax_binding.BLOCK_PARCEL_FIELDS (and never the board's own
    parcel_id either way, see the module docstring), and this enrichment attaches to rows from
    ANY original scraper, so no row-source relation exists -- BEFORE enrich_tax_owed()'s Pass B
    ever runs, so tax_owed/tax_aging_surfaced never derive. With 'situs' stamped (the exact
    address _confirm_parid() already matched), bind_block() resolves 'own_address' and the block
    is kept."""
    from foreclosure_scraper import tax_binding

    li = Listing(source="counties_generic.liensnc", source_url="https://x", state="NC",
                 county="Alamance", street_address="3949 Rural Retreat Road",
                 parcel_id="8844451684")
    bills = [_bill(2026, "open", 100.0)]

    unbound_block = build_block(bills)  # pre-fix shape: no confirmed_address
    assert tax_binding.bind_block(li, RAW_KEY, unbound_block) == "no_evidence"

    bound_block = build_block(bills, confirmed_address="3949 RURAL RETREAT RD")
    assert tax_binding.bind_block(li, RAW_KEY, bound_block) == "own_address"


def test_build_mydt_block_none_below_min_years():
    assert build_mydt_block([_bill(2026, "open", 50.0)], today=TODAY) is None


def test_build_mydt_block_none_when_nothing_matured():
    bills = [_bill(2026, "open", 50.0), _bill(2027, "open", 60.0)]
    assert build_mydt_block(bills, today=TODAY) is None


def test_build_mydt_block_qualifies_and_sums_known_amounts():
    bills = [_bill(2023, "open", 100.0), _bill(2024, "partially paid", None),
             _bill(2025, "paid in full", 0.0)]
    block = build_mydt_block(bills, today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024]
    assert block["total_due"] == 100.0
    assert block["amount_known"] is True


def test_build_two_year_block_unconditional():
    assert build_two_year_block([_bill(2026, "paid in full", 0.0)], today=TODAY)["is_two_year_plus"] is False
    bills = [_bill(2021, "open", 10.0), _bill(2022, "open", 10.0)]
    block = build_two_year_block(bills, today=TODAY)
    assert block["is_two_year_plus"] is True
    assert block["oldest_year"] == 2021


def test_eligible_requires_alamance_owner_name_and_not_already_done():
    li = Listing(source="t", source_url="https://x", state="NC", county="Alamance",
                 owner_name="SMITH JOHN")
    assert _eligible(li) is True
    other_county = Listing(source="t", source_url="https://x", state="NC", county="Wake",
                           owner_name="SMITH JOHN")
    assert _eligible(other_county) is False
    no_owner = Listing(source="t", source_url="https://x", state="NC", county="Alamance")
    assert _eligible(no_owner) is False
    done = Listing(source="t", source_url="https://x", state="NC", county="Alamance",
                   owner_name="SMITH JOHN", raw={RAW_KEY: {}})
    assert _eligible(done) is False

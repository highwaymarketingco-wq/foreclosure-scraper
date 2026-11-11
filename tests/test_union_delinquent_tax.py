"""counties_nc.union_delinquent_tax: pure parsing/grouping of the county's Granicus CSV export
("Property Display Name, Property Key, Year, Primary Source, Balance Due") into one Listing
per real-estate parcel, plus the shared multi_year_delinquent_tax block for parcels that clear
the >=2-matured-year gate (reusing enrichment_ptscloud_multiyear_tax.build_block unchanged).

Row shapes below mirror the live 2026-11-11 export exactly (including the "PP" personal-
property noise and the unconfirmed "RR" code), not invented data.
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.scrapers.counties_nc.union_delinquent_tax import (
    _money, build_listings,
)

TODAY = date(2026, 11, 11)


def _row(name: str, key: str, year: str, source: str, due: str) -> dict:
    return {"Property Display Name": name, "Property Key": key, "Year": year,
            "Primary Source": source, "Balance Due": due, "": ""}


def test_money_parses_dollar_and_comma():
    assert _money("$16,882.45") == 16882.45
    assert _money("") is None
    assert _money(None) is None
    assert _money("$0.00") is None  # zero/negative balances are not a lead


def test_build_listings_excludes_personal_property():
    rows = [_row("CGL GRADING LLC", "408394", "2019", "PP", "$25,058.57")]
    out = build_listings(rows, today=TODAY)
    assert out == []


def test_build_listings_excludes_unconfirmed_source_code():
    """"RR" appeared in the live export (3 of 5,942 rows) with no documented meaning --
    excluded rather than guessed at as real estate."""
    rows = [_row("SOMEONE", "999999", "2024", "RR", "$500.00")]
    out = build_listings(rows, today=TODAY)
    assert out == []


def test_build_listings_single_year_real_estate_no_mydt_block():
    rows = [_row("JONES MARY", "111111", "2025", "RE", "$904.12")]
    out = build_listings(rows, today=TODAY)
    assert len(out) == 1
    li = out[0]
    assert li.county == "Union" and li.state == "NC"
    assert li.parcel_id == "111111"
    assert li.owner_name == "JONES MARY"
    assert li.judgment_amount == 904.12
    assert li.raw["union_delinquent_tax"]["years"] == ["2025"]
    assert "multi_year_delinquent_tax" not in li.raw


def test_build_listings_multi_year_real_estate_qualifies_mydt():
    rows = [
        _row("EVANS WILLIE P HEIRS", "09125043", "2021", "RE", "$1,798.98"),
        _row("EVANS WILLIE P HEIRS", "09125043", "2022", "RE", "$14,355.02"),
        _row("EVANS WILLIE P HEIRS", "09125043", "2023", "RE", "$216.46"),
    ]
    out = build_listings(rows, today=TODAY)
    assert len(out) == 1
    li = out[0]
    assert li.judgment_amount == 16370.46
    mydt = li.raw.get("multi_year_delinquent_tax")
    assert mydt is not None
    assert mydt["years"] == [2021, 2022, 2023]
    assert mydt["years_delinquent"] == 3
    # The reused ptscloud build_block's own hard-coded fallback URL/layers must be
    # overwritten with this source's real values, not left pointing at bcpwa.ncptscloud.com.
    assert mydt["source_url"].startswith("https://www.unioncountync.gov")
    assert mydt["layers"] == ["union_nc_granicus_delinquent_tax_list"]


def test_build_listings_groups_pp_and_re_rows_for_same_parcel_separately():
    """A parcel with BOTH a personal-property row (different tax account, same owner/parcel
    key by coincidence) and a real-estate row must only count the RE rows toward the lead."""
    rows = [
        _row("SAME OWNER LLC", "222222", "2023", "PP", "$9,000.00"),
        _row("SAME OWNER LLC", "222222", "2023", "RE", "$450.00"),
        _row("SAME OWNER LLC", "222222", "2024", "RE", "$460.00"),
    ]
    out = build_listings(rows, today=TODAY)
    assert len(out) == 1
    assert out[0].judgment_amount == 910.0  # 450 + 460, PP excluded


def test_build_listings_zero_balance_row_dropped():
    rows = [_row("PAID OFF LLC", "333333", "2024", "RE", "$0.00")]
    assert build_listings(rows, today=TODAY) == []


def test_main_registers_union_as_dateless_ok():
    """This source is a standing roll with no per-parcel event date; main.py must whitelist
    it or _active_only silently drops every row (same reasoning as every other county
    delinquent-tax source already in DATELESS_OK_SOURCES)."""
    from foreclosure_scraper import main as m
    assert "counties_nc.union_delinquent_tax" in m.DATELESS_OK_SOURCES

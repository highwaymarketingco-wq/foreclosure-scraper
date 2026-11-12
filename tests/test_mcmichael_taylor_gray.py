"""McMichael Taylor Gray — PowerBI iframe row parsing (pure-function tests).

Audited 2026-10-01 as part of the law_firms.* per-source audit batch. NOT
live-verified this session: the live fetch requires a ~5-10 minute headless
Playwright/Scrapling StealthyFetcher render per state (NC + SC), and another
session's patchright driver process was already running on this 8GB Mac with
~64MB free RAM / 3.5GB of 5GB swap in use at audit time — stacking a second
stealth-browser process risks the same OOM/kernel-panic failure mode this
repo's memory has already hit twice (see feedback_one_board_process_8gb).
These tests cover `_parse_row` (the pure row-shape -> Listing conversion,
independent of the browser-scraping half) against the row layout documented
in the module's own docstring, confirmed correct by code review.

No scope self-filter is needed here (unlike ingle_firm.py /
shapiro_ingle_powerbi.py): FORECLOSURE_SALE is a flip-type in main.py's
_FLIP_LISTING_TYPES, so every row this scraper returns is filtered to the
18-county footprint centrally by main._in_scope() -> _county_in_scope() ->
config.in_scope(), regardless of what county the row carries.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.law_firms.mcmichael_taylor_gray import _parse_row


def test_nc_row_with_sp_case_number():
    cells = [
        "Select Row", "NC", "Rutherford County", "10/15/2026", "MTG-12345",
        "26 SP000484-000", "747 Hidden Springs Road, West Jefferson, NC, 28694", "$125,000",
    ]
    li = _parse_row(cells, "law_firms.mcmichael_taylor_gray")
    assert li is not None
    assert li.state == "NC"
    assert li.county == "Rutherford"
    assert li.street_address == "747 Hidden Springs Road"
    assert li.city == "West Jefferson"
    assert li.zip_code == "28694"
    assert li.case_number == "26 SP000484-000"  # NC SP case# preferred over internal file#
    assert li.opening_bid == 125000.0
    assert li.raw["mtg_file"] == "MTG-12345"


def test_sc_row_falls_back_to_internal_file_number():
    cells = [
        "Select Row", "SC", "Spartanburg County", "11/1/2026", "MTG-99999",
        "", "123 Main St, Spartanburg, SC, 29301", "",
    ]
    li = _parse_row(cells, "law_firms.mcmichael_taylor_gray")
    assert li is not None
    assert li.state == "SC"
    assert li.case_number == "MTG-99999"  # no SP case# for SC -> internal file#
    assert li.opening_bid is None


def test_composite_county_split_on_hyphen():
    """PowerBI emits 'Guilford-Forsyth' composites — keep the first."""
    cells = [
        "Select Row", "NC", "Guilford-Forsyth", "10/15/2026", "MTG-1",
        "26SP000001-000", "1 Main St, Greensboro, NC, 27401", "",
    ]
    li = _parse_row(cells, "law_firms.mcmichael_taylor_gray")
    assert li.county == "Guilford"


def test_mcdowell_source_casing_normalized_to_canonical_spelling():
    """Live-verified 2026-10-04: the real PowerBI data itself emits this
    county cell as "Mcdowell" (source-side typo, not introduced by our
    code). A bare .title() does nothing to fix that spelling (it's already
    title-case), so the row would silently miss every enrichment keyed on
    the exact string "McDowell" (config.NC_COUNTIES' own canonical
    spelling). normalize_county must recover it regardless of source
    casing."""
    cells = [
        "Select Row", "NC", "Mcdowell", "8/27/2026", "25-000931-01",
        "25 SP 000063-580", "195 Old River Road, Marion, NC, 28752", "$49,472.39",
    ]
    li = _parse_row(cells, "law_firms.mcmichael_taylor_gray")
    assert li.county == "McDowell"  # not "Mcdowell"

    # Also holds for an all-caps or fully-lowercased source variant.
    for variant in ("MCDOWELL", "mcdowell", "McDOWELL"):
        cells[2] = variant
        li2 = _parse_row(cells, "law_firms.mcmichael_taylor_gray")
        assert li2.county == "McDowell", variant


def test_non_nc_sc_state_rejected():
    cells = ["Select Row", "GA", "Fulton", "10/15/2026", "F1", "", "1 Main St, Atlanta, GA, 30301", ""]
    assert _parse_row(cells, "law_firms.mcmichael_taylor_gray") is None


def test_too_few_cells_rejected():
    assert _parse_row(["Select Row", "NC"], "law_firms.mcmichael_taylor_gray") is None


def test_blank_address_rejected():
    cells = ["Select Row", "NC", "Rutherford", "10/15/2026", "F1", "", "", ""]
    assert _parse_row(cells, "law_firms.mcmichael_taylor_gray") is None


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "law_firms.mcmichael_taylor_gray" in {s.slug for s in all_scrapers()}

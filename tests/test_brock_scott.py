"""Brock & Scott trustee-sale parser — pinned to REAL captures (2026-10-01).

SITE REDESIGN 2026-10-01: the site migrated off `article.foreclosure_search`
card markup to a plain `<table>`, AND off `?sf_paged={N}` query-string
pagination to WordPress's `/page/{N}/` path pagination (the query param is
now silently ignored — confirmed live, it always returns page 1's rows
regardless of N). This had been returning 0 Listings on every run: the old
code's end-of-list check was "zero `article.foreclosure_search` found", and
the new table markup has zero of those on EVERY page, including page 1.

Fixtures are the real `<table>` lifted off
/foreclosure-sales/?_sft_foreclosure_state={nc,sc} (2026-10-01), the 8
columns unchanged (County | Sale Date | State | Court SP # | Case # |
Address | Opening Bid Amt. | Book Page), just in `<td>` cells now instead of
`.forecol` divs. The regressions this file locks in:

  * Address states are SPELLED OUT ("North Carolina"), which a 2-letter-only
    regex could not match.
  * "Opening Bid Amt." is "$0.00" until the bid is published; zero must read
    as unknown, not as a $0 opening bid.
  * `case_number` must be the COURT number (Court SP #), not the firm's
    internal file number, or the SC case-detail and NC court-bid enrichments
    never fire.
  * Deed-of-trust book/page has to survive into raw["rod_docs"].
  * The sale-date cell's machine-readable `<time datetime="...">` attribute
    is used (not a re-parse of the display text), and the `.sale-time` span
    text becomes `sale_time`.
  * Pagination must use the real `/page/{N}/` scheme and must not silently
    truncate on one failed page.
"""
from __future__ import annotations

from pathlib import Path

from selectolax.parser import HTMLParser

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.law_firms.brock_scott import (
    BrockScott,
    _parse_money,
    _parse_row,
    _split_address,
    _split_book_page,
    _table_header_indices,
)

FIX = Path(__file__).parent / "fixtures"
SLUG = "law_firms.brock_scott"


def _rows(name: str, state: str):
    tree = HTMLParser((FIX / name).read_text())
    table = tree.css_first("table")
    cols = _table_header_indices(table)
    page_url = f"https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state={state}"
    return [
        _parse_row(tr, cols, state, SLUG, page_url)
        for tr in table.css("tbody tr")
    ]


# --------------------------------------------------------------------------- #
# address                                                                      #
# --------------------------------------------------------------------------- #
def test_split_address_handles_spelled_out_state():
    street, city, zc = _split_address("105 Coachman Lane   Newport, North Carolina 28570")
    assert (street, city, zc) == ("105 Coachman Lane", "Newport", "28570")


def test_split_address_handles_multiword_city():
    street, city, zc = _split_address("6612 Heron Pt   Myrtle Beach, South Carolina 29588")
    assert (street, city, zc) == ("6612 Heron Pt", "Myrtle Beach", "29588")


def test_split_address_handles_undashed_zip9():
    street, city, zc = _split_address("283 Woodfield Rd   Aiken, South Carolina 298030000")
    assert (street, city, zc) == ("283 Woodfield Rd", "Aiken", "29803")


def test_split_address_accepts_two_letter_state_too():
    street, city, zc = _split_address("12 Main St   Shelby, NC 28150")
    assert (street, city, zc) == ("12 Main St", "Shelby", "28150")


def test_split_address_falls_back_to_street_only_when_tail_is_unparseable():
    street, city, zc = _split_address("Lot 4 Somewhere Rural Tract")
    assert street == "Lot 4 Somewhere Rural Tract"
    assert city is None and zc is None


# --------------------------------------------------------------------------- #
# money + book/page                                                            #
# --------------------------------------------------------------------------- #
def test_zero_opening_bid_reads_as_unknown_not_zero():
    assert _parse_money("$0.00") is None
    assert _parse_money("0") is None
    assert _parse_money("") is None
    assert _parse_money(None) is None


def test_real_opening_bid_parses():
    assert _parse_money("$192,744.81") == 192744.81
    assert _parse_money("131,100.00") == 131100.00


def test_split_book_page():
    assert _split_book_page("08795/0627") == ("08795", "0627")
    assert _split_book_page("2005/45") == ("2005", "45")
    assert _split_book_page("") == (None, None)
    assert _split_book_page(None) == (None, None)


# --------------------------------------------------------------------------- #
# header-driven column mapping (table replaced the old .forecol divs)          #
# --------------------------------------------------------------------------- #
def test_table_header_indices_maps_every_known_column():
    tree = HTMLParser((FIX / "brock_scott_nc_page.html").read_text())
    cols = _table_header_indices(tree.css_first("table"))
    assert cols == {
        "county": 0, "sale_date": 1, "state": 2, "court_case": 3,
        "firm_file_no": 4, "address": 5, "bid": 6, "book_page": 7,
    }


# --------------------------------------------------------------------------- #
# end-to-end parse of the real table markup                                    #
# --------------------------------------------------------------------------- #
def test_nc_row_parses_every_field():
    rows = _rows("brock_scott_nc_page.html", "nc")
    cumberland = rows[0]
    assert cumberland.state == "NC"
    assert cumberland.county == "Cumberland"
    assert cumberland.street_address == "8105 Dunholme Dr"
    assert cumberland.city == "Fayetteville"
    assert cumberland.zip_code == "28304"
    assert cumberland.opening_bid == 192744.81
    assert cumberland.listing_type is ListingType.FORECLOSURE_SALE
    # Court SP #, NOT the 26-04342-FC01 firm file number.
    assert cumberland.case_number == "26SP000590-250"
    assert "26-04342-FC01" in cumberland.description
    assert cumberland.sale_date is not None
    assert cumberland.sale_date.strftime("%Y-%m-%d") == "2026-09-30"
    assert cumberland.sale_time == "1:30 PM"
    assert cumberland.raw.get("rod_docs") == [{
        "doc_type": "DEED OF TRUST", "book": "08795", "page": "0627",
        "amount": None, "recorded_date": None,
        "county": "Cumberland", "state": "NC", "source": SLUG,
    }]


def test_nc_zero_bid_row_reads_as_none():
    rows = _rows("brock_scott_nc_page.html", "nc")
    edgecombe = next(r for r in rows if r.county == "Edgecombe")
    assert edgecombe.opening_bid is None
    assert edgecombe.case_number == "25SP001047-320"


def test_nc_footprint_county_present_and_parsed():
    """Gaston is one of the 11 in-footprint NC counties."""
    rows = _rows("brock_scott_nc_page.html", "nc")
    gaston = next(r for r in rows if r.county == "Gaston")
    assert gaston.street_address == "408 Oakdale St"
    assert gaston.city == "Gastonia"


def test_sc_row_uses_the_cp_docket_as_case_number():
    rows = _rows("brock_scott_sc_page.html", "sc")
    richland = rows[0]
    assert richland.state == "SC"
    assert richland.county == "Richland"
    assert richland.case_number == "2025-CP-40-06856"
    assert richland.city == "Irmo"
    assert richland.zip_code == "29063"


def test_sc_footprint_counties_present_and_parsed():
    """Oconee, Pickens, and Spartanburg are in-footprint SC counties."""
    rows = _rows("brock_scott_sc_page.html", "sc")
    counties = {r.county for r in rows}
    assert {"Oconee", "Pickens", "Spartanburg"} <= counties
    pickens = [r for r in rows if r.county == "Pickens"]
    assert len(pickens) == 3
    assert all(r.street_address for r in pickens)


def test_source_url_is_unique_per_row():
    rows = _rows("brock_scott_nc_page.html", "nc")
    urls = {r.source_url for r in rows}
    assert len(urls) == len(rows)
    assert all(u.startswith("https://www.brockandscott.com/foreclosure-sales/") for u in urls)
    assert all("#case-" in u for u in urls)


# --------------------------------------------------------------------------- #
# footprint gate                                                               #
# --------------------------------------------------------------------------- #
def test_footprint_gate_keeps_in_scope_rows():
    from foreclosure_scraper.scrapers.law_firms._footprint import in_footprint, keep

    nc = _rows("brock_scott_nc_page.html", "nc")
    sc = _rows("brock_scott_sc_page.html", "sc")
    kept = [r for r in nc + sc if keep(r.county, r.state)]
    in_scope = [r for r in kept if in_footprint(r.county, r.state)]
    # Gaston NC + Oconee/Pickens(x3)/Spartanburg(x3) SC are the real
    # in-footprint rows on these two live-captured pages.
    assert {r.county for r in in_scope} >= {"Gaston", "Oconee", "Pickens", "Spartanburg"}


# --------------------------------------------------------------------------- #
# pagination: real /page/{N}/ scheme, must not silently truncate               #
# --------------------------------------------------------------------------- #
def test_page_url_uses_path_pagination_not_the_ignored_query_param():
    assert BrockScott._page_url("nc", 1) == (
        "https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=nc"
    )
    assert BrockScott._page_url("nc", 3) == (
        "https://www.brockandscott.com/foreclosure-sales/page/3/?_sft_foreclosure_state=nc"
    )


def test_pagination_skips_a_failed_page_instead_of_truncating(monkeypatch):
    """A single 429 mid-crawl used to `break` and ship a partial state as final.

    Pages are directly addressable, so a hard-failed page is skipped and
    paging continues; only a successfully-fetched EMPTY tbody ends the state.
    """
    nc_html = (FIX / "brock_scott_nc_page.html").read_text()
    empty_html = "<html><body><table><thead><tr><th>County</th></tr></thead><tbody></tbody></table></body></html>"
    calls: list[tuple[str, int]] = []

    async def fake_page(self, state, page):
        calls.append((state, page))
        if page == 2:
            return None                      # simulate the 429
        if page <= 3:
            return HTMLParser(nc_html)
        return HTMLParser(empty_html)

    monkeypatch.setattr(BrockScott, "_page", fake_page)

    import asyncio

    rows = asyncio.run(_collect(BrockScott()))
    # Page 2 failed but pages 1 and 3 were still collected for BOTH states.
    assert ("nc", 3) in calls and ("sc", 3) in calls
    # Each successful page is the same 20-row NC fixture parsed twice (pages
    # 1 and 3) for both state passes; only the in-footprint rows survive
    # `keep()`. Just assert it's non-empty and bounded (no infinite pagination).
    assert 0 < len(rows) < 200


def test_all_pages_failing_raises_so_the_run_reports_blocked(monkeypatch):
    async def always_fail(self, state, page):
        return None

    monkeypatch.setattr(BrockScott, "_page", always_fail)

    import asyncio

    import pytest

    with pytest.raises(RuntimeError, match="every page fetch failed"):
        asyncio.run(_collect(BrockScott()))


async def _collect(scraper):
    return list(await scraper.fetch())

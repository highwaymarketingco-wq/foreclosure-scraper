"""Hutchens / Foundation Legal Group grid parser — pinned to REAL captures.

Fixtures are the verbatim header row, the grid's own "Displaying page 1 of 1"
pager row, and six data rows from each of NCfcSalesList.aspx and
SCfcSalesList.aspx (captured 2026-07-31). The regressions they lock in:

  * "Bid upset 04/03/2024, increasing bid to $746,000.00" — the old
    digit-anywhere regex read "04" out of the upset DATE and stored a $4.00
    opening bid on all 26 live rows shaped like this.
  * `case_number` must be the COURT number (NC SP# / SC Case Docket#), not the
    firm's internal "Case No." — enrichment_case_detail matches SC on
    `\\d{4}-CP-\\d{2}-\\d{4,6}` and enrichment_court_bid matches NC on the SP
    pattern, so the firm file number blocks both.
  * The NC and SC grids have DIFFERENT column counts (SC adds Deficiency), so
    columns are resolved from the header row rather than fixed indices.
  * Deed-of-trust book/page (incl. "R "/"MO "/"Volume " prefixes) has to survive
    into raw["rod_docs"].
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.law_firms.hutchens import (
    Hutchens,
    _parse_bid,
    _parse_csz,
    _split_book_page,
)

FIX = Path(__file__).parent / "fixtures"
NC_URL = "https://sales.hutchenslawfirm.com/NCfcSalesList.aspx"
SC_URL = "https://sales.hutchenslawfirm.com/SCfcSalesList.aspx"


def _grid(name: str, url: str, state: str):
    """-> (rows_scraped, kept_listings) straight off the fixture."""
    return Hutchens()._parse_grid((FIX / name).read_text(), url, state)


# --------------------------------------------------------------------------- #
# bid parsing — the $4.00 bug                                                  #
# --------------------------------------------------------------------------- #
def test_upset_bid_text_does_not_yield_the_date_as_the_bid():
    amount, upset = _parse_bid("Bid upset 04/03/2024, increasing bid to $746,000.00")
    assert amount == 746000.00           # was 4.0 before the fix
    assert upset == "04/03/2024"


def test_plain_dollar_bid_parses():
    assert _parse_bid("$49,489.91") == (49489.91, None)


def test_bid_not_available_is_none():
    assert _parse_bid("Bid not available yet") == (None, None)
    assert _parse_bid("") == (None, None)
    assert _parse_bid(None) == (None, None)


def test_bare_number_without_dollar_sign_is_not_treated_as_a_bid():
    # Only a $-anchored figure is a bid; free text with digits must not leak in.
    assert _parse_bid("Postponed to 10/06/2026") == (None, None)


# --------------------------------------------------------------------------- #
# small parsers                                                                #
# --------------------------------------------------------------------------- #
def test_parse_csz():
    assert _parse_csz("Yadkinville, NC 27055") == ("Yadkinville", "27055")
    assert _parse_csz("Fuquay Varina, NC 27526") == ("Fuquay Varina", "27526")
    assert _parse_csz("nonsense") == (None, None)


def test_split_book_page_keeps_book_prefixes():
    assert _split_book_page("1241 / 2") == ("1241", "2")
    assert _split_book_page("R 8776 / 2360") == ("R 8776", "2360")
    assert _split_book_page("MO 5421 / 1478") == ("MO 5421", "1478")
    assert _split_book_page("Volume 6309 / 320") == ("Volume 6309", "320")
    assert _split_book_page(None) == (None, None)


# --------------------------------------------------------------------------- #
# NC grid                                                                      #
# --------------------------------------------------------------------------- #
def test_nc_grid_skips_header_and_pager_rows():
    scraped, _ = _grid("hutchens_nc_grid.html", NC_URL, "NC")
    assert scraped == 7          # 7 data rows; the "Displaying page 1 of 1" row is not one


def test_nc_row_uses_sp_number_as_case_number():
    _, kept = _grid("hutchens_nc_grid.html", NC_URL, "NC")
    buncombe = [r for r in kept if r.street_address == "16 Overlook Drive"][0]
    assert buncombe.case_number == "22SP000481-100"     # court file, not "4050-14295"
    assert "4050-14295" in buncombe.description
    assert buncombe.county == "Buncombe"
    assert buncombe.state == "NC"
    assert buncombe.city == "Leicester"
    assert buncombe.zip_code == "28748"
    assert buncombe.listing_type is ListingType.FORECLOSURE_SALE
    assert buncombe.sale_date.strftime("%Y-%m-%d") == "2026-08-18"
    assert buncombe.opening_bid is None                 # "Bid not available yet"


def test_nc_book_page_lands_in_rod_docs():
    _, kept = _grid("hutchens_nc_grid.html", NC_URL, "NC")
    buncombe = [r for r in kept if r.street_address == "16 Overlook Drive"][0]
    docs = buncombe.raw["rod_docs"]
    assert docs == [{
        "doc_type": "DEED OF TRUST",
        "book": "4323",
        "page": "52",
        "amount": None,
        "recorded_date": None,
        "county": "Buncombe",
        "state": "NC",
        "source": "law_firms.hutchens",
    }]


def test_nc_footprint_gate_drops_statewide_noise():
    scraped, kept = _grid("hutchens_nc_grid.html", NC_URL, "NC")
    # Yadkin / Avery are out of footprint; Wake / Iredell are explicitly denied.
    assert scraped == 7
    assert sorted(r.county for r in kept) == ["Buncombe", "Buncombe", "Buncombe"]


# --------------------------------------------------------------------------- #
# upset-bid deadline promotion (NC only) — fixed 2026-10-04                    #
# --------------------------------------------------------------------------- #
def test_nc_upset_bid_promotes_structured_deadline():
    """An NC row whose Bid Amount is "Bid upset <date>, increasing bid to $X"
    must set upset_bid_deadline (filed date + 10 days, NCGS §45-21.27) and
    raw["upset_bid"]["source"] = "published" so enrichment_upset_bid.py does
    not derive its own (weaker, sale_date-based) deadline over it."""
    _, kept = _grid("hutchens_nc_grid.html", NC_URL, "NC")
    groton = [r for r in kept if r.street_address == "21 Groton Way"][0]
    assert groton.county == "Buncombe"
    assert groton.opening_bid == 347287.50          # the increased bid, not the filed date
    assert groton.upset_bid_deadline is not None
    assert groton.upset_bid_deadline.strftime("%Y-%m-%d") == "2026-10-02"  # 09/22 + 10 days
    upset = groton.raw["upset_bid"]
    assert upset["source"] == "published"
    assert upset["deadline_iso"].startswith("2026-10-02")
    assert upset["current_bid"] == 347287.50
    assert upset["upset_filed_iso"].startswith("2026-09-22")
    assert upset["court_file"] == "24SP000512-100"


def test_sc_upset_bid_text_does_not_get_an_nc_deadline():
    """SC's post-sale period is not NCGS §45-21.27's statutory 10-day window
    (nothing in this codebase defines an SC equivalent), so an SC "Bid upset"
    row must stay free-text only -- no fabricated upset_bid_deadline. Tested
    directly on the row (the live Greenville example is also footprint-
    dropped, which would make the assertion trivially true for the wrong
    reason if checked only through the filtered `kept` list)."""
    from selectolax.parser import HTMLParser

    from foreclosure_scraper.scrapers.law_firms.hutchens import _header_indices

    html = (FIX / "hutchens_sc_grid.html").read_text()
    tree = HTMLParser(html)
    grid = tree.css_first("table[id*='SalesListGrid']")
    cols = _header_indices(grid)
    row = next(
        r for r in grid.css("tr")
        if not r.css("th") and any("upset" in c.text(strip=True).lower() for c in r.css("td"))
    )
    cells = [c.text(strip=True) for c in row.css("td")]
    li = Hutchens()._row_to_listing(cells, cols, SC_URL, "SC")
    assert li is not None
    assert "upset" in (li.description or "").lower()
    assert li.opening_bid == 746000.00  # the increased bid still parses
    assert li.upset_bid_deadline is None
    assert "upset_bid" not in li.raw


# --------------------------------------------------------------------------- #
# SC grid (different column layout — Deficiency column)                        #
# --------------------------------------------------------------------------- #
def test_sc_grid_column_map_survives_the_extra_deficiency_column():
    scraped, kept = _grid("hutchens_sc_grid.html", SC_URL, "SC")
    assert scraped == 6
    anderson = [r for r in kept if r.county == "Anderson"][0]
    assert anderson.case_number == "2022-CP-04-00760"   # Case Docket#, not "6614-25154"
    assert anderson.street_address == "5 Circle Street"
    assert anderson.city == "La France"
    assert anderson.zip_code == "29656"
    assert anderson.opening_bid == 49489.91
    assert anderson.raw["rod_docs"][0]["book"] == "5947"
    assert "deficiency waived" in anderson.description.lower()


def test_sc_footprint_gate_keeps_in_scope_plus_coastal():
    _, kept = _grid("hutchens_sc_grid.html", SC_URL, "SC")
    # Anderson is in-footprint. Horry (Myrtle Beach) is now excluded per user
    # direction 2026-08-12. Greenville is denied, and Dorchester / Richland /
    # Berkeley are simply out.
    assert sorted(r.county for r in kept) == ["Anderson"]


def test_missing_grid_yields_nothing_without_raising():
    scraped, kept = Hutchens()._parse_grid("<html><body>maintenance</body></html>", NC_URL, "NC")
    assert (scraped, kept) == (0, [])


# --------------------------------------------------------------------------- #
# both lists are pulled, and a total outage is reported as an error            #
# --------------------------------------------------------------------------- #
def test_fetch_pulls_both_nc_and_sc_lists(monkeypatch):
    import asyncio

    seen: list[str] = []
    pages = {
        NC_URL: (FIX / "hutchens_nc_grid.html").read_text(),
        SC_URL: (FIX / "hutchens_sc_grid.html").read_text(),
    }

    async def fake_get_text(url, **kwargs):
        seen.append(url)
        return pages[url]

    monkeypatch.setattr(
        "foreclosure_scraper.scrapers.law_firms.hutchens.get_text", fake_get_text
    )
    rows = asyncio.run(_collect(Hutchens()))
    assert seen == [NC_URL, SC_URL]
    assert sorted(r.county for r in rows) == ["Anderson", "Buncombe", "Buncombe", "Buncombe"]
    assert {r.state for r in rows} == {"NC", "SC"}


def test_both_lists_unreachable_raises_so_the_run_reports_blocked(monkeypatch):
    import asyncio

    import pytest

    async def boom(url, **kwargs):
        raise RuntimeError("HTTP 403")

    async def stealth_boom(url):
        return None

    monkeypatch.setattr(
        "foreclosure_scraper.scrapers.law_firms.hutchens.get_text", boom
    )
    monkeypatch.setattr(
        Hutchens, "_stealth_fetch", staticmethod(stealth_boom)
    )
    with pytest.raises(RuntimeError, match="no grid reachable"):
        asyncio.run(_collect(Hutchens()))


async def _collect(scraper):
    return list(await scraper.fetch())

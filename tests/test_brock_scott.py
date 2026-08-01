"""Brock & Scott trustee-sale parser — pinned to REAL captures (2026-07-31).

The fixtures are verbatim `article.foreclosure_search` nodes lifted off
/foreclosure-sales/?_sft_foreclosure_state={nc,sc}. The regressions they lock in:

  * Address states are SPELLED OUT ("North Carolina"), which the old 2-letter
    regex could not match — city and zip came back null on all 282 live rows.
  * "Opening Bid Amount" is "0.00" until the bid is published; zero must read as
    unknown, not as a $0 opening bid.
  * `case_number` must be the COURT number (Court SP #), not the firm's internal
    file number, or the SC case-detail and NC court-bid enrichments never fire.
  * Deed-of-trust book/page has to survive into raw["rod_docs"].
"""
from __future__ import annotations

from pathlib import Path

from selectolax.parser import HTMLParser

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.law_firms.brock_scott import (
    BrockScott,
    _parse_article,
    _parse_money,
    _split_address,
    _split_book_page,
)

FIX = Path(__file__).parent / "fixtures"
SLUG = "law_firms.brock_scott"


def _articles(name: str):
    tree = HTMLParser((FIX / name).read_text())
    return tree.css("article.foreclosure_search")


def _parse(name: str, state: str):
    return [_parse_article(a, state, SLUG) for a in _articles(name)]


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
    # Two live rows carry a 9-digit zip with no dash.
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
    assert _parse_money("0.00") is None
    assert _parse_money("0") is None
    assert _parse_money("") is None
    assert _parse_money(None) is None


def test_real_opening_bid_parses():
    assert _parse_money("192056.41") == 192056.41
    assert _parse_money("131,100.00") == 131100.00


def test_split_book_page():
    assert _split_book_page("164/919") == ("164", "919")
    assert _split_book_page("2005/45") == ("2005", "45")
    assert _split_book_page("") == (None, None)
    assert _split_book_page(None) == (None, None)


# --------------------------------------------------------------------------- #
# end-to-end parse of the real article markup                                  #
# --------------------------------------------------------------------------- #
def test_nc_article_parses_every_field():
    carteret = _parse("brock_scott_nc_page.html", "nc")[0]
    assert carteret.state == "NC"
    assert carteret.county == "Carteret"
    assert carteret.street_address == "105 Coachman Lane"
    assert carteret.city == "Newport"
    assert carteret.zip_code == "28570"
    assert carteret.opening_bid == 192056.41
    assert carteret.listing_type is ListingType.FORECLOSURE_SALE
    # Court SP #, NOT the 25-02977-FC01 firm file number.
    assert carteret.case_number == "25SP001025-150"
    assert "25-02977-FC01" in carteret.description
    assert carteret.sale_date is not None
    assert carteret.sale_date.strftime("%Y-%m-%d") == "2026-07-30"
    assert carteret.sale_time == "02:00:00 PM"
    # This row genuinely has an empty Book Page cell.
    assert carteret.raw.get("rod_docs") is None


def test_sc_article_uses_the_cp_docket_as_case_number():
    cherokee = _parse("brock_scott_sc_page.html", "sc")[0]
    assert cherokee.state == "SC"
    assert cherokee.county == "Cherokee"
    assert cherokee.case_number == "2026-CP-11-00018"
    assert cherokee.city == "Gaffney"
    assert cherokee.zip_code == "29340"


def test_book_page_lands_in_rod_docs():
    harnett = _parse("brock_scott_nc_page.html", "nc")[1]
    docs = harnett.raw.get("rod_docs")
    assert isinstance(docs, list) and len(docs) == 1
    doc = docs[0]
    assert doc["doc_type"] == "DEED OF TRUST"
    assert doc["book"] == "2005"
    assert doc["page"] == "45"
    assert doc["county"] == "Harnett"
    assert doc["state"] == "NC"
    assert doc["source"] == SLUG


def test_source_url_is_unique_per_row():
    rows = _parse("brock_scott_nc_page.html", "nc")
    urls = {r.source_url for r in rows}
    assert len(urls) == len(rows)
    assert all(u.startswith("https://www.brockandscott.com/foreclosure-sales/") for u in urls)


# --------------------------------------------------------------------------- #
# footprint gate                                                               #
# --------------------------------------------------------------------------- #
def test_footprint_gate_keeps_in_scope_and_coastal_drops_the_rest():
    from foreclosure_scraper.scrapers.law_firms._footprint import in_footprint, keep

    nc = _parse("brock_scott_nc_page.html", "nc")   # Carteret, Harnett, Edgecombe
    sc = _parse("brock_scott_sc_page.html", "sc")   # Cherokee, Beaufort, Greenville
    kept = [r for r in nc + sc if keep(r.county, r.state)]
    counties = sorted(r.county for r in kept)
    # Carteret + Beaufort ride the coastal lane; Cherokee SC is in-footprint;
    # Harnett/Edgecombe/Greenville are dropped at parse time.
    assert counties == ["Beaufort", "Carteret", "Cherokee"]
    assert sum(1 for r in kept if in_footprint(r.county, r.state)) == 1


# --------------------------------------------------------------------------- #
# pagination must not silently truncate                                        #
# --------------------------------------------------------------------------- #
def test_pagination_skips_a_failed_page_instead_of_truncating(monkeypatch):
    """A single 429 mid-crawl used to `break` and ship a partial state as final.

    Pages are directly addressable (sf_paged=N), so a hard-failed page is skipped
    and paging continues; only a successfully-fetched EMPTY page ends the state.
    """
    nc_html = (FIX / "brock_scott_nc_page.html").read_text()
    calls: list[tuple[str, int]] = []

    async def fake_page(self, state, page):
        calls.append((state, page))
        if page == 2:
            return None                      # simulate the 429
        if page <= 3:
            return HTMLParser(nc_html)
        return HTMLParser("<html><body></body></html>")

    monkeypatch.setattr(BrockScott, "_page", fake_page)

    import asyncio

    rows = asyncio.run(_collect(BrockScott()))
    # Page 2 failed but pages 1 and 3 were still collected for BOTH states.
    assert ("nc", 3) in calls and ("sc", 3) in calls
    # Fixture holds 3 NC articles; only Carteret survives the gate. Two good
    # pages per state x two states = 4 kept rows.
    assert len(rows) == 4


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

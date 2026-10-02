"""scpublicnotices.com (SC Press Association) parser -- `publicnoticesc.py`.

`tests/fixtures/publicnoticesc_grid.html` is four VERBATIM `<table
class="nested">` result blocks captured live 2026-10-02 against the site's
own "Foreclosures" quick-search preset (statewide, no county ticked -- see
the module docstring for why): Spartanburg (650001, the plaintiff/defendant
caption-boilerplate bug case), Anderson (647355, the street-address
case-number-tail false-positive bug case), Pickens (649998, a real in-
footprint row that is NOT a foreclosure case at all -- an abandoned-vehicle
notice with no court case number), and Charleston (650332, out-of-footprint).
Every assertion below is about a row that actually published.
"""
from __future__ import annotations

from pathlib import Path

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.public_notices import _press_assoc as pa
from foreclosure_scraper.scrapers.public_notices import publicnoticesc as M

_FIXTURE = Path(__file__).parent / "fixtures" / "publicnoticesc_grid.html"
_SLUG = "public_notices.publicnoticesc"


def _rows() -> list[dict]:
    return pa.parse_grid(_FIXTURE.read_text())


def _listings() -> dict[str, object]:
    """notice_id -> Listing|None, keyed for easy lookup per test."""
    return {r["notice_id"]: M._to_listing(r, _SLUG) for r in _rows()}


# ---------------------------------------------------------------- grid read -

def test_parse_grid_reads_every_row():
    rows = _rows()
    assert len(rows) == 4
    by_id = {r["notice_id"]: r for r in rows}
    assert by_id["650001"]["county_meta"] == "Spartanburg"
    assert by_id["650001"]["publication"] == "Herald-Journal"
    assert by_id["650001"]["date_text"] == "Thursday, October 01, 2026"
    assert by_id["647355"]["county_meta"] == "Anderson"
    assert by_id["649998"]["county_meta"] == "Pickens"
    assert by_id["650332"]["county_meta"] == "Charleston"
    for r in rows:
        assert "click 'view' to open the full text" not in r["text"].lower()


def test_pager_labels():
    html = _FIXTURE.read_text()
    assert pa.total_pages(html) == 20
    assert pa.current_page(html) == 1


# -------------------------------------------------------------- footprint --

def test_out_of_footprint_row_is_dropped():
    """Charleston is not one of the 7 footprint counties -- dropped even
    though it is a real, well-formed foreclosure notice with a case number.
    This client-side gate on the grid's own County: field stands in for the
    server-side county checkbox filter, which does not reliably restrict
    keyword-search results (see module docstring)."""
    listings = _listings()
    assert listings["650332"] is None


def test_every_emitted_listing_is_in_the_seven_county_footprint_and_sc():
    listings = [li for li in _listings().values() if li]
    assert listings
    assert {li.county for li in listings} <= set(M.FOOTPRINT)
    assert {li.state for li in listings} == {"SC"}


# ------------------------------------------------------- relevance gate ----

def test_no_case_number_noise_row_is_dropped():
    """649998 is a real Pickens row from the "Foreclosures" preset's own
    result set (the site's OR-keyword match ran against the full body, which
    we can't see), but its preview is an abandoned-VEHICLE notice with no SC
    court case number at all. Requiring a case number is what keeps this
    scraper from reporting a towed car as a foreclosure case."""
    row = next(r for r in _rows() if r["notice_id"] == "649998")
    assert "vehicle" in row["text"].lower()
    assert M._CASE_RE.search(row["text"]) is None
    assert M._to_listing(row, _SLUG) is None


def test_classify_requires_a_case_number_regardless_of_sale_language():
    sale_text = "NOTICE OF SALE will sell to the highest bidder at public auction."
    assert M._classify(sale_text, None) is None
    assert M._classify(sale_text, "2025-CP-04-02240") == (ListingType.FORECLOSURE_SALE, "sale")
    filed_text = "SUMMONS AND NOTICE OF FILING OF COMPLAINT, no sale scheduled yet."
    assert M._classify(filed_text, "2026-CP-04-00334") == (ListingType.LIS_PENDENS, "filed")


# ------------------------------------------------------------ real rows ----

def test_lis_pendens_classified_and_case_number_normalized():
    li = _listings()["650001"]
    assert li is not None
    assert li.listing_type is ListingType.LIS_PENDENS
    assert li.county == "Spartanburg"
    assert li.state == "SC"
    assert li.case_number == "2026CP4204581"
    assert li.foreclosure_process == "judicial"
    assert li.source_url == "https://www.scpublicnotices.com/Details.aspx?ID=650001"


def test_plaintiff_does_not_swallow_the_case_number_preamble():
    """Real text: 'STATE OF SOUTH CAROLINA, COUNTY OF SPARTANBURG; IN THE
    COURT OF COMMON PLEAS; CASE NO. 2026CP4204581 FIRST PIEDMONT FEDERAL
    SAVINGS AND LOAN ASSOCIATION, PLAINTIFF V. ...'. Before the
    _LEADING_CASE_NO_RE fix, _tidy_party() returned the whole 'CASE NO.
    2026CP4204581 FIRST PIEDMONT...' string -- a wrong value in a real
    listing, this codebase's defining failure mode."""
    li = _listings()["650001"]
    assert li.plaintiff == "FIRST PIEDMONT FEDERAL SAVINGS AND LOAN ASSOCIATION"
    assert "CASE NO" not in (li.plaintiff or "")
    assert "2026CP4204581" not in (li.plaintiff or "")


def test_defendant_captured_across_a_k_a_slashes():
    """_DEFENDANT_RE's capture class must allow '/' or the match dies at the
    first A/K/A in a real multi-alias defendant name."""
    li = _listings()["650001"]
    assert li.defendant is not None
    assert li.defendant.startswith("CARLA FRANCES CAVANAGH HOWARD")
    assert "A/K/A" in li.defendant
    assert li.owner_name == li.defendant  # mirrored per ncpublicnotices.py convention


def test_foreclosure_sale_classified_with_decree_language():
    li = _listings()["647355"]
    assert li is not None
    assert li.listing_type is ListingType.FORECLOSURE_SALE
    assert li.county == "Anderson"
    assert li.case_number == "2025-CP-04-02240"
    assert li.raw["public_notice"]["foreclosure_signal"] is True


def test_case_number_tail_is_not_fabricated_as_a_street_address():
    """Real text: 'C/A No: 2025-CP-04-02240 BY VIRTUE OF A DECREE of the
    Court of Common Pleas for Anderson County...'. Before the fix,
    street_address came back '02240 BY VIRTUE OF A DECREE of the Court' --
    the case number's own trailing digits read as a house number. The
    preview is truncated well before any real address, so the correct
    result is None, not a wrong one."""
    li = _listings()["647355"]
    assert li.street_address is None


# --------------------------------------------------- regex unit coverage --

def test_case_re_matches_hyphenated_concatenated_and_embedded_forms():
    assert M._CASE_RE.search("CASE NO. 2026CP4204581 FIRST").group(1) == "2026CP4204581"
    assert M._CASE_RE.search("C/A No: 2025-CP-04-02240 BY VIRTUE").group(1) == "2025-CP-04-02240"
    assert M._CASE_RE.search("DOCKETNO.2026CP1004189PennyMac").group(1) == "2026CP1004189"


def test_tidy_party_strips_leading_case_number_preamble():
    raw = "CASE NO. 2026CP4204581 FIRST PIEDMONT FEDERAL SAVINGS AND LOAN ASSOCIATION"
    assert M._tidy_party(raw) == "FIRST PIEDMONT FEDERAL SAVINGS AND LOAN ASSOCIATION"


def test_tidy_party_rejects_too_short_or_too_long():
    assert M._tidy_party("Jo") is None
    assert M._tidy_party("X" * 200) is None
    assert M._tidy_party(None) is None
    assert M._tidy_party("12345") is None  # no letters


def test_plausible_address_rejects_decree_boilerplate_but_accepts_a_real_street():
    assert M._plausible_address("00543 BY VIRTUE OF A DECREE of the Court") is False
    assert M._plausible_address("118 Sycamore Lane") is True
    assert M._plausible_address(None) is False


def test_addr_re_does_not_match_a_case_number_tail():
    text = "C/A No: 2025-CP-37-00543 BY VIRTUE OF A DECREE of the Court of Common Pleas"
    assert M._ADDR_RE.search(text) is None


def test_addr_re_matches_a_real_short_street_mention():
    text = "the property commonly known as 118 Sycamore Lane will be sold"
    m = M._ADDR_RE.search(text)
    assert m is not None
    assert m.group(1) == "118 Sycamore Lane"


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers

    assert _SLUG in {s.slug for s in all_scrapers()}

"""scripts/scrape_liensnc.py address extraction.

Board audit 2026-09-23 joined every liensnc row against its own parcel_id's
county parcel-cache situs and found 655 (counties_generic.liensnc) + 468
(liensnc) disagreements. Pulling real board rows (iter_board_rows) and their
raw['liensnc']['property_text'] traced a real subset of those to a genuine
extraction bug in ADDR_RE: it searches the whole multi-line "Project Property"
cell for the LEFTMOST digit+street-suffix substring, so a lot/subdivision
label that reads like a street ("Lot 3 Watkins St Subdivision") gets matched
before the real numbered site address that follows it in the same cell.

All property_text blobs below are real, pulled live from the published board
2026-09-23 (not fabricated) -- entry numbers and PINs included so they can be
cross-checked. Most liensnc mismatches are NOT this bug (see the scraper's
docstring / the audit report for the dominant causes: parcel_id attached by a
downstream address resolver that sometimes lands on a neighbour's parcel, and
new-construction addresses that predate the county's own GIS addressing) --
this file only covers the piece that is actually a scraper parsing bug.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scrape_liensnc as sl  # noqa: E402


def test_lot_subdivision_label_no_longer_shadows_real_address():
    """Entry #2666449 (Wake County, filed 08/26/2026): the cell opens with
    'Lot 3 Watkins St Subdivision', whose embedded 'St' reads as a street
    suffix, matching '3 Watkins St' before the parser ever reaches the real
    site address '1900 Watkins St Raleigh'. On the live board this shipped as
    street_address '3 Watkins St' with parcel_id 1714359804 (correctly
    extracted, from the explicit 'pin 1714359804' line) -- whose OWN county
    parcel-cache situs is '1900 WATKINS ST', proving the parcel was right and
    only the address was wrong."""
    property_text = (
        "Lot 3 Watkins St Subdivision \n"
        "pin 1714359804\n"
        "BOM 2023 PG 1522\n"
        "1900 Watkins St Raleigh\n"
        "Raleigh ,\n"
        "                            \n"
        "                            NC 27604\n"
        "Wake  County"
    )
    assert sl._extract_address(property_text) == "1900 Watkins St"


def test_lot_subdivision_variants_from_windgate_iredell_county():
    """Five liensnc rows on Windgate Way / Windgate (Iredell County) all carry
    the identical 'Lot <N> Windgate' label before their real site address, and
    all five previously landed on the board with the lot label mis-taken as
    the street ('35 Windgate', '33 Windgate', ...). Each one's cache-verified
    correct address follows the 'PIN' line."""
    cases = [
        (
            "Lot 35 Windgate\nPIN\t4658977453.000\n104 Birchfield Drive\n"
            "Mooresville,\n                            \n                            NC 28115\nIredell County",
            "104 Birchfield Drive",
        ),
        (
            "Lot 33 Windgate\nPIN\t4658976353.000\n112 Birchfield Drive\n"
            "Mooresville,\n                            \n                            NC 28115\nIredell County",
            "112 Birchfield Drive",
        ),
        (
            "Lot 31 Windgate\nPIN\t4658978233.000\n109 Birchfield Drive\n"
            "Mooresville,\n                            \n                            NC 28115\nIredell County",
            "109 Birchfield Drive",
        ),
        (
            "Lot 25 Windgate\nPIN \t4668072148.000\n174 WIndgate Way\n"
            "Mooresville,\n                            \n                            NC 28115\nIredell County",
            "174 WIndgate Way",
        ),
        (
            "Lot 7 Windgate\nPIN \t4668070387.000\n165 Windgate Way\n"
            "Mooresville,\n                            \n                            NC 28115\nIredell County",
            "165 Windgate Way",
        ),
    ]
    for property_text, expected in cases:
        assert sl._extract_address(property_text) == expected


def test_clean_single_line_address_still_extracts_unchanged():
    """Entry #2622932 (Mecklenburg County): the cell has no lot/subdivision
    label ahead of the address, just a project name followed by the real
    address on its own line. Must not regress -- this was already correct."""
    property_text = (
        "3290CLT26X - Aurea Station - Retaining Wall Improvements\n"
        "8625 Winter Oaks Ln\n"
        "Charlotte,\n"
        "                            \n"
        "                            NC 28210\n"
        "Mecklenburg County"
    )
    assert sl._extract_address(property_text) == "8625 Winter Oaks Ln"


def test_address_with_trailing_period_preserved():
    """Entry #2666399 (Yadkin County): a deed-reference line precedes the
    address; the address itself keeps a trailing period on the suffix."""
    property_text = (
        "Deed ref: 1423/0442\n"
        "3018 Larry Rd.\n"
        "Boonville,\n"
        "                            \n"
        "                            NC 27011\n"
        "Yadkin County"
    )
    assert sl._extract_address(property_text) == "3018 Larry Rd."


def test_no_line_level_match_falls_back_to_unanchored_search():
    """When no line is a clean address by itself, fall back to the old
    unanchored ADDR_RE search rather than returning nothing -- preserves
    whatever recall the parser already had on cells that don't put the
    address on its own line."""
    property_text = "Notes: survey marker near 15 Main Street per surveyor\nsome other line"
    assert sl.ADDR_RE.search(property_text) is not None  # sanity: the fallback path is exercised
    assert sl._extract_address(property_text) == sl.ADDR_RE.search(property_text).group(1).strip()


def test_parse_results_end_to_end_uses_fixed_extraction():
    """parse_results() (the HTML-table parser) must route through the fixed
    _extract_address(), not the raw ADDR_RE.search() it used to call inline."""
    html = """
    <table class="table-striped">
      <tr><th>Filing</th><th>Filed By</th><th>Project</th><th>Owner</th><th>Related</th></tr>
      <tr>
        <td>Appointment of Lien Agent<br>08/26/2026<br>Entry #: 2666449</td>
        <td>ltbleon</td>
        <td>Lot 3 Watkins St Subdivision \npin 1714359804\n1900 Watkins St Raleigh\nRaleigh, NC 27604</td>
        <td>LTB Construction LLC, 2905 Stubble Field Drive, Raleigh, NC 27613</td>
        <td>No</td>
      </tr>
    </table>
    """
    results = sl.parse_results(html)
    assert len(results) == 1
    assert results[0]["address"] == "1900 Watkins St"
    assert results[0]["entry_number"] == "2666449"

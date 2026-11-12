"""NC DEQ DSCA dry-cleaner facility lists — rebuilt 2026-10-01.

The scraper was disabled since 2026-09-15 because its old target page has no
real site-list table at all (its <tr> regex matched the page's sidebar NAV
table and emitted nav labels as fake contamination-site listings). Rebuilt
against the real downloadable .xlsx workbooks (Active/Inactive + Closed
dry-cleaner facility lists) on the DEQ "site lists/facility inventories"
page.

Workbooks are built in memory with the same structure the live stdlib
reader (_xlsx_stdlib) parses (shared strings + numeric cells), same builder
shape as tests/test_charleston_horry_xlsx.py / test_dillon_delinquent_tax.py
use for the sibling .xlsx sources.
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from foreclosure_scraper.scrapers.counties_nc.nc_deq_dsca import (
    NCDEQDSCA,
    find_excel_links,
    parse_workbook,
)


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def make_xlsx(rows: list[list]) -> bytes:
    sst: list[str] = []

    def sid(t: str) -> int:
        if t not in sst:
            sst.append(t)
        return sst.index(t)

    body = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            if v is None or v == "":
                continue
            ref = f"{_col(c)}{r}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="s"><v>{sid(str(v))}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_xml = f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData></worksheet>'
    sst_xml = (f'<?xml version="1.0"?><sst xmlns="{ns}">'
               + "".join(f"<si><t>{escape(t)}</t></si>" for t in sst) + "</sst>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


ACTIVE_HEADER = ["Facility ID", "County", "Inspector", "Facility Name", "Address",
                 "City", "ZIP", "Service Type", "Inspected", "Generator Status",
                 "# Machines", "# Hal", "# Petro", "# Other"]

ACTIVE_ROWS = [
    ["LIST OF ACTIVE AND INACTIVE DRY CLEANERS - FEBRUARY 2025"],
    ACTIVE_HEADER,
    ["110099C", "Buncombe", "NCC", "Hour Glass Cleaners", "85 Tunnel Road",
     "Asheville", "28805", "Full Service (Active)", 45645, "CESQG", 1, 1, "", ""],
    # Out-of-footprint county must be dropped.
    ["010001C", "Alamance", "JVS", "Boston Cleaners", "2182 N Church Street",
     "Burlington", "27215", "Full Service (Active)", 45645, "CESQG", 1, 1, "", ""],
    ["080005C", "Gaston", "NCC", "Suds Laundromat", "100 Main St",
     "Gastonia", "28052", "Coin-Op Laundromat (Inactive)", 45000, "NA", 1, "", "", ""],
]

CLOSED_HEADER = ["Facility ID", "County", "Inspector", "Facility Name", "Address",
                 "City", "ZIP", "Service Type", "Closed"]
CLOSED_ROWS = [
    ["LIST OF CLOSED DRY CLEANERS - FEBRUARY 2025"],
    CLOSED_HEADER,
    ["110013C", "Buncombe", "NCC", "Oakley Coin Laundry", "788 Fairview Rd",
     "Asheville", "28803-1140", "Coin-Op Laundromat (Full Service Closed)", 42375],
]


def test_parse_workbook_filters_to_footprint_and_captures_fields():
    out = parse_workbook(make_xlsx(ACTIVE_ROWS), "active_inactive", "http://x")
    assert len(out) == 2  # Alamance dropped
    by_name = {li.raw["nc_deq_dsca"]["facility_name"]: li for li in out}
    hg = by_name["Hour Glass Cleaners"]
    assert hg.county == "Buncombe"
    assert hg.street_address == "85 Tunnel Road"
    assert hg.city == "Asheville"
    assert hg.zip_code == "28805"
    assert hg.raw["nc_deq_dsca"]["status"] == "active"
    # 2026-10-03 (HERMES extraction-completeness audit, batch 5): live-sampled
    # 26/26 footprint active_inactive rows carry a machine-type count that
    # was never read. # Hal (halogenated/PERC solvent) is a materially worse
    # contamination signal than # Petro, so it must survive as its own field.
    assert hg.raw["nc_deq_dsca"]["machines"] == 1
    assert hg.raw["nc_deq_dsca"]["machines_hal"] == 1
    assert hg.raw["nc_deq_dsca"]["machines_petro"] is None
    suds = by_name["Suds Laundromat"]
    assert suds.raw["nc_deq_dsca"]["status"] == "inactive"
    assert suds.raw["nc_deq_dsca"]["machines"] == 1
    assert suds.raw["nc_deq_dsca"]["machines_hal"] is None


def test_parse_workbook_closed_list_status_and_zip_plus4_stripped():
    out = parse_workbook(make_xlsx(CLOSED_ROWS), "closed", "http://x")
    assert len(out) == 1
    li = out[0]
    assert li.raw["nc_deq_dsca"]["status"] == "closed"
    assert li.raw["nc_deq_dsca"]["list_kind"] == "closed"
    assert li.zip_code == "28803"  # +4 suffix stripped
    assert li.raw["nc_deq_dsca"]["status_date"] == "2016-01-06"
    # Closed workbook has no machine-count columns at all -- must not fabricate.
    assert li.raw["nc_deq_dsca"]["machines"] is None


def test_parse_workbook_empty_on_bad_header():
    assert parse_workbook(make_xlsx([["not", "a", "real", "sheet"]]), "active_inactive", "http://x") == []


def test_find_excel_links_matches_each_heading_to_its_own_excel_anchor():
    html = (
        '<p>Active and Inactive Drycleaner Facilities '
        '<a href="/waste-management/dwm/sf/dsca/active-and-inactive-drycleaner-facilities-pdf-february-2025/download?attachment">PDF</a> '
        '<a href="/active-and-inactive-drycleaner-facilities-excel-february-2025/download?attachment">EXCEL</a>&nbsp;(February 2025)</p>'
        '<p>Closed Dry-Cleaner Facilities '
        '<a href="/waste-management/dwm/sf/dsca/closed-dry-cleaner-facilities-pdf-february-2025/download?attachment">PDF</a> '
        '<a href="/closed-dry-cleaner-facilities-excel-february-2025/download?attachment">EXCEL</a> (February 2025)</p>'
    )
    links = find_excel_links(html)
    assert links["active_inactive"] == (
        "https://www.deq.nc.gov/active-and-inactive-drycleaner-facilities-excel-february-2025/download?attachment")
    assert links["closed"] == (
        "https://www.deq.nc.gov/closed-dry-cleaner-facilities-excel-february-2025/download?attachment")


def test_find_excel_links_empty_when_headings_absent():
    assert find_excel_links("<p>nothing relevant here</p>") == {}


def test_registered_and_dateless():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.nc_deq_dsca" in {s.slug for s in all_scrapers()}
    assert NCDEQDSCA.slug == "counties_nc.nc_deq_dsca"
    from foreclosure_scraper.main import DATELESS_OK_SOURCES
    assert "counties_nc.nc_deq_dsca" in DATELESS_OK_SOURCES

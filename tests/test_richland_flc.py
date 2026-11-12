"""Tests for Richland County SC FLC-owned-property xlsx parser."""
import zipfile
from io import BytesIO

from foreclosure_scraper.scrapers.counties_sc.richland_flc import parse_flc_xlsx

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _make_xlsx(rows: list[list[str]]) -> bytes:
    """Build a minimal single-sheet xlsx via xl/sharedStrings.xml (the format
    Richland's real file actually uses, confirmed live 2026-09-14) from a
    list of row values, for testing the parser without a real file."""
    shared: list[str] = []

    def _sst_idx(s: str) -> int:
        if s not in shared:
            shared.append(s)
        return shared.index(s)

    sheet_rows = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, val in enumerate(row):
            col = chr(65 + c_idx)
            if val is None:
                continue
            try:
                float(val)
                cells.append(f'<c r="{col}{r_idx}"><v>{val}</v></c>')
            except (TypeError, ValueError):
                idx = _sst_idx(val)
                cells.append(f'<c r="{col}{r_idx}" t="s"><v>{idx}</v></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = (f'<?xml version="1.0"?><worksheet xmlns="{_NS}">'
                 f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    sst_xml = (f'<?xml version="1.0"?><sst xmlns="{_NS}" count="{len(shared)}" '
               f'uniqueCount="{len(shared)}">'
               + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


SAMPLE_ROWS = [
    ["FLC - RICHLAND COUNTY OWNED PROPERTY"],
    ["TAX MAP#", "OWNER NAME", "LOCATION", "OPENING BID"],
    ["01000-03-38-", "RICHLAND CO FORFEITED LAND COMM", "N/S HUBERT SIMPSON RD", "1300"],
    ["09403-04-05-", "RICHLAND CO FORFEITED LAND COMM", "W/S WAGES RD", "1200"],
    ["46239"],
    [],
]


def test_parses_three_real_rows():
    recs = parse_flc_xlsx(_make_xlsx(SAMPLE_ROWS))
    assert len(recs) == 2
    assert recs[0]["parcel"] == "01000-03-38-"
    assert recs[0]["owner"] == "RICHLAND CO FORFEITED LAND COMM"
    assert recs[0]["location"] == "N/S HUBERT SIMPSON RD"
    assert recs[0]["opening_bid"] == 1300.0


def test_skips_header_and_title_rows():
    recs = parse_flc_xlsx(_make_xlsx(SAMPLE_ROWS))
    parcels = {r["parcel"] for r in recs}
    assert "TAX MAP#" not in parcels
    assert "FLC - RICHLAND COUNTY OWNED PROPERTY" not in parcels


def test_skips_stray_trailing_artifact_row():
    """The lone '46239' cell (no owner/location/bid) must not become a record."""
    recs = parse_flc_xlsx(_make_xlsx(SAMPLE_ROWS))
    assert not any(r["parcel"] == "46239" for r in recs)


def test_parcel_number_trailing_hyphen_preserved():
    recs = parse_flc_xlsx(_make_xlsx(SAMPLE_ROWS))
    assert all(r["parcel"].endswith("-") for r in recs)


def test_empty_sheet():
    assert parse_flc_xlsx(_make_xlsx([])) == []

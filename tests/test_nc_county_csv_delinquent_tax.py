"""NC county CSV delinquent-tax extraction-completeness audit (2026-10-03).

Live-pulled New Hanover's real CSV (3,544 rows): header is "Customer Name,
Property ID,Property Location,Bill Year,Bill Number,Total Receivable" --
"Bill Number" (100% filled, the county's own per-year tax-bill id) was read
nowhere. 629 of 1,404 live parcels carry 2+ billing years, so the fix keys
bill numbers by year rather than a flat list to avoid losing the pairing."""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_nc.nc_county_csv_delinquent_tax import (
    COUNTIES,
    _parse_csv,
    _parse_xlsx,
    _to_listing,
)

_COLS = COUNTIES["New Hanover"]["cols"]

# Shape mirrors the real live CSV (owner/parcel/amounts changed).
_CSV_TEXT = (
    "Customer Name,Property ID,Property Location,Bill Year,Bill Number,Total Receivable\n"
    "DOE JOHN,R01000-005-026-016,22 CASTLE FARMS RD,2016,16000250,$324.77 \n"
    "DOE JOHN,R01000-005-026-016,22 CASTLE FARMS RD,2017,17000252,$341.10 \n"
    "SMITH JANE,R02500-003-008-000,1524 ROCK HILL RD,2016,16003059,\"$1,547.16 \"\n"
)


def test_parse_csv_keys_bill_numbers_by_year_not_a_flat_list():
    recs = _parse_csv(_CSV_TEXT, _COLS)
    by_parcel = {r["parcel"]: r for r in recs}
    multi = by_parcel["R01000-005-026-016"]
    assert multi["bill_numbers"] == {"2016": "16000250", "2017": "17000252"}
    single = by_parcel["R02500-003-008-000"]
    assert single["bill_numbers"] == {"2016": "16003059"}


def test_parse_csv_sums_amount_across_years():
    recs = _parse_csv(_CSV_TEXT, _COLS)
    multi = next(r for r in recs if r["parcel"] == "R01000-005-026-016")
    assert round(multi["amount"], 2) == 665.87


def test_to_listing_surfaces_bill_numbers_in_raw():
    rec = _parse_csv(_CSV_TEXT, _COLS)[0]
    li = _to_listing(rec, "New Hanover", COUNTIES["New Hanover"]["url"])
    raw = li.raw["nc_county_csv_delinquent_tax"]
    assert raw["bill_numbers"] == {"2016": "16000250", "2017": "17000252"}
    assert raw["bill_years"] == ["2016", "2017"]


def test_parse_csv_without_bill_number_column_does_not_crash():
    """A county config with no 'bill_number' mapped must still work cleanly."""
    cols_no_bill = {k: v for k, v in _COLS.items() if k != "bill_number"}
    recs = _parse_csv(_CSV_TEXT, cols_no_bill)
    assert recs and all(r["bill_numbers"] == {} for r in recs)


# ---------------------------------------------------------------------------------------------
# 2026-11-17 fixes (gap_matrix "no source known" tax-cluster survey): the county rotated this
# same DocumentCenter URL from CSV to .xlsx, and multi_year_delinquent_tax/two_year_delinquent
# were never stamped from the bill-year set this module already computes.

def _build_xlsx(rows: list[list[str]]) -> bytes:
    """Minimal real .xlsx (stdlib zipfile only) with one sheet, string cells via
    sharedStrings, mirroring the shape _parse_xlsx actually reads."""
    import io
    import zipfile

    strings: list[str] = []
    idx: dict[str, int] = {}

    def sidx(s: str) -> int:
        if s not in idx:
            idx[s] = len(strings)
            strings.append(s)
        return idx[s]

    col_letters = "ABCDEFGHIJ"
    sheet_rows = []
    for r_i, row in enumerate(rows, start=1):
        cells = "".join(
            f'<c r="{col_letters[c_i]}{r_i}" t="s"><v>{sidx(val)}</v></c>'
            for c_i, val in enumerate(row)
        )
        sheet_rows.append(f'<row r="{r_i}">{cells}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" '
        f'uniqueCount="{len(strings)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        zf.writestr("xl/sharedStrings.xml", sst_xml)
    return buf.getvalue()


_XLSX_ROWS = [
    ["Customer Name", "Property ID", "Property Location", "Bill Year", "Bill Number",
     "Total Receivable"],
    ["DOE JOHN", "R01000-005-026-016", "22 CASTLE FARMS RD", "2016", "16000250", "324.77"],
    ["DOE JOHN", "R01000-005-026-016", "22 CASTLE FARMS RD", "2017", "17000252", "341.10"],
    ["SMITH JANE", "R02500-003-008-000", "1524 ROCK HILL RD", "2016", "16003059", "1547.16"],
]


def test_parse_xlsx_matches_parse_csv_for_equivalent_content():
    """The county now serves the identical schema as an .xlsx; the stdlib-only reader must
    aggregate it exactly like _parse_csv does for the same rows."""
    xlsx_recs = {r["parcel"]: r for r in _parse_xlsx(_build_xlsx(_XLSX_ROWS), _COLS)}
    csv_recs = {r["parcel"]: r for r in _parse_csv(_CSV_TEXT, _COLS)}
    assert set(xlsx_recs) == set(csv_recs)
    for parcel, rec in xlsx_recs.items():
        assert rec["years"] == csv_recs[parcel]["years"]
        assert round(rec["amount"], 2) == round(csv_recs[parcel]["amount"], 2)


def test_to_listing_stamps_multi_year_delinquent_tax_on_a_real_2plus_year_parcel():
    rec = next(r for r in _parse_csv(_CSV_TEXT, _COLS) if r["parcel"] == "R01000-005-026-016")
    li = _to_listing(rec, "New Hanover", COUNTIES["New Hanover"]["url"])
    assert li.raw["multi_year_delinquent_tax"]["years_delinquent"] == 2
    assert li.raw["two_year_delinquent"] == {
        "is_two_year_plus": True, "years_delinquent": 2,
        "bill_years": ["2016", "2017"], "source": "nc_county_csv_delinquent_tax",
    }
    assert "_nc_csv_tax_mydt_checked" not in li.raw


def test_to_listing_stamps_checked_not_multi_year_on_a_genuine_1year_parcel():
    """A real 1-year parcel must stay a 'checked' row (gap_matrix.py's own shadow-key
    pattern), never a false multi_year_delinquent_tax hit and never left unchecked."""
    rec = next(r for r in _parse_csv(_CSV_TEXT, _COLS) if r["parcel"] == "R02500-003-008-000")
    li = _to_listing(rec, "New Hanover", COUNTIES["New Hanover"]["url"])
    assert "multi_year_delinquent_tax" not in li.raw
    assert li.raw["_nc_csv_tax_mydt_checked"] is True
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is False

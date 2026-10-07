"""scripts/ingest_county_roll.py + foreclosure_scraper.county_roll: county roll files from
public-records requests into the parcel-cache roll sidecar.

One hand-written fixture per format (CSV, TSV, pipe, fixed-width with a layout, fixed-width
inferred from its header, XLSX, ZIP). Every name, street and number is made up.
"""
from __future__ import annotations

import hashlib
import io
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from foreclosure_scraper import county_roll as cr
from foreclosure_scraper import parcel_cache as pc
from foreclosure_scraper.models import Listing
from foreclosure_scraper.parcel_cache_join import join_listings

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import ingest_county_roll as script  # noqa: E402

HEAD = ["TMS", "ACCOUNT", "OWNER NAME", "OWNER NAME 2", "MAIL ADDR 1", "MAIL CITY", "MAIL STATE",
        "MAIL ZIP", "PROPERTY ADDRESS", "LAND USE", "MARKET VALUE", "ASSESSED VALUE", "ACRES",
        "SQFT", "YEAR BUILT", "BEDROOMS", "FULL BATHS", "HALF BATHS", "SALE DATE", "SALE PRICE",
        "OWNER SSN", "DATE OF BIRTH"]
ROWS = [
    ["045-00-00-012", "A100", "SAMPLE OWNER ONE", "", "77 FICTION AVE", "TRENTON", "NJ", "08601",
     "12 IMAGINARY RD", "RESIDENTIAL", "85,000", "3,400", "0.5", "1200", "1962", "3", "1", "1",
     "03/14/2019", "$40,000", "000-00-0000", "01/01/1950"],
    ["045-00-00-013", "A101", "PRETEND HOLDINGS LLC", "", "PO BOX 9", "KINGSTREE", "SC", "29556",
     "14 IMAGINARY RD", "VACANT", "12,000", "480", "1.2", "", "", "", "", "", "20200101", "0",
     "000-00-0001", "02/02/1960"],
]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path / "cache")
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    pc._CONN_COLS.clear()
    yield
    for k in list(pc._CONN):
        pc._CONN.pop(k).close()
    pc._CONN_COLS.clear()


def _delimited(tmp_path, delim, name):
    import csv
    p = tmp_path / name
    with open(p, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh, delimiter=delim, lineterminator="\n").writerows([HEAD, *ROWS])
    return p


def _fixed_lines():
    widths = [max(len(h), *(len(r[i]) for r in ROWS)) + 3 for i, h in enumerate(HEAD)]
    def line(cells):
        return "".join(str(c).ljust(w) for c, w in zip(cells, widths))
    return [line(HEAD), *(line(r) for r in ROWS)], widths


def _xlsx_bytes(rows):
    def cell(ci, ri, v):
        col = ""
        n = ci + 1
        while n:
            n, rem = divmod(n - 1, 26)
            col = chr(65 + rem) + col
        v = str(v).replace("&", "&amp;").replace("<", "&lt;")
        return f'<c r="{col}{ri}" t="inlineStr"><is><t>{v}</t></is></c>'
    body = "".join(f'<row r="{i + 1}">' + "".join(cell(j, i + 1, v) for j, v in enumerate(r) if v != "")
                   + "</row>" for i, r in enumerate(rows))
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet '
             'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + body + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _check(headers, body, override=None):
    assert "OWNER SSN" in headers                     # the file has it ...
    m = cr.detect_mapping(headers, override)
    roles = m.roles
    assert "OWNER SSN" not in str(roles) and "DATE OF BIRTH" not in str(roles)
    assert set(roles["id"]) == {"TMS", "ACCOUNT"}
    assert roles["owner1"] == "OWNER NAME" and roles["mail_street"] == "MAIL ADDR 1"
    assert roles["mail_zip"] == "MAIL ZIP" and roles["situs"] == "PROPERTY ADDRESS"
    assert roles["year_built"] == "YEAR BUILT" and roles["baths_half"] == "HALF BATHS"
    recs = cr.build_records(headers, body, m)
    assert recs.stats["rows"] == 2 and recs.stats["parcels_indexed"] == 2
    flat = repr(recs.rows)
    assert "000-00-0000" not in flat and "1950" not in flat.replace("1950.0", "")  # SSN/DOB never kept
    by_id = {r[0]: r for r in recs.rows}
    r = by_id["0450000012"]
    vals = dict(zip(("id", *pc._COLS), r))
    assert vals["owner_mailing"] == "77 FICTION AVE TRENTON NJ 08601"
    assert vals["market_value"] == 85000.0 and vals["tax_value"] == 3400.0
    assert vals["year_built"] == 1962.0 and vals["bathrooms"] == 1.5 and vals["bedrooms"] == 3.0
    assert vals["sale_date"] == "2019-03-14" and vals["sale_price"] == 40000.0
    assert "a100" in by_id                             # the account number is a key too
    v2 = dict(zip(("id", *pc._COLS), by_id["0450000013"]))
    assert v2["sale_date"] == "2020-01-01" and v2["year_built"] is None
    return recs


@pytest.mark.parametrize("delim,name", [(",", "SC_Williamsburg_roll_2026-11-03.csv"),
                                        ("\t", "roll.tsv"), ("|", "roll.txt")])
def test_delimited_formats(tmp_path, delim, name):
    headers, body, fmt = cr.read_table(_delimited(tmp_path, delim, name))
    assert fmt.startswith("delimited")
    _check(headers, body)


def test_fixed_width_with_a_layout(tmp_path):
    lines, widths = _fixed_lines()
    p = tmp_path / "roll.dat"
    p.write_text("\n".join(lines) + "\n")
    starts = [sum(widths[:i]) for i in range(len(widths))]
    layout = [[h, s, s + w] for h, s, w in zip(HEAD, starts, widths)]
    headers, body, fmt = cr.read_table(p, override={"fixed_width": layout})
    assert fmt == "fixed"
    _check(headers, body)


def test_fixed_width_inferred_from_the_header(tmp_path):
    lines, _w = _fixed_lines()
    p = tmp_path / "roll.prn"
    p.write_text("\n".join(lines) + "\n")
    headers, body, fmt = cr.read_table(p)
    assert fmt == "fixed" and headers[:3] == ["TMS", "ACCOUNT", "OWNER NAME"]
    _check(headers, body)


def test_xlsx(tmp_path):
    p = tmp_path / "roll.xlsx"
    p.write_bytes(_xlsx_bytes([["County roll export"], HEAD, *ROWS]))
    headers, body, fmt = cr.read_table(p)
    assert fmt == "xlsx"
    _check(headers, body)


def test_zip_holding_a_csv(tmp_path):
    csvp = _delimited(tmp_path, ",", "inner.csv")
    z = tmp_path / "SC_Kershaw_roll_2026-11-10.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(csvp, "export/inner.csv")
        zf.writestr("readme.pdf", b"%PDF")
    headers, body, fmt = cr.read_table(z)
    _check(headers, body)
    assert cr.file_date(z) == "2026-11-10"


def test_override_replaces_roles_but_never_admits_a_sensitive_column(tmp_path):
    headers, body, _ = cr.read_table(_delimited(tmp_path, ",", "r.csv"))
    m = cr.detect_mapping(headers, {"id": ["TMS", "OWNER SSN"], "owner1": "OWNER NAME 2",
                                    "year_built": "DATE OF BIRTH"})
    assert m.roles["id"] == ["TMS"] and m.roles["owner1"] == "OWNER NAME 2"
    assert m.roles["year_built"] == "YEAR BUILT"


def test_write_is_idempotent_and_county_names_are_checked(tmp_path):
    headers, body, _ = cr.read_table(_delimited(tmp_path, ",", "r.csv"))
    recs = cr.build_records(headers, body, cr.detect_mapping(headers))
    p1 = cr.write_roll("williamsburg", "SC", recs, "2026-11-03")
    h1 = hashlib.sha256(_dump(p1)).hexdigest()
    p2 = cr.write_roll("Williamsburg", "sc", recs, "2026-11-03")
    assert p1 == p2 and hashlib.sha256(_dump(p2)).hexdigest() == h1
    assert p1.name == "williamsburg.roll.sqlite"
    with pytest.raises(ValueError):
        cr.write_roll("Williamsberg", "SC", recs, "2026-11-03")
    assert cr.write_roll("Beaufort", "SC", recs, "2026-11-03").name == "beaufort_sc.roll.sqlite"


def _dump(p):
    con = sqlite3.connect(p)
    rows = con.execute("SELECT * FROM parcels ORDER BY id").fetchall()
    con.close()
    return repr(rows).encode()


def test_synthetic_board_before_and_after(tmp_path):
    """A synthetic three-row board in a county with no layer cache: the join fills nothing,
    then the roll lands and the same join fills mailing, value and facts on the two matching
    rows (counts only)."""
    def board():
        return [Listing(source="t", source_url="https://example.invalid/x", state="SC",
                        county="Williamsburg", parcel_id=pid, street_address=st)
                for pid, st in (("045-00-00-012", "12 IMAGINARY RD"),
                                ("0450000013", "14 IMAGINARY RD"),
                                ("045-00-00-099", "99 NOWHERE RD"))]
    before_rows = board()
    before = join_listings(before_rows)
    assert before.get("cache HIT", 0) == 0
    csvp = _delimited(tmp_path, ",", "SC_Williamsburg_roll_2026-11-03.csv")
    assert script.main(["--county", "Williamsburg", "--state", "SC", "--file", str(csvp)]) == 0
    after_rows = board()
    after = join_listings(after_rows)
    assert after["cache HIT"] == 2 and after["filled owner mailing"] == 2
    assert after["filled year built"] == 1 and after["filled market value"] == 2
    om = after_rows[0].raw["owner_mailing"]
    assert om["out_of_state"] is True and om["mail_state"] == "NJ"
    assert after_rows[2].raw.get("owner_mailing") is None


def test_dry_run_writes_nothing(tmp_path, capsys):
    csvp = _delimited(tmp_path, ",", "r.csv")
    assert script.main(["--county", "Kershaw", "--state", "SC", "--file", str(csvp), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "sensitive columns dropped unread: 2" in out
    assert "SAMPLE OWNER ONE" not in out and "77 FICTION AVE" not in out
    assert not (pc.CACHE_DIR / "kershaw.roll.sqlite").exists()

"""Minimal stdlib .xlsx reader for the county delinquent-tax spreadsheets.

WHY THIS EXISTS. openpyxl is not a project dependency (horry_flc.py made the same
call and carries a private copy of this logic). A .xlsx is a zip of XML, so the
first worksheet can be read with zipfile + ElementTree, streaming, with no third
party code. The registry skips modules whose name starts with an underscore, so
this helper is never mistaken for a scraper.

The bytes are read from memory only. Callers download the workbook into a bytes
object and hand it here; nothing is written to disk, because the sheets carry
owner names and mailing data that must never land in the repository.

Public API
    read_rows(data: bytes, sheet: int = 1) -> list[list[str]]
        Every row of the chosen worksheet as a dense list of strings ("" for a
        blank cell), trailing blanks trimmed. Dates stay as their Excel serial
        text; use excel_serial_to_date() for the columns known to hold dates.
    header_index(rows, must_have) -> (row_idx, {normalised header: col})
        Find the header row (the first row containing every token in
        `must_have`, matched case-insensitively) and map header text to column.
    excel_serial_to_date(text) -> datetime | None
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
from io import BytesIO
from xml.etree.ElementTree import iterparse

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_COL_RE = re.compile(r"^([A-Z]+)")
_EPOCH = _dt.datetime(1899, 12, 30)


def _col_to_idx(ref: str) -> int:
    m = _COL_RE.match(ref or "A1")
    letters = m.group(1) if m else "A"
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    out: list[str] = []
    if "xl/sharedStrings.xml" not in zf.namelist():
        return out
    with zf.open("xl/sharedStrings.xml") as fh:
        cur: list[str] = []
        in_si = False
        for ev, el in iterparse(fh, events=("start", "end")):
            if el.tag == _NS + "si":
                if ev == "start":
                    cur, in_si = [], True
                else:
                    out.append("".join(cur))
                    in_si = False
                    el.clear()
            elif el.tag == _NS + "t" and ev == "end" and in_si:
                cur.append(el.text or "")
    return out


def _sheet_path(zf: zipfile.ZipFile, sheet: int) -> str | None:
    """Path of the Nth (1-based) worksheet. Uses the numeric suffix so sheet10 does
    not sort before sheet2."""
    sheets = [n for n in zf.namelist()
              if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
    sheets.sort(key=lambda n: int(re.findall(r"(\d+)\.xml$", n)[0]) if re.findall(r"(\d+)\.xml$", n) else 0)
    return sheets[sheet - 1] if 0 < sheet <= len(sheets) else None


def read_rows(data: bytes, sheet: int = 1) -> list[list[str]]:
    """All rows of one worksheet as dense string lists."""
    if not data or data[:2] != b"PK":
        raise ValueError("not an .xlsx (no PK zip header)")
    zf = zipfile.ZipFile(BytesIO(data))
    sst = _shared_strings(zf)
    path = _sheet_path(zf, sheet)
    if not path:
        return []
    rows: list[list[str]] = []
    with zf.open(path) as fh:
        cur: dict[int, str] = {}
        col, ctype = 0, None
        vbuf: list[str] = []
        for ev, el in iterparse(fh, events=("start", "end")):
            tag = el.tag
            if tag == _NS + "row" and ev == "start":
                cur = {}
            elif tag == _NS + "c":
                if ev == "start":
                    col = _col_to_idx(el.get("r") or "A1")
                    ctype = el.get("t")
                    vbuf = []
                else:
                    val = "".join(vbuf)
                    if ctype == "s" and val != "":
                        try:
                            val = sst[int(val)]
                        except (ValueError, IndexError):
                            pass
                    if val != "":
                        cur[col] = val
                    el.clear()
            elif tag == _NS + "v" and ev == "end":
                vbuf.append(el.text or "")
            elif tag == _NS + "is" and ev == "end":
                txt = "".join(t.text or "" for t in el.iter(_NS + "t"))
                if txt:
                    cur[col] = txt
                el.clear()
            elif tag == _NS + "row" and ev == "end":
                width = (max(cur) + 1) if cur else 0
                rows.append([cur.get(i, "") for i in range(width)])
                el.clear()
    return rows


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()


def header_index(rows: list[list[str]], must_have: tuple[str, ...],
                 scan: int = 30) -> tuple[int, dict[str, int]] | None:
    """Locate the header row. Returns (row index, {normalised header text: column})."""
    need = [_norm(m) for m in must_have]
    for i, row in enumerate(rows[:scan]):
        cells = [_norm(c) for c in row]
        if all(any(n in c for c in cells) for n in need):
            return i, {c: j for j, c in enumerate(cells) if c}
    return None


def excel_serial_to_date(text: str | None) -> _dt.datetime | None:
    """'46335' -> datetime(2026, 11, 9). Non-numeric or absurd values return None."""
    if text is None or str(text).strip() == "":
        return None
    try:
        serial = float(str(text).strip())
    except ValueError:
        return None
    if not (20000 < serial < 80000):
        return None
    return _EPOCH + _dt.timedelta(days=int(serial))


def cell(row: list[str], idx: int | None) -> str:
    """Safe cell read: '' for a missing column or a short row."""
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()

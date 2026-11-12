"""Build a minimal, real-shaped .xlsx in memory from a {col_idx: value} row list.

The repo's .gitignore excludes ``*.xlsx``, so a binary workbook fixture would
never ship. Instead the real sheet rows are checked in as JSON and the workbook
is rebuilt here at test time — which has the side benefit of exercising the
scrapers' stdlib zip+iterparse reader against a genuine PK-zip file rather than
a mock.
"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

_NUMERIC = re.compile(r"-?\d+(\.\d+)?$")


def _ref(col: int, row: int) -> str:
    letters = ""
    n = col + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def build_xlsx(rows: list[dict[int, str]]) -> bytes:
    """rows: list of {column_index: cell_value}, in sheet order."""
    sst: dict[str, int] = {}
    xml_rows: list[str] = []
    for r_i, row in enumerate(rows, start=1):
        cells = []
        for col in sorted(row):
            val = row[col]
            ref = _ref(col, r_i)
            if _NUMERIC.match(str(val)):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            else:
                sst.setdefault(str(val), len(sst))
                cells.append(f'<c r="{ref}" t="s"><v>{sst[str(val)]}</v></c>')
        xml_rows.append(f'<row r="{r_i}">{"".join(cells)}</row>')

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{ns}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    )
    strings = "".join(f"<si><t>{escape(s)}</t></si>" for s in sst)
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{ns}" count="{len(sst)}" uniqueCount="{len(sst)}">{strings}</sst>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{ns}"><sheets><sheet name="Sheet1" sheetId="1"/>'
        "</sheets></workbook>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()

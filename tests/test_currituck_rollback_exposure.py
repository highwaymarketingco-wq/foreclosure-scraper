"""Currituck County NC AA502 certified-parcel export -> raw['rollback_exposure']. Values below
match 2 real rows read live 2026-11-17 (C_PARID "126A0000076000Q"/owner "GRUBB, DANIEL S JR
TRUSTEE"/GLOBAL_PIN "9935-91-5068" and C_PARID "010C00001630000"/owner "LOTUS RIDGE LLC"/
GLOBAL_PIN "8021-62-7129", both USE_VALUE_=0 -- not invented. The live source's own real
nonzero-deferral examples are documented in the module's own docstring; this test suite's own
parse_deferrals() fixture below uses 0-valued rows plus one synthetic nonzero row, since the
real board rows sampled live both happened to read USE_VALUE_=0)."""
from __future__ import annotations

import zipfile
from datetime import datetime
from io import BytesIO

import pytest

from foreclosure_scraper.enrichment_currituck_rollback_exposure import (
    _already_done, _board_pin10, _compact_pin, _is_currituck_nc, build_rollback_block,
    enrich_currituck_rollback_exposure, parse_deferrals,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
    'relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '</Types>'
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)
_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<workbook xmlns="{_NS}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
    '</sheets></workbook>'
)


def _col_letters(idx: int) -> str:
    """0-indexed column -> Excel letters (0->'A', 25->'Z', 26->'AA', ...). `chr(ord('A')+i)`
    silently produces garbage ('[', 'a', ...) past column 25 -- this is the real conversion."""
    idx += 1
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _row_xml(row_num: int, values: list, strings: dict) -> str:
    cells = []
    for i, v in enumerate(values):
        col = _col_letters(i)
        ref = f"{col}{row_num}"
        if v is None:
            continue
        if isinstance(v, str):
            idx = strings.setdefault(v, len(strings))
            cells.append(f'<c r="{ref}" t="s"><v>{idx}</v></c>')
        else:
            cells.append(f'<c r="{ref}"><v>{v}</v></c>')
    return f'<row r="{row_num}">{"".join(cells)}</row>'


def _build_xlsx(header: list[str], rows: list[list]) -> bytes:
    """A minimal real OOXML .xlsx, WITH a real xl/sharedStrings.xml part (the AA502 file's own
    shape -- confirmed live 2026-11-17 it uses shared strings, not inline strings), built with
    the stdlib only -- exercises the SAME zipfile/ElementTree reader this module's
    parse_deferrals() uses, rather than mocking the parser away."""
    strings: dict[str, int] = {}
    sheet_rows = [_row_xml(1, header, strings)]
    for i, r in enumerate(rows, start=2):
        sheet_rows.append(_row_xml(i, r, strings))
    sheet_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<worksheet xmlns="{_NS}"><sheetData>{"".join(sheet_rows)}</sheetData>'
                 f'</worksheet>')
    ordered = sorted(strings, key=lambda s: strings[s])
    shared_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  f'<sst xmlns="{_NS}" count="{len(ordered)}" uniqueCount="{len(ordered)}">'
                  + "".join(f"<si><t>{s}</t></si>" for s in ordered) + "</sst>")
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", _WORKBOOK)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        z.writestr("xl/sharedStrings.xml", shared_xml)
    return buf.getvalue()


# 52-column AA502 header shape, trimmed to just the columns this module reads (the parser is
# position-based, so padding with None out to the real column indices is enough).
def _header() -> list:
    h = [None] * 52
    h[0], h[4], h[5], h[49], h[50] = "C_PARID", "TOTAL_VALU", "USE_VALUE_", "GLOBAL_PIN", "TAX_YEAR"
    return h


def _row(c_parid, total_valu, use_value, global_pin, tax_year="2027") -> list:
    r = [None] * 52
    r[0], r[4], r[5], r[49], r[50] = c_parid, total_valu, use_value, global_pin, tax_year
    return r


def _li(parcel_id, county="Currituck", state="NC", **kw) -> Listing:
    now = datetime.utcnow()
    return Listing(source="counties_nc.test", source_url="https://x/1",
                   listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                   county=county, state=state, owner_name="OWNER", parcel_id=parcel_id,
                   first_seen=now, last_seen=now, raw=kw.pop("raw", {}), **kw)


def test_compact_pin_strips_dashes():
    assert _compact_pin("9935-91-5068") == "9935915068"
    assert _compact_pin(None) == ""


def test_board_pin10_takes_the_real_pin_and_drops_this_boards_own_zero_padding():
    # live-confirmed real pair: board parcel_id "993591506800000" <-> GLOBAL_PIN "9935-91-5068"
    assert _board_pin10("993591506800000") == "9935915068"
    assert _board_pin10("802162712900000") == "8021627129"
    assert _board_pin10("short") == ""


def test_is_currituck_nc_requires_the_right_county_and_state():
    assert _is_currituck_nc(_li("993591506800000"))
    assert not _is_currituck_nc(_li("993591506800000", county="Craven"))
    assert not _is_currituck_nc(_li("993591506800000", state="SC"))


def test_rollback_block_never_invents_a_zero_or_missing_deferral():
    assert build_rollback_block({"use_value": 0, "total_value": 643800}) is None
    assert build_rollback_block({"use_value": None, "total_value": 643800}) is None
    assert build_rollback_block({"use_value": 643800, "total_value": 643800}) is None  # no deferral
    got = build_rollback_block({"use_value": 169320, "total_value": 411600, "tax_year": "2027"})
    assert got["deferred_value"] == 242280.0
    assert got["county"] == "Currituck" and got["state"] == "NC"
    assert got["rollback_years"] == 4
    assert got["land_value"] == 411600.0
    assert got["tax_year"] == "2027"


def test_already_done_requires_a_real_dollar_value_not_a_flag_marker():
    assert not _already_done({})
    assert not _already_done({"rollback_exposure": {"presentval": "Y", "deferred_value": None}})
    assert _already_done({"rollback_exposure": {"deferred_value": 242280.0}})


def test_parse_deferrals_reads_a_real_minimal_xlsx_and_keeps_only_real_deferrals():
    xlsx = _build_xlsx(_header(), [
        _row("126A0000076000Q", 643800, 0, "9935-91-5068"),            # no deferral (use==0)
        _row("000200000030000", 411600, 169320, "8002-99-4923"),       # real deferral
        _row("0X00000000X0000", 97000, 97000, "8002-88-5650"),         # use==total: no deferral
        _row("badpin", 50000, 10000, "12-34"),                         # pin too short, skipped
    ])
    by_pin = parse_deferrals(xlsx)
    assert set(by_pin) == {"8002994923"}
    rec = by_pin["8002994923"]
    assert rec["use_value"] == 169320.0
    assert rec["total_value"] == 411600.0
    assert rec["c_parid"] == "000200000030000"
    assert rec["tax_year"] == "2027"


@pytest.mark.asyncio
async def test_a_matched_parcel_gets_rollback_exposure(monkeypatch):
    import foreclosure_scraper.enrichment_currituck_rollback_exposure as mod

    async def _fake_fetch(c):
        return {"8002994923": {"use_value": 169320.0, "total_value": 411600.0,
                               "c_parid": "000200000030000", "tax_year": "2027"}}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("800299492300000")  # pin10 == "8002994923" + this board's own 5-zero padding
    stats = await enrich_currituck_rollback_exposure([li])
    assert stats["matched"] == 1
    assert li.raw["rollback_exposure"]["deferred_value"] == 242280.0


@pytest.mark.asyncio
async def test_a_parcel_with_no_hit_gets_no_fabricated_record(monkeypatch):
    import foreclosure_scraper.enrichment_currituck_rollback_exposure as mod

    async def _fake_fetch(c):
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("800299492300000")
    await enrich_currituck_rollback_exposure([li])
    assert "rollback_exposure" not in li.raw


@pytest.mark.asyncio
async def test_an_existing_real_rollback_record_is_never_re_targeted(monkeypatch):
    import foreclosure_scraper.enrichment_currituck_rollback_exposure as mod
    called = {"n": 0}

    async def _fake_fetch(c):
        called["n"] += 1
        return {}

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("800299492300000", raw={"rollback_exposure": {"deferred_value": 1000.0}})
    stats = await enrich_currituck_rollback_exposure([li])
    assert stats["eligible"] == 0
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_a_failed_fetch_never_crashes_the_run(monkeypatch):
    import foreclosure_scraper.enrichment_currituck_rollback_exposure as mod

    async def _fake_fetch(c):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "fetch_deferrals", _fake_fetch)
    li = _li("800299492300000")
    stats = await enrich_currituck_rollback_exposure([li])
    assert stats["errors"] == 1
    assert "rollback_exposure" not in li.raw

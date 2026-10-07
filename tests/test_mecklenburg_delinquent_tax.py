"""Mecklenburg County NC advertisement of unpaid tax liens (NCGS 105-369), XLSX.

Hand-written fixtures: every name, street and amount is made up. The row shape is
the live workbook's as read on 2026-10-07 -- four cells per row (name, property
address, "$", amount), no header row, sheet name 'IND_ADVERTISEMENT_REGULAR_03-12',
workbook created 2026-03-12. The workbook is rebuilt in memory at test time
(tests/_xlsx_fixture.py) because *.xlsx is git-ignored.
"""
from __future__ import annotations

import asyncio
import zipfile
from io import BytesIO

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc import mecklenburg_delinquent_tax as mod
from foreclosure_scraper.web_artifact import RAW_KEEP

from tests._xlsx_fixture import build_xlsx

ROWS = [
    {0: "TESTPERSON, ALEXANDRA Q", 1: "1511 EXAMPLE AV CHARLOTTE NC 28216", 2: "$", 3: "1250.75"},
    {0: "SAMPLE, ROBERT", 1: "15100   FICTION RD MECKLENBURG", 2: "$", 3: "3513.37"},
    {0: "DOE-NOTREAL, MARY ANN", 1: "88 PRETEND LN MINT HILL NC 28227", 2: "$", 3: "41.30"},
    {0: "PLACEHOLDER, JON", 1: "7 MADEUP CT HUNTERSVILLE", 2: "$", 3: "0.00"},  # nothing owed -> dropped
    {0: "", 1: "", 2: "", 3: ""},                                                  # blank -> dropped
]

SHARE_HTML = (
    '<html><body><a id="download" href="/content/abc123xyz/original/'
    'IND_Taxbills_Advertisement.xlsx?u=zzz111&amp;download=true" '
    'class="toolbarButton download">Download</a></body></html>'
)


def _workbook(rows=ROWS, sheet="IND_ADVERTISEMENT_REGULAR_03-12", created="2026-03-12T12:27:24Z") -> bytes:
    """build_xlsx() plus the two parts the module reads for provenance."""
    base = zipfile.ZipFile(BytesIO(build_xlsx(rows)))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in base.namelist():
            data = base.read(name)
            if name == "xl/workbook.xml":
                data = data.replace(b'name="Sheet1"', f'name="{sheet}"'.encode())
            z.writestr(name, data)
        z.writestr("docProps/core.xml",
                   '<cp:coreProperties xmlns:cp="x" xmlns:dcterms="y">'
                   f'<dcterms:created>{created}</dcterms:created></cp:coreProperties>')
    return buf.getvalue()


def test_split_address_handles_zip_city_and_unincorporated():
    assert mod.split_address("1511 EXAMPLE AV CHARLOTTE NC 28216") == ("1511 EXAMPLE AV", "CHARLOTTE", "28216")
    assert mod.split_address("15100   FICTION RD MECKLENBURG") == ("15100 FICTION RD", None, None)
    assert mod.split_address("88 PRETEND LN MINT HILL NC 28227") == ("88 PRETEND LN", "MINT HILL", "28227")
    assert mod.split_address("7 MADEUP CT HUNTERSVILLE") == ("7 MADEUP CT", "HUNTERSVILLE", None)
    assert mod.split_address("2 NOPLACE ST CHARLOTTE NC 00000") == ("2 NOPLACE ST", "CHARLOTTE", None)
    assert mod.split_address("") == (None, None, None)


def test_download_path_reads_the_share_page_link():
    assert mod.download_path(SHARE_HTML) == (
        "/content/abc123xyz/original/IND_Taxbills_Advertisement.xlsx?u=zzz111&download=true")
    assert mod.download_path("<html>no link</html>") is None


def test_parse_rows_keeps_only_rows_with_an_amount():
    from foreclosure_scraper.scrapers._xlsx_stdlib import read_rows
    recs = mod.parse_rows(read_rows(_workbook()))
    assert [r["total_due"] for r in recs] == [1250.75, 3513.37, 41.30]
    assert recs[0]["owner"] == "TESTPERSON, ALEXANDRA Q"


def test_workbook_meta_reads_sheet_name_and_created_date():
    meta = mod.workbook_meta(_workbook())
    assert meta == {"sheet": "IND_ADVERTISEMENT_REGULAR_03-12", "created": "2026-03-12"}


def test_listing_shape_and_tax_year_from_the_file_date():
    meta = mod.workbook_meta(_workbook())
    rec = {"owner": "TESTPERSON, ALEXANDRA Q", "address": "1511 EXAMPLE AV CHARLOTTE NC 28216",
           "total_due": 1250.75}
    li = mod.build_listing(rec, kind="individual", share_url=mod.LISTS[0][1], meta=meta,
                           now=mod.datetime(2026, 10, 7))
    assert li.listing_type == ListingType.TAX_LIEN
    assert li.foreclosure_process == "tax"
    assert li.owner_name == li.defendant == "TESTPERSON, ALEXANDRA Q"
    assert (li.street_address, li.city, li.zip_code) == ("1511 EXAMPLE AV", "CHARLOTTE", "28216")
    assert li.county == "Mecklenburg" and li.parcel_id is None
    block = li.raw["mecklenburg_delinquent_tax"]
    assert block["total_due"] == 1250.75 and block["tax_year"] == 2025
    assert block["list"] == "individual"
    assert "mecklenburg_delinquent_tax" in RAW_KEEP


class _Resp:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code, self.text, self.content = status_code, text, content


class _Http:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def get(self, url, **kw):
        self.calls.append(url)
        for frag, resp in self.routes.items():
            if frag in url:
                return resp
        return _Resp(404)


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_fetch_follows_share_page_to_workbook_and_skips_a_broken_list(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    http = _Http({
        "/s/vb8vhrwvtm/": _Resp(text=SHARE_HTML),
        "/content/abc123xyz/": _Resp(content=_workbook()),
        "/s/slsnqr9prl/": _Resp(text="<html>moved</html>"),  # business list: no link today
    })
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    rows = asyncio.run(mod.MecklenburgDelinquentTax().fetch())
    assert len(rows) == 3
    assert {li.raw["mecklenburg_delinquent_tax"]["list"] for li in rows} == {"individual"}
    assert http.calls[1] == mod.WIDEN_HOST + "/content/abc123xyz/original/IND_Taxbills_Advertisement.xlsx?u=zzz111&download=true"
    assert len(http.calls) == 3, "two share pages and one workbook, nothing else"


def test_non_xlsx_download_is_ignored(monkeypatch):
    monkeypatch.delenv(mod.ENV_OFF, raising=False)
    http = _Http({
        "/s/vb8vhrwvtm/": _Resp(text=SHARE_HTML),
        "/content/abc123xyz/": _Resp(content=b"<html>error</html>"),
    })
    monkeypatch.setattr(mod, "client", lambda *a, **kw: _Ctx(http))
    assert asyncio.run(mod.MecklenburgDelinquentTax().fetch()) == []

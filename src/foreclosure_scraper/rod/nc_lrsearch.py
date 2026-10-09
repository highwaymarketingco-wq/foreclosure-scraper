"""Courthouse Computer Systems 'LRSearch' (the newer MVC land-records search), Beaufort NC: the name
index, the document-type window search the county-wide lien sweep uses, and the register's own
Marriage index.

Audit 2026-10-09, top-80 build list ranks 31, 49 (Beaufort liens, atty_rod_lien_checked) and 79
(Beaufort marriage licences). The 2026-10-07 cluster note called the county walled ("challenge marker
on the vendor's us5 host"). Re-read 2026-10-09: the county's landing page (/BeaufortNC2/) carries
Cloudflare's passive browser beacon (a script tag to /cdn-cgi/challenge-platform/), which the shared
wall detector reads as a challenge page. It is not one: the search pages answer 200 to an ordinary
browser request with no CAPTCHA, login or challenge. The disclaimer is a client-side dialog (its Accept
button only closes the dialog; no request is made). This adapter never fetches the landing page and
walls the county on the first real challenge, CAPTCHA, login or block exactly as the other adapters do.

THE FLOW (live-checked 2026-10-09)
  1. GET  /BeaufortNC2/LRSearch/LRIndex?searchTabID=0       the search page (session cookie, form defaults)
  2. POST /BeaufortNC2/LRSearch/ExecuteSearch               the Standard form: Last, Given (begins with),
         SearchType 1|2|3 (grantor|grantee|either), FromDate/ToDate, PageSize 500, MaxRecordCount 5000 ->
         an HTML grid; one row per party pair: Doc #, Book, Page, Date, Kind, [R|E] party, [R|E] reverse
         party, Description, prime key. 'Total Records: N Total Documents: D'.
         The Advanced form adds DocTypes (comma list of the county's own codes), AdvancedFromDate /
         AdvancedToDate and the MultiName*/AdvancedDescription* fields it posts empty.
  3. GET  /BeaufortNC2/LRSearch/GetDocTypes                 [[code, name, book type, id], ...] (text)
  4. POST /BeaufortNC2/VRMarriageSearch/ExecuteSearch       the Marriages tab of the same site: last, given,
         PartyType, fromdate, todate -> Date, Applicant 2/1 surname and given, Book, Page, License#,
         Issue Date. Open, no login (unlike Forsyth and Guilford).
Document images are never opened.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from dataclasses import dataclass
from typing import Optional

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "ccs_lrsearch"
ENV_FLAG = "FORECLOSURE_NC_LRSEARCH_ROD"
PAGE_SIZE = 500                  # the grid's largest page size
MAX_RECORDS = 5000               # the form's own MaxRecordCount
_SIDE = {"grantor": "1", "grantee": "2", "both": "3"}
_XHR = {"X-Requested-With": "XMLHttpRequest"}


@dataclass(frozen=True)
class LrCounty:
    base: str                    # .../<Tenant>/ (ends with a slash)


COUNTIES: dict[str, LrCounty] = {
    "Beaufort": LrCounty("https://us5.courthousecomputersystems.com/BeaufortNC2/"),
}


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def form_defaults(page_html: str, form_id: str = "QueryFields_ExecuteSearch") -> dict:
    """Every named input and select of the search form with the value a browser would post (hidden
    inputs, text boxes, the selected option of a select; unchecked boxes left out)."""
    m = re.search(rf'<form[^>]*id="{re.escape(form_id)}".*?</form>', page_html or "", re.S)
    if not m:
        return {}
    form = m.group(0)
    out: dict = {}
    for tag in re.findall(r"<input([^>]*)>", form):
        name = re.search(r'name="([^"]+)"', tag)
        if not name or re.search(r'type="(?:checkbox|radio)"', tag):
            continue
        val = re.search(r'value="([^"]*)"', tag)
        out[name.group(1)] = htmllib.unescape(val.group(1)) if val else ""
    for name, body in re.findall(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', form, re.S):
        sel = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', body) or re.search(r'<option[^>]*value="([^"]*)"', body)
        out[name] = sel.group(1) if sel else ""
    return out


def totals(text: str) -> tuple[Optional[int], Optional[int]]:
    """('Total Records', 'Total Documents') of a results grid."""
    t = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", text or "", flags=re.S)).split())
    m = re.search(r"Total Records:\s*(\d+)\s*Total Documents:\s*(\d+)", t)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _cell(row: str, cls: str) -> str:
    m = re.search(rf'<td[^>]*class="[^"]*\bCell_{cls}\b[^"]*"[^>]*>(.*?)</td>', row, re.S)
    if not m:
        return ""
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).replace("\xa0", " ").split())


def _parties(row: str, cls: str) -> list[tuple[str, str]]:
    """[(role, name)] of a party cell: '[R] SMITH, JOHN' pairs."""
    m = re.search(rf'<td[^>]*class="[^"]*\bCell_{cls}\b[^"]*"[^>]*>(.*?</table>)\s*</td>', row, re.S)
    if not m:
        return []
    cell = m.group(1)
    return [(r.upper(), " ".join(htmllib.unescape(n).split()))
            for r, n in re.findall(r"<b>\[([A-Za-z])\]</b>.*?<span>([^<]*)</span>", cell, re.S) if n.strip()]


def _rows(text: str, marker: str) -> list[str]:
    """The HTML of each data row of a DevExpress grid (rows nest tables, so split on row starts)."""
    parts = re.split(rf'<tr id="[^"]*{marker}\d+"[^>]*>', text or "")
    return parts[1:]


def parse_grid(text: str) -> list[IndexRecord]:
    """One IndexRecord per grid row (a party pair); role R = grantor/mortgagor, E = grantee/lender."""
    out: list[IndexRecord] = []
    for row in _rows(text, "gridTrad_DXDataRow"):
        kind = _cell(row, "Kind")
        rec = IndexRecord(recorded=mdy_to_iso(_cell(row, "Date")), book=_cell(row, "Book") or None,
                          page=_cell(row, "Page") or None, instrument_no=_cell(row, "DocNo") or None,
                          doc_type=kind, description=_cell(row, "Description") or None)
        for cls in ("Party1", "Party2"):
            for role, name in _parties(row, cls):
                bucket = rec.grantors if role == "R" else rec.grantees if role == "E" else None
                if bucket is not None and name not in bucket:
                    bucket.append(name)
        if rec.book or rec.instrument_no:
            out.append(rec)
    return out


def parse_marriage_grid(text: str) -> list[dict]:
    """[{date, issued, license_no, book, page, a1: 'SURNAME, GIVEN', a2: ...}] of a marriage grid. The
    cells carry no stable class for the dates and given names, so they are read by position after
    the row number."""
    out: list[dict] = []
    for row in _rows(text, "DXDataRow"):
        tds = [" ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", c)).replace("\xa0", " ").split())
               for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        i = next((k for k, v in enumerate(tds) if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v)), None)
        if i is None or len(tds) < i + 9:
            continue
        d, s2, g2, s1, g1, book, page, lic, issued = tds[i:i + 9]
        out.append({"date": mdy_to_iso(d), "issued": mdy_to_iso(issued), "license_no": lic, "book": book,
                    "page": page, "a1": f"{s1}, {g1}".strip(", "), "a2": f"{s2}, {g2}".strip(", ")})
    return out


def parse_doc_types(payload: str) -> list[tuple[str, str]]:
    """[(code, name)] from GetDocTypes ('[[[code, name, book type, id], ...], [groups]]')."""
    try:
        data = json.loads(payload)
        rows = data[0]
    except (ValueError, TypeError, IndexError):
        return []
    return [(str(r[0]), str(r[1])) for r in rows if isinstance(r, list) and len(r) >= 2]


_ADVERSE = re.compile(r"LIEN|JUDG|LIS PENDENS|FORECLOS|ATTACH|\bTAX\b", re.I)
_NOT_ADVERSE = re.compile(r"SATISF|RELEASE|WITHDRAW|CANCEL|AMEND|SUBORDIN|ASSIGN|RESCIS|DISCHARGE|NOTICE OF INTENT|"
                          r"NOTICE REQUEST", re.I)


def adverse_codes(types: list[tuple[str, str]]) -> list[str]:
    """The county's own codes for liens, judgments, lis pendens and foreclosure instruments (not their
    satisfactions, releases or amendments)."""
    return [c for c, n in types if _ADVERSE.search(n) and not _NOT_ADVERSE.search(n)]


def standard_form(defaults: dict, who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    d = dict(defaults)
    d.update({"Last": who.last, "Given": "" if who.entity else who.first, "SearchType": _SIDE.get(side, "3"),
              "FromDate": "", "ToDate": iso_to_mdy(date_thru), "PageSize": str(PAGE_SIZE),
              "MaxRecordCount": str(MAX_RECORDS), "IsAdvancedSearch": "False"})
    return d


def window_form(defaults: dict, codes: list[str], date_from: str, date_to: str) -> dict:
    """The Advanced form for a document-type window (no name)."""
    d = dict(defaults)
    d.update({"IsAdvancedSearch": "True", "Last": "", "Given": "", "FromDate": "", "ToDate": "",
              "AdvancedFromDate": iso_to_mdy(date_from), "AdvancedToDate": iso_to_mdy(date_to),
              "DocTypes": ",".join(codes), "MultiNameLast": "", "MultiNameGiven": "", "MultiNameSearchType": "3",
              "MultiNameAndOr": "and", "AdvancedDescriptionQualifier": "+", "AdvancedDescriptionAndOr": "AND",
              "AdvancedDescriptionValue": "", "PageSize": str(PAGE_SIZE), "MaxRecordCount": str(MAX_RECORDS)})
    return d


def marriage_form(defaults: dict, date_from: str, date_to: str, last: str = "", given: str = "") -> dict:
    d = dict(defaults)
    d.update({"last": last, "given": given, "fromdate": iso_to_mdy(date_from), "todate": iso_to_mdy(date_to),
              "PageSize": str(PAGE_SIZE), "MaxRecordCount": str(MAX_RECORDS), "PartyType": "0"})
    return d


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------


def clean_name(name: Optional[str]) -> str:
    """The owner string without the trailing comma / semicolon some county rolls leave on a name
    ('DOE JOHN A,'), which makes the shared name parser drop the given name and search the surname alone."""
    return re.sub(r"[\s,;]+$", "", name or "").strip()


class LrSearch(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES
    cap_env = "FORECLOSURE_NC_LRSEARCH_ROD_MAX"

    def search_by_name_sync(self, state, county, name, max_docs=80):
        return super().search_by_name_sync(state, county, clean_name(name), max_docs)

    def search_by_name_status_sync(self, state, county, name, max_docs=80):
        return super().search_by_name_status_sync(state, county, clean_name(name), max_docs)

    def source_url(self, cfg: LrCounty) -> str:
        return cfg.base + "LRSearch/LRIndex?searchTabID=0"

    def _open(self, client: PoliteClient, cfg: LrCounty):
        return open_search(client, cfg)

    def _search(self, client: PoliteClient, cfg: LrCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        url = self.source_url(cfg)
        rep = client.post(cfg.base + "LRSearch/ExecuteSearch", standard_form(ctx["defaults"], who, side, date_thru),
                          headers=ctx["xhr"])
        n, docs = totals(rep.text)
        if n is None:
            return SearchResult(status="error", url=url, reason="the search reply is not a results grid")
        if n == 0:
            return SearchResult(records=[], total=0, url=url)
        recs = parse_grid(rep.text)
        if not recs:
            return SearchResult(status="error", url=url, reason="the grid was empty although it counted rows")
        return SearchResult(records=recs, total=docs if docs is not None else n, url=url,
                            truncated=n > len(recs) or n >= MAX_RECORDS)


def open_search(client: PoliteClient, cfg: LrCounty) -> dict:
    ref = cfg.base + "LRSearch/LRIndex?searchTabID=0"
    xhr = {**_XHR, "Referer": cfg.base}
    page = client.get(ref, headers=xhr)
    defaults = form_defaults(page.text)
    if "ExecuteSearch" not in page.text or "Last" not in defaults:
        raise RuntimeError("the land-records search page did not open")
    return {"defaults": defaults, "xhr": {**_XHR, "Referer": ref}}


def doc_types(client: PoliteClient, cfg: LrCounty, ctx: dict) -> list[tuple[str, str]]:
    rep = client.get(cfg.base + "LRSearch/GetDocTypes", headers=ctx["xhr"])
    return parse_doc_types(rep.text)


def open_marriage(client: PoliteClient, cfg: LrCounty) -> dict:
    ref = cfg.base + "VRMarriageSearch/MarriageIndex"
    page = client.get(ref, headers={**_XHR, "Referer": cfg.base})
    defaults = form_defaults(page.text)
    if "ExecuteSearch" not in page.text or "last" not in defaults:
        raise RuntimeError("the marriage search page did not open")
    return {"defaults": defaults, "xhr": {**_XHR, "Referer": ref}}


def marriage_window(client: PoliteClient, cfg: LrCounty, ctx: dict, date_from: str, date_to: str
                    ) -> tuple[list[dict], bool]:
    """(licences in the window, overflow). overflow: the register showed fewer rows than it counted."""
    rep = client.post(cfg.base + "VRMarriageSearch/ExecuteSearch",
                      marriage_form(ctx["defaults"], date_from, date_to), headers=ctx["xhr"])
    n, _ = totals(rep.text)
    if n is None:
        raise RuntimeError("the marriage reply is not a results grid")
    rows = parse_marriage_grid(rep.text) if n else []
    return rows, n > len(rows) or n >= MAX_RECORDS


ADAPTER = LrSearch()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


async def search_by_name_status(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name_status(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, clean_name(owner_name), state=state, depth=depth)

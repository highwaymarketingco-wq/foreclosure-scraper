"""Tyler Technologies register search, name index: Self-Service (Durham) and its predecessor
EagleWeb (Johnston). One adapter, two protocol variants chosen per county. Plain HTTP; the pages'
own requests, read from a browser once and replayed (live-checked 2026-10-07).

SELF-SERVICE (rodweb.dconc.gov/web)
  1. GET  /web/                          -> redirects to /web/user/disclaimer for a new session
  2. POST /web/user/disclaimer (XHR)     -> 'true': the 'I Accept' button's own AJAX call
  3. GET  /web/search/<SEARCH_ID>        -> the search form (sets the search context)
  4. POST /web/searchPost/<SEARCH_ID>    field_BothNamesID_DOT_Surname / _Name (or GrantorID /
          GranteeID for one side), field_RecordingDateID_DOT_StartDate / _EndDate
          -> {"validationMessages":{}, "totalPages":N, "currentPage":1}
  5. GET  /web/searchResults/<SEARCH_ID>?page=k  -> li.ss-search-row items: header
          '<doc no> • BT: <type> B: <book> P: <page> • MM/DD/YYYY hh:mm', then columns Document
          Type, Grantor/Party 1, Grantee/Party 2, Legal.
EAGLEWEB (erec.johnstonnc.com/recorder)
  1. GET  /recorder/web/  -> the disclaimer form; POST its action with guest=true ('I Acknowledge')
  2. GET  /recorder/eagleweb/docSearch.jsp  -> the docSearch form
  3. POST its action (docSearchPOST.jsp) with the form's own defaults plus BothNamesIDSurname /
          BothNamesIDName (or GrantorID* / GranteeID*), RecordingDateIDEnd
          -> docSearchResults.jsp: table#searchResultsTable, one row per document: type and
             document number; 'BOOK: b PAGE: p' and the recording time; Grantor, Grantee, Legal.
     A guest search lists at most 50 results ('Search 1: *50 results'; the star marks the current
     search, not a cap): a count of 50 is reported as truncated.

WAKE (Tyler Self-Service) is left out: its search shows a reCAPTCHA. Durham's disclaimer page
loads Google's reCAPTCHA script but showed no challenge on 2026-10-07; any challenge, login page
or block walls the county (rod/nc_polite.py).

EAGLEWEB MARRIAGE-TYPE SWEEP (added 2026-10-21, Johnston marriage_license gap). docSearch.jsp's
own BookTypeID select carries an 'M - Marriage' option -- a document-TYPE filter, not just a
per-owner name search with marriage records mixed into deed results (the shape
enrichment_marriage_license.py already uses for Aumentum). LIVE-VERIFIED 2026-10-21 against
erec.johnstonnc.com/recorder: a BLANK-NAME docSearchPOST.jsp with BookTypeID='M' and a
RecordingDateIDStart/End window returns real marriage rows with NO guest-result cap -- unlike the
per-owner EagleWeb path this module's EAGLEWEB_GUEST_CAP constant documents, this type-filtered,
name-blank search paged past 50 cleanly (1,340 real 2024 records, 14 pages of
docSearchResults.jsp?searchId=<id>&page=<n>, with 'Next'/'Last' links present the whole way; no
login, no CAPTCHA, guest disclaimer only -- the same accept Tyler._open() already does for this
county's deed side). A marriage row's summary cell is NOT the deed shape's labelled
'Grantor:'/'Grantee:' <td>s parse_eagleweb() reads -- it is a free-text '<b>SPOUSE ONE</b> married
to <b>SPOUSE TWO</b>' line (real sample: 'MAGNUSON ELIZABETH JO married to RUSSELL CHADWICK
VAUGHN', book/page printed as 'M B: 2024 P: 1' -- year and a sequence number, not a real
recording book), so this gets its own parser, eagleweb_window_fields()/parse_eagleweb_marriage()/
eagleweb_result_pages() below, built for rod/county_sweeps.EagleWebMarriageReader's county-wide,
date-windowed sweep (the same architecture already serves Beaufort's CCS LRSearch Marriages
index) rather than nc_tyler.search_by_name()'s per-owner path above.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "tyler_recorder"
ENV_FLAG = "FORECLOSURE_NC_TYLER_ROD"
PAGE_CAP = 5                     # Self-Service result pages read per lookup
EAGLEWEB_GUEST_CAP = 50          # an EagleWeb guest search lists at most this many results


@dataclass(frozen=True)
class TylerCounty:
    root: str                    # scheme://host
    kind: str                    # 'selfservice' or 'eagleweb'
    search_id: str = ""          # Self-Service document search id


COUNTIES: dict[str, TylerCounty] = {
    "Durham": TylerCounty("https://rodweb.dconc.gov", "selfservice", "DOCSEARCH5S1"),
    "Johnston": TylerCounty("https://erec.johnstonnc.com", "eagleweb"),
}

#: Tyler Self-Service county whose search shows a reCAPTCHA: a person reads it
WALLED_COUNTIES = ("Wake",)

_ENTITY_TAIL = re.compile(r"^(LLC|L\.L\.C\.?|INC\.?|CORP\.?|CO\.?|LTD\.?|LP|L\.P\.|LLP|PLLC|P\.A\.|PA|NA|N\.A\.|"
                          r"TRUSTEE|TR|JR\.?|SR\.?|II|III|IV)$", re.I)


def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


def split_names(s: str) -> list[str]:
    """'HAMILTON LARA K., SMITH LARA K.' -> two names; 'EXAMPLE HOLDINGS, LLC' stays one."""
    out: list[str] = []
    for part in [p.strip() for p in (s or "").split(",")]:
        if not part:
            continue
        if out and _ENTITY_TAIL.match(part):
            out[-1] = f"{out[-1]}, {part}"
        else:
            out.append(part)
    return out


# ------------------------------------------------------------------------------------------------
# Self-Service
# ------------------------------------------------------------------------------------------------

def selfservice_fields(who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    prefix = {"grantor": "field_GrantorID_DOT_", "grantee": "field_GranteeID_DOT_"}.get(side, "field_BothNamesID_DOT_")
    return {prefix + "Surname": who.last, prefix + "Name": "" if who.entity else who.first,
            "field_RecordingDateID_DOT_StartDate": "", "field_RecordingDateID_DOT_EndDate": iso_to_mdy(date_thru)}


def parse_search_post(text: str) -> tuple[Optional[int], dict]:
    """(totalPages, validationMessages) of a searchPost reply; (None, {}) when it is not one."""
    try:
        j = json.loads(text or "")
    except ValueError:
        return None, {}
    if not isinstance(j, dict) or "totalPages" not in j:
        return None, {}
    try:
        pages = int(j.get("totalPages") or 0)
    except (TypeError, ValueError):
        pages = None
    return pages, (j.get("validationMessages") or {})


# Header shape: '<instrument_no> • <metadata> • <date> <time>', e.g.
# '2026186084 • BT: OPR B: 10616 P: 073 • 08/28/2026 04:09 PM'. The middle
# <metadata> section is captured as a BLOB (group 2) rather than fixed
# BT:/B:/P: slots, because a real multi-tract instrument renders TWO
# "B: x P: y" pairs in that section with no bullet between them (live,
# Wake instrument 2026086748: "B: 020299 P: 01082   B: 020299 P: 01083") --
# confirmed 2026-10-14 this fails the OLD fixed-slot regex entirely (no
# match at all), silently dropping instrument_no/book/page/recorded for a
# real lead on both Wake and Durham (which share this parser). Splitting on
# the two '•' bullets first, then pulling BT:/B:/P: out of the middle blob
# with their own sub-patterns below, makes instrument_no/date immune to
# however many book/page pairs the middle section holds -- the FIRST B:/P:
# pair becomes the record's book/page (the primary tract; a multi-tract
# instrument's secondary pairs are not separately modeled, same scope the
# task asked for -- "at minimum the primary one, without silently dropping
# instrument_no/date").
_SS_HEAD = re.compile(r"^\s*(\S+)\s*•\s*(.*?)\s*•\s*(\d{1,2}/\d{1,2}/\d{4})")
_SS_HEAD_BT = re.compile(r"BT:\s*(\S+)")
_SS_HEAD_BP = re.compile(r"B:\s*(\S+)\s*P:\s*(\S+)")


def parse_selfservice(html: str) -> list[IndexRecord]:
    s = BeautifulSoup(html or "", "lxml")
    out: list[IndexRecord] = []
    for li in s.select("li.ss-search-row"):
        h1 = li.find("h1")
        m = _SS_HEAD.match(_txt(h1))
        middle = (m.group(2) or "") if m else ""
        bt = _SS_HEAD_BT.search(middle)
        bp = _SS_HEAD_BP.search(middle)
        cols: dict[str, list[str]] = {}
        for ul in li.select("ul.selfServiceSearchResultColumn"):
            items = ul.find_all("li", recursive=False)
            if not items:
                continue
            label = re.sub(r"\s*\(\d+\)\s*$", "", _txt(items[0])).lower()
            cols[label] = [_txt(x) for x in items[1:] if _txt(x)]
        legal = cols.get("legal") or []
        out.append(IndexRecord(
            recorded=mdy_to_iso(m.group(3)) if m else None, instrument_no=m.group(1) if m else None,
            index_code=(bt.group(1) if bt else None), book=(bp.group(1) if bp else None),
            page=(bp.group(2) if bp else None),
            doc_type=(cols.get("document type") or [""])[0],
            grantors=cols.get("grantor/party 1") or [], grantees=cols.get("grantee/party 2") or [],
            description="; ".join(legal[:3]) or None))
    return out


# ------------------------------------------------------------------------------------------------
# EagleWeb
# ------------------------------------------------------------------------------------------------

def form_defaults(form) -> list[tuple[str, str]]:
    """The fields a browser posts for this form untouched: selects' selected option, checked
    boxes, every text and hidden input."""
    data: list[tuple[str, str]] = []
    for i in form.find_all(["input", "select", "textarea"]):
        n = i.get("name")
        if not n:
            continue
        t = (i.get("type") or "").lower()
        if i.name == "select":
            o = i.find("option", selected=True) or i.find("option")
            data.append((n, (o.get("value") if o else "") or ""))
        elif t in ("checkbox", "radio"):
            if i.has_attr("checked"):
                data.append((n, i.get("value") or "on"))
        elif t not in ("submit", "button", "reset", "image"):
            data.append((n, i.get("value") or ""))
    return data


def eagleweb_fields(defaults: list[tuple[str, str]], who: OwnerName, side: str,
                    date_thru: Optional[str]) -> list[tuple[str, str]]:
    prefix = {"grantor": "GrantorID", "grantee": "GranteeID"}.get(side, "BothNamesID")
    over = {prefix + "Surname": who.last, prefix + "Name": "" if who.entity else who.first,
            "RecordingDateIDEnd": iso_to_mdy(date_thru)}
    return [(k, over.get(k, v)) for k, v in defaults]


_EW_BP = re.compile(r"BOOK:\s*(\S+)\s*PAGE:\s*(\d+)")


def parse_eagleweb(html: str) -> tuple[list[IndexRecord], Optional[int], bool]:
    """(rows, the result count the page reports, whether the count sits at the guest maximum)."""
    s = BeautifulSoup(html or "", "lxml")
    out: list[IndexRecord] = []
    tab = s.find("table", id="searchResultsTable")
    rows = [tr for tr in tab.find_all("tr") if tr.find_parent("table") is tab] if tab is not None else []
    for tr in rows:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        a = tds[0].find("a", href=re.compile(r"viewDoc\.jsp"))
        if a is None:
            continue
        head = [x.strip() for x in a.get_text("\n").split("\n") if x.strip()]
        summary = tds[1]
        bp = _EW_BP.search(_txt(summary))
        date = re.search(r"\d{1,2}/\d{1,2}/\d{4}", _txt(summary))
        cells: dict[str, str] = {}
        for td in summary.find_all("td"):
            b = td.find("b")
            if b is None:
                continue
            label = _txt(b).rstrip(":").lower()
            b.extract()
            cells[label] = _txt(td)
        out.append(IndexRecord(
            recorded=mdy_to_iso(date.group(0)) if date else None, doc_type=head[0] if head else "",
            instrument_no=head[1] if len(head) > 1 else None,
            book=bp.group(1) if bp else None, page=bp.group(2) if bp else None,
            grantors=split_names(cells.get("grantor", "")), grantees=split_names(cells.get("grantee", "")),
            description=cells.get("legal") or None, xref=cells.get("related") or None))
    m = re.search(r"Search 1:\s*</strong>\s*<strong>\s*<a[^>]*>\s*\*?(\d+)\s+results", html or "", re.I)
    count = int(m.group(1)) if m else None
    return out, count, bool(count is not None and count >= EAGLEWEB_GUEST_CAP)


def eagleweb_window_fields(defaults: list[tuple[str, str]], book_type: str,
                           date_from: Optional[str], date_to: Optional[str]) -> list[tuple[str, str]]:
    """The docSearchPOST.jsp body for a BLANK-NAME, one-book-type, date-windowed sweep -- the
    sibling of eagleweb_fields() above, which fills in a per-owner search instead.
    rod.county_sweeps.EagleWebMarriageReader's own read(a, b) is this function's only caller:
    BookTypeID is the only document-type filter EagleWeb's guest docSearch form exposes, and a
    window with no name at all is what lets one sweep serve every board row of the county instead
    of one per-owner search each (see this module's docstring)."""
    over = {"BookTypeID": book_type, "BothNamesIDSurname": "", "BothNamesIDName": "",
            "RecordingDateIDStart": iso_to_mdy(date_from) if date_from else "",
            "RecordingDateIDEnd": iso_to_mdy(date_to) if date_to else ""}
    return [(k, over.get(k, v)) for k, v in defaults]


_EW_MARRIAGE_BP = re.compile(r"\bB:\s*(\S+)\s*P:\s*(\S+)", re.I)
_EW_MARRIED_TO = re.compile(r"\s+married to\s+", re.I)


def parse_eagleweb_marriage(html: str) -> tuple[list[dict], Optional[int]]:
    """(rows, the result count the page reports) off one page of an EagleWeb BookTypeID='M'
    search. Each row is {recorded (iso date), instrument_no, book, page, spouse1, spouse2} read
    off the record's own free-text '<b>NAME ONE</b> married to <b>NAME TWO</b>' summary line --
    a different shape from a deed's labelled Grantor:/Grantee: cells (parse_eagleweb() above), so
    this is its own parser. [] rows when the table isn't there (an empty result, a login/CAPTCHA
    page, or an unrelated reply) -- never raises."""
    s = BeautifulSoup(html or "", "lxml")
    out: list[dict] = []
    tab = s.find("table", id="searchResultsTable")
    rows = [tr for tr in tab.find_all("tr") if tr.find_parent("table") is tab] if tab is not None else []
    for tr in rows:
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        a = tds[0].find("a", href=re.compile(r"viewDoc\.jsp"))
        if a is None:
            continue
        head = [x.strip() for x in a.get_text("\n").split("\n") if x.strip()]
        instrument_no = head[1] if len(head) > 1 else None
        summary = tds[1]
        text = _txt(summary)
        bp = _EW_MARRIAGE_BP.search(text)
        date = re.search(r"\d{1,2}/\d{1,2}/\d{4}", text)
        # Every <b> in the summary cell: the first is the 'M B: x P: y' line (dropped by the
        # B:/P: regex check below); the two that remain, in order, are the spouses.
        names = [_txt(b) for b in summary.find_all("b") if not _EW_MARRIAGE_BP.search(_txt(b))]
        if len(names) < 2:
            continue
        out.append({
            "recorded": mdy_to_iso(date.group(0)) if date else None,
            "instrument_no": instrument_no,
            "book": bp.group(1) if bp else None, "page": bp.group(2) if bp else None,
            "spouse1": names[0], "spouse2": names[1],
        })
    m = re.search(r"(\d+)\s+results", html or "", re.I)
    count = int(m.group(1)) if m else None
    return out, count


_EW_RESULT_PAGE = re.compile(r"docSearchResults\.jsp\?searchId=(\d+)[^\"'<>]*?page=(\d+)", re.I)


def eagleweb_result_pages(html: str) -> tuple[Optional[str], int]:
    """(searchId, highest page number linked on a docSearchPOST/docSearchResults reply) -- (None,
    1) when there is no pagination (a single-page result, or nothing parseable)."""
    ids: set[str] = set()
    pages: set[int] = set()
    for m in _EW_RESULT_PAGE.finditer(html or ""):
        ids.add(m.group(1))
        pages.add(int(m.group(2)))
    search_id = next(iter(ids)) if ids else None
    return search_id, (max(pages) if pages else 1)


def no_results(html: str) -> bool:
    return bool(re.search(r"No results found|returned no results|0 results", html or "", re.I))


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class Tyler(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES

    def source_url(self, cfg: TylerCounty) -> str:
        return cfg.root + ("/web/search/" + cfg.search_id if cfg.kind == "selfservice"
                           else "/recorder/eagleweb/docSearch.jsp")

    # -- sessions ----------------------------------------------------------------------------
    def _open(self, client: PoliteClient, cfg: TylerCounty) -> dict:
        if cfg.kind == "selfservice":
            self._ss_accept(client, cfg)
            return {}
        r = client.get(cfg.root + "/recorder/web/")
        form = BeautifulSoup(r.text, "lxml").find("form")
        if form is None or not form.find("input", attrs={"name": "guest"}):
            raise RuntimeError("the EagleWeb disclaimer form was not found")
        client.post(urljoin(r.final_url, form.get("action") or ""), {"guest": "true", "submit": "I Acknowledge"},
                    headers={"Referer": r.final_url})
        return {}

    def _ss_accept(self, client: PoliteClient, cfg: TylerCounty) -> None:
        home = client.get(cfg.root + "/web/")
        if "/user/disclaimer" in home.final_url:
            acc = client.post(home.final_url, {}, headers={"X-Requested-With": "XMLHttpRequest",
                                                            "Accept": "application/json", "Referer": home.final_url})
            if acc.text.strip().lower() != "true":
                raise RuntimeError("the disclaimer accept did not answer 'true'")

    # -- one lookup --------------------------------------------------------------------------
    def _search(self, client: PoliteClient, cfg: TylerCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        if cfg.kind == "selfservice":
            return self._search_ss(client, cfg, who, side, date_thru)
        return self._search_ew(client, cfg, who, side, date_thru)

    def _search_ss(self, client, cfg, who, side, date_thru) -> SearchResult:
        url = self.source_url(cfg)
        form = client.get(url)
        if "/user/disclaimer" in form.final_url:          # the guest session expired: accept once more
            self._ss_accept(client, cfg)
            form = client.get(url)
        post = client.post(cfg.root + "/web/searchPost/" + cfg.search_id, selfservice_fields(who, side, date_thru),
                           headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
                                    "Referer": form.final_url})
        pages, problems = parse_search_post(post.text)
        if pages is None:
            return SearchResult(status="error", reason="the search reply was not the expected JSON", url=url)
        if problems:
            return SearchResult(status="error", reason=f"the register refused the search: {str(problems)[:120]}", url=url)
        rows: list[IndexRecord] = []
        for k in range(1, min(pages, PAGE_CAP) + 1):
            page = client.get(cfg.root + f"/web/searchResults/{cfg.search_id}?page={k}", headers={"Referer": url})
            got = parse_selfservice(page.text)
            if not got and k == 1 and "ss-search-row" not in page.text and not no_results(page.text):
                return SearchResult(status="error", reason="the results page could not be read", url=url)
            rows += got
        return SearchResult(records=rows, total=len(rows), truncated=pages > PAGE_CAP, url=url)

    def _search_ew(self, client, cfg, who, side, date_thru) -> SearchResult:
        url = self.source_url(cfg)
        ds = client.get(url)
        form = BeautifulSoup(ds.text, "lxml").find("form", attrs={"name": "docSearch"})
        if form is None:                                    # the guest session expired
            self._open(client, cfg)
            ds = client.get(url)
            form = BeautifulSoup(ds.text, "lxml").find("form", attrs={"name": "docSearch"})
            if form is None:
                return SearchResult(status="error", reason="the EagleWeb search form did not open", url=url)
        res = client.post(urljoin(ds.final_url, form.get("action") or ""),
                          eagleweb_fields(form_defaults(form), who, side, date_thru), headers={"Referer": ds.final_url})
        rows, count, capped = parse_eagleweb(res.text)
        if not rows and count is None and "searchResultsTable" not in res.text and not no_results(res.text):
            return SearchResult(status="error", reason="the results page could not be read", url=url)
        return SearchResult(records=rows, total=count if count is not None else len(rows), truncated=capped, url=url)


ADAPTER = Tyler()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)


async def search_by_name_status(state: str, county: str, name: str, max_docs: int = 80):
    """(docs, status, truncated) -- see rod/nc_cott_v4.search_by_name_status."""
    return await ADAPTER.search_by_name_status(state, county, name, max_docs)

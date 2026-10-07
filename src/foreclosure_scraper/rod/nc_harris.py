"""Harris Recording Solutions 'ROD Web Access' (Aumentum Recorder), real-estate name index, in a
headless browser: Mecklenburg and Carteret. The search form is ASP.NET WebForms with Infragistics
editors whose values travel in client-state JSON, so the adapter types into the page the way a
person does instead of building the post (rod/nc_render.py; the Spartanburg precedent).

FLOW (live-checked 2026-10-07 on Carteret and Mecklenburg)
  1. <root>/                      'Welcome - ... ROD Web Access': a 'Click here to acknowledge the
                                   disclaimer and enter the site' postback link (the optional account
                                   sign-in box on the same page is never touched)
  2. <root>/RealEstate/SearchEntry.aspx
       Party Name (#cphNoMargin_f_txtParty, 'LAST FIRST', begins with), party type radio (both /
       grantor / grantee), Date Filed from / to (the inputs inside #cphNoMargin_f_ddcDateFiled*),
       Search (#cphNoMargin_SearchButtons1_btnSearch)
  3. SearchResults.aspx: 'Showing Records 1 through 25 ( N records found ...)'; the WebDataGrid's
     header cells carry stable column keys (INSTRUMENT_NUMBER, BOOK, PAGE, DATE_RECEIVED,
     DOCUMENT_TYPE_DESC, NAME_TYPE, GRANTOR, NAME_TYPE2, GRANTEE, COMBINED_LEGAL); one row per
     matched party; NAME_TYPE R / E says whether the party column holds the grantor or the grantee.
     '(+)' after a name means more parties on the document (the detail page, not opened).
     Next page: #OptionsBar1_imgNext (up to PAGE_CAP pages).
WHAT IS NOT READ: the detail page and the document images.
MOORE runs the same app but answered the disclaimer postback with HTTP 403 on 2026-10-07: walled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso
from .nc_render import NcRenderPlatform, RenderPage

PLATFORM = "harris_rod_web_access"
ENV_FLAG = "FORECLOSURE_NC_HARRIS_ROD"
CAP_ENV = "FORECLOSURE_NC_HARRIS_ROD_MAX"
PAGE_CAP = 4                       # 25 rows a page

ACCEPT_LINK = "text=Click here to acknowledge the disclaimer"
PARTY = "#cphNoMargin_f_txtParty"
SIDE_RADIO = {"both": "#cphNoMargin_f_drbPartyType_0", "grantor": "#cphNoMargin_f_drbPartyType_1",
              "grantee": "#cphNoMargin_f_drbPartyType_2"}
DATE_FROM = "#cphNoMargin_f_ddcDateFiledFrom input"
DATE_TO = "#cphNoMargin_f_ddcDateFiledTo input"
SEARCH = "#cphNoMargin_SearchButtons1_btnSearch"
NEXT = "#OptionsBar1_imgNext:not([disabled])"


@dataclass(frozen=True)
class HarrisCounty:
    root: str


COUNTIES: dict[str, HarrisCounty] = {
    "Mecklenburg": HarrisCounty("https://meckrod.manatron.com"),
    "Carteret": HarrisCounty("https://deeds.carteretcountync.gov"),
}

WALLED_COUNTIES = ("Moore",)


def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


def _name(s: str) -> str:
    return re.sub(r"\s*\(\+\)\s*$", "", s or "").strip()


def parse_results(html: str) -> tuple[list[IndexRecord], Optional[int], int]:
    """(rows, the 'N records found' count or None, the number of result pages offered)."""
    s = BeautifulSoup(html or "", "lxml")
    keys = [th.get("key") for th in s.find_all("th") if th.get("key")]
    out: list[IndexRecord] = []
    for tr in s.find_all("tr", attrs={"adr": True}):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != len(keys):
            continue
        v = {k: _txt(td) for k, td in zip(keys, tds)}
        party, reverse = _name(v.get("GRANTOR", "")), _name(v.get("GRANTEE", ""))
        party_is_grantee = (v.get("NAME_TYPE") or "").upper() == "E"
        grantors, grantees = ([reverse], [party]) if party_is_grantee else ([party], [reverse])
        out.append(IndexRecord(
            recorded=mdy_to_iso(v.get("DATE_RECEIVED")), instrument_no=v.get("INSTRUMENT_NUMBER") or None,
            book=v.get("BOOK") or None, page=v.get("PAGE") or None,
            doc_type=v.get("DOCUMENT_TYPE_DESC") or v.get("DOCUMENT_TYPE") or "",
            grantors=[g for g in grantors if g], grantees=[g for g in grantees if g],
            description=v.get("COMBINED_LEGAL") or None))
    text = _txt(s)
    m = re.search(r"\(\s*([\d,]+)\s+records? found", text, re.I)
    found = int(m.group(1).replace(",", "")) if m else None
    sel = s.select_one("select[aria-label='Results Page Selection']")     # the first of the two option bars
    pages = len(sel.find_all("option")) if sel is not None else (1 if out else 0)
    return out, found, pages


def no_records(html: str) -> bool:
    return bool(re.search(r"\(\s*0\s+records? found|No records found|returned no records", html or "", re.I))


def party_text(who: OwnerName) -> str:
    return who.last if who.entity else f"{who.last} {who.first}".strip()


class Harris(NcRenderPlatform):
    platform = PLATFORM
    counties = COUNTIES
    cap_env = CAP_ENV

    def source_url(self, cfg: HarrisCounty) -> str:
        return cfg.root + "/RealEstate/SearchEntry.aspx"

    def _render_search(self, rp: RenderPage, cfg: HarrisCounty, who: OwnerName, side: str,
                       date_thru: Optional[str], date_from: Optional[str] = None) -> SearchResult:
        url = self.source_url(cfg)
        rp.goto(cfg.root + "/")
        if rp.has(ACCEPT_LINK):
            rp.click_nav(ACCEPT_LINK)
        rp.goto(url)
        if not rp.has(PARTY):
            return SearchResult(status="error", reason="the real-estate search form did not open", url=url)
        rp.type_into(PARTY, party_text(who))
        if rp.has(SIDE_RADIO.get(side, SIDE_RADIO["both"])):
            rp.click_local(SIDE_RADIO.get(side, SIDE_RADIO["both"]))
        if date_from and rp.has(DATE_FROM):
            rp.type_into(DATE_FROM, iso_to_mdy(date_from))
        if date_thru and rp.has(DATE_TO):
            rp.type_into(DATE_TO, iso_to_mdy(date_thru))
        html = rp.click_nav(SEARCH)
        rows, found, pages = parse_results(html)
        if not rows:
            if found == 0 or no_records(html):
                return SearchResult(records=[], total=0, url=url)
            return SearchResult(status="error", reason="the results page could not be read", url=url)
        read = 1
        while read < min(pages, PAGE_CAP) and rp.has(NEXT):
            html = rp.click_wait(NEXT, settle_ms=2000)
            more, _, _ = parse_results(html)
            if not more:
                break
            rows += more
            read += 1
        return SearchResult(records=rows, total=found, url=url, truncated=bool(found and pages > read))


ADAPTER = Harris()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

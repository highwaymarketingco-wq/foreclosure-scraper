"""Older Cott Systems eSearch (cotthosting.com/<tenant>/LandRecords/protected/SrchQuickName.aspx)
register reader by NAME: search_by_name, deed chain and lien existence. County: Marlboro SC (per-
county config in COTT_ESEARCH_COUNTIES). Not the v4 app rod/aumentum.py and rod/nc_cott_v4.py read.

THE FLOW (the browser's own requests, captured and replayed 2026-10-07)
  1. GET  SrchQuickName.aspx  -> 302 to User/Login.aspx?ReturnUrl=... -> 302 back: the site signs a
          visitor in as its guest by itself (no form, no button, no credential), and lands on the
          Name Search page with ASP.NET session cookies. __VIEWSTATE is empty (the session lives in
          cookies, as on the v4 app).
  2. POST SrchQuickName.aspx  with every field the page posts (the ScriptManager hidden field, the
          empty ClientState fields and hiddenInputToUpdateATBuffer_CommonToolkitScripts=1 included:
          without them the post re-renders the blank form), txtFirmSurName / txtGivenName1,
          'Begins With' (0), ddlParty -1 (any) | 1 (Party One) | 2 (Party Two), txtFiledFrom /
          txtFiledThru (MM/DD/YYYY or empty), and btnSearchAll = 'SEARCH - Show Final Results'
     -> table#ctl00_cphMain_lrrgResults_cgvResults: rows of 13 cells: #, select, Index (LAN/PLT),
        Date Filed, Doc Type, Party Ones, Party Twos (a nested table, one name per row, the matched
        name in <b>), Description, File Number, Book/Page ('1515 / 960'), Ref, Images, Flag; and
        'Displaying records 1 - N of M'.
Party One is the grantor side (seller, borrower), Party Two the grantee side. Document images are
paid here and never touched.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, run_chain, run_search, run_search_status
from .sc_polite import PoliteSession

PLATFORM = "cott_esearch_classic"
COTT_ESEARCH_COUNTIES: dict[str, str] = {
    "marlboro": "http://www.cotthosting.com/scmarlboro",
}
GRID_ID = "ctl00_cphMain_lrrgResults_cgvResults"
NO_RESULTS = re.compile(r"did not return any results|no (?:records|results|matches) (?:were )?found", re.I)
TIMEOUT_S = 90.0
_P = "ctl00$cphMain$SrchNames1$"
_D = "ctl00$cphMain$SrchDates1$"
_I = "ctl00$cphMain$SrchIndexInformation1$"


def _base(state: str, county: str) -> Optional[str]:
    if (state or "").upper() != "SC":
        return None
    return COTT_ESEARCH_COUNTIES.get((county or "").strip().lower())


def search_body(script_hidden: str, last: str, first: str, side: str,
                date_from: Optional[date], date_to: Optional[date]) -> list[tuple[str, str]]:
    mdy = (lambda d: d.strftime("%m/%d/%Y") if d else "")
    party = {"grantor": "1", "grantee": "2"}.get(side, "-1")
    return [("ctl00_smScriptMan_HiddenField", script_hidden), ("__EVENTTARGET", ""), ("__EVENTARGUMENT", ""),
            ("__LASTFOCUS", ""), ("__VIEWSTATE", ""), ("__SCROLLPOSITIONX", "0"), ("__SCROLLPOSITIONY", "0"),
            ("__VIEWSTATEENCRYPTED", ""),
            (_P + "txtFirmSurName", last), (_P + "ddlWildcardLast", "0"), (_P + "txtMiddleName", ""),
            (_P + "txtGivenName1", first), (_P + "ddlWildcardFirst1", "0"), (_P + "txtNameTitle", ""),
            (_P + "txtGivenName2", ""), (_P + "ddlWildcardFirst2", "0"), (_P + "ddlParty", party),
            (_D + "weFiledFrom_ClientState", ""), (_D + "weFiledThru_ClientState", ""),
            (_D + "meeFiledFrom_ClientState", ""), (_D + "meeFiledThru_ClientState", ""),
            (_D + "txtFiledFrom", mdy(date_from)), (_D + "txtFiledThru", mdy(date_to)),
            (_I + "lseIndexTypes_LB_ClientState", ""), (_I + "lseKinds_ClientState", ""),
            (_I + "lseKindGroup_ClientState", ""), (_I + "meeAmountMin_ClientState", ""),
            (_I + "meeAmountMax_ClientState", ""), (_I + "weAmountsMin_ClientState", ""),
            (_I + "weAmountsMax_ClientState", ""),
            ("ctl00$cphMain$btnSearchAll", "SEARCH - Show Final Results"), ("ctl00$txtJobReference", ""),
            ("ctl00$ucShoppingCart$meeZipCode_ClientState", ""), ("ctl00$ucShoppingCart$hfQuantity", ""),
            ("hiddenInputToUpdateATBuffer_CommonToolkitScripts", "1")]


def script_hidden_field(html: str) -> str:
    m = re.search(r'name="ctl00_smScriptMan_HiddenField"[^>]*value="([^"]*)"', html or "") or \
        re.search(r'value="([^"]*)"[^>]*name="ctl00_smScriptMan_HiddenField"', html or "")
    return m.group(1) if m else ""


#: the [TAG] older entries carry in the description when the Doc Type column is empty
_TAG_WORDS = {"MTG": "MORTGAGE", "SAT": "SATISFACTION", "POA": "POWER OF ATTORNEY", "ASGN": "ASSIGNMENT",
              "LP": "LIS PENDENS", "JDG": "JUDGMENT", "EMA": "EASEMENT"}


def _names(td) -> list[str]:
    out: list[str] = []
    for cell in td.find_all("td") if td is not None else []:
        n = " ".join(cell.get_text(" ", strip=True).replace("\xa0", " ").split())
        if n and set(n) != {"-"} and n not in out:
            out.append(n)
    return out


def _txt(td) -> str:
    return " ".join((td.get_text(" ", strip=True) if td is not None else "").replace("\xa0", " ").split())


def parse_grid(html: str, county: str) -> tuple[list[RodDoc], Optional[int]]:
    """The results grid -> (RodDocs, the total the page says it found)."""
    soup = BeautifulSoup(html or "", "lxml")
    grid = soup.find("table", id=GRID_ID)
    total = None
    m = re.search(r"Displaying records\s+\d+\s*-\s*\d+\s+of\s+(\d+)", soup.get_text(" "))
    if m:
        total = int(m.group(1))
    out: list[RodDoc] = []
    if grid is None:
        return out, total
    body = grid.find("tbody") or grid
    for tr in body.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 10:
            continue
        dm = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", _txt(tds[3]))
        if not dm:
            continue
        index_code = _txt(tds[2]).upper()
        label = _txt(tds[4]).upper()
        raw_desc = _txt(tds[7])
        tags = [t.strip().upper() for t in re.findall(r"\[([^\]]*)\]", raw_desc) if t.strip()]
        if not label and tags:          # older entries carry the kind as a [TAG] in the description
            label = _TAG_WORDS.get(tags[0], tags[0])
        bp = [x.strip() for x in _txt(tds[9]).split("/")]
        desc = " ".join(re.sub(r"\[[^\]]*\]", " ", raw_desc).split()) or None
        out.append(RodDoc(county=county, state="SC", doc_type=label or index_code or "UNKNOWN",
                          recorded_date=datetime(int(dm.group(3)), int(dm.group(1)), int(dm.group(2))),
                          book=(bp[0] or None) if bp else None, page=(bp[1] or None) if len(bp) > 1 else None,
                          grantor="; ".join(_names(tds[5])) or None, grantee="; ".join(_names(tds[6])) or None,
                          instrument_no=_txt(tds[8]) or None, notes=desc and desc[:200],
                          raw={"platform": PLATFORM, "doc_type_label": label or None,
                               "index_code": index_code or None, "description": desc}))
    return out, total


def make_searcher(state: str, county: str, *, session: Optional[PoliteSession] = None,
                  date_from: Optional[date] = None) -> Searcher:
    base = _base(state, county)
    if base is None:
        raise KeyError(f"{county} {state} is not an older Cott eSearch county here")
    url = f"{base}/LandRecords/protected/SrchQuickName.aspx"
    http = session or PoliteSession(timeout=TIMEOUT_S)
    state_ = {"hidden": None}
    cname = county.strip().title()

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if state_["hidden"] is None:
            r = http.get(url)
            if r.status_code != 200 or "txtFirmSurName" not in r.text:
                raise RuntimeError(f"name search page not reached ({r.status_code})")
            state_["hidden"] = script_hidden_field(r.text)
        last, first = (q.term, "") if q.entity else (q.last, q.first)
        r = http.post(url, data=search_body(state_["hidden"], last, first, side, date_from, date_to),
                      headers={"Referer": url})
        if r.status_code != 200:
            raise RuntimeError(f"search answered HTTP {r.status_code}")
        docs, total = parse_grid(r.text, cname)
        if not docs and GRID_ID not in r.text and not NO_RESULTS.search(r.text):
            raise RuntimeError("the search re-rendered the blank form")
        out = Docs()
        out.extend(d for d in docs if not (date_to and d.recorded_date and d.recorded_date.date() > date_to))
        out.truncated = bool(total and total > len(docs))
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    base = _base(state, county)
    if base is None:
        raise KeyError(f"{county} {state} is not an older Cott eSearch county here")
    return run_chain(platform=PLATFORM, state="SC", county=county.strip().title(), owner_name=owner_name,
                     make_searcher=lambda: make_searcher(state, county, session=session), max_prior=depth,
                     source_url=f"{base}/LandRecords/protected/SrchQuickName.aspx").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _base(state, county) is None:
        return []
    return run_search(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                      make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first)."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)


def _search_status_sync(state: str, county: str, name: str, max_docs: int):
    if _base(state, county) is None:
        return [], "error", False
    return run_search_status(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                             make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name_status(state: str, county: str, name: str, max_docs: int = 50):
    """(docs, status, truncated): status ok | walled | capped | error | noname (rod/sc_chain.run_search_status)."""
    return await asyncio.to_thread(_search_status_sync, state, county, name, max_docs)

"""Harris AcclaimWeb register reader by NAME: search_by_name, deed chain and lien existence.

Counties: Horry and Pickens SC (per-county config in ACCLAIM_NAME_COUNTIES). rod/acclaim.py is the
same platform's date-window sweep for recent distress recordings (Pickens); this module is the
per-owner name search and is separate so neither changes the other.

THE FLOW (the browser's own steps; live-checked 2026-10-07 on Horry and Pickens):
  1. GET  {base}/search/SearchTypeName      a guest is sent to Search/Disclaimer?st=...; the
                                             disclaimer is accuracy-only text and its form posts
                                             disclaimer=true. No CAPTCHA, login or challenge.
  2. POST {base}/search/SearchTypeName?Length=6 (X-Requested-With: XMLHttpRequest)
          PartyType Both|Direct|Reverse (Direct = the name as grantor, Reverse = as grantee),
          SearchOnName, RecordDateFrom/To (M/D/YYYY; the form's own floor is the default from-date),
          DocTypes=all, BookTypes = every BookTypeInfoCheckBox value on the form
       -> the name list: a tree of indexed names with counts (a kendo JSON tree on Horry, a
          t-treeview of <input name="itemValue"> on Pickens), or 'No names found', or ShowError(...).
  3. POST {base}/Search/SearchTypePreName   the tree's hidden fields + NameList = the chosen names
                                             joined by '|||' (only names that fit the owner)
  4. POST {base}/Search/GridResults          page=1, size, pageSize -> JSON {Data|data: [...],
                                             Total|total}. A row is one party pairing: Party
                                             From|To, Name (the searched party), CrossPartyName,
                                             DocTypeDescription (Horry) or DocType code (Pickens),
                                             RecordDate (/Date(ms)/ or YYYY/MM/DD), BookPage 'b/p',
                                             InstrumentNumber, Comments (the index's legal / memo),
                                             Consideration, ParcelNumber.
Pickens shows vendor codes (D/POA, MTG, M/SAT); their words come from the form's own
'(CODE) LABEL' list, and only the codes in PICKENS_DEED_CODES count as conveyances (Pickens files
easements, notices and agreements under 'DEED ...' labels).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import urljoin

from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, kind_of, name_fit, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "harris_acclaimweb"
MAX_NAMES = 20
PAGE_SIZE = 500
TIMEOUT_S = 60.0


@dataclass(frozen=True)
class AcclaimCounty:
    base: str                       # .../AcclaimWeb, no trailing slash
    floor: str                      # the register's own earliest from-date (form default)


ACCLAIM_NAME_COUNTIES: dict[str, AcclaimCounty] = {
    "horry": AcclaimCounty("https://acclaimweb.horrycounty.org/AcclaimWeb", "1/1/1984"),
    "pickens": AcclaimCounty("https://www.pickensscrod.us/AcclaimWeb", "1/1/1828"),
}

#: Pickens vendor codes that are conveyances (live code list 2026-10-07). Its other 'D/' codes are
#: instruments filed in the deed book that convey nothing (easements, notices, agreements, ...).
PICKENS_DEED_CODES = {"DEED", "D/DIST", "D/FORECLOSE", "D/PER REP", "D/DEV", "D/NO FEE", "D/EXEMPT",
                      "D/INDENT", "D/TRANS"}


def _cfg(state: str, county: str) -> Optional[AcclaimCounty]:
    if (state or "").upper() != "SC":
        return None
    return ACCLAIM_NAME_COUNTIES.get((county or "").strip().lower())


def _mdy(d: date) -> str:
    return f"{d.month}/{d.day}/{d.year}"


# -- pure parsers ---------------------------------------------------------------------------------
def parse_form(html: str) -> dict:
    """The name-search form: book-type values, the from-date floor, and the doc-type code words."""
    books = re.findall(r'BookTypeInfoCheckBox"[^>]*value="([^"]+)"', html or "")
    if not books:
        books = re.findall(r'value="([^"]+)"[^>]*name="BookTypeInfoCheckBox"', html or "")
    floor = None
    m = re.search(r'name="RecordDateFrom"[^>]*value="([^"]+)"', html or "") or \
        re.search(r'value="([^"]+)"[^>]*name="RecordDateFrom"', html or "")
    if m:
        floor = m.group(1).strip()
    words: dict[str, str] = {}
    for opt in re.findall(r'<option[^>]*value="([^"]*)"', html or ""):
        for code, label in re.findall(r"\(([^)]*)\)\s*([^,|(]+)", opt.replace("&amp;", "&")):
            if code.strip() and label.strip():
                words.setdefault(code.strip().upper(), label.strip().upper())
    return {"book_types": books, "floor": floor, "doc_words": words}


def parse_names(html: str) -> tuple[list[str], dict[str, str]]:
    """The name list after step 2 -> (names, the hidden fields to send back with them)."""
    names: list[str] = []
    m = re.search(r'kendoTreeView\(\{"dataSource":(\[.*?\]),"loadOnDemand"', html or "", re.S)
    if m:
        try:
            tree = json.loads(m.group(1))
        except ValueError:
            tree = []

        def walk(nodes):
            for n in nodes:
                if n.get("items"):
                    walk(n["items"])
                else:
                    t = str(n.get("text") or "")
                    names.append((t[:t.rfind("(")] if "(" in t else t).strip())
        walk(tree)
    else:
        for li in re.findall(r'<li[^>]*Title="NameListTreeView_Select_[^"]*"[^>]*>(.*?)</li>', html or "", re.S):
            v = re.search(r'name="itemValue"[^>]*value="([^"]*)"', li)
            if v:
                names.append(v.group(1).strip())
    hidden: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", html or ""):
        n = re.search(r'name="([^"]+)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n and n.group(1) in ("PartyType", "RecordDateFrom", "RecordDateTo", "BookTypes", "DocTypes",
                                "SearchOnName", "SearchOnLastOrBusinessName", "SearchOnFirstName",
                                "ShowAllNames", "ShowAllLegals"):
            hidden[n.group(1)] = v.group(1) if v else ""
    return [n for n in names if n], hidden


def _date(s) -> Optional[datetime]:
    s = str(s or "")
    m = re.search(r"/Date\((-?\d+)", s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


def parse_rows(rows: list[dict], county: str, doc_words: Optional[dict[str, str]] = None) -> list[RodDoc]:
    """GridResults rows -> RodDocs (one per party pairing; sc_chain merges an instrument's rows)."""
    out: list[RodDoc] = []
    words = doc_words or {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        name = " ".join(str(r.get("Name") or "").split())
        other = " ".join(str(r.get("CrossPartyName") or "").split())
        role = str(r.get("Party") or "").strip().title()
        if role == "From":
            grantor, grantee = name, other
        elif role == "To":
            grantor, grantee = other, name
        else:
            grantor, grantee = (str(r.get("DirectName") or "").strip(), str(r.get("IndirectName") or "").strip())
        code = str(r.get("DocType") or "").strip().upper()
        label = str(r.get("DocTypeDescription") or "").strip().upper() or words.get(code, "") or code
        bp = str(r.get("BookPage") or "")
        book, _, page = bp.partition("/")
        comments = " ".join(str(r.get("Comments") or "").split())[:200] or None
        cons = r.get("Consideration")
        doc = RodDoc(county=county, state="SC", doc_type=label or "UNKNOWN", recorded_date=_date(r.get("RecordDate")),
                     book=book.strip() or None, page=page.strip() or None,
                     grantor=grantor or None, grantee=grantee or None,
                     consideration_amount=float(cons) if isinstance(cons, (int, float)) and cons > 0 else None,
                     instrument_no=str(r.get("InstrumentNumber") or "").strip() or None,
                     parcel_id=str(r.get("ParcelNumber") or "").strip() or None, notes=comments,
                     raw={"platform": PLATFORM, "doc_type_label": label or None, "doc_type_code": code or None,
                          "book_type": r.get("BookType"), "party_role": role or None, "description": comments})
        if code.startswith("D/") and code not in PICKENS_DEED_CODES and kind_of(doc) == "deed":
            doc.raw["kind_hint"] = "other"
        elif code in PICKENS_DEED_CODES and kind_of(doc) == "other":
            doc.raw["kind_hint"] = "deed"
        out.append(doc)
    return out


def check_search_reply(text: str) -> Optional[str]:
    """None when the reply is a name list; 'none' for no names; else the register's error text."""
    if re.search(r"No names found", text or "", re.I):
        return "none"
    m = re.search(r"ShowError\(\s*'([^']*)'", text or "")
    if m:
        return m.group(1)
    return None


# -- the searcher ---------------------------------------------------------------------------------
def make_searcher(state: str, county: str, *, session: Optional[PoliteSession] = None,
                  date_from: Optional[date] = None) -> Searcher:
    cfg = _cfg(state, county)
    if cfg is None:
        raise KeyError(f"{county} {state} is not an AcclaimWeb name county")
    http = session or PoliteSession(timeout=TIMEOUT_S)
    form: dict = {}
    cname = county.strip().title()

    def open_session() -> None:
        r = http.get(f"{cfg.base}/search/SearchTypeName")
        if "disclaimer" in (r.url or "").lower() or 'name="disclaimer"' in r.text:
            m = re.search(r'<form action="([^"]+)"', r.text)
            if not m:
                raise RuntimeError("disclaimer form not found")
            r = http.post(urljoin(r.url, m.group(1).replace("&amp;", "&")), data={"disclaimer": "true"})
        if r.status_code != 200 or "SearchOnName" not in r.text:
            raise RuntimeError(f"name search page not reached ({r.status_code})")
        form.update(parse_form(r.text))
        if not form.get("book_types"):
            raise RuntimeError("no book types on the name search form")

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not form:
            open_session()
        party = {"both": "Both", "grantor": "Direct", "grantee": "Reverse"}[side]
        data = {"PartyType": party, "SearchOnName": q.term, "DateRangeList": " ",
                "DocTypes": "all", "DocTypesDisplay-input": "All", "DocTypesDisplay": "",
                "RecordDateFrom": _mdy(date_from) if date_from else (form.get("floor") or cfg.floor),
                "RecordDateTo": _mdy(date_to or date.today()),
                "BookTypes": ",".join(form["book_types"]), "BookTypesDisplay": "All"}
        xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{cfg.base}/search/SearchTypeName"}
        r = http.post(f"{cfg.base}/search/SearchTypeName?Length=6", data=data, headers=xhr)
        out = Docs()
        verdict = check_search_reply(r.text)
        if verdict == "none":
            return out
        if verdict is not None:
            if re.search(r"too many|exceed|narrow", verdict, re.I):
                out.truncated = True
                return out
            raise RuntimeError(f"register error: {verdict[:80]}")
        names, hidden = parse_names(r.text)
        rank = {"full": 0, "compatible": 1}
        fit = sorted((n for n in names if name_fit(q, n)), key=lambda n: rank[name_fit(q, n)])
        out.truncated = len(fit) > MAX_NAMES
        if not fit:
            return out
        hidden = {**{k: str(v) for k, v in data.items() if k in ("PartyType", "SearchOnName", "BookTypes",
                                                                  "DocTypes")}, **hidden}
        hidden["NameList"] = "|||".join(fit[:MAX_NAMES])
        http.post(f"{cfg.base}/Search/SearchTypePreName", data=hidden, headers=xhr)
        g = http.post(f"{cfg.base}/Search/GridResults",
                      data={"page": "1", "size": str(PAGE_SIZE), "pageSize": str(PAGE_SIZE)},
                      headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            payload = json.loads(g.text)
        except ValueError as exc:
            raise RuntimeError("grid results were not JSON") from exc
        rows = payload.get("Data") if "Data" in payload else payload.get("data")
        total = payload.get("Total") if "Total" in payload else payload.get("total")
        out.extend(parse_rows(rows or [], cname, form.get("doc_words")))
        if isinstance(total, int) and total > len(rows or []):
            out.truncated = True
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    cfg = _cfg(state, county)
    if cfg is None:
        raise KeyError(f"{county} {state} is not an AcclaimWeb name county")
    return run_chain(platform=PLATFORM, state="SC", county=county.strip().title(), owner_name=owner_name,
                     make_searcher=lambda: make_searcher(state, county, session=session), max_prior=depth,
                     source_url=f"{cfg.base}/search/SearchTypeName").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _cfg(state, county) is None:
        return []
    return run_search(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                      make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first): the shared
    enrichment_generic_rod interface."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)

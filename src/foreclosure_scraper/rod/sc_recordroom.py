"""Cott Systems RecordRoom register reader by NAME: search_by_name, deed chain and lien existence.
County: Union SC (per-county config in RECORDROOM_COUNTIES). rod/cott_recordroom.py is the same
platform's date-window sweep for recent distress recordings and is unchanged.

THE FLOW (the page's own requests, captured in a browser and replayed 2026-10-07; guest access,
no CAPTCHA, login or challenge)
  1. GET  /{slug}/guest/Search/records                      guest session cookies
  2. POST /{slug}/search/Records  (form, 302 to Guest/Search/Records/Result)
          SearchTerm = 'LAST FIRST' (the quick name box: the register parses it itself,
          'UnparsedNameSearch'; the Names[0].LastName boxes of the advanced panel are ignored
          unless that panel is switched on, and a search with only them returns the whole date
          window unfiltered), PartyType 1 (all) | 8 (Party One) | 9 (Party Two),
          FromDate / ThruDate (YYYY-MM-DD or empty for the whole index), Type=0, and the rest of
          the form's fields empty
  3. GET  /{slug}/Search/Records/SelectedSearch/?_=<ms>      (what the result page asks first)
  4. POST /{slug}/Search/Records/Result/  JSON DataTables payload (start, length, order)
          -> {recordsTotal, data: [{RecordingDate, Type ('DEE<br/>DEED'), PartyOne, PartyTwo
             (HTML: one name per line, a grantee's address in .indexdetail_address), Property
             (Parcel #, Remarks = the index's legal description, Amount), FileNumber,
             BookPage ' 333 /  528'}]}; when nothing matches, data is an object, not a list.
Party One is the grantor side (seller, borrower), Party Two the grantee side.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "cott_recordroom_names"
HOST = "https://recordroom.cottsystems.com"
RECORDROOM_COUNTIES: dict[str, str] = {"union": "unionsc"}
PAGE = 100
MAX_PAGES = 4
TIMEOUT_S = 60.0
_COLS = [("function", False), ("function", False), ("function", False), ("ScanPages", True),
         ("RecordingDate", True), ("Type", True), ("PartyOne", False), ("PartyTwo", False),
         ("Property", False), ("FileNumber", True), ("BookPage", True)]


def _slug(state: str, county: str) -> Optional[str]:
    if (state or "").upper() != "SC":
        return None
    return RECORDROOM_COUNTIES.get((county or "").strip().lower())


def search_form(term: str, side: str, date_from: Optional[date], date_to: Optional[date]) -> list[tuple[str, str]]:
    iso = (lambda d: d.isoformat() if d else "")
    party = {"grantor": "8", "grantee": "9"}.get(side, "1")
    names = []
    for i in (0, 1):
        names += [(f"Names[{i}].LastName", ""), (f"Names[{i}].FirstName", ""), (f"Names[{i}].MiddleName", ""),
                  (f"Names[{i}].Title", ""), (f"Names[{i}].NameTypeId", "0")]
    return ([("SearchTerm", term), ("Book", ""), ("Page", ""), ("PartyType", party),
             ("FromDate", iso(date_from)), ("ThruDate", iso(date_to)), ("BeginsWithSearch", "false")]
            + names[:5] + [("Operator", "Or")] + names[5:]
            + [("Property", ""), ("PropertyOperator", "And"), ("PropertyTypeId", ""),
               ("FromDate", iso(date_from)), ("ThruDate", iso(date_to)), ("Type", "0"),
               ("NameDirectory", ""), ("PropertyDirectory", "")])


def grid_payload(start: int) -> dict:
    cols = [{"data": d, "name": "", "searchable": True, "orderable": o, "search": {"value": "", "regex": False}}
            for d, o in _COLS]
    return {"draw": 1, "columns": cols, "order": [{"column": 4, "dir": "desc"}], "start": start, "length": PAGE,
            "search": {"value": "", "regex": False}, "Filters": []}


def party_names(cell_html: str) -> list[str]:
    """A PartyOne / PartyTwo cell's names (address blocks and labels dropped)."""
    soup = BeautifulSoup(cell_html or "", "lxml")
    for blk in soup.select(".indexdetail_address, .indexdetail_label"):
        blk.decompose()
    out: list[str] = []
    for s in soup.stripped_strings:
        n = " ".join(s.split())
        if n and not n.endswith(":") and n not in out:
            out.append(n)
    return out


def _field(html: str, label: str) -> Optional[str]:
    m = re.search(label + r":</strong>\s*<span[^>]*>(?:<a[^>]*>)?([^<]+)", html or "", re.I)
    return " ".join(m.group(1).split()) if m else None


def parse_rows(rows: list, county: str) -> list[RodDoc]:
    out: list[RodDoc] = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        parts = [p.strip() for p in re.split(r"<br\s*/?>", str(r.get("Type") or ""), flags=re.I) if p.strip()]
        code = parts[0].upper() if parts else ""
        label = (parts[-1] if parts else "").upper()
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(r.get("RecordingDate") or ""))
        rec = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
        bp = re.findall(r"[0-9A-Z-]+", str(r.get("BookPage") or ""))
        prop = str(r.get("Property") or "")
        legal = _field(prop, "Remarks")
        amount = None
        am = re.search(r"Amount:</strong>\s*\$\s*([\d,]+(?:\.\d+)?)", prop, re.I)
        if am:
            amount = float(am.group(1).replace(",", ""))
        out.append(RodDoc(county=county, state="SC", doc_type=label or code or "UNKNOWN", recorded_date=rec,
                          book=bp[0] if bp else None, page=bp[1] if len(bp) > 1 else None,
                          grantor="; ".join(party_names(r.get("PartyOne"))) or None,
                          grantee="; ".join(party_names(r.get("PartyTwo"))) or None,
                          amount=amount, instrument_no=str(r.get("FileNumber") or "").strip() or None,
                          parcel_id=_field(prop, r"Parcel\s*#"), notes=(legal or None) and legal[:200],
                          raw={"platform": PLATFORM, "doc_type_label": label or None, "doc_type_code": code or None,
                               "description": legal, "index_id": r.get("IndexId")}))
    return out


def make_searcher(state: str, county: str, *, session: Optional[PoliteSession] = None,
                  date_from: Optional[date] = None) -> Searcher:
    slug = _slug(state, county)
    if slug is None:
        raise KeyError(f"{county} {state} is not a RecordRoom county here")
    base = f"{HOST}/{slug}"
    http = session or PoliteSession(timeout=TIMEOUT_S)
    opened = {"ok": False}
    cname = county.strip().title()

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not opened["ok"]:
            http.get(f"{base}/guest/Search/records")
            opened["ok"] = True
        r = http.post(f"{base}/search/Records", data=search_form(q.term, side, date_from, date_to),
                      headers={"Referer": f"{base}/guest/Search/records"})
        if r.status_code != 200:
            raise RuntimeError(f"search answered HTTP {r.status_code}")
        xhr = {"X-Requested-With": "XMLHttpRequest", "Referer": r.url}
        http.get(f"{base}/Search/Records/SelectedSearch/?_={int(time.time() * 1000)}", headers=xhr)
        out = Docs()
        for page in range(MAX_PAGES):
            g = http.post(f"{base}/Search/Records/Result/", json=grid_payload(page * PAGE), headers=xhr)
            try:
                data = json.loads(g.text)
            except ValueError as exc:
                raise RuntimeError(f"grid answered {g.text[:60]!r}") from exc
            rows = data.get("data") if isinstance(data.get("data"), list) else []
            out.extend(parse_rows(rows, cname))
            total = data.get("recordsTotal") or 0
            if len(rows) < PAGE or (page + 1) * PAGE >= total:
                break
        else:
            out.truncated = True
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    slug = _slug(state, county)
    if slug is None:
        raise KeyError(f"{county} {state} is not a RecordRoom county here")
    return run_chain(platform=PLATFORM, state="SC", county=county.strip().title(), owner_name=owner_name,
                     make_searcher=lambda: make_searcher(state, county, session=session), max_prior=depth,
                     source_url=f"{HOST}/{slug}/guest/Search/records").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _slug(state, county) is None:
        return []
    return run_search(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                      make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first)."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)

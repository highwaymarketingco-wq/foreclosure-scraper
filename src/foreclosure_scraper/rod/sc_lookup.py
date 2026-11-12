"""SC 'The Lookup' (Logan Systems, the newer DataTables build) register reader: name search, deed
chain and lien existence. County: Spartanburg (per-county config in SC_LOOKUP_COUNTIES).

enrichment_spartanburg_rod.py reads Spartanburg's liens by driving a headless browser (rod/
logan_render.py, about 25 s and one Chromium per owner, from 2010 on). The browser is not needed:
the page's own requests work from a plain session (live-checked 2026-10-07), so this reader adds
the deed chain over HTTP and leaves raw['rod'] to the render enricher (registered chain-only).

THE FLOW (the browser's own requests; no CAPTCHA, login or challenge; the disclaimer is
accuracy-only text)
  1. GET  index.php?Accept=Accept           -> the search page, PHPSESSID
  2. GET  content.php?embed=1&searchType=name&last_name&first_name&party_type=Both|Grantor|Grantee
          &start_date&end_date (MM/DD/YYYY)&show_pick_list=1
          -> the pick list: one <input name="name[]" value="SMITH JOHN -JR"
             onclick="storeEID(<count>, 'SMITH_JOHN_-JR')"> per indexed name, and pickListForm's
             hidden fields
  3. POST ajaxActions.php {entityID: <eid>, action: storeEID}   once per name ticked
  4. POST ajaxActions.php {action: checkEID}  -> how many names the session holds (must equal the
                                                names ticked, else the rows are not read)
  5. POST ajaxActions.php {action: storeDataString, dataString: <pickListForm serialized with the
          ticked name[] values>}            what 'Show Records' does
  6. GET  content.php?embedded=1&<random>   -> the instrument rows (<a id="link_<inst>">date</a>
          and summary cells: Book Info | Doc Type | Property Desc | Party Type | Searched Party |
          Reverse Party). A party cell lists several names split by <br>; Party Type is 'Party 1'
          (the grantor side) or 'Party 2' (the grantee side) here, GRANTOR / GRANTEE on other builds.
          An instrument spans one row per searched name and is merged by instrument number.
The site shows at most 2000 rows; names are ticked until their counts reach that.
"""
from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from .logan import _split_book_page
from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, name_fit, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "sc_logan_lookup"
SITE_ROW_CAP = 2000
MAX_NAMES = 12
TIMEOUT_S = 120.0

SC_LOOKUP_COUNTIES: dict[str, str] = {
    "spartanburg": "https://search.spartanburgdeeds.com",
}


def _base(state: str, county: str) -> Optional[str]:
    if (state or "").upper() != "SC":
        return None
    return SC_LOOKUP_COUNTIES.get((county or "").strip().lower())


@dataclass
class PickBox:
    value: str          # the indexed name, e.g. 'SMITH JOHN -JR'
    count: int
    eid: str            # what storeEID takes, e.g. 'SMITH_JOHN_-JR'


def parse_pick(html: str) -> tuple[list[PickBox], list[tuple[str, str]]]:
    """(the pick list's names, pickListForm's hidden fields)."""
    soup = BeautifulSoup(html or "", "lxml")
    boxes: list[PickBox] = []
    for b in soup.find_all("input", attrs={"name": "name[]"}):
        m = re.search(r"storeEID\(\s*(\d+)\s*,\s*'([^']*)'", b.get("onclick") or "")
        if m:
            boxes.append(PickBox(" ".join((b.get("value") or "").split()), int(m.group(1)), m.group(2)))
    form = soup.find("form", id="pickListForm")
    hidden: list[tuple[str, str]] = []
    if form is not None:
        for i in form.find_all("input", attrs={"type": "hidden"}):
            if i.get("name"):
                hidden.append((i["name"], i.get("value") or ""))
    return boxes, hidden


def _names(cell) -> list[str]:
    """A party cell's names (split on <br>)."""
    if cell is None:
        return []
    for br in cell.find_all("br"):
        br.replace_with("\n")
    out = []
    for part in cell.get_text("").replace("\xa0", " ").split("\n"):
        n = " ".join(part.split())
        if n and n not in out:
            out.append(n)
    return out


def _grantee_role(role: str) -> bool:
    r = (role or "").upper()
    return "GRANTEE" in r or "INDIRECT" in r or bool(re.search(r"PARTY\s*2", r))


def to_docs(html: str, county: str) -> list[RodDoc]:
    """The records page -> RodDocs, one per instrument (rows merged by instrument number)."""
    soup = BeautifulSoup(html or "", "lxml")
    by_inst: dict[str, RodDoc] = {}
    order: list[str] = []
    for tr in soup.find_all("tr"):
        link = tr.find("a", id=re.compile(r"^link_"))
        if link is None:
            continue
        inst = link["id"][5:]
        cells = [td for td in tr.find_all("td", recursive=False) if "summary" in (td.get("class") or [])]
        if len(cells) < 5:
            continue
        txt = [" ".join(c.get_text(" ").replace("\xa0", " ").split()) for c in cells[:4]]
        book_info, dtype, desc, role = txt[0], txt[1].upper(), txt[2] or None, txt[3]
        searched = _names(cells[4])
        reverse = _names(cells[5]) if len(cells) > 5 else []
        grantors, grantees = (reverse, searched) if _grantee_role(role) else (searched, reverse)
        doc = by_inst.get(inst)
        if doc is None:
            m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", link.get_text(" "))
            rec = datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else None
            book, page = _split_book_page(re.sub(r"^\s*[A-Z]{1,4}\s+", "", book_info))
            doc = by_inst[inst] = RodDoc(
                county=county, state="SC", doc_type=dtype or "UNKNOWN", recorded_date=rec, book=book, page=page,
                grantor=None, grantee=None, instrument_no=inst, notes=desc,
                raw={"platform": PLATFORM, "doc_type_label": dtype or None, "ki": dtype or None,
                     "description": desc, "book_info": book_info})
            order.append(inst)
        for names, side in ((grantors, "grantor"), (grantees, "grantee")):
            have = [p for p in (getattr(doc, side) or "").split("; ") if p]
            for n in names:
                if n not in have:
                    have.append(n)
            setattr(doc, side, "; ".join(have) or None)
    return [by_inst[i] for i in order]


def _mdy(d: Optional[date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


def make_searcher(state: str, county: str, *, session: Optional[PoliteSession] = None,
                  date_from: Optional[date] = None) -> Searcher:
    base = _base(state, county)
    if base is None:
        raise KeyError(f"{county} {state} is not a 'The Lookup' county here")
    http = session or PoliteSession(timeout=TIMEOUT_S)
    opened = {"ok": False}
    cname = county.strip().title()
    ajax = {"X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/content.php"}

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not opened["ok"]:
            r = http.get(f"{base}/index.php?Accept=Accept")
            if r.status_code != 200 or "content.php" not in r.text:
                raise RuntimeError(f"search page not reached ({r.status_code})")
            opened["ok"] = True
        params = {"embed": "1", "searchType": "name", "search_type": "Standard", "sort_type": "Date",
                  "party_type": {"grantor": "Grantor", "grantee": "Grantee"}.get(side, "Both"),
                  "entity_type": "", "exact_match": "",
                  "last_name": q.term if q.entity else q.last, "first_name": "" if q.entity else q.first,
                  "start_date": _mdy(date_from), "end_date": _mdy(date_to), "show_pick_list": "1"}
        p = http.get(f"{base}/content.php", params=params, headers={"Referer": f"{base}/index.php?Accept=Accept"})
        if p.status_code != 200:
            raise RuntimeError(f"pick list answered HTTP {p.status_code}")
        boxes, hidden = parse_pick(p.text)
        out = Docs()
        if not boxes:
            out.extend(to_docs(p.text, cname))           # a build that skips the pick list
            return out
        rank = {"full": 0, "compatible": 1}
        fit = sorted((b for b in boxes if name_fit(q, b.value)), key=lambda b: rank[name_fit(q, b.value)])
        chosen, rows = [], 0
        for b in fit:
            if len(chosen) >= MAX_NAMES or rows + b.count > SITE_ROW_CAP:
                out.truncated = True
                continue
            chosen.append(b)
            rows += b.count
        if not chosen:
            return out
        for b in chosen:
            http.post(f"{base}/ajaxActions.php", data={"entityID": b.eid, "action": "storeEID"}, headers=ajax)
        held = http.post(f"{base}/ajaxActions.php", data={"action": "checkEID"}, headers=ajax)
        if re.sub(r"\D", "", held.text or "") != str(len(chosen)):
            raise RuntimeError(f"the session holds {held.text.strip()[:8]!r} names, not {len(chosen)}")
        data = urlencode(hidden + [("name[]", b.value) for b in chosen])
        http.post(f"{base}/ajaxActions.php", data={"dataString": data, "action": "storeDataString"}, headers=ajax)
        rec = http.get(f"{base}/content.php?embedded=1&{random.random()}", headers={"Referer": f"{base}/index.php"})
        if rec.status_code != 200:
            raise RuntimeError(f"records answered HTTP {rec.status_code}")
        for d in to_docs(rec.text, cname):
            day = d.recorded_date.date() if d.recorded_date else None
            if day and date_to and day > date_to:
                continue
            out.append(d)
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    base = _base(state, county)
    if base is None:
        raise KeyError(f"{county} {state} is not a 'The Lookup' county here")
    return run_chain(platform=PLATFORM, state="SC", county=county.strip().title(), owner_name=owner_name,
                     make_searcher=lambda: make_searcher(state, county, session=session), max_prior=depth,
                     source_url=f"{base}/index.php").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _base(state, county) is None:
        return []
    return run_search(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                      make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first)."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)

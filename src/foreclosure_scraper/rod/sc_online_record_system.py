"""SC 'Online Record System' register reader (NameSearch / NamePick / NameDisplay): name search,
deed chain and lien existence for the ten SC counties on it.

Counties: Abbeville, Barnwell, Berkeley, Colleton, Dorchester, Florence, Georgetown, York (whose
rows enrichment_rod_name_index.py already reads for lien flags, with no chain) and Laurens and
Lancaster (not read before). Per-county config is one line in SC_ORS_COUNTIES.

THE FLOW (the browser's own steps; live-checked 2026-10-07 on Laurens, Lancaster, Georgetown and
Barnwell; docs/ROD_PORTAL_ACCESS.md has the history):
  1. GET  NameSearch.php?Accept=Accept   clears the accuracy-only disclaimer (no automation clause),
                                          sets PHPSESSID; the search page is 30-220 KB
  2. POST NamePick.php                    search_type=Standard, sort_type=Date, entity_type=Both,
                                          instType[ALL]=ALL, start_date/end_date (MM/DD/YYYY), and
                                          the name: tor_last_name + search_each=on for either side,
                                          tee_last_name for the grantee side, tor_last_name alone for
                                          the grantor side. -> the party pick list: one
                                          entityID[<id>] checkbox per indexed name (aria-label holds
                                          the name), with its count. searchLimit is 2000 names.
  3. POST NameDisplay.php                 igheader=ALL, igquerystring='', displaybutton and the
                                          ticked entityID[<id>] boxes (only the picker's own fields:
                                          echoing the search fields back is rejected)
     -> the rows twice: grouped under '<NAME> ( Grantor|Grantee)' headers (Date | Code-Book-Page |
        Type | Description | Amount | Reverse Party | Cross-Ref | Img?), and a 'sortable' table
        #sortableResultsTable (Date | Book-Page | Type | Grantor | Grantee | Party Type |
        Description | Amount | Image). The sortable table is read when present, else the groups.
Only names that fit the query are ticked at step 3, so a common surname never pulls a stranger's
rows. Every date limit is applied again on the parsed rows, whatever the register did with it.
All hosts are reached over https (see SC_ORS_COUNTIES: over http the form is silently dropped).

Not read: document images and DetailScreen.php (all parties of one instrument; the list shows one
reverse party per row, which is the first-named one).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from bs4 import BeautifulSoup

from .models import RodDoc
from .sc_chain import Docs, NameQuery, Searcher, name_fit, run_chain, run_search
from .sc_polite import PoliteSession

PLATFORM = "sc_online_record_system"
SEARCH_LIMIT = 2000
MAX_NAMES = 12                 # fitting names read per search (full fits first)
BATCH = 6                      # name boxes ticked per display request (a long list can time out)
BATCH_ROWS = 200               # and at most this many indexed rows (the pick list's counts) per request
HEAVY_NAME = 1500              # a name indexed more often than this is not displayed (truncated)
TIMEOUT_S = 90.0


@dataclass(frozen=True)
class OrsCounty:
    base: str                  # scheme + host, no trailing slash
    date_filter: Optional[bool]  # does the register honour start_date/end_date (measured)


#: https everywhere: the http hosts answer a POST with a 302 to https, the client re-sends it as a
#: GET without the form, and NamePick then lists the first 2000 names of the whole index whatever
#: name was typed (found 2026-10-07; it is why five of these counties looked as if they ignored the
#: date window in enrichment_rod_name_index.DATE_FILTER). date_filter: measured over https.
SC_ORS_COUNTIES: dict[str, OrsCounty] = {
    "abbeville": OrsCounty("https://search.abbevilledeeds.com", None),
    "barnwell": OrsCounty("https://barnwelldeeds.com", True),
    "berkeley": OrsCounty("https://search.berkeleydeeds.com", None),
    "colleton": OrsCounty("https://search.colletondeeds.com", None),
    "dorchester": OrsCounty("https://search.dorchesterdeeds.com", None),
    "florence": OrsCounty("https://search.florencedeeds.com", None),
    "georgetown": OrsCounty("https://georgetowndeeds.com", True),
    "lancaster": OrsCounty("https://lancasterscdeeds.com", True),
    "laurens": OrsCounty("https://search.laurensdeeds.com", True),
    "york": OrsCounty("https://search.yorkdeeds.com", None),
}


def _cfg(state: str, county: str) -> Optional[OrsCounty]:
    if (state or "").upper() != "SC":
        return None
    return SC_ORS_COUNTIES.get((county or "").strip().lower())


def _txt(el) -> str:
    if el is None:
        return ""
    return " ".join(el.get_text(" ", strip=True).replace("\xa0", " ").split())


def _mdy(d: Optional[date]) -> str:
    return d.strftime("%m/%d/%Y") if d else ""


# -- pure parsers ---------------------------------------------------------------------------------
@dataclass
class PickName:
    entity_id: str
    name: str
    count: Optional[int]


def parse_pick(html: str) -> list[PickName]:
    """The party pick list: one entry per entityID checkbox."""
    soup = BeautifulSoup(html or "", "lxml")
    out: list[PickName] = []
    for box in soup.find_all("input", attrs={"name": re.compile(r"^entityID\[")}):
        eid = box.get("value") or re.sub(r"^entityID\[|\]$", "", box.get("name", ""))
        name = (box.get("aria-label") or "").strip()
        row = box.find_parent("tr")
        cells = row.find_all("td") if row is not None else []
        if not name and len(cells) > 1:
            name = _txt(cells[1])
        count = None
        if len(cells) > 2:
            m = re.search(r"\d+", _txt(cells[2]))
            count = int(m.group()) if m else None
        if eid:
            out.append(PickName(eid, " ".join(name.split()), count))
    return out


_BP = re.compile(r"^(.*?)[\s-]*-\s*([0-9A-Z]+)\s*-\s*([0-9A-Z]+)\s*$", re.I)


def split_book_page(s: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'RECORD BOOK-5077-480' -> ('RECORD BOOK', '5077', '480'); 'DEED-2113-253' -> ('DEED', ...)."""
    m = _BP.match((s or "").strip())
    if not m:
        return None, None, None
    return (m.group(1).strip() or None), m.group(2).lstrip("0") or m.group(2), m.group(3).lstrip("0") or m.group(3)


def _date(s: str) -> Optional[datetime]:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", s or "")
        if not m2:
            return None
        return datetime(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
    return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))


def _amount(s: str) -> Optional[float]:
    t = re.sub(r"[^0-9.]", "", s or "")
    try:
        return float(t) if t and float(t) > 0 else None
    except ValueError:
        return None


def _inst(cell) -> Optional[str]:
    a = cell.find("a", href=True) if cell is not None else None
    m = re.search(r"inst_num=([0-9A-Za-z-]+)", a["href"]) if a else None
    return m.group(1) if m else None


def _doc(county: str, recorded, bp: str, typ: str, grantor: str, grantee: str, desc: str, amount: str,
         inst: Optional[str], role: str) -> RodDoc:
    code, book, page = split_book_page(bp)
    label = typ.upper().strip()
    return RodDoc(county=county, state="SC", doc_type=label or "UNKNOWN", recorded_date=recorded,
                  book=book, page=page, grantor=grantor or None, grantee=grantee or None,
                  amount=_amount(amount), instrument_no=inst, notes=(desc or None) and desc[:200],
                  raw={"platform": PLATFORM, "doc_type_label": label or None, "book_code": code,
                       "party_role": role or None, "description": (desc or None) and desc[:200]})


def parse_display(html: str, county: str) -> list[RodDoc]:
    """NameDisplay.php -> RodDocs. Reads #sortableResultsTable when present, else the groups."""
    soup = BeautifulSoup(html or "", "lxml")
    table = soup.find("table", id="sortableResultsTable")
    out: list[RodDoc] = []
    if table is not None:
        heads = [_txt(th).upper() for th in table.find_all("th")]
        col = {h: i for i, h in enumerate(heads)}

        def at(cells, name):
            i = col.get(name)
            return cells[i] if i is not None and i < len(cells) else None
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            dc = at(cells, "DATE")
            rec = _date((dc.get("data-order") if dc is not None else "") or _txt(dc))
            if rec is None:
                continue
            out.append(_doc(county, rec, _txt(at(cells, "BOOK-PAGE")), _txt(at(cells, "TYPE")),
                            _txt(at(cells, "GRANTOR")), _txt(at(cells, "GRANTEE")),
                            _txt(at(cells, "DESCRIPTION")), _txt(at(cells, "AMOUNT")), _inst(dc),
                            _txt(at(cells, "PARTY TYPE"))))
        return out
    # grouped layout: a '<NAME> ( Grantor)' header row, a column-label row, then data rows
    name, role, cols = "", "", []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        text = _txt(tr)
        m = re.match(r"^(.*?)\s*\(\s*(Grantor|Grantee)\s*\)\s*$", text, re.I)
        if len(cells) == 1 and m:
            name, role = m.group(1).strip(), m.group(2).title()
            continue
        labels = [_txt(c).upper() for c in cells]
        if "DATE" in labels and "TYPE" in labels:
            cols = labels
            continue
        if not cols or not name or len(cells) < 4:
            continue
        rec = _date(_txt(cells[0]))
        if rec is None or not re.match(r"\d{1,2}/\d{1,2}/\d{4}$", _txt(cells[0])):
            continue
        get = {lab: (cells[i] if i < len(cells) else None) for i, lab in enumerate(cols)}
        rev = next((v for k, v in get.items() if "REVERSE" in k), None)
        other = _txt(rev)
        grantor, grantee = (name, other) if role == "Grantor" else (other, name)
        bp = get.get("CODE-BOOK-PAGE") or get.get("BOOK-PAGE")
        out.append(_doc(county, rec, _txt(bp), _txt(get.get("TYPE")), grantor, grantee,
                        _txt(get.get("DESCRIPTION")), _txt(get.get("AMOUNT")), _inst(cells[0]), role))
    return out


def search_ui_reached(html: str) -> bool:
    """The accepted search page (frmlookup_form), not the disclaimer (about 5 KB) again."""
    return "frmlookup_form" in (html or "") or "NamePick.php" in (html or "")


def batches(picks: list[PickName]) -> list[list[PickName]]:
    """Display requests: at most BATCH names and about BATCH_ROWS indexed rows each (a name
    without a count is taken as 50 rows), so one request never asks for a slow, huge page."""
    out: list[list[PickName]] = []
    cur: list[PickName] = []
    rows = 0
    for p in picks:
        n = p.count if p.count is not None else 50
        if cur and (len(cur) >= BATCH or rows + n > BATCH_ROWS):
            out.append(cur)
            cur, rows = [], 0
        cur.append(p)
        rows += n
    if cur:
        out.append(cur)
    return out


# -- the searcher ---------------------------------------------------------------------------------
def make_searcher(state: str, county: str, *, session: Optional[PoliteSession] = None,
                  date_from: Optional[date] = None) -> Searcher:
    cfg = _cfg(state, county)
    if cfg is None:
        raise KeyError(f"{county} {state} is not an Online Record System county")
    http = session or PoliteSession(timeout=TIMEOUT_S)
    opened = {"ok": False}
    cname = county.strip().title()

    def open_session() -> None:
        r = http.get(f"{cfg.base}/NameSearch.php?Accept=Accept")
        if r.status_code != 200 or not search_ui_reached(r.text):
            raise RuntimeError(f"search page not reached ({r.status_code}, {len(r.text)} bytes)")
        opened["ok"] = True

    def search(q: NameQuery, side: str, date_to: Optional[date]) -> list[RodDoc]:
        if not opened["ok"]:
            open_session()
        data = {"search_type": "Standard", "sort_type": "Date", "entity_type": "Both",
                "instType[ALL]": "ALL", "tor_last_name": "", "tee_last_name": "",
                "start_date": _mdy(date_from), "end_date": _mdy(date_to)}
        if side == "grantee":
            data["tee_last_name"] = q.term
        else:
            data["tor_last_name"] = q.term
            if side == "both":
                data["search_each"] = "on"
        r = http.post(f"{cfg.base}/NamePick.php", data=data,
                      headers={"Referer": f"{cfg.base}/NameSearch.php?Accept=Accept"})
        if r.status_code != 200:
            raise RuntimeError(f"name pick answered HTTP {r.status_code}")
        picks = parse_pick(r.text)
        rank = {"full": 0, "compatible": 1}
        fit = sorted((p for p in picks if name_fit(q, p.name)), key=lambda p: rank[name_fit(q, p.name)])
        out = Docs()
        out.truncated = len(picks) >= SEARCH_LIMIT or len(fit) > MAX_NAMES
        fit = fit[:MAX_NAMES]
        if any((p.count or 0) > HEAVY_NAME for p in fit):
            out.truncated = True
            fit = [p for p in fit if (p.count or 0) <= HEAVY_NAME]
        for batch in batches(fit):
            form = [("igheader", "ALL"), ("igquerystring", ""), ("displaybutton", "Display Detail Listing")]
            form += [(f"entityID[{p.entity_id}]", p.entity_id) for p in batch]
            r = http.post(f"{cfg.base}/NameDisplay.php", data=form,
                          headers={"Referer": f"{cfg.base}/NamePick.php"})
            if r.status_code != 200:
                raise RuntimeError(f"name display answered HTTP {r.status_code}")
            for d in parse_display(r.text, cname):
                day = d.recorded_date.date() if d.recorded_date else None
                if day and ((date_to and day > date_to) or (date_from and day < date_from)):
                    continue                   # five counties ignore the window: apply it here
                out.append(d)
        return out

    return search


def chain(county: str, owner_name: str, *, state: str = "SC", depth: int = 3,
          session: Optional[PoliteSession] = None) -> dict:
    """Last deed into the owner + up to `depth` earlier deeds + lien existence: the shared
    raw['rod_chain'] dict (rod/sc_chain.ChainResult.to_dict)."""
    cfg = _cfg(state, county)
    if cfg is None:
        raise KeyError(f"{county} {state} is not an Online Record System county")
    return run_chain(platform=PLATFORM, state="SC", county=county.strip().title(), owner_name=owner_name,
                     make_searcher=lambda: make_searcher(state, county, session=session), max_prior=depth,
                     source_url=f"{cfg.base}/NameSearch.php?Accept=Accept").to_dict()


def _search_sync(state: str, county: str, name: str, max_docs: int) -> list[RodDoc]:
    if _cfg(state, county) is None:
        return []
    return run_search(platform=PLATFORM, state="SC", county=county.strip().title(), name=name,
                      make_searcher=lambda: make_searcher(state, county), max_docs=max_docs)


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Every instrument naming `name` as grantor or grantee (newest first): the shared
    enrichment_generic_rod interface."""
    return await asyncio.to_thread(_search_sync, state, county, name, max_docs)

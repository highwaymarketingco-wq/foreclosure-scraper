"""Business Information Systems 'Online Record System' (NameSearch / NamePick / NameDisplay), name
index: one adapter for the NC counties on it. The SC counties on the same platform are read by
enrichment_rod_name_index.py; this is the NC side, with the chain.

PROTOCOL (the browser's own steps; live-checked 2026-10-07 on New Hanover and Davidson)
  1. accept the accuracy disclaimer: GET <prefix>NameSearch.php?Accept=Accept (New Hanover, Forsyth)
     or POST Accept=Accept to <prefix>NameSearch.php (Davidson, Guilford) -> the search form
     (frmlookup_form), PHPSESSID
  2. POST the form to its own action (<prefix>NamePick.php): search_type=Standard, party_type
     Both|Grantor|Grantee, entity_type, instType[ALL]=ALL, start_date / end_date (MM/DD/YYYY) and the
     name. Two field styles exist: last_name / first_name, or (New Hanover) tor_last_name /
     tor_first_name with search_each=on, which the page ticks by default ('records that are either
     grantor or grantee'); without search_each the name is searched as grantor only.
     -> the party pick list: one entityID[<id>] checkbox per indexed name, with its count
  3. POST the pick list's own form (frm -> <prefix>NameDisplay.php): its hidden fields, the ticked
     entityID[<id>] boxes and displaybutton='Display Detail Listing'
     -> one block per name: a '<NAME> (Grantor|Grantee)' header, then rows under a header row
        Date | Code-Book-Page | Type | Description | [Amount] | Reverse Party | Cross-Ref | Img?
        (NC shows no Amount column; columns are read by their header labels).
  The page declares searchLimit 2000 parties; a pick list at that size is reported as truncated.

WHAT IS NOT READ: document images and the DetailScreen page (all parties of an instrument; the list
shows one reverse party per row).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso, same_party
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "bis_online_record_system"
ENV_FLAG = "FORECLOSURE_NC_ORS_ROD"
MAX_NAMES = 25
SEARCH_LIMIT = 2000


@dataclass(frozen=True)
class OrsCounty:
    host: str
    search_page: str                 # e.g. NameSearch.php, davidsonNameSearch.php
    accept: str = "GET"              # GET ?Accept=Accept, or POST Accept=Accept


COUNTIES: dict[str, OrsCounty] = {
    "New Hanover": OrsCounty("https://search.newhanoverdeeds.com", "NameSearch.php", "GET"),
    "Davidson": OrsCounty("https://www.davidsondeeds.com", "davidsonNameSearch.php", "POST"),
    "Forsyth": OrsCounty("https://forsythdeeds.com", "forsythNameSearch.php", "GET"),
    "Guilford": OrsCounty("https://rdlxweb.guilfordcountync.gov", "guilfordNameSearch.php", "POST"),
}


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


@dataclass
class SearchForm:
    action: str
    style: str                       # 'single' (last_name) or 'split' (tor_last_name + search_each)
    entity_both: str                 # the entity_type radio's 'both' value as the page spells it
    has_sort: bool
    categories: dict[str, str]


def parse_search_form(html: str) -> Optional[SearchForm]:
    s = BeautifulSoup(html or "", "lxml")
    f = s.find("form", id="frmlookup_form")
    if f is None:
        return None
    names = {i.get("name") for i in f.find_all(["input", "select"]) if i.get("name")}
    ent = [i.get("value") for i in f.find_all("input", attrs={"name": "entity_type"}) if i.get("value")]
    both = next((v for v in ent if v.lower() == "both"), "Both")
    cats: dict[str, str] = {}
    for n in names:
        m = re.match(r"instType\[([^\]]+)\]\[([^\]]+)\]$", n or "")
        if m and m.group(1).upper() not in ("INSTCODES", "ALL"):
            cats.setdefault(m.group(2).strip().upper(), m.group(1).strip().upper())
    return SearchForm(action=f.get("action") or "", style="split" if "tor_last_name" in names else "single",
                      entity_both=both, has_sort="sort_type" in names, categories=cats)


def pick_data(form: SearchForm, who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    d = {"search_type": "Standard", "party_type": {"grantor": "Grantor", "grantee": "Grantee"}.get(side, "Both"),
         "entity_type": form.entity_both, "instType[ALL]": "ALL", "start_date": "",
         "end_date": iso_to_mdy(date_thru)}
    if form.has_sort:
        d["sort_type"] = "Date"
    first = "" if who.entity else who.first
    if form.style == "split":
        d.update({"tor_last_name": who.last, "tor_first_name": first, "tee_last_name": "", "tee_first_name": "",
                  "search_each": "on"})
    else:
        d.update({"last_name": who.last, "first_name": first})
    return d


@dataclass
class OrsName:
    entity_id: str
    last: str
    first: str
    count: int


def parse_pick(html: str) -> tuple[list[OrsName], str, list[tuple[str, str]]]:
    """(names, the display form's action, its hidden fields)."""
    s = BeautifulSoup(html or "", "lxml")
    names: list[OrsName] = []
    for box in s.find_all("input", attrs={"name": re.compile(r"^entityID\[")}):
        tr = box.find_parent("tr")
        cells = [_txt(td) for td in tr.find_all("td", recursive=False)] if tr is not None else []
        cells = (cells + ["", "", "", ""])[:4]
        cnt = re.sub(r"\D", "", cells[3])
        names.append(OrsName(entity_id=box.get("value") or "", last=cells[1], first=cells[2],
                             count=int(cnt) if cnt else 0))
    form = s.find("form", id="frm") or (box.find_parent("form") if names else None)
    action = (form.get("action") if form is not None else "") or ""
    hidden = [(i.get("name"), i.get("value") or "") for i in (form.find_all("input", type="hidden") if form else [])
              if i.get("name")]
    return names, action, hidden


def _book_page(cbp: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """'RB-6872-2731' / 'RECORD BOOK-5057-427' -> (code, book, page)."""
    parts = [p.strip() for p in (cbp or "").split("-") if p.strip()]
    if len(parts) >= 3:
        return "-".join(parts[:-2]) or None, parts[-2], parts[-1]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return None, (parts[0] if parts else None), None


_HEAD = {"date": "date", "code-book-page": "cbp", "type": "type", "description": "desc", "amount": "amount",
         "cross-ref": "xref", "img?": "img"}


def parse_display(html: str, categories: Optional[dict[str, str]] = None) -> list[IndexRecord]:
    """Instrument rows of a NameDisplay page, with each block's searched name and role."""
    s = BeautifulSoup(html or "", "lxml")
    cats = categories or {}
    out: list[IndexRecord] = []
    name, role, cols = "", "", {}
    for tr in s.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue
        first = _txt(tds[0])
        if len(tds) == 1:
            m = re.match(r"^(.*?)\s*\((Grantor|Grantee)\)\s*$", first, re.I)
            if m:
                name, role = m.group(1).strip(), m.group(2).lower()
            continue
        labels = [_txt(td).lower() for td in tds]
        if labels and labels[0] == "date" and any("book" in x for x in labels):
            cols = {}
            for i, lab in enumerate(labels):
                key = _HEAD.get(lab) or ("reverse" if "reverse party" in lab else None)
                if key:
                    cols[key] = i
            continue
        a = tds[0].find("a", href=re.compile(r"inst_num="))
        if a is None or not cols or not re.search(r"\d{2}/\d{2}/\d{4}", first):
            continue

        def cell(key):
            i = cols.get(key)
            return _txt(tds[i]) if i is not None and i < len(tds) else ""

        code, book, page = _book_page(cell("cbp"))
        dtype = cell("type")
        reverse = cell("reverse")
        xref_i = cols.get("xref")
        xa = tds[xref_i].find("a") if xref_i is not None and xref_i < len(tds) else None
        mi = re.search(r"inst_num=(\d+)", a.get("href", ""))
        rec = IndexRecord(recorded=mdy_to_iso(first), book=book, page=page,
                          instrument_no=mi.group(1) if mi else None, doc_type=dtype,
                          category=cats.get(dtype.upper()), description=cell("desc") or None,
                          xref=(_txt(xa) or None) if xa is not None else (cell("xref") or None), index_code=code)
        searched = [name] if name else []
        other = [reverse] if reverse else []
        rec.grantors, rec.grantees = (other, searched) if role == "grantee" else (searched, other)
        out.append(rec)
    return out


def no_names_found(html: str) -> bool:
    """The pick screen's own 'nothing matched' answer ('Name Pick Screen ... 0 Names Found')."""
    return bool(re.search(r"\b0\s+Names?\s+Found", html or "", re.I)) and "entityID" not in (html or "")


def pick_matching(names: list[OrsName], who: OwnerName) -> list[OrsName]:
    """The pick-list names that are this owner (Last Name / First Name columns; an entity's whole
    name sits in Last Name)."""
    out = []
    for n in names:
        label = f"{n.last} {n.first}".strip() if who.entity else f"{n.last}, {n.first}"
        if same_party(who, label):
            out.append(n)
    return out


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class OnlineRecordSystem(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES

    def source_url(self, cfg: OrsCounty) -> str:
        return f"{cfg.host}/{cfg.search_page}"

    def _open(self, client: PoliteClient, cfg: OrsCounty) -> SearchForm:
        url = f"{cfg.host}/{cfg.search_page}"
        if cfg.accept == "POST":
            page = client.post(url, {"Accept": "Accept"}, headers={"Referer": url})
        else:
            page = client.get(url + "?Accept=Accept")
        form = parse_search_form(page.text)
        if form is None or not form.action:
            raise RuntimeError("the disclaimer did not open the name search form")
        return form

    def _search(self, client: PoliteClient, cfg: OrsCounty, form: SearchForm, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        url = f"{cfg.host}/{cfg.search_page}"
        pick = client.post(f"{cfg.host}/{form.action.lstrip('/')}", pick_data(form, who, side, date_thru),
                           headers={"Referer": url})
        if pick.status >= 400:
            return SearchResult(status="error", reason=f"HTTP {pick.status}", url=url)
        names, action, hidden = parse_pick(pick.text)
        if not names:
            if no_names_found(pick.text):
                return SearchResult(records=[], total=0, url=url)
            return SearchResult(status="error", reason="the pick list could not be read", url=url)
        chosen = pick_matching(names, who)
        if not chosen:
            return SearchResult(records=[], total=0, url=url)
        if not action:
            return SearchResult(status="error", reason="the pick list has no display form", url=url)
        truncated = len(chosen) > MAX_NAMES or len(names) >= SEARCH_LIMIT
        chosen = chosen[:MAX_NAMES]
        data = [*hidden, ("displaybutton", "Display Detail Listing")]
        data += [(f"entityID[{n.entity_id}]", n.entity_id) for n in chosen]
        page = client.post(f"{cfg.host}/{action.lstrip('/')}", data, headers={"Referer": pick.final_url})
        if page.status >= 400:
            return SearchResult(status="error", reason=f"HTTP {page.status}", url=url)
        rows = parse_display(page.text, form.categories)
        expected = sum(n.count for n in chosen)
        if not rows and expected:
            return SearchResult(status="error", reason="the ticked names list no rows", url=url)
        return SearchResult(records=rows, total=expected, truncated=truncated, url=url)


ADAPTER = OnlineRecordSystem()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

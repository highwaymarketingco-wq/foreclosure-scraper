"""'The Lookup' (Logan Systems / Business Information Systems land-record search), name index: one
adapter for every NC county on it (search.<county>deeds.com and robeson.bislandrecords.com).

PROTOCOL, the same steps a person's browser takes (live-checked 2026-10-07 on Avery and Columbus)
  1. GET  index.php?Accept=Accept       clears the accuracy disclaimer; PHPSESSID; 'The Lookup'
  2. GET  content.php?embed=1&searchType=name&last_name=&first_name=&party_type=Both|Grantor|Grantee
          &start_date=&end_date=MM/DD/YYYY&show_pick_list=1 ...
          -> the name pick list: one checkbox per indexed name (LastName | FirstName | Count) and the
             pickListForm's hidden fields
  3. POST ajaxActions.php {entityID, action: storeEID}   once per name ticked (what a tick does)
  4. POST ajaxActions.php {action: checkEID}             -> how many names the session holds; must
                                                            equal the names ticked, else the rows
                                                            are not read (a stale selection would
                                                            mix another search's names in)
  5. GET  content.php?<pickListForm fields>&embed=1      -> the instruments of the ticked names
  A new pick list clears the previous selection (checked live), so one session serves a run.
  Row: Date | Book Info ('RE 623 1239') | Doc Type (county code) | Property Desc | Party Type |
       Searched Party | Reverse Party | XRef | Clipboard | Image?  -- one row per party pair, so an
       instrument with several parties spans several rows (folded by instrument number).

Where the county publishes its code list (instType[CATEGORY][CODE] on the search page, e.g.
Avery), the category (DEED, DEED OF TRUST, CANCELLATION, OTHER) is used to classify the code;
newer builds (Columbus) publish none, and the code is classified by its own text.

WHAT IS NOT READ: document images (view_image.php keys are session-scoped; never fetched).
COUNTIES ALREADY READ ELSEWHERE: Clay, Haywood, Yancey (enrichment_rod_lookup, raw['rod_lookup']);
Transylvania, McDowell, Mitchell (rod/logan.py recent-NOD sweep only). This adapter adds the
per-owner lien read (raw['rod']) and the chain for them too, behind the same default-off flag.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .logan import _split_book_page
from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso, party_name, same_party
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "logan_lookup"
ENV_FLAG = "FORECLOSURE_NC_LOOKUP_ROD"

#: the most names one lookup ticks, and the row cap the site itself announces ('only 2000 records
#: will be displayed')
MAX_NAMES = 25
SITE_ROW_CAP = 2000


@dataclass(frozen=True)
class LookupCounty:
    host: str                        # scheme://host, no trailing slash


COUNTIES: dict[str, LookupCounty] = {
    "Avery": LookupCounty("https://search.averydeeds.com"),
    "Bertie": LookupCounty("https://search.bertiedeeds.com"),
    "Columbus": LookupCounty("https://search.columbusdeeds.com"),
    "Macon": LookupCounty("https://search.macondeeds.com"),
    "Robeson": LookupCounty("https://robeson.bislandrecords.com"),
    # read elsewhere already (see the module docstring)
    "Clay": LookupCounty("http://search.claydeeds.com"),
    "Haywood": LookupCounty("http://search.haywooddeeds.com"),
    "Yancey": LookupCounty("http://search.yanceydeeds.com"),
    "Transylvania": LookupCounty("https://search.transylvaniadeeds.com"),
    "McDowell": LookupCounty("https://search.mcdowelldeeds.com"),
    "Mitchell": LookupCounty("https://search.mitchelldeeds.com"),
}


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


def is_search_page(html: str) -> bool:
    return "the lookup" in (html or "").lower() and "content.php" in (html or "")


def code_categories(search_page: str) -> dict[str, str]:
    """{code: category} from the instType[CATEGORY][CODE] checkboxes, when the county publishes them."""
    out: dict[str, str] = {}
    for cat, code in re.findall(r'name="instType\[([^\]]+)\]\[([^\]]+)\]"', search_page or ""):
        if cat.upper() not in ("ALL", "INSTCODES"):
            out.setdefault(code.strip().upper(), cat.strip().upper())
    return out


@dataclass
class PickName:
    entity_id: str
    last: str
    first: str
    count: int

    @property
    def full(self) -> str:
        return f"{self.last} {self.first}".strip()


def parse_pick_list(html: str) -> tuple[list[PickName], list[tuple[str, str]]]:
    """(the names on the pick list, the pickListForm's hidden fields)."""
    s = BeautifulSoup(html or "", "lxml")
    names: list[PickName] = []
    for box in s.find_all("input", attrs={"name": "entityID[]"}):
        tr = box.find_parent("tr")
        if tr is None:
            continue
        cells = [_txt(td) for td in tr.find_all("td", recursive=False)]
        cells = (cells + ["", "", "", ""])[:4]
        cnt = re.sub(r"\D", "", cells[3])
        names.append(PickName(entity_id=box.get("value") or "", last=cells[1], first=cells[2],
                              count=int(cnt) if cnt else 0))
    form = s.find("form", id="pickListForm")
    hidden: list[tuple[str, str]] = []
    if form is not None:
        for i in form.find_all("input", type="hidden"):
            if i.get("name"):
                hidden.append((i.get("name"), i.get("value") or ""))
    return names, hidden


def parse_rows(html: str, categories: Optional[dict[str, str]] = None) -> list[IndexRecord]:
    """Instrument rows, folded by instrument number (one row per party pair on the page)."""
    s = BeautifulSoup(html or "", "lxml")
    cats = categories or {}
    out: dict[str, IndexRecord] = {}
    order: list[str] = []
    for tr in s.find_all("tr"):
        link = tr.find("a", id=re.compile(r"^link_\d+"))
        if link is None:
            continue
        inst = link.get("id", "")[5:]
        summ = [_txt(td) for td in tr.find_all("td", recursive=False) if "summary" in (td.get("class") or [])]
        if len(summ) < 5:
            continue
        if len(summ) >= 6:
            book_info, dtype, desc, role, searched, reverse = summ[:6]
        else:
            book_info, dtype, desc, role, searched = summ[:5]
            reverse = ""
        is_grantee = "GRANTEE" in role.upper() or "INDIRECT" in role.upper()
        tds = tr.find_all("td", recursive=False)
        xref = None
        for td in tds:
            a = td.find("a", href=re.compile(r"loadDetailsScreen"))
            if a is not None and a is not link:
                xref = _txt(a) or None
                break
        rec = out.get(inst)
        if rec is None:
            book, page = _split_book_page(book_info)
            code = (dtype or "").strip().upper()
            bm = re.match(r"\s*([A-Z]{1,4})\s+\d", book_info or "")
            rec = out[inst] = IndexRecord(
                recorded=mdy_to_iso(_txt(link)), book=book, page=page, instrument_no=inst,
                doc_type=(dtype or "").strip(), category=cats.get(code), description=desc or None,
                xref=xref, index_code=bm.group(1) if bm else None)
            order.append(inst)
        grantors, grantees = (rec.grantees, rec.grantors) if is_grantee else (rec.grantors, rec.grantees)
        for name, bucket in ((searched, grantors), (reverse, grantees)):
            if name and name not in bucket:
                bucket.append(name)
        rec.xref = rec.xref or xref
    return [out[i] for i in order]


def no_records(html: str) -> bool:
    return bool(re.search(r"no (?:records|matches|names|results)(?: were)? found|returned no", html or "", re.I))


def pick_matching(names: list[PickName], who: OwnerName) -> list[PickName]:
    """The pick-list names that are this owner (index names are surname first)."""
    out = []
    for n in names:
        if who.entity:
            pn = party_name(n.full)
            if pn is not None and same_party(who, n.full):
                out.append(n)
        elif same_party(who, f"{n.last}, {n.first}"):
            out.append(n)
    return out


def pick_query(who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    return {"embed": "1", "searchType": "name", "search_type": "Standard", "sort_type": "Date",
            "party_type": {"grantor": "Grantor", "grantee": "Grantee"}.get(side, "Both"), "entity_type": "",
            "exact_match": "", "last_name": who.last, "first_name": "" if who.entity else who.first,
            "start_date": "", "end_date": iso_to_mdy(date_thru), "show_pick_list": "1"}


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class Lookup(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES

    def source_url(self, cfg: LookupCounty) -> str:
        return cfg.host + "/index.php"

    def _open(self, client: PoliteClient, cfg: LookupCounty) -> dict:
        page = client.get(cfg.host + "/index.php?Accept=Accept")
        if not is_search_page(page.text):
            raise RuntimeError("the disclaimer did not open 'The Lookup' search page")
        return {"categories": code_categories(page.text)}

    def _search(self, client: PoliteClient, cfg: LookupCounty, ctx: dict, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        host, url = cfg.host, cfg.host + "/index.php"
        ref = {"Referer": host + "/index.php?Accept=Accept"}
        pick = client.get(host + "/content.php", params=pick_query(who, side, date_thru), headers=ref)
        if pick.status >= 400:
            return SearchResult(status="error", reason=f"HTTP {pick.status}", url=url)
        names, hidden = parse_pick_list(pick.text)
        if not names:
            rows = parse_rows(pick.text, ctx.get("categories"))      # a build that skips the pick list
            if rows:
                return SearchResult(records=rows, total=len(rows), url=url)
            if no_records(pick.text) or "pickListForm" in pick.text:
                return SearchResult(records=[], total=0, url=url)
            return SearchResult(status="error", reason="the answer was neither a pick list nor rows", url=url)
        chosen = pick_matching(names, who)
        if not chosen:
            return SearchResult(records=[], total=0, url=url)
        truncated = len(chosen) > MAX_NAMES
        chosen = chosen[:MAX_NAMES]
        ajax = {"Referer": host + "/content.php", "X-Requested-With": "XMLHttpRequest"}
        for n in chosen:
            client.post(host + "/ajaxActions.php", {"entityID": n.entity_id, "action": "storeEID"}, headers=ajax)
        held = client.post(host + "/ajaxActions.php", {"action": "checkEID"}, headers=ajax)
        if re.sub(r"\D", "", held.text or "") != str(len(chosen)):
            return SearchResult(status="error", url=url,
                                reason=f"the session holds {held.text.strip()[:10]!r} names, not the "
                                       f"{len(chosen)} ticked; rows not read")
        page = client.get(host + "/content.php", params=[*hidden, ("embed", "1")],
                          headers={"Referer": host + "/content.php"})
        if page.status >= 400:
            return SearchResult(status="error", reason=f"HTTP {page.status}", url=url)
        rows = parse_rows(page.text, ctx.get("categories"))
        expected = sum(n.count for n in chosen)
        if not rows and expected:
            return SearchResult(status="error", url=url, reason="the ticked names list no rows")
        return SearchResult(records=rows, total=expected, url=url,
                            truncated=truncated or expected > SITE_ROW_CAP)


ADAPTER = Lookup()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

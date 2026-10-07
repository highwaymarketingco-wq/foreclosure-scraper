"""Logan Systems 'Register Of Deeds Remote Access Site' (classic ASP site; the name search is a
Gizmox Visual WebGui app, search.wgx), name index, in a headless browser: Anson, Ashe, Bladen,
Cherokee, Davie, Martin, Northampton, Swain, Vance, Warren, Yadkin. The search UI is drawn by the
Visual WebGui client script and talks XML events to the server, so the adapter does what a person
does on the drawn page (rod/nc_render.py; the Spartanburg precedent) instead of emulating the
client.

FLOW (live-checked 2026-10-07 on Vance)
  1. <root>              the disclaimer; 'Acknowledge Disclaimer to Begin Searching Records' is a
                         link to welcome.asp (sets the session)
  2. <root>SearchStart.aspx -> search.wgx: Index Search tab, Name sub-tab. The text boxes carry
     generated ids and no <label for>, so each is found on the same row as its caption: 'Surname
     (last name)', 'Given Name', 'Start Date' / 'End Date' (masked boxes: set in one step and
     committed with Tab, since typed keys come out garbled); 'Non-Human' for an entity; 'Search'.
  3. the 'Directory' tab (#TXT_12): a grid (rows VWGROW2_<grid>_R<n>) of Name | Entries with a
     check box per row; tick the owner's names; 'View Checked'
  4. the 'Index/Detail' tab (#TXT_13): a grid whose header cells (VWG_<grid>_C<n>) line up with
     the row cells: C, Series ('1-Grantor' / '2-Grantee'), Name, Reverse Party, Description,
     Rec Date, Type, Book/Page.
  The date limits are applied again here on the recorded dates. The directory shows no total: 25 or
  more name rows, or fewer detail rows than the ticked names' entry counts (the grid draws only the
  rows in view), is reported as truncated.
WHAT IS NOT READ: the imaging pages (BookAndPage.asp, the scanned index books).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso, same_party
from .nc_render import NcRenderPlatform, RenderPage

PLATFORM = "logan_remote_access"
ENV_FLAG = "FORECLOSURE_NC_LOGAN_REMOTE_ROD"
CAP_ENV = "FORECLOSURE_NC_LOGAN_REMOTE_ROD_MAX"
MAX_NAMES = 25
DIRECTORY_PAGE = 25
SETTLE_POLLS = 20

ACK = "text=Acknowledge Disclaimer"
SURNAME = "Surname (last name)"
GIVEN = "Given Name"
START = "Start Date"
END = "End Date"
SEARCH = "span:text-is('Search')"
DIRECTORY_TAB = "#TXT_12"
DETAIL_TAB = "#TXT_13"
VIEW_CHECKED = "span:text-is('View Checked'):visible"


def name_type(entity: bool) -> str:
    return "span:text-is('Non-Human')" if entity else "span:text-is('Human')"


def row_check(grid: str, row: int, col: int = 0) -> str:
    """The row's check box by structure: the focusable control inside the check-box column's cell.
    Class and handler names differ by skin (Vance 'CheckBox-Control_ca' / CheckBox_Click; Davie
    minified 'cb30 cb27 cca1' / s237.sx1), the structure does not."""
    return f"#VWGROW2_{grid}_R{row} > div:nth-child({col + 1}) [data-vwgfocuselement]"


@dataclass(frozen=True)
class RemoteCounty:
    root: str                      # ends with '/'


COUNTIES: dict[str, RemoteCounty] = {
    "Davie": RemoteCounty("https://www.daviencrod.org/"),
    "Yadkin": RemoteCounty("https://www.yadkincorod.org/"),
    "Vance": RemoteCounty("https://www.vancencrod.org/"),
    "Martin": RemoteCounty("https://www.martinrod.org/"),
    "Cherokee": RemoteCounty("https://www.cherokeencrod.org/"),
    "Anson": RemoteCounty("https://www.ansonncrod.org/"),
    "Bladen": RemoteCounty("https://www.bladenncrod.org/"),
    "Ashe": RemoteCounty("https://www.ashencrod.org/"),
    "Northampton": RemoteCounty("https://northamptonrod.org/"),
    "Warren": RemoteCounty("https://warrenrod.org/"),
    "Swain": RemoteCounty("https://www.swaincorod.org/"),
}


def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


def parse_grids(html: str) -> dict[str, tuple[list[str], list[tuple[int, list[str]]]]]:
    """{grid id: (header labels, [(row number, cell texts)])} for every Visual WebGui grid."""
    s = BeautifulSoup(html or "", "lxml")
    out: dict[str, tuple[list[str], list[tuple[int, list[str]]]]] = {}
    for h in s.find_all(id=re.compile(r"^VWG_\d+_C\d+$")):
        g = h["id"].split("_")[1]
        out.setdefault(g, ([], []))[0].append(_txt(h))
    for r in s.find_all(id=re.compile(r"^VWGROW2_\d+_R\d+$")):
        _, g, rn = r["id"].split("_")
        cells = [_txt(c) for c in r.find_all(recursive=False)]
        out.setdefault(g, ([], []))[1].append((int(rn[1:]), cells))
    return out


def directory(html: str) -> tuple[Optional[str], list[tuple[int, str, int]], int]:
    """(the Directory grid id or None, [(row number, name, entries)], the check-box column)."""
    for g, (heads, rows) in parse_grids(html).items():
        low = [x.lower() for x in heads]
        if "name" in low and "entries" in low:
            ni, ei = low.index("name"), low.index("entries")
            check_col = low.index("") if "" in low else 0
            out = []
            for rn, cells in rows:
                if len(cells) > max(ni, ei) and cells[ni]:
                    cnt = re.sub(r"\D", "", cells[ei])
                    out.append((rn, cells[ni], int(cnt) if cnt else 0))
            return g, out, check_col
    return None, [], 0


def _bp(s: str) -> tuple[Optional[str], Optional[str]]:
    a, _, b = (s or "").partition("/")
    a, b = a.strip().lstrip("0") or a.strip(), b.strip().lstrip("0") or b.strip()
    return (a or None), (b or None)


def detail(html: str) -> Optional[list[tuple[IndexRecord, str]]]:
    """[(record, the named party's side)] from the Index/Detail grid, or None when it is absent."""
    for heads, rows in parse_grids(html).values():
        low = [x.lower() for x in heads]
        if "series" not in low or "reverse party" not in low:
            continue
        out: list[tuple[IndexRecord, str]] = []
        for _, cells in sorted(rows):
            if len(cells) != len(low):
                continue
            v = dict(zip(low, cells))
            grantee_side = "grantee" in v.get("series", "").lower()
            party, reverse = v.get("name", ""), v.get("reverse party", "")
            book, page = _bp(v.get("book/page", ""))
            out.append((IndexRecord(
                recorded=mdy_to_iso(v.get("rec date")), book=book, page=page, doc_type=v.get("type", ""),
                description=v.get("description") or None,
                grantors=[x for x in ([reverse] if grantee_side else [party]) if x],
                grantees=[x for x in ([party] if grantee_side else [reverse]) if x]),
                "grantee" if grantee_side else "grantor"))
        return out
    return None


class LoganRemote(NcRenderPlatform):
    platform = PLATFORM
    counties = COUNTIES
    cap_env = CAP_ENV

    def source_url(self, cfg: RemoteCounty) -> str:
        return cfg.root + "SearchStart.aspx"

    def _render_search(self, rp: RenderPage, cfg: RemoteCounty, who: OwnerName, side: str,
                       date_thru: Optional[str], date_from: Optional[str] = None) -> SearchResult:
        url = self.source_url(cfg)
        rp.goto(cfg.root)
        if rp.has(ACK):
            rp.click_nav(ACK)
        else:
            rp.goto(cfg.root + "welcome.asp")
        rp.goto(url)
        if not rp.wait_for(f"span:text-is('{SURNAME}')", timeout_ms=30000):
            return SearchResult(status="error", reason="the name search did not open", url=url)
        surname, given = rp.input_beside(SURNAME), rp.input_beside(GIVEN)
        if not surname:
            return SearchResult(status="error", reason="the surname box was not found", url=url)
        if who.entity:
            rp.click_local(name_type(True))
        rp.type_into(surname, who.last)
        rp.press("Tab")                                   # the drawn box commits its value on blur
        if given and not who.entity and who.first:
            rp.type_into(given, who.first)
            rp.press("Tab")
        # The date boxes are masked inputs that garble typed keys, so their value is set in one step
        # and committed with Tab (live-checked on Vance: a June-September window listed 19 names, each
        # counted inside the window). The limits are applied again below on the recorded dates.
        for label, iso in ((START, date_from), (END, date_thru)):
            box = rp.input_beside(label) if iso else None
            if box:
                rp.fill(box, iso_to_mdy(iso))
                rp.press("Tab")
        rp.click_wait(SEARCH, settle_ms=4000)
        html = rp.click_wait(DIRECTORY_TAB, settle_ms=2000)
        grid, names, check_col = directory(html)
        for _ in range(SETTLE_POLLS):
            if grid is not None:
                break
            rp.page.wait_for_timeout(1000)
            html = rp.html()
            grid, names, check_col = directory(html)
        if grid is None:
            return SearchResult(status="error", reason="the Directory grid did not appear", url=url)
        chosen = [n for n in names if same_party(who, n[1])]
        if not chosen:
            return SearchResult(records=[], total=0, url=url)
        truncated = len(chosen) > MAX_NAMES or len(names) >= DIRECTORY_PAGE
        for rn, _, _ in chosen[:MAX_NAMES]:
            rp.click_local(row_check(grid, rn, check_col))
        rp.click_wait(VIEW_CHECKED, settle_ms=4000)
        html = rp.click_wait(DETAIL_TAB, settle_ms=2000)
        sided = detail(html)
        for _ in range(SETTLE_POLLS):
            if sided:
                break
            rp.page.wait_for_timeout(1000)
            html = rp.html()
            sided = detail(html)
        if not sided:
            return SearchResult(status="error", reason="the Index/Detail grid could not be read", url=url)
        rows = [r for r, s in sided
                if (side not in ("grantor", "grantee") or s == side)
                and (not date_thru or not r.recorded or r.recorded <= date_thru)
                and (not date_from or not r.recorded or r.recorded >= date_from)]
        expected = sum(n[2] for n in chosen[:MAX_NAMES])
        return SearchResult(records=rows, total=len(sided), url=url,
                            truncated=truncated or len(sided) < expected)


ADAPTER = LoganRemote()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

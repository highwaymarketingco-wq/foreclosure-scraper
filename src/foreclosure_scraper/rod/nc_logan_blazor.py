"""Logan Systems 'Public Records' (server-side Blazor, DevExpress grids) name index, in a headless
browser: Catawba, Cumberland, Union, Cabarrus, Chatham, Sampson, Wilkes. The search runs over a
Blazor websocket, so there is no request to replay; the adapter clicks and types the way a person
does (rod/nc_render.py; the Spartanburg precedent). Element ids are random per session, so every
control is found by its visible label or button text.

FLOW (live-checked 2026-10-07 on Catawba, Cumberland, Union)
  1. <root>                         'Acknowledge Disclaimer to Begin Searching Records' button
  2. 'Full System' button           -> /FullSystem, the Index Search tab, Name sub-tab
  3. Human / Corp radio, 'Last Name', 'Given Name', 'End Date' (the inputs after those labels),
     the 'Search' button            -> the 'Directory (N)' tab: one row per indexed name
                                       (Name, Entries) with a check box
  4. tick the rows that are the owner, 'View Checked' -> the 'Index Detail (N)' tab: Index, C,
     Series ('1-Grantor' / '2-Grantee': the named party's side), Name, Reverse Party,
     Description, Rec Date, Type, Book/Page (and Instrument # where the county shows it), read by
     header label. Fewer rendered rows than N is reported as truncated.
  The answers arrive over the websocket after 'network idle', so the Directory and Index Detail
  counts are polled for up to SETTLE_POLLS seconds before a zero is believed.
  The name index has no side selector: a grantee-side search keeps the rows whose Series is
  2-Grantee.
WHAT IS NOT READ: the Image tab (document images).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso, same_party
from .nc_render import NcRenderPlatform, RenderPage

PLATFORM = "logan_blazor"
ENV_FLAG = "FORECLOSURE_NC_LOGAN_BLAZOR_ROD"
CAP_ENV = "FORECLOSURE_NC_LOGAN_BLAZOR_ROD_MAX"
MAX_NAMES = 25
SETTLE_POLLS = 30                # seconds to wait for a slow Directory answer before reading it as empty

ACK = "text=Acknowledge Disclaimer"
FULL_SYSTEM = "button:has-text('Full System')"
SEARCH = "button >> text=/^\\s*Search\\s*$/"
VIEW_CHECKED = "button:visible:has-text('View Checked')"


def labeled(label: str) -> str:
    return f"xpath=//label[normalize-space()='{label}']/following::input[1]"


def radio(label: str) -> str:
    return f"xpath=//label[normalize-space()='{label}']"


def directory_check(index: int) -> str:
    return f'dxbl-grid >> nth=0 >> tr[data-visible-index="{index}"] >> dxbl-check'


@dataclass(frozen=True)
class BlazorCounty:
    root: str                     # ends with '/'


COUNTIES: dict[str, BlazorCounty] = {
    "Catawba": BlazorCounty("https://www.catawbarod.org/"),
    "Cumberland": BlazorCounty("https://www.ccrodinternet.org/"),
    "Union": BlazorCounty("https://www.unionconcrod.org/"),
    "Cabarrus": BlazorCounty("https://www.cabarrusncrod.org/"),
    "Chatham": BlazorCounty("https://www.chathamncrod.org/"),
    "Sampson": BlazorCounty("https://www.sampsonrod.org/"),
    "Wilkes": BlazorCounty("https://www.wilkesncrod.org/"),
}


def _txt(el) -> str:
    return " ".join((el.get_text(" ", strip=True) if el is not None else "").replace("\xa0", " ").split())


def tab_counts(html: str) -> dict[str, int]:
    """{'directory': N, 'index detail': N} from the tab captions."""
    out: dict[str, int] = {}
    for tab in BeautifulSoup(html or "", "lxml").find_all("dxbl-tab-item"):
        m = re.match(r"^([A-Za-z][A-Za-z ]*?)\s*\((\d+)\)", _txt(tab))   # the caption repeats itself
        if m:
            out[m.group(1).strip().lower()] = int(m.group(2))
    return out


def _grids(html: str):
    return BeautifulSoup(html or "", "lxml").find_all("dxbl-grid")


def parse_directory(html: str) -> list[tuple[int, str, int]]:
    """(row index, indexed name, entries) for each Directory row."""
    grids = _grids(html)
    out: list[tuple[int, str, int]] = []
    if not grids:
        return out
    for tr in grids[0].find_all("tr", attrs={"data-visible-index": True}):
        cells = [_txt(td) for td in tr.find_all("td", attrs={"role": "gridcell"})]
        if not cells or not cells[0]:
            continue
        n = re.sub(r"\D", "", cells[1]) if len(cells) > 1 else ""
        out.append((int(tr["data-visible-index"]), cells[0], int(n) if n else 0))
    return out


def _bp(s: str) -> tuple[Optional[str], Optional[str]]:
    a, _, b = (s or "").partition("/")
    a, b = a.strip().lstrip("0") or a.strip(), b.strip().lstrip("0") or b.strip()
    return (a or None), (b or None)


def parse_detail_sides(html: str) -> list[tuple[IndexRecord, str]]:
    """(record, 'grantor' or 'grantee': the named party's side) for each Index Detail row (the grid
    whose header has Series and Reverse Party)."""
    out: list[tuple[IndexRecord, str]] = []
    for g in _grids(html):
        heads = [_txt(th).lower() for th in g.find_all("th")]
        if "series" not in heads or "reverse party" not in heads:
            continue
        for tr in g.find_all("tr", attrs={"data-visible-index": True}):
            tds = tr.find_all("td")
            if len(tds) != len(heads):
                continue
            v = {h: _txt(td) for h, td in zip(heads, tds)}
            party, reverse = v.get("name", ""), v.get("reverse party", "")
            grantee_side = "grantee" in v.get("series", "").lower()
            book, page = _bp(v.get("book/page", ""))
            out.append((IndexRecord(
                recorded=mdy_to_iso(v.get("rec date")), book=book, page=page, doc_type=v.get("type", ""),
                instrument_no=v.get("instrument #") or None,
                description=v.get("description") or None, index_code=v.get("index") or None,
                grantors=[x for x in ([reverse] if grantee_side else [party]) if x],
                grantees=[x for x in ([party] if grantee_side else [reverse]) if x]),
                "grantee" if grantee_side else "grantor"))
        break
    return out


def parse_detail(html: str) -> list[IndexRecord]:
    return [r for r, _ in parse_detail_sides(html)]


class LoganBlazor(NcRenderPlatform):
    platform = PLATFORM
    counties = COUNTIES
    cap_env = CAP_ENV

    def source_url(self, cfg: BlazorCounty) -> str:
        return cfg.root + "FullSystem"

    def _render_search(self, rp: RenderPage, cfg: BlazorCounty, who: OwnerName, side: str,
                       date_thru: Optional[str], date_from: Optional[str] = None) -> SearchResult:
        url = self.source_url(cfg)
        rp.goto(cfg.root)
        # the Blazor page draws its buttons after its websocket connects, i.e. after network idle
        if rp.wait_for(ACK, timeout_ms=20000):
            rp.click_wait(ACK, settle_ms=2500)
        if not rp.wait_for(FULL_SYSTEM, timeout_ms=20000):
            return SearchResult(status="error", reason="the records menu did not open", url=url)
        rp.click_wait(FULL_SYSTEM, settle_ms=2500)
        if not rp.wait_for(labeled("Last Name"), timeout_ms=30000):
            return SearchResult(status="error", reason="the name search did not open", url=url)
        rp.click_local(radio("Corp" if who.entity else "Human"))
        rp.type_into(labeled("Last Name"), who.last)
        rp.type_into(labeled("Given Name"), "" if who.entity else who.first)
        if date_from:
            rp.type_into(labeled("Start Date"), iso_to_mdy(date_from))
        rp.type_into(labeled("End Date"), iso_to_mdy(date_thru) if date_thru else "")
        html = rp.click_wait(SEARCH, settle_ms=3000)
        counts = tab_counts(html)
        # the answer arrives over the websocket, after network idle: give it up to SETTLE_POLLS s
        for _ in range(SETTLE_POLLS):
            if counts.get("directory"):
                break
            rp.page.wait_for_timeout(1000)
            html = rp.html()
            counts = tab_counts(html)
        if "directory" not in counts:
            return SearchResult(status="error", reason="the search answered without a Directory tab", url=url)
        names = parse_directory(html)
        if counts["directory"] == 0 or not names:
            return SearchResult(records=[], total=0, url=url)
        chosen = [n for n in names if same_party(who, n[1])]
        if not chosen:
            return SearchResult(records=[], total=0, url=url)
        truncated = len(chosen) > MAX_NAMES or len(names) < counts["directory"]
        for idx, _, _ in chosen[:MAX_NAMES]:
            rp.click_local(directory_check(idx))
        html = rp.click_wait(VIEW_CHECKED, settle_ms=3000)
        for _ in range(SETTLE_POLLS):
            if tab_counts(html).get("index detail"):
                break
            rp.page.wait_for_timeout(1000)
            html = rp.html()
        sided = parse_detail_sides(html)
        detail_n = tab_counts(html).get("index detail")
        if detail_n is None or (detail_n and not sided):
            return SearchResult(status="error", reason="the Index Detail grid could not be read", url=url)
        rows = [r for r, s in sided if side not in ("grantor", "grantee") or s == side]
        return SearchResult(records=rows, total=detail_n, url=url,
                            truncated=truncated or detail_n > len(sided))


ADAPTER = LoganBlazor()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

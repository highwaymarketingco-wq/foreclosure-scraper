"""The register-of-deeds half of an adapter, for a county whose register runs Cott eSearch v4 as a
guest with no login (Buncombe on the county's own domain, Polk on cotthosting.com).

  * Book/Page search by GET (SrchBookPage.aspx?bAutoSearch=true&bk=&pg=&idx=ALL). Pre-1995 deeds
    and deeds of trust were kept in separate book series, so one book/page can hold two
    instruments: intake.py picks the one whose date agrees with the parcel record's deed date.
  * Document Details by the grid's own postback (same session).
  * Name search (SrchName.aspx, the WebForms POST a person's browser sends): GET the form for the
    session cookies, then POST it. Index All, or DEATHS where the register has a deaths index
    (Buncombe does; Polk's online index offers only real property).
Document IMAGES are never opened. The parsers below are tested on hand-written fixtures
(tests/test_quiet_title_buncombe_parse.py imports them through buncombe.py).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..fetch import Walled
from ..model import DeathEntry, DeathSearch, Instrument, NameSearch
from ..names import PersonName

_P = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"
_SIDE = {"both": "-1", "grantor": "1", "grantee": "2"}


# ---------------------------------------------------------------------------------------------
# pure parsers
# ---------------------------------------------------------------------------------------------

def mdy_iso(s: Optional[str]) -> Optional[str]:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", (s or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def _parties(td) -> tuple[list[str], list[str]]:
    names, matched = [], []
    cells = td.find_all("td")
    if not cells:
        t = td.get_text(" ", strip=True)
        return ([t] if t else []), []
    for c in cells:
        t = c.get_text(" ", strip=True)
        if not t or t in ("[-]", "[+]"):          # the grid's collapse / expand toggles
            continue
        if t not in names:                          # the grid repeats a long list collapsed + expanded
            names.append(t)
        if c.find("b") is not None and t not in matched:
            matched.append(t)
    return names, matched


def parse_rod_grid(html: str) -> dict:
    """The eSearch results grid: {'rows': [Instrument], 'total': int|None, 'coverage': [(index,
    from, thru)]}. Deaths are masked to the year ('**/**/1983')."""
    s = BeautifulSoup(html or "", "lxml")
    rows: list[Instrument] = []
    # the Images column: td10 on Buncombe's grid (..., Ref, Images, GIS, Tax), td11 on Polk's
    # (..., Ref, Amount, Images): read from the header row when there is one
    img = 10
    for tr in s.find_all("tr"):
        heads = [th.get_text(" ", strip=True).lower() for th in tr.find_all("th", recursive=False)]
        if "images" in heads and "book/page" in heads:
            img = heads.index("images")
            break
    for tr in s.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 11 or not tds[0].get_text(strip=True).isdigit():
            continue
        strs = list(tds[1].stripped_strings)
        d = strs[0] if strs else ""
        grantors, gm = _parties(tds[4])
        grantees, em = _parties(tds[5])
        a = tds[8].find("a")
        bp = (a.get_text(" ", strip=True) if a else tds[8].get_text(" ", strip=True))
        book, _, page = [x.strip() for x in bp.partition("/")]
        target = None
        if a is not None:
            mm = re.search(r'WebForm_PostBackOptions\("([^"]+)"', a.get("href", ""))
            target = mm.group(1) if mm else None
        pages_txt = re.sub(r"\D", "", tds[img].get_text(" ", strip=True)) if img < len(tds) else ""
        y = re.search(r"(\d{4})\s*$", d)
        side = "both" if gm and em else ("grantor" if gm else ("grantee" if em else None))
        rows.append(Instrument(date=d, date_iso=mdy_iso(d), year=int(y.group(1)) if y else None,
                               index_code=tds[2].get_text(" ", strip=True), kind=tds[3].get_text(" ", strip=True),
                               grantors=grantors, grantees=grantees, matched=gm + em, matched_side=side,
                               description=tds[6].get_text(" ", strip=True), book=book, page=page,
                               pages=int(pages_txt) if pages_txt else None, link_target=target))
    text = s.get_text(" ", strip=True)
    m = re.search(r"\b\d+\s*-\s*\d+\s+of\s+(\d+)\b", text)
    total = int(m.group(1)) if m else (0 if not rows else None)
    cov = []
    for mm in re.finditer(r"([A-Z][A-Z0-9 ,&\-]*?)\s+Valid From\s+(\S+)\s+Thru\s+(\S+)", text):
        item = (mm.group(1).strip(), mm.group(2), mm.group(3))
        if item not in cov:
            cov.append(item)
    return {"rows": rows, "total": total, "coverage": cov}


def parse_rod_detail(html: str) -> dict:
    s = BeautifulSoup(html or "", "lxml")
    out: dict = {}
    t = s.find(id="ctl00_cphMain_gvDetails1")
    if t is not None:
        trs = [tr for tr in t.find_all("tr") if tr.find("td")]
        if trs:
            c = [td.get_text(" ", strip=True) for td in trs[0].find_all("td")]
            keys = ["book_page", "index_type", "kind", "description", "date_filed", "images"]
            out.update(dict(zip(keys, c)))
    for key, tid in (("grantors", "ctl00_cphMain_gvParties1"), ("grantees", "ctl00_cphMain_gvParties2")):
        t = s.find(id=tid)
        out[key] = [td.get_text(" ", strip=True) for td in t.find_all("td")] if t is not None else []
    return out


def hidden_fields(html: str) -> dict:
    s = BeautifulSoup(html or "", "lxml")
    return {i.get("name"): i.get("value") or "" for i in s.find_all("input", type="hidden") if i.get("name")}


# ---------------------------------------------------------------------------------------------
# the register half of an adapter
# ---------------------------------------------------------------------------------------------


class CottV4Register:
    """Mixin: deed_at, deed_detail, plat_at, name_search, death_search for a Cott eSearch v4 register.
    A subclass sets rod_base (ending in /protected/v4/), src_rod and deaths_index."""
    rod_base: str = ""
    src_rod: str = ""
    deaths_index: bool = True

    @property
    def rod_name(self) -> str:
        return self.rod_base + "SrchName.aspx"

    @property
    def rod_bookpage(self) -> str:
        return self.rod_base + "SrchBookPage.aspx"

    def _bp_sessions(self) -> dict:
        if not hasattr(self, "_bp"):
            self._bp = {}
        return self._bp

    def deed_at(self, book: str, page: str, label: Optional[str] = None) -> tuple[list[Instrument], str]:
        url = f"{self.rod_bookpage}?" + urlencode({"bAutoSearch": "true", "bk": book, "pg": page, "idx": "ALL"})
        ex = self.new_exhibit(label or f"Register of Deeds: every index entry at book {book} page {page}",
                              self.src_rod, url, shot_kind="rod_grid")
        ses = self.f.new_session()
        resp = self.f.get(url, session=ses, tag="rod_bookpage")
        self.keep(ex, resp, f"rod_book_{book}_page_{page}", "html")
        g = parse_rod_grid(resp.text)
        for r in g["rows"]:
            r.exhibit = ex.key
        self._bp_sessions()[(book, page)] = (ses, resp)
        return g["rows"], url

    def deed_detail(self, inst: Instrument) -> Optional[str]:
        held = self._bp_sessions().get((inst.book, inst.page))
        if not held or not inst.link_target:
            return None
        ses, resp = held
        d = hidden_fields(resp.text)
        d["__EVENTTARGET"], d["__EVENTARGUMENT"] = inst.link_target, ""
        ex = self.new_exhibit(f"Register of Deeds: Document Details for book {inst.book} page {inst.page}",
                              self.src_rod, resp.final_url, method="POST", shot_kind="rod_detail",
                              note=f"Open the book/page link, then click {inst.book} / {inst.page} in the results.")
        r3 = self.f.post(resp.final_url, d, session=ses, tag="rod_detail")
        self.keep(ex, r3, f"rod_detail_{inst.book}_{inst.page}", "html")
        det = parse_rod_detail(r3.text)
        if det.get("grantors"):
            inst.grantors = det["grantors"]
        if det.get("grantees"):
            inst.grantees = det["grantees"]
        pg = re.sub(r"\D", "", det.get("images") or "")
        if pg:
            inst.pages = int(pg)
        if det.get("kind") and not inst.kind:
            inst.kind = det["kind"]
        inst.detail_exhibit = ex.key
        return r3.final_url if "DocumentDetails" in (r3.final_url or "") else None

    def plat_at(self, book: str, page: str) -> tuple[list[Instrument], str]:
        return self.deed_at(book, page, label=f"Register of Deeds: every index entry at book {book} page {page} "
                                              f"(the plat reference the county cites)")

    def _search(self, *, last: str, first: str, wild_last: str, wild_first: str, side: str,
                index_type: str, date_from: str, date_thru: str, label: str, slug: str, note: str):
        ses = self.f.new_session()
        form = self.f.get(self.rod_name, session=ses, tag="rod_form")
        if "/User/Login.aspx" in (form.final_url or ""):
            raise Walled(self.rod_name, "login page")
        d = hidden_fields(form.text)
        d.update({_P + "txtFirmSurname": last, _P + "ddlWildcardLast": wild_last, _P + "txtGivenName": first,
                  _P + "ddlWildcardFirst": wild_first, _P + "ddlSide": _SIDE[side], _P + "ddlType": "-1",
                  _P + "ddlIndexType": index_type, _P + "txtFiledFrom": date_from, _P + "txtFiledThru": date_thru,
                  _P + "ddlSortDir": "Date Ascending", _P + "btnInstruments": "Search (All Matches)"})
        ex = self.new_exhibit(label, self.src_rod, self.rod_name, method="POST", note=note, shot_kind="rod_grid")
        resp = self.f.post(self.rod_name, d, session=ses, tag="rod_search")
        self.keep(ex, resp, slug, "html")
        g = parse_rod_grid(resp.text)
        for r in g["rows"]:
            r.exhibit = ex.key
        return g, ex

    @staticmethod
    def _who(person: PersonName | str) -> tuple[str, str, str, str]:
        if isinstance(person, PersonName):
            return person.last, person.first, "2", "0"
        return str(person).strip(), "", "2", "0"

    def name_search(self, purpose: str, person: PersonName | str, *, side: str = "both",
                    date_from: str = "", date_thru: str = "") -> NameSearch:
        last, first, wl, wf = self._who(person)
        ns = NameSearch(purpose=purpose, last=last, first=first, side=side, date_from=date_from, date_thru=date_thru)
        note = (f"Quick Name search. Last / Firm Name: {last} (Exactly). First Name: {first or '(blank)'} "
                f"(Begins With). Party side: {side}. Index Type: All. Filed from: {date_from or '(blank)'}; "
                f"thru: {date_thru or '(blank)'}. Press Search (All Matches).")
        try:
            g, ex = self._search(last=last, first=first, wild_last=wl, wild_first=wf, side=side, index_type="",
                                 date_from=date_from, date_thru=date_thru,
                                 label=f"Register of Deeds name search: {purpose}",
                                 slug=f"rod_name_{last}_{first}_{side}", note=note)
        except Walled as w:
            ns.walled, ns.wall_reason = True, w.reason
            return ns
        ns.exhibit, ns.total, ns.rows, ns.shown = ex.key, g["total"], g["rows"], len(g["rows"])
        return ns

    def death_search(self, person: PersonName, reading: str) -> DeathSearch:
        ds = DeathSearch(person=person.indexed(), reading=reading, last=person.last, first=person.first)
        if not self.deaths_index:
            return ds
        note = (f"Quick Name search. Last / Firm Name: {person.last} (Exactly). First Name: {person.first} "
                f"(Begins With). Index Type: DEATHS. Press Search (All Matches).")
        try:
            g, ex = self._search(last=person.last, first=person.first, wild_last="2", wild_first="0", side="both",
                                 index_type="DTH", date_from="", date_thru="",
                                 label=f"Register of Deeds deaths index: {person.last}, {person.first}",
                                 slug=f"rod_deaths_{person.last}_{person.first}", note=note)
        except Walled as w:
            ds.walled, ds.wall_reason = True, w.reason
            return ds
        ds.exhibit, ds.total = ex.key, g["total"]
        for lbl, fr, th in g["coverage"]:
            if "DEATH" in lbl:
                ds.valid_from, ds.valid_thru = fr, th
        for r in g["rows"]:
            as_dec = any(n in r.grantors for n in r.matched)
            ds.entries.append(DeathEntry(year=r.year, date=r.date, book_page=r.book_page,
                                         decedent_names=r.grantors, parents=r.grantees,
                                         matched_as="decedent" if as_dec else "parent",
                                         fit="parent_only" if not as_dec else "candidate"))
        return ds

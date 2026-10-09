"""County-wide date sweeps of the Cott eSearch v4 registers (guest search), for the liens and marriage
licences that the per-owner name search (rod/nc_cott_v4.py) can never reach across a whole county.

Audit 2026-10-09, top-80 build list ranks 29, 30, 46, 54, 58, 64, 65 (Cott eSearch counties). The name
search costs 3 to 4 requests an owner and is capped at 30 lookups a county a run, against 800 to
9,300 board rows in each of these counties. The same Cott app has a Date Range search whose form also
takes an instrument-kind list and an index-type list, so one county-wide read by kind and date window
(a few dozen requests for several years) serves every board row, matched offline in
rod/county_sweeps.py (PartyIndex, stamps, cache in data/county_sweeps/).

THE FLOW (the browser's own steps; plain HTTP through nc_polite.PoliteClient; live-checked 2026-10-09
on Nash, Onslow, Alamance, Alexander, Pamlico, Edgecombe, Rutherford)
  1. the Quick Name page as guest (nc_cott_v4.CottV4._form: a 'Sign in as a Guest' click-through where
     the tenant has one), then the 'Date Range' tab postback  -> SrchDate.aspx
  2. the kind list (lbKinds, option value 'ids|index types') or the index-type list (lbIndexTypes) is
     an auto-postback list: ONE postback with the chosen values selects them in the server session
     (posting them with the search itself is ignored: tested, the count stayed the whole county's)
  3. POST the date window (txtFiledFrom / txtFiledThru, at most 29 days apart: the vendor's own cap,
     a wider window answers an empty form) -> the results grid; 'Your search returned N results'.
     The grid pages at 10 to 500 rows (a tenant default): the results-per-page list is raised to its
     largest value, and Page$N postbacks read the rest. A window whose count is over MAX_WINDOW_ROWS
     is bisected by rod/county_sweeps.read_back.

TWO READERS
  CottLienReader      kinds whose name says lien, judgment, lis pendens, foreclosure, assessment ...
                      (adverse_kind): the stamp is raw['rod_lien_sweep'] (found / possible / none_found
                      for window_from..window_to only, adverse kinds only: not a mortgage check)
  CottMarriageReader  the MARRIAGES index (code MAR) of the six tenants that publish one: the stamp is
                      raw['marriage_license'] (rod/county_sweeps.marriage_stamp)

Nothing here solves or works around a wall: every request is paced per host (>= 1.6 s), one at a time,
and every answer is checked for a CAPTCHA / challenge / login / block (RodWalled ends the sweep and
stamps nothing). A guest session that expires mid-sweep is answered by the guest button once more; a
second sign-in page ends the sweep as an error.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from . import aumentum as _A
from . import county_sweeps as CS
from .nc_chain import IndexRecord
from .nc_cott_v4 import ADAPTER, COUNTIES, CottCounty, guest_signin_form, hidden_fields, is_guest_signin, parse_grid
from .nc_polite import PoliteClient

PLATFORM = "cott_esearch_v4_sweep"
MAX_WINDOW_ROWS = 1500                 # more than this in one window: bisect rather than page for minutes
MAX_SPAN_DAYS = 29                     # the vendor's own cap on one Date Range search
MAX_PAGES = 120

#: the counties swept for liens (all read through nc_cott_v4; Rowan is a challenge page and stays out)
LIEN_COUNTIES = ("Onslow", "Pitt", "Alamance", "Alexander", "Pamlico", "Polk", "Edgecombe", "Rutherford",
                 "Graham", "Nash")

_ADV = re.compile(r"\bLIEN|\bJUDG|\bJGMT\b|\bJDGMT\b|\bJDG|FINALJUDGE|\bLIS\b|\bLIS P|LIS PEND|\bFORCL\b|\bFCL\b|"
                  r"FORECLOS|\bATTACH|GARNISH|EXECUTION|ASSESSMENT|\bLP\b|NOTICE OF (SALE|DEFAULT|HEARING)|"
                  r"\bIRS\b|FEDERAL TAX|STATE TAX", re.I)
_NOT = re.compile(r"SATISF|RELEASE|\bREL\b|REL LIS|CANCEL|DISCHARGE|DISLN|SUBORD|CORRECT|\bCORR\b|DEED OF TRUST|"
                  r"TRUSTEE|AMEND|WITHDRAW|RESCIND|\bQUIT|DISCLAIM|PARTIAL|REQUEST|MARRIAGE|\bD/T|\bD T\b|CERT|"
                  r"REFUSAL", re.I)

_P = _A._P_DATE


def adverse_kind(name: str) -> bool:
    return bool(_ADV.search(name or "")) and not _NOT.search(name or "")


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written pages)
# ------------------------------------------------------------------------------------------------

def _select(html: str, suffix: str):
    s = BeautifulSoup(html or "", "lxml")
    for sel in s.find_all("select"):
        if (sel.get("name") or "").endswith(suffix):
            return sel
    return None


def parse_options(html: str, suffix: str) -> list[tuple[str, str]]:
    """[(value, text)] of one of the Date Range tab's lists (lbKinds / lbIndexTypes)."""
    sel = _select(html, suffix)
    if sel is None:
        return []
    return [(o.get("value") or "", o.get_text(strip=True)) for o in sel.find_all("option")]


def adverse_options(options: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(v, n) for v, n in options if adverse_kind(n)]


def selected_count(html: str, suffix: str) -> int:
    sel = _select(html, suffix)
    return len(sel.find_all("option", selected=True)) if sel is not None else 0


def per_page_control(html: str) -> Optional[tuple[str, str, int]]:
    """(the Top 'results per page' select's name, its largest value, the current value)."""
    sel = None
    for cand in BeautifulSoup(html or "", "lxml").find_all("select"):
        n = cand.get("name") or ""
        if n.endswith("cpInstruments_Top$ddlResultsPerPage"):
            sel = cand
            break
    if sel is None:
        return None
    vals = [int(o.get("value")) for o in sel.find_all("option") if (o.get("value") or "").isdigit()]
    cur = next((int(o.get("value")) for o in sel.find_all("option", selected=True) if (o.get("value") or "").isdigit()),
               min(vals) if vals else 0)
    return (sel.get("name"), str(max(vals)), cur) if vals else None


def grid_target(html: str) -> Optional[str]:
    """The results grid's postback target (for Page$N)."""
    m = re.search(r"&#39;(ctl00\$cphMain\$tcMain\$tpInstruments\$ucInstrumentsGridV2\$cpgvInstruments)&#39;|"
                  r"'(ctl00\$cphMain\$tcMain\$tpInstruments\$ucInstrumentsGridV2\$cpgvInstruments)'", html or "")
    return (m.group(1) or m.group(2)) if m else None


def date_body(a: date, b: date) -> dict:
    return _A._date_search_body(a.strftime("%m/%d/%Y"), b.strftime("%m/%d/%Y"))


def select_body(suffix: str, values: list[str]) -> dict:
    """The auto-postback that selects `values` in a Date Range list."""
    d = _A._common_hidden()
    d["__EVENTTARGET"] = _P + suffix
    d[_P + suffix] = list(values)
    d[_P + "txtFiledFrom"] = ""
    d[_P + "txtFiledThru"] = ""
    d[_P + "ddlType"] = "-1"
    return d


# ------------------------------------------------------------------------------------------------
# readers
# ------------------------------------------------------------------------------------------------

class _SessionExpired(RuntimeError):
    pass


class _CottDateReader(CS.Reader):
    state = "NC"
    suffix = ""                       # lbKinds | lbIndexTypes

    def __init__(self, county: str, client: Optional[PoliteClient] = None) -> None:
        if county not in COUNTIES:
            raise KeyError(county)
        self.county = county
        self.cfg: CottCounty = COUNTIES[county]
        self.client = client or PoliteClient(PLATFORM, "NC", county)
        self.url = ""
        self.values: list[str] = []

    # -- which values to select (the subclass decides) ---------------------------------------
    def choose(self, nav_html: str) -> list[str]:
        raise NotImplementedError

    def _post(self, url: str, data: dict):
        page = self.client.post(url, data, headers={"Referer": url}, accept_signin=lambda p: is_guest_signin(p.text))
        if is_guest_signin(page.text):
            raise _SessionExpired("the guest session expired")
        return page

    def open(self) -> None:
        form = ADAPTER._form(self.client, self.cfg)
        final = form.final_url or (self.cfg.base + "SrchName.aspx")
        nav = self._post(final, _A._date_nav_body())
        if "ucSrchDates" not in nav.text:
            raise RuntimeError("the Date Range tab did not open")
        self.values = self.choose(nav.text)
        if not self.values:
            raise RuntimeError("no matching entry in the Date Range list")
        self.url = nav.final_url or final
        self._reselect()

    def _reselect(self) -> None:
        """The server forgets the list selection once a search has run (live 2026-10-09: the second
        window of a sweep came back unfiltered), so it is posted again before every window."""
        sel = self._post(self.url, select_body(self.suffix, self.values))
        if selected_count(sel.text, self.suffix) < 1:
            raise RuntimeError("the list selection was not kept by the server")
        self.url = sel.final_url or self.url

    # -- one window ------------------------------------------------------------------------------
    def _rows(self, a: date, b: date) -> tuple[list[IndexRecord], Optional[int], str]:
        self._reselect()
        page = self._post(self.url, date_body(a, b))
        rows, total = parse_grid(page.text)
        if total is None and not rows:
            raise RuntimeError("the answer was not a results grid")
        return rows, total, page.text

    def _page_through(self, rows: list[IndexRecord], total: int, html: str) -> list[IndexRecord]:
        ctl = per_page_control(html)
        url = self.url
        if ctl and len(rows) < total and ctl[2] < int(ctl[1]):
            d = hidden_fields(html)
            d["__EVENTTARGET"] = ctl[0]
            d[ctl[0]] = ctl[1]
            page = self._post(url, d)
            more, _t = parse_grid(page.text)
            if len(more) > len(rows):
                rows, html = more, page.text
        target = grid_target(html)
        pageno = 1
        while len(rows) < total and target and pageno < MAX_PAGES:
            pageno += 1
            d = hidden_fields(html)
            d["__EVENTTARGET"], d["__EVENTARGUMENT"] = target, f"Page${pageno}"
            page = self._post(url, d)
            more, _t = parse_grid(page.text)
            if not more:
                break
            html = page.text
            seen = {r.key() for r in rows}
            fresh = [r for r in more if r.key() not in seen]
            if not fresh:
                break
            rows = rows + fresh
        return rows

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        if (b - a).days > MAX_SPAN_DAYS:
            return [], True                       # no request: the vendor refuses a wider window
        for attempt in (1, 2):
            try:
                rows, total, html = self._rows(a, b)
                break
            except _SessionExpired:
                if attempt == 2:
                    raise RuntimeError("the guest session expired twice")
                self.open()
        if not total:
            return [], False
        if total > MAX_WINDOW_ROWS:
            return [], True
        if len(rows) < total:
            rows = self._page_through(rows, total, html)
        if len(rows) < total:
            return [], True                       # could not read them all: split the window
        return [CS.summarize(r) for r in rows], False


class CottLienReader(_CottDateReader):
    """Adverse instruments (lien, judgment, lis pendens, foreclosure, assessment ...) by kind."""
    suffix = "lbKinds"
    label = "cott_v4_lien_sweep"

    def choose(self, nav_html: str) -> list[str]:
        opts = adverse_options(parse_options(nav_html, "lbKinds"))
        self.types = len(opts)
        return [v for v, _n in opts]


class CottMarriageReader(_CottDateReader):
    """The MARRIAGES index (code MAR) of the tenants that publish one."""
    suffix = "lbIndexTypes"
    label = "cott_v4_marriage_sweep"

    @property
    def key(self) -> str:
        return f"{self.state}_{self.county}_marriage".lower()

    def choose(self, nav_html: str) -> list[str]:
        self.types = 1
        return ["MAR"] if any(v == "MAR" for v, _n in parse_options(nav_html, "lbIndexTypes")) else []

    def read(self, a: date, b: date) -> tuple[list[dict], bool]:
        out, overflow = super().read(a, b)
        for s in out:                              # a blank Type cell under the MAR filter is still a marriage
            if not s.get("t"):
                s["t"] = "MARRIAGE"
        return out, overflow

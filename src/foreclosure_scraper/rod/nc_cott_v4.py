"""Cott Systems eSearch v4, the guest name index: one adapter for every NC county whose register
runs it open to a guest with no sign-in (county records matrix, access 'open').

PROTOCOL (the WebForms POST a person's browser sends; live-checked 2026-10-07 on Nash and Graham)
  1. GET  <base>SrchName.aspx            the 'Quick Name Search' form as Guest User, session cookies
  2. POST <base>SrchName.aspx            the form's own hidden fields plus
        ucSrchNames$txtFirmSurname / ddlWildcardLast (2 = Exactly, 0 = Begins With)
        ucSrchNames$txtGivenName   / ddlWildcardFirst (0 = Begins With)
        ucSrchNames$ddlSide (-1 both, 1 grantor, 2 grantee), txtFiledFrom / txtFiledThru (MM/DD/YYYY)
        ucSrchNames$btnInstruments = 'Search (All Matches)'
     -> the cpgvInstruments results grid; 'Your search returned <strong> N</strong> results'.
  Grid row, direct-child cells: 0 row #, 1 date filed (deaths masked '**/**/YYYY'), 2 index code,
  3 type, 4 grantor(s) (nested table), 5 grantee(s), 6 description, 7 file number, 8 book / page,
  9 Ref (the book / page of the instrument this one refers to, e.g. the deed of trust a foreclosure
  notice names).

WHAT IS NOT READ: document images (a paid order flow); the Document Details page.

COUNTIES LEFT OUT ON PURPOSE
  * Guest sign-in tenants (GUEST_SIGNIN_COUNTIES): the search URL lands on the vendor's
    'Account Sign In' page (a username/password form with a 'Sign in as a Guest' button). The
    shared wall detector reads that as a login page, so this adapter records the county walled and
    stops. Pressing the guest button needs the owner's ruling, not code.
  * Buncombe and Polk are configured here for chain() (the quiet-title chain); their lien
    existence already comes from enrichment_aumentum_rod / rod.cott.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .nc_chain import IndexRecord, OwnerName, SearchResult, iso_to_mdy, mdy_to_iso
from .nc_platform import NcRodPlatform
from .nc_polite import PoliteClient

PLATFORM = "cott_esearch_v4"
ENV_FLAG = "FORECLOSURE_NC_COTT_ROD"

_P = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"
_SIDE = {"both": "-1", "grantor": "1", "grantee": "2"}


@dataclass(frozen=True)
class CottCounty:
    base: str                        # ends with /LandRecords/protected/v4/


COUNTIES: dict[str, CottCounty] = {
    "Alexander": CottCounty("https://cotthosting.com/ncalexander/LandRecords/protected/v4/"),
    "Graham": CottCounty("https://cotthosting.com/ncgraham/LandRecords/protected/v4/"),
    "Granville": CottCounty("http://www.granvillecountydeeds.org/External/LandRecords/protected/v4/"),
    "Jackson": CottCounty("http://deeds.jacksonnc.org/External/LandRecords/protected/v4/"),
    "Jones": CottCounty("https://cotthosting.com/ncjones/LandRecords/protected/v4/"),
    "Nash": CottCounty("https://cotthosting.com/NCNashExternal/LandRecords/protected/v4/"),
    "Pamlico": CottCounty("https://cotthosting.com/ncpamlicoexternal/LandRecords/protected/v4/"),
    "Wayne": CottCounty("http://rod.waynegov.com/External/LandRecords/protected/v4/"),
    # already read for lien existence elsewhere; here for chain()
    "Buncombe": CottCounty("https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4/"),
    "Polk": CottCounty("https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4/"),
}

#: same vendor app, but the search lands on the 'Account Sign In' page (guest button). Not read.
GUEST_SIGNIN_COUNTIES = ("Alamance", "Edgecombe", "Halifax", "Lenoir", "Onslow", "Pitt", "Rowan",
                         "Rutherford", "Scotland", "Wilson")


# ------------------------------------------------------------------------------------------------
# pure parsers (tested on hand-written fixtures)
# ------------------------------------------------------------------------------------------------

def hidden_fields(html: str) -> dict:
    s = BeautifulSoup(html or "", "lxml")
    return {i.get("name"): i.get("value") or "" for i in s.find_all("input", type="hidden") if i.get("name")}


def _names(td) -> list[str]:
    cells = td.find_all("td")
    if not cells:
        t = td.get_text(" ", strip=True)
        return [t] if t else []
    out: list[str] = []
    for c in cells:
        t = c.get_text(" ", strip=True)
        if t and t not in ("[-]", "[+]") and t not in out:   # the grid repeats a long list collapsed + expanded
            out.append(t)
    return out


def _direct_tds(tr) -> list:
    return tr.find_all("td", recursive=False)


def parse_grid(html: str) -> tuple[list[IndexRecord], Optional[int]]:
    """(rows, the register's own result count). The count is None when the page carries no 'Your
    search returned N results' banner: a genuine empty answer says 0 (live-checked on Graham), so a
    page with neither banner nor rows is not a results page at all."""
    s = BeautifulSoup(html or "", "lxml")
    rows: list[IndexRecord] = []
    for tr in s.find_all("tr"):
        tds = _direct_tds(tr)
        if len(tds) < 9 or not tds[0].get_text(strip=True).isdigit():
            continue
        strs = list(tds[1].stripped_strings)
        date_txt = strs[0] if strs else ""
        bp_a = tds[8].find("a")
        bp = (bp_a.get_text(" ", strip=True) if bp_a else tds[8].get_text(" ", strip=True))
        book, _, page = [x.strip() for x in bp.partition("/")]
        rows.append(IndexRecord(
            recorded=mdy_to_iso(date_txt) if "*" not in date_txt else None,
            index_code=tds[2].get_text(" ", strip=True) or None,
            doc_type=tds[3].get_text(" ", strip=True),
            grantors=_names(tds[4]), grantees=_names(tds[5]),
            description=tds[6].get_text(" ", strip=True) or None,
            instrument_no=tds[7].get_text(" ", strip=True) or None,
            book=book or None, page=page or None,
            xref=(tds[9].get_text(" ", strip=True) or None) if len(tds) > 9 else None,
        ))
    m = re.search(r"search returned\s*<strong>\s*([\d,]+)\s*</strong>", html or "", re.I)
    total = int(m.group(1).replace(",", "")) if m else None
    return rows, total


def too_many(html: str) -> bool:
    return bool(re.search(r"maximum number of allowable results|allowable results", html or "", re.I))


def name_form(form_html: str, who: OwnerName, side: str, date_thru: Optional[str]) -> dict:
    d = hidden_fields(form_html)
    if who.entity:
        last, wild_last, first = who.last, "0", ""
    else:
        last, wild_last, first = who.last, "2", who.first
    d.update({_P + "txtFirmSurname": last, _P + "ddlWildcardLast": wild_last,
              _P + "txtGivenName": first, _P + "ddlWildcardFirst": "0",
              _P + "ddlSide": _SIDE.get(side, "-1"), _P + "ddlType": "-1", _P + "ddlIndexType": "",
              _P + "txtFiledFrom": "", _P + "txtFiledThru": iso_to_mdy(date_thru),
              _P + "ddlSortDir": "Date Descending", _P + "btnInstruments": "Search (All Matches)"})
    return d


# ------------------------------------------------------------------------------------------------
# the adapter
# ------------------------------------------------------------------------------------------------

class CottV4(NcRodPlatform):
    platform = PLATFORM
    counties = COUNTIES

    def source_url(self, cfg: CottCounty) -> str:
        return cfg.base + "SrchName.aspx"

    def _search(self, client: PoliteClient, cfg: CottCounty, ctx, who: OwnerName, side: str,
                date_thru: Optional[str]) -> SearchResult:
        url = cfg.base + "SrchName.aspx"
        form = client.get(url)                                   # resets the server-side search context
        post_url = form.final_url or url
        page = client.post(post_url, name_form(form.text, who, side, date_thru), headers={"Referer": post_url})
        if too_many(page.text):
            return SearchResult(status="too_many", url=url,
                                reason="the register found more entries than it will list for this name")
        if page.status >= 400:
            return SearchResult(status="error", url=url, reason=f"HTTP {page.status}")
        rows, total = parse_grid(page.text)
        if total is None and not rows:
            return SearchResult(status="error", url=url, reason="the answer was not a results grid")
        return SearchResult(records=rows, total=total, url=url,
                            truncated=bool(total is not None and total > len(rows)))


ADAPTER = CottV4()


async def search_by_name(state: str, county: str, name: str, max_docs: int = 80):
    return await ADAPTER.search_by_name(state, county, name, max_docs)


def chain(county: str, owner_name: Optional[str], *, state: str = "NC", depth: int = 3) -> dict:
    return ADAPTER.chain(county, owner_name, state=state, depth=depth)

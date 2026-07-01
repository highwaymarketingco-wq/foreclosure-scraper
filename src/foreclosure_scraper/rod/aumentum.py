"""Aumentum / Cott eSearch v4 LandRecords — Buncombe + Gaston NC Register of Deeds.

FREE, no-login, no-CAPTCHA name/date index search. (A reCAPTCHA gates only the
PAID document-image order flow — we never touch images.) URL pattern:
  https://{rod-host}/External/LandRecords/protected/v4/SrchName.aspx
  https://{rod-host}/External/LandRecords/protected/v4/SrchDate.aspx

HANDSHAKE (re-captured LIVE 2026-07-01 on both hosts):
This is a Cott eSearch v4 ASP.NET WebForms app where the search context lives in
SERVER-SIDE SESSION STATE, not in __VIEWSTATE. The captured form ships an EMPTY
__VIEWSTATE and NO __VIEWSTATEGENERATOR / __EVENTVALIDATION at all. So the flow is:
  1. GET SrchName.aspx (or SrchDate.aspx) -> ASP.NET_SessionId + CottSqlAuthCookie
     cookies; the server seeds the search context for that session.
  2. POST the search on the SAME cookie session with __VIEWSTATE="" and the
     ucSrchNames (name index) or ucSrchDates (date index) fields.
The submit is a named button:
  - name index: ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$btnInstruments
                = "Search (All Matches)"
  - date index: requires a nav postback to the Date-Range tab first (that tab is
                lazy-loaded), THEN ctl00$...$ucSrchDates$btnSearch = "Search".

RESULTS GRID (verified live — this is NOT a DevExpress dxgv grid; the old parser
assumed dxgv/DevExpress and a flat <tr> and matched 0 rows on real data):
  table id = ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments
  data rows = <tr class="cottPagedGridViewRowStyle"> / "cottPagedGridViewAltRowStyle"
  14 direct-child <td>, header-aligned:
    td0=row#, td1=Date Filed (MM/DD/YYYY or masked '**/**/YYYY'), td2=Index code,
    td3=Type (doc type), td4=Grantor, td5=Grantee, td6=Description,
    td7=File Number (instrument #), td8=Book/Page ('6547 / 1497'), td9=Ref,
    td10=Images, td11=GIS, td12=Tax, td13=spacer.
  Grantor/Grantee/Description cells embed NESTED <table>s, so the parser MUST use a
  real HTML parser walking DIRECT-CHILD <td> (regex-on-<tr> breaks on nested </tr>).
  Masked-date rows ('**/**/2026', protected DTH docs) are KEPT with recorded_date=None
  — they still carry grantor/grantee/book-page name-index signal.

COMPLIANCE: public records, free, read-only index lookups; no login, no CAPTCHA
solve, no paid image order, real-Chrome TLS fingerprint only (not a WAF defeat).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from . import deed_stamp
from .models import RodDoc, normalize_doc_type

AUMENTUM_COUNTIES = {
    ("NC", "Mecklenburg"): "https://meckrod.manatron.com/External/LandRecords/protected/v4",
    ("NC", "Buncombe"): "https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4",
    ("NC", "Gaston"): "https://deeds.gastongov.com/external/LandRecords/protected/v4",
}

# Control prefixes for the two lazy-loaded search-tab user controls.
_P_NAME = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"
_P_DATE = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchDates$"

# Client-state hidden that RadTabStrip reads. The default (New Search tab active)
# value is enough to satisfy the postback; the server rewrites it in the response.
_TAB_CLIENTSTATE = (
    '{"ActiveTabIndex":0,"TabEnabledState":[true,false,false,false,true],'
    '"TabWasLoadedOnceState":[false,false,false,false,false]}'
)

# Grid + row selectors (live-verified 2026-07-01).
_GRID_ID = "ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments"
_ROW_SEL = "tr.cottPagedGridViewRowStyle, tr.cottPagedGridViewAltRowStyle"

# Doc-type label sets kept for the sibling cott.py tenants (Polk/Rutherford) that
# import them, and for the sold-recordings test surface. Not used by the
# Buncombe/Gaston name/date-index flow, which post-filters on the grid Type column
# via the NOD_KEYWORDS / POST_SALE_KEYWORDS sets below.
AUMENTUM_NOD_DOC_TYPES = (
    "NOTICE OF FORECLOSURE SALE", "NOTICE OF SALE", "NOTICE OF DEFAULT",
    "LIS PENDENS", "NOTICE OF HEARING", "FORECLOSURE",
)
AUMENTUM_POST_SALE_DOC_TYPES = (
    "TRUSTEES DEED UPON SALE", "TRUSTEE'S DEED UPON SALE",
    "TRUSTEES DEED", "TRUSTEE'S DEED",
    "SUBSTITUTE TRUSTEES DEED", "SUBSTITUTE TRUSTEE'S DEED",
    "FORECLOSURE DEED", "DEED UNDER POWER OF SALE",
    "COMMISSIONER'S DEED", "COMMISSIONERS DEED",
)

# NOD / post-sale doc-type keyword sets (post-filtered on the grid Type column,
# which the vendor renders as full words on Buncombe and terse codes on Gaston).
NOD_KEYWORDS = (
    "NOTICE OF FORECLOSURE", "NOTICE OF DEFAULT", "NOTICE OF SALE",
    "LIS PENDENS", "FORECLOSURE", "SUBSTITUTE TRUSTEE",
    "NOS", "NOD", "S/TR", "SUB/TR",
)
POST_SALE_KEYWORDS = (
    "TRUSTEE", "FORECLOSURE DEED", "COMMISSIONER", "POWER OF SALE",
    "TRUSTEES DEED", "TRUSTEE'S DEED", "S/TR DEED",
)


def _is_nod(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in NOD_KEYWORDS)


def _is_post_sale(doc_type: str | None) -> bool:
    """True for recordings that transfer title to a foreclosure-auction winner."""
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in POST_SALE_KEYWORDS)


# --------------------------------------------------------------------------- #
# Grid parsing                                                                 #
# --------------------------------------------------------------------------- #
_MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")


def _money(s: str | None) -> float | None:
    """Parse '$45,000.00' / '7.50' -> float; None for empty / implausible."""
    if not s:
        return None
    m = _MONEY_RE.search(s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v <= 50_000_000 else None


def _extract_hidden(html: str, field: str) -> str:
    """Read an ASP.NET hidden input's value (e.g. __VIEWSTATE). Used by the
    sibling cott.py Polk/Rutherford flow, which posts real viewstate tokens."""
    m = re.search(rf'<input[^>]*name="{field}"[^>]*value="([^"]*)"', html or "")
    return m.group(1) if m else ""


def _parse_grid(html: str, county: str, state: str) -> list[RodDoc]:
    """Header-driven parser for the generic Cott/Aumentum results grid used by the
    Polk/Rutherford (cotthosting) tenants — table id contains ResultsGrid /
    gvResults with a <th> header row. Kept for cott.py; the Buncombe/Gaston
    name/date index uses _parse_instruments_grid (cpgvInstruments) instead."""
    out: list[RodDoc] = []
    tree = HTMLParser(html or "")
    grid = tree.css_first("table[id*='ResultsGrid'], table[id*='gvResults']")
    if not grid:
        return out
    headers = [h.text(strip=True).lower() for h in grid.css("th")]

    def col(row, *names) -> str:
        for n in names:
            for i, h in enumerate(headers):
                if n in h:
                    cells = row.css("td")
                    if i < len(cells):
                        return cells[i].text(strip=True)
        return ""

    for row in grid.css("tr")[1:]:
        cells = row.css("td")
        if not cells:
            continue
        date_str = col(row, "record date", "date")
        if not date_str:
            continue
        recorded = _parse_date(date_str)
        if recorded is None:
            continue
        consideration = _money(col(row, "consideration", "sale price"))
        stamp = _money(col(row, "excise tax", "tax stamp", "stamp", "stamps"))
        consideration = deed_stamp.consideration_from_fields(consideration, stamp)
        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(col(row, "doc type", "type")),
                recorded_date=recorded,
                book=(col(row, "book") or None),
                page=(col(row, "page") or None),
                grantor=(col(row, "grantor")[:200] or None),
                grantee=(col(row, "grantee")[:200] or None),
                instrument_no=(col(row, "instrument", "doc#", "doc no") or None),
                amount=_money(col(row, "amount", "doc amount")),
                consideration_amount=consideration,
                excise_tax_stamp=stamp,
            )
        )
    return out


def _direct_tds(tr):
    """Direct-child <td> of a row only (nested-table cells contain their own
    <td>/<tr>, so a plain descendant query would over-count). selectolax has no
    :scope selector, so walk the sibling chain."""
    out = []
    ch = tr.child
    while ch is not None:
        if ch.tag == "td":
            out.append(ch)
        ch = ch.next
    return out


def _cell(tds, i: int) -> str:
    if i < 0 or i >= len(tds):
        return ""
    return " ".join(tds[i].text(separator=" ", strip=True).split())


def _parse_date(s: str):
    """'12/03/2025' -> datetime; masked '**/**/2026' / junk -> None.
    The date cell can carry a trailing 'Date Filed ...' status label, so take the
    first MM/DD/YYYY token only."""
    if not s or "*" in s:
        return None
    m = re.search(r"\d{1,2}/\d{1,2}/\d{4}", s)
    if not m:
        return None
    try:
        return dateparser.parse(m.group(0))
    except (ValueError, TypeError, OverflowError):
        return None


def _split_book_page(bp: str) -> tuple[str | None, str | None]:
    """'6547 / 1497' -> ('6547', '1497'). Tolerates '/' or '-' separators."""
    bp = (bp or "").strip()
    if not bp:
        return None, None
    for sep in ("/", "-"):
        if sep in bp:
            a, _, b = bp.partition(sep)
            return (a.strip() or None), (b.strip() or None)
    return bp or None, None


def _parse_instruments_grid(html: str, county: str, state: str) -> list[RodDoc]:
    """Parse the Cott eSearch v4 cpgvInstruments results grid into RodDocs.

    Column order verified live 2026-07-01 (Buncombe + Gaston):
      td0=row#, td1=Date Filed, td2=Index, td3=Type, td4=Grantor, td5=Grantee,
      td6=Description, td7=File Number, td8=Book/Page, td9=Ref, td10=Images.
    Keeps masked-date rows (recorded_date=None) — they still carry name-index
    grantor/grantee/book-page signal used by the lien-existence classifier."""
    out: list[RodDoc] = []
    if not html:
        return out
    tree = HTMLParser(html)
    grid = tree.css_first(f"table#{_GRID_ID}")
    if grid is None:
        # ID can vary if the tenant bumps the control version; fall back to any
        # cpgvInstruments-suffixed table.
        for t in tree.css("table"):
            tid = t.attributes.get("id") or ""
            if tid.endswith("cpgvInstruments"):
                grid = t
                break
    if grid is None:
        return out

    for tr in grid.css(_ROW_SEL):
        tds = _direct_tds(tr)
        if len(tds) < 6:
            continue
        dtype = _cell(tds, 3)
        grantor = _cell(tds, 4)
        grantee = _cell(tds, 5)
        # A wholly-empty row (grid spacer) has no names and no type — skip it.
        if not (dtype or grantor or grantee):
            continue
        recorded = _parse_date(_cell(tds, 1))
        instrument_no = _cell(tds, 7)
        book, page = _split_book_page(_cell(tds, 8))
        # Amount / consideration is not a column on the name/date index grid for
        # these NC tenants; recover a sold price from an excise stamp only if the
        # description carries one (rare). Left None here on purpose.
        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(dtype),
                recorded_date=recorded,
                book=book,
                page=page,
                grantor=(grantor[:200] or None),
                grantee=(grantee[:200] or None),
                instrument_no=(instrument_no or None),
                notes=(_cell(tds, 6)[:300] or None),  # Description
            )
        )
    return out


def _result_count(html: str) -> int | None:
    """'Your search returned <strong> 167</strong> results' -> 167."""
    m = re.search(r"search returned\s*<strong>\s*([\d,]+)", html or "", re.S | re.I)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Request bodies                                                               #
# --------------------------------------------------------------------------- #
def _common_hidden() -> dict:
    return {
        "ctl00_cphMain_tcMain_ClientState": _TAB_CLIENTSTATE,
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": "", "__SCROLLPOSITIONX": "0", "__SCROLLPOSITIONY": "0",
        "__VIEWSTATEENCRYPTED": "",
        "ctl00$txtJobReference": "",
        "ctl00$ucShoppingCart$hfQuantity": "",
    }


def _name_body(last: str, first: str, dfrom: str = "", dthru: str = "") -> dict:
    b = _common_hidden()
    b.update({
        _P_NAME + "weFiledFrom_ClientState": "", _P_NAME + "weFiledThru_ClientState": "",
        _P_NAME + "meeFiledFrom_ClientState": "", _P_NAME + "meeFiledThru_ClientState": "",
        _P_NAME + "txtFirmSurname": last, _P_NAME + "ddlWildcardLast": "0",
        _P_NAME + "txtGivenName": first, _P_NAME + "ddlWildcardFirst": "0",
        _P_NAME + "ddlSide": "-1", _P_NAME + "ddlType": "-1", _P_NAME + "ddlIndexType": "",
        _P_NAME + "txtFiledFrom": dfrom, _P_NAME + "txtFiledThru": dthru,
        _P_NAME + "ddlSortDir": "Date Descending",
        _P_NAME + "btnInstruments": "Search (All Matches)",
    })
    return b


def _date_nav_body() -> dict:
    """Postback that activates the (lazy-loaded) Date-Range search tab."""
    b = _common_hidden()
    b["ctl00$NavMenuIdxRec$btnNav_IdxRec_Date_NEW"] = "Date Range"
    return b


def _date_search_body(dfrom: str, dthru: str) -> dict:
    b = _common_hidden()
    b.update({
        _P_DATE + "weFiledFrom_ClientState": "", _P_DATE + "weFiledThru_ClientState": "",
        _P_DATE + "meeFiledFrom_ClientState": "", _P_DATE + "meeFiledThru_ClientState": "",
        _P_DATE + "txtFiledFrom": dfrom, _P_DATE + "txtFiledThru": dthru,
        _P_DATE + "ddlType": "-1", _P_DATE + "txtDescription": "",
        _P_DATE + "txtAmountMin": "", _P_DATE + "txtAmountMax": "",
        _P_DATE + "ddlSortDir": "Date Descending",
        _P_DATE + "btnSearch": "Search",
    })
    return b


def _split_name(name: str) -> tuple[str, str]:
    """'SMITH, JOHN' -> ('SMITH','JOHN'); 'JOHN SMITH' -> ('JOHN','SMITH')
    (surname-first heuristic mirrors the existing enrichers); entity names pass
    through last-only."""
    if "," in name:
        a, b = name.split(",", 1)
        return a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    parts = name.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return name.strip(), ""


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #
async def search_by_name(state: str, county: str, name: str, max_docs: int = 400) -> list[RodDoc]:
    """Cott/Aumentum v4 name-index search (live-verified 2026-07-01).

    GET SrchName.aspx to seed the session cookies + server-side search context,
    then POST the ucSrchNames tab with btnInstruments='Search (All Matches)'
    (__VIEWSTATE intentionally empty). curl_cffi chrome impersonation + verify=
    False (Buncombe/Gaston SSL chains). Returns parsed grid rows (surname-broad;
    the caller filters to the target owner)."""
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    if not name or not name.strip():
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    url = f"{base}/SrchName.aspx"
    last, first = _split_name(name.strip())
    if not last:
        return []
    try:
        from curl_cffi.requests import AsyncSession
    except Exception:  # pragma: no cover
        return []
    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            r2 = await s.post(final, data=_name_body(last, first),
                              headers={"Referer": final}, allow_redirects=True, timeout=60)
            rows = _parse_instruments_grid(r2.text, county, state)
            # A bare/common surname can blow past the server result cap: the grid
            # comes back empty with a "maximum number of allowable results" panel.
            # Narrow by a wide Filed-date window (still captures relevant recent
            # mortgages/liens).
            if not rows and re.search(r"allowable results|maximum number", r2.text or "", re.I):
                today = datetime.now().strftime("%m/%d/%Y")
                r3 = await s.post(final, data=_name_body(last, first, "01/01/2005", today),
                                  headers={"Referer": final}, allow_redirects=True, timeout=60)
                rows = _parse_instruments_grid(r3.text, county, state)
    except Exception:  # noqa: BLE001
        return []
    return rows[:max_docs]


async def _date_swept_docs(state: str, county: str, days_back: int, max_docs: int) -> list[RodDoc]:
    """Shared Date-Range index sweep: nav to the Date tab, then POST a
    [today-days_back, today] Filed-date search and parse the grid. Doc-type
    filtering happens in the caller via the grid Type column (the vendor's date
    ddlType is an index CATEGORY, not fine-grained doc types)."""
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    url = f"{base}/SrchName.aspx"
    today = datetime.now()
    from_date = today - timedelta(days=max(1, days_back))
    try:
        from curl_cffi.requests import AsyncSession
    except Exception:  # pragma: no cover
        return []
    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            rnav = await s.post(final, data=_date_nav_body(),
                                headers={"Referer": final}, allow_redirects=True, timeout=45)
            date_url = str(rnav.url)
            body = _date_search_body(from_date.strftime("%m/%d/%Y"), today.strftime("%m/%d/%Y"))
            r2 = await s.post(date_url, data=body,
                              headers={"Referer": date_url}, allow_redirects=True, timeout=90)
            return _parse_instruments_grid(r2.text, county, state)[:max_docs]
    except Exception:  # noqa: BLE001
        return []


async def discover_recent_nods(
    state: str, county: str, days_back: int = 60, max_docs: int = 100,
) -> list[RodDoc]:
    """Recent-recordings sweep filtered to NOD-style doc types (Notice of Sale /
    Default, Lis Pendens, Substitute Trustee) via the Date-Range index."""
    docs = await _date_swept_docs(state, county, days_back, max_docs * 6)
    from_date = datetime.now() - timedelta(days=max(1, days_back))
    out: list[RodDoc] = []
    seen: set[tuple] = set()
    for d in docs:
        if not _is_nod(d.doc_type):
            continue
        if d.recorded_date and d.recorded_date < from_date:
            continue
        key = (d.book, d.page, (d.instrument_no or "").upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= max_docs:
            break
    return out


async def discover_recent_sold_recordings(
    state: str, county: str, days_back: int = 90, max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep post-sale doc types (Trustee's Deed Upon Sale and equivalents) via
    the Date-Range index. NOTE: the name/date index grid does NOT expose a
    consideration/excise column for these NC tenants, so sold-price recovery from
    this path is not available — records surface as leads, priced downstream."""
    docs = await _date_swept_docs(state, county, days_back, max_docs * 6)
    from_date = datetime.now() - timedelta(days=max(1, days_back))
    out: list[RodDoc] = []
    seen: set[tuple] = set()
    for d in docs:
        if not _is_post_sale(d.doc_type):
            continue
        if d.recorded_date and d.recorded_date < from_date:
            continue
        key = (d.book, d.page, (d.instrument_no or "").upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= max_docs:
            break
    return out

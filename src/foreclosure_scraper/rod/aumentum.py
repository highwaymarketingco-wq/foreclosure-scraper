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

2026-10-02 RE-VERIFIED LIVE: the Date-Range search (_date_swept_docs, used by
discover_recent_nods / discover_recent_sold_recordings) was returning 0 rows
for every default call. Root cause (confirmed by instrumenting the real POST
response, not guessed): the GET/nav/search POST sequence itself was never
broken — no missing postback field — the vendor enforces a HARD 30-CALENDAR-DAY
MAX on a single Date-Range search. A wider range (the 60/90-day defaults this
module requests) gets silently bounced back to the New-Search tab with no HTTP-
level error (ActiveTabIndex resets to 0; the page embeds a client-side
`alert('Please enter a valid date range. The maximum range allowed is 30...')`
that only a real browser would ever show — an httpx/curl-cffi POST just gets
the inert HTML with that string baked into a <script> block). Live-measured on
Buncombe: a 29-day-span window (30 calendar days, the largest that works)
returns up to the grid's own page-size cap of 500 rows — and THAT cap is real
too (one 30-day window had 3,805 total matches per the page's own "Your search
returned X results" banner, confirmed by paging). _date_swept_docs now chunks
the requested days_back into <=29-day-span windows (reusing one session/date_
url — re-navigating to the Date tab is NOT needed per window, confirmed live)
and bisects any window whose own result count is >= the 500-row page cap,
mirroring rod/cchs.py's sweep-bisection pattern, down to a 1-day floor.

Polk/Rutherford (rod/cott.py) run the IDENTICAL Cott eSearch v4 app on
cotthosting.com instead of a county .gov domain — live-confirmed 2026-10-02 by
running this module's own search_by_name against Polk's base URL directly (real
results, real recent 2026 recordings). cott.py's own parallel implementation
(real __VIEWSTATE/__EVENTVALIDATION extraction, `ctl00$cphMain$txtLastName`
field names) was built against a generic ASP.NET WebForms template that does
not match this vendor: __VIEWSTATE is empty/absent here exactly like Buncombe/
Gaston (the session lives in cookies, not viewstate) and those field names
don't exist on the real page, so every one of its POSTs just re-rendered the
blank search form. cott.py now delegates to the `*_at()` entry points below
instead of maintaining a second, broken copy of this vendor's protocol.

RUTHERFORD IS SEPARATELY WALLED (not fixed by the above, and not a code bug):
live-probed 2026-10-02, EVERY path under Rutherford's
cotthosting.com/NCRUTHERFORDEXTERNAL/.../protected/v4/ 302s to
`/User/Login.aspx?ReturnUrl=...` — a real "eSearch | Account Sign In" page with
a password field. Polk, on the exact same vendor app, has no such redirect.
_is_login_wall() below detects this (compares the bootstrap GET's final URL)
and short-circuits to `[]` with a log.warning instead of posting a search body
to a login form and silently reading 0 rows back as if it were a real empty
result. Per CLAUDE.md this is a genuine login wall: not defeated, no
credentials held — Rutherford via this vendor is a manual-lane candidate, not
a bypass target. RE-VERIFIED LIVE 2026-10-03 (not a transient Buncombe/Gaston-
style redirect-loop artifact: a persistent cookie jar across the full redirect
chain still lands on a real "Account Sign In" page with a `type="password"`
field, while the SAME treatment on Polk still lands on the real "Guest User"
search menu) — still genuinely walled, still correctly short-circuited.

GASTON REMOVED 2026-10-03 — NOT a timeout-value bug, NOT transient, a dead
host (this repo's docs already called it, this just finishes the fix):
`deeds.gastongov.com` TCP-connects on :443 but never completes a TLS
handshake and never sends a byte back, confirmed 2026-10-03 across 5+ live
attempts (plain curl, curl -k, curl --http1.1, and this module's own
curl_cffi impersonate="chrome" x3 trials) and every timeout value tried (20s/
25s/30s/45s) — an indefinite hang, not a slow-but-completing response, so a
longer timeout_s would not help. Ruled out a local/sandbox network problem:
in the same session, google.com (0.2s), gastongov.com's own apex domain
(1.4s), and sibling Aumentum tenants Buncombe (0.4s) and Mecklenburg (0.4s,
403 as expected without impersonation) all answered normally. This matches
docs/completeness_document.md and docs/completeness_deeds.md (both already
diagnosed this exact dead-host target on 2026-08-02) and
rod/doc_images.py's own `("NC","Gaston"): ("unreachable", ...)` entry — Gaston
migrated its ROD off Aumentum to Courthouse Computer Systems on 2026-05-28,
and nothing in this module was ever updated to follow. The real, live,
working Gaston ROD is `gastonnc.courthousecomputersystems.com` (a CCHS
DevExpress "LRSearch" MVC app — a different protocol from both this module
and the classic-ASP `rod/cchs.py` SearchService.asp counties), already
reused for name-indexed lien-existence lookups by
`enrichment_gaston_rod.py`. That module only supports a per-owner-name
search, not a date-range sweep, so it is not a drop-in replacement for this
module's `discover_recent_nods`/`discover_recent_sold_recordings` callers —
removing the dead mapping here (rather than silently eating a 30s timeout
every run) is the fix in scope today; a real Gaston NOD-via-date-sweep would
need new work against the LRSearch protocol, tracked separately.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from . import deed_stamp
from .models import RodDoc, normalize_doc_type

log = structlog.get_logger()

AUMENTUM_COUNTIES = {
    ("NC", "Mecklenburg"): "https://meckrod.manatron.com/External/LandRecords/protected/v4",
    ("NC", "Buncombe"): "https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4",
    # Gaston deliberately NOT here — see module docstring "GASTON REMOVED
    # 2026-10-03": deeds.gastongov.com is a confirmed-dead host (TCP connects,
    # TLS handshake never completes), Gaston moved its ROD to Courthouse
    # Computer Systems on 2026-05-28. Do not re-add without a live re-probe.
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


def _is_login_wall(final_url: str) -> bool:
    """True if the bootstrap GET to SrchName.aspx/SrchDate.aspx got redirected
    to this tenant's own sign-in page (live-confirmed 2026-10-02: Rutherford
    NC's cotthosting.com tenant requires an account — every protected/v4/*
    path 302s to /User/Login.aspx?ReturnUrl=... with a real password field —
    while Polk/Buncombe/Gaston on the SAME vendor app are open, no login).
    This is a genuine compliance wall (CLAUDE.md: a login wall is not defeated,
    no credentials held) — not a parsing bug, so callers must stop here rather
    than post a search body to a login form and silently read 0 rows back."""
    return "/User/Login.aspx" in final_url


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

# The vendor's own hard cap on a single Date-Range search (live-verified
# 2026-10-02 — see module docstring): a window with a (end - start) SPAN of 29
# days (= 30 calendar days inclusive) works; 30 fails silently. And the results
# grid's own page-size selector tops out at 500 (<option value="500">, the
# live-observed default) — a window whose own "Your search returned X results"
# count is >= this is the head of a longer list, not the whole list.
_MAX_WINDOW_SPAN_DAYS = 29
_RESULTS_PAGE_CAP = 500


async def _search_by_name_at(
    base: str, county: str, state: str, name: str, max_docs: int = 400,
) -> list[RodDoc]:
    """Cott/Aumentum v4 name-index search (live-verified 2026-07-01, and again
    2026-10-02 against both a county .gov tenant and cott.py's cotthosting.com
    tenants — same app, same protocol).

    GET SrchName.aspx to seed the session cookies + server-side search context,
    then POST the ucSrchNames tab with btnInstruments='Search (All Matches)'
    (__VIEWSTATE intentionally empty). curl_cffi chrome impersonation + verify=
    False (Buncombe/Gaston SSL chains). Returns parsed grid rows (surname-broad;
    the caller filters to the target owner). Parameterized by `base` so
    rod/cott.py's Polk/Rutherford tenants can call straight into this instead
    of keeping a second, broken implementation of the same vendor."""
    if not name or not name.strip():
        return []
    url = f"{base}/SrchName.aspx"
    last, first = _split_name(name.strip())
    if not last:
        return []
    try:
        from curl_cffi.requests import AsyncSession
    except Exception as exc:  # pragma: no cover  # noqa: BLE001
        log.warning("aumentum.curl_cffi_unavailable", base=base, county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return []
    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            if _is_login_wall(final):
                log.warning("aumentum.login_wall", base=base, county=county, final_url=final)
                return []
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
    except Exception as exc:  # noqa: BLE001
        log.warning("aumentum.search_by_name_failed", base=base, county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return []
    return rows[:max_docs]


async def search_by_name(state: str, county: str, name: str, max_docs: int = 400) -> list[RodDoc]:
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    return await _search_by_name_at(AUMENTUM_COUNTIES[(state, county)], county, state, name, max_docs)


async def _sweep_date_window(
    session, date_url: str, county: str, state: str,
    a: datetime, b: datetime, out: list[RodDoc], seen: set[tuple],
) -> None:
    """One <=29-day-span Date-Range search, bisecting further if the page's
    own result count is at/over the _RESULTS_PAGE_CAP (the head of a longer
    list, not the whole list) — same cap-detection shape as rod/cchs.py's
    sweep. Appends newly-seen rows into `out`/`seen` in place."""
    span = (b - a).days
    body = _date_search_body(a.strftime("%m/%d/%Y"), b.strftime("%m/%d/%Y"))
    r = await session.post(date_url, data=body, headers={"Referer": date_url},
                           allow_redirects=True, timeout=90)
    total = _result_count(r.text)
    if total is not None and total >= _RESULTS_PAGE_CAP and span >= 1:
        mid = a + timedelta(days=span // 2)
        await _sweep_date_window(session, date_url, county, state, a, mid, out, seen)
        await _sweep_date_window(session, date_url, county, state,
                                 mid + timedelta(days=1), b, out, seen)
        return
    for d in _parse_instruments_grid(r.text, county, state):
        key = (d.book, d.page, (d.instrument_no or "").upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(d)


# A fully-unbounded sweep (raw_row_cap=None) still needs SOME circuit breaker
# against a pathological county/days_back combination — this is far above any
# real observed volume (Buncombe: 8,055 rows / 60 days) so it never engages in
# normal operation.
_RAW_SWEEP_SAFETY_CEILING = 25_000


async def _date_swept_docs_at(
    base: str, county: str, state: str, days_back: int,
    raw_row_cap: int | None,
) -> list[RodDoc]:
    """Shared Date-Range index sweep: nav to the Date tab ONCE, then POST a
    series of <=29-day-span Filed-date searches covering [today-days_back,
    today] over that SAME session (re-navigating per window is not needed —
    live-confirmed 2026-10-02). Doc-type filtering happens in the caller via
    the grid Type column (the vendor's date ddlType is an index CATEGORY, not
    fine-grained doc types). Parameterized by `base` — see _search_by_name_at.

    `raw_row_cap`: stop once this many RAW rows (any doc type) have been
    collected — fine for a caller that wants a quick sample of recent
    recordings regardless of type (cash_buyer_deeds.py: deed/DOT rows are
    common, so an early sample is representative). Pass **None** to always
    sweep the FULL days_back window instead: required for a doc-type KEYWORD
    filter (discover_recent_nods / discover_recent_sold_recordings) — a NOD-
    style doc is a small fraction of total volume (0.5% live-measured on
    Buncombe: 41 of 8,055 rows over 60 days), so stopping on raw row count
    would silently return a biased, often-empty sample from whichever few
    calendar days happened to fill the quota first — the exact silent-wrong-
    success shape this project's CLAUDE.md warns about."""
    url = f"{base}/SrchName.aspx"
    today = datetime.now()
    from_date = today - timedelta(days=max(1, days_back))
    try:
        from curl_cffi.requests import AsyncSession
    except Exception as exc:  # pragma: no cover  # noqa: BLE001
        log.warning("aumentum.curl_cffi_unavailable", base=base, county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return []
    out: list[RodDoc] = []
    seen: set[tuple] = set()
    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            if _is_login_wall(final):
                log.warning("aumentum.login_wall", base=base, county=county, final_url=final)
                return []
            rnav = await s.post(final, data=_date_nav_body(),
                                headers={"Referer": final}, allow_redirects=True, timeout=45)
            date_url = str(rnav.url)
            b = today
            while b >= from_date and len(out) < _RAW_SWEEP_SAFETY_CEILING:
                if raw_row_cap is not None and len(out) >= raw_row_cap:
                    break
                a = max(from_date, b - timedelta(days=_MAX_WINDOW_SPAN_DAYS))
                await _sweep_date_window(s, date_url, county, state, a, b, out, seen)
                b = a - timedelta(days=1)
    except Exception as exc:  # noqa: BLE001
        log.warning("aumentum.date_sweep_failed", base=base, county=county,
                    error=f"{type(exc).__name__}: {str(exc)[:160]}")
        # partial `out` is still useful to the caller's keyword post-filter
    return out[:raw_row_cap] if raw_row_cap is not None else out


async def _date_swept_docs(state: str, county: str, days_back: int, max_docs: int) -> list[RodDoc]:
    """Per-(state, county) wrapper kept for scrapers.national.cash_buyer_deeds,
    which wants an early-stop sample of ALL recent doc types (deeds/DOTs are
    common, so `max_docs` raw rows is a representative sample) — see
    _date_swept_docs_at's docstring for why discover_recent_nods/sold_
    recordings below do NOT use this early-stop behavior."""
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    return await _date_swept_docs_at(
        AUMENTUM_COUNTIES[(state, county)], county, state, days_back, raw_row_cap=max_docs)


async def discover_recent_nods_at(
    base: str, county: str, state: str, days_back: int = 60, max_docs: int = 100,
) -> list[RodDoc]:
    """Recent-recordings sweep filtered to NOD-style doc types (Notice of Sale /
    Default, Lis Pendens, Substitute Trustee) via the Date-Range index.
    Parameterized by `base` — see _search_by_name_at."""
    docs = await _date_swept_docs_at(base, county, state, days_back, raw_row_cap=None)
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


async def discover_recent_nods(
    state: str, county: str, days_back: int = 60, max_docs: int = 100,
) -> list[RodDoc]:
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    return await discover_recent_nods_at(
        AUMENTUM_COUNTIES[(state, county)], county, state, days_back, max_docs)


async def discover_recent_sold_recordings_at(
    base: str, county: str, state: str, days_back: int = 90, max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep post-sale doc types (Trustee's Deed Upon Sale and equivalents) via
    the Date-Range index. NOTE: the name/date index grid does NOT expose a
    consideration/excise column for these NC tenants, so sold-price recovery from
    this path is not available — records surface as leads, priced downstream.
    Parameterized by `base` — see _search_by_name_at."""
    docs = await _date_swept_docs_at(base, county, state, days_back, raw_row_cap=None)
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


async def discover_recent_sold_recordings(
    state: str, county: str, days_back: int = 90, max_docs: int = 100,
) -> list[RodDoc]:
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    return await discover_recent_sold_recordings_at(
        AUMENTUM_COUNTIES[(state, county)], county, state, days_back, max_docs)

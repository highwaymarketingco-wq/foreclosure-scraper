"""Aumentum / Manatron LandRecords — Mecklenburg, Buncombe, Gaston NC.

ASP.NET WebForms with __VIEWSTATE. URL pattern:
  https://{rod-host}/External/LandRecords/protected/v4/SrchName.aspx
The form must POST __VIEWSTATE + __EVENTVALIDATION + name fields.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

AUMENTUM_COUNTIES = {
    ("NC", "Mecklenburg"): "https://meckrod.manatron.com/External/LandRecords/protected/v4",
    ("NC", "Buncombe"): "https://registerofdeeds.buncombenc.gov/External/LandRecords/protected/v4",
    ("NC", "Gaston"): "https://deeds.gastongov.com/external/LandRecords/protected/v4",
}

# Document-type labels Aumentum's SrchDocType.aspx exposes for NC ROD.
# Aumentum stores both a short code and a free-text label; we POST the label
# in the doc-type listbox and post-filter by keyword.
AUMENTUM_NOD_DOC_TYPES = (
    "NOTICE OF FORECLOSURE SALE",
    "NOTICE OF SALE",
    "NOTICE OF DEFAULT",
    "LIS PENDENS",
    "NOTICE OF HEARING",
    "FORECLOSURE",
)

# POST-sale recording labels — these are recorded AFTER the foreclosure
# auction completes, with deed-tax stamps that encode the hammer price
# (NC charges $1 excise tax per $500 of consideration). Each is the
# document that transfers title from the trustee/borrower to the
# winning bidder.
AUMENTUM_POST_SALE_DOC_TYPES = (
    "TRUSTEES DEED UPON SALE",
    "TRUSTEE'S DEED UPON SALE",
    "TRUSTEES DEED",
    "TRUSTEE'S DEED",
    "SUBSTITUTE TRUSTEES DEED",
    "SUBSTITUTE TRUSTEE'S DEED",
    "FORECLOSURE DEED",
    "DEED UNDER POWER OF SALE",
    "COMMISSIONER'S DEED",
    "COMMISSIONERS DEED",
)

NOD_KEYWORDS = (
    "NOTICE OF FORECLOSURE",
    "NOTICE OF DEFAULT",
    "NOTICE OF SALE",
    "LIS PENDENS",
    "NOS",
    "NOD",
    "FORECLOSURE SALE",
)

# Keywords that identify a post-sale (already-completed-auction) recording.
# Used to filter the grid response since Aumentum sometimes ignores the
# doc-type filter and returns everything in the date range.
POST_SALE_KEYWORDS = (
    "TRUSTEE",   # catches Trustee's Deed / Substitute Trustees Deed / Trustees Deed Upon Sale
    "FORECLOSURE DEED",
    "COMMISSIONER",  # Commissioner's Deed (less common but used in some NC counties)
    "POWER OF SALE",
)


def _is_nod(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in NOD_KEYWORDS)


def _is_post_sale(doc_type: str | None) -> bool:
    """True for recordings that transfer title to the foreclosure auction
    winner — Trustee's Deed Upon Sale and equivalents."""
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in POST_SALE_KEYWORDS)


def _extract_hidden(html: str, field: str) -> str:
    m = re.search(rf'<input[^>]*name="{field}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""


def _parse_grid(html: str, county: str, state: str) -> list[RodDoc]:
    """Extract recorded-document rows from the SrchName grid (id=ResultsGrid)."""
    out: list[RodDoc] = []
    tree = HTMLParser(html)
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
        try:
            recorded = dateparser.parse(date_str)
        except (ValueError, TypeError):
            continue
        doc_type = col(row, "doc type", "type")
        book = col(row, "book")
        page = col(row, "page")
        grantor = col(row, "grantor")
        grantee = col(row, "grantee")
        instrument_no = col(row, "instrument", "doc#", "doc no")
        # Amount columns vary by tenant. Aumentum exposes some combination
        # of: "Consideration", "Excise Tax", "Tax Stamp", "Amount". Try
        # all common labels — we keep both raw consideration (sale price)
        # and the stamp value separately when both are available.
        consideration_str = col(row, "consideration", "sale price")
        stamp_str = col(row, "excise tax", "tax stamp", "stamp", "stamps")
        amount_str = col(row, "amount", "doc amount")

        consideration = _money(consideration_str)
        stamp = _money(stamp_str)
        # Derive consideration from stamp when only the stamp is shown
        # (NC: $1 stamp per $500 consideration).
        if consideration is None and stamp is not None:
            consideration = stamp * 500.0
        amt = _money(amount_str)

        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(doc_type),
                recorded_date=recorded,
                book=book or None,
                page=page or None,
                grantor=grantor[:200] or None,
                grantee=grantee[:200] or None,
                instrument_no=instrument_no or None,
                amount=amt,
                consideration_amount=consideration,
                excise_tax_stamp=stamp,
            )
        )
    return out


_MONEY_RE = re.compile(r"\$?\s*([\d,]+(?:\.\d{2})?)")


def _money(s: str | None) -> float | None:
    """Parse a dollar-amount string like '$45,000.00' or '7.50' into float.
    Returns None for empty / unparseable input or implausible values."""
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


_INSTR_GRID_ROW = re.compile(
    r"<tr[^>]*>((?:(?!</tr>).)*?\d{2}/\d{2}/\d{4}(?:(?!</tr>).)*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def _cell_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _parse_instruments_grid(html: str, county: str, state: str) -> list[RodDoc]:
    """Parse the Cott/Aumentum v4 cpgvInstruments results grid (position-based).
    Column order verified live (Buncombe/Gaston 2026-06-30):
    td0=row#, 1=Date Filed, 2=Code, 3=Type, 4=Grantor, 5=Grantee, 6=Description,
    7=File Number, 8=Book-Page."""
    out: list[RodDoc] = []
    for m in _INSTR_GRID_ROW.finditer(html or ""):
        cells = [_cell_text(c) for c in _TD.findall(m.group(1))]
        if len(cells) < 5:
            continue
        date_s = cells[1]
        try:
            recorded = dateparser.parse(date_s)
        except (ValueError, TypeError, OverflowError):
            recorded = None
        dtype = cells[3] if len(cells) > 3 else ""
        grantor = cells[4] if len(cells) > 4 else ""
        grantee = cells[5] if len(cells) > 5 else ""
        bp = cells[8] if len(cells) > 8 else ""
        book, page = bp, ""
        for sep in ("/", "-"):
            if sep in bp:
                parts = [p.strip() for p in bp.split(sep, 1)]
                book, page = parts[0], (parts[1] if len(parts) > 1 else "")
                break
        out.append(RodDoc(
            county=county, state=state, doc_type=normalize_doc_type(dtype),
            recorded_date=recorded, book=book.strip() or None, page=page.strip() or None,
            grantor=grantor[:200] or None, grantee=grantee[:200] or None,
        ))
    return out


async def search_by_name(state: str, county: str, name: str, max_docs: int = 400) -> list[RodDoc]:
    """Cott/Aumentum v4 name-index search (live-verified 2026-06-30; replaces the old
    broken field names + the empty-__VIEWSTATE bail). GET SrchName.aspx to seed the
    session cookies, then POST the ucSrchNames tab with btnInstruments='Search (All
    Matches)' (server holds search state in the session, __VIEWSTATE is intentionally
    empty on this Cott v4 form). curl_cffi chrome impersonation + verify=False for the
    Buncombe SSL chain."""
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    url = f"{base}/SrchName.aspx"
    last, first = name, ""
    if "," in name:
        a, b = name.split(",", 1)
        last, first = a.strip(), (b.strip().split(" ")[0] if b.strip() else "")
    elif " " in name:
        parts = name.split()
        last, first = parts[0], parts[1]
    try:
        from curl_cffi.requests import AsyncSession
    except Exception:  # pragma: no cover
        return []
    P = "ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$"

    def _body(dfrom: str, dthru: str) -> dict:
        return {
            "ctl00_cphMain_tcMain_ClientState": '{"ActiveTabIndex":0,"TabEnabledState":[true,false,false,false,true],"TabWasLoadedOnceState":[false,false,false,false,false]}',
            "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "",
            "__VIEWSTATE": "", "__SCROLLPOSITIONX": "0", "__SCROLLPOSITIONY": "0",
            "__VIEWSTATEENCRYPTED": "",
            P + "weFiledFrom_ClientState": "", P + "weFiledThru_ClientState": "",
            P + "meeFiledFrom_ClientState": "", P + "meeFiledThru_ClientState": "",
            P + "txtFirmSurname": last, P + "ddlWildcardLast": "0",
            P + "txtGivenName": first, P + "ddlWildcardFirst": "0",
            P + "ddlSide": "-1", P + "ddlType": "-1", P + "ddlIndexType": "",
            P + "txtFiledFrom": dfrom, P + "txtFiledThru": dthru,
            P + "ddlSortDir": "Date Descending",
            P + "btnInstruments": "Search (All Matches)",
            "ctl00$txtJobReference": "",
            "ctl00$ucShoppingCart$meeZipCode_ClientState": "",
            "ctl00$ucShoppingCart$hfQuantity": "",
        }

    try:
        async with AsyncSession(verify=False, impersonate="chrome") as s:
            r = await s.get(url, allow_redirects=True, timeout=30)
            final = str(r.url)
            r2 = await s.post(final, data=_body("", ""), headers={"Referer": final},
                              allow_redirects=True, timeout=45)
            rows = _parse_instruments_grid(r2.text, county, state)
            # A bare/common surname blows past the server result cap: the grid is empty
            # and the message panel says "maximum number of allowable results". Narrow by
            # a wide Filed-date window (captures any still-relevant recent mortgage/lien).
            if not rows and re.search(r"allowable results", r2.text or "", re.I):
                today = datetime.now().strftime("%m/%d/%Y")
                r3 = await s.post(final, data=_body("01/01/2005", today),
                                  headers={"Referer": final}, allow_redirects=True, timeout=45)
                rows = _parse_instruments_grid(r3.text, county, state)
    except Exception:
        return []
    return rows[:max_docs]


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Aumentum recent-recordings sweep filtered by NOD-style doc types.

    Strategy: hit SrchDocType.aspx (the doc-type-driven search form) and POST
    one doc-type at a time across our NOD label set, with a recorded-date
    range of [today-days_back, today]. Aumentum sometimes silently ignores
    the doc-type filter, so we still post-filter by keyword.
    """
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    form_url = f"{base}/SrchDocType.aspx"
    fallback_url = f"{base}/SrchName.aspx"
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    def _accept(rows: list[RodDoc]) -> bool:
        added_any = False
        for d in rows:
            if not _is_nod(d.doc_type):
                continue
            if d.recorded_date and d.recorded_date < from_date:
                continue
            key = (d.book, d.page, (d.instrument_no or "").upper())
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
            added_any = True
            if len(out) >= max_docs:
                return True
        return added_any

    try:
        async with client(timeout=30.0) as c:
            r = await c.get(form_url)
            if r.status_code != 200:
                # Some installs only expose SrchDate.aspx — fall through
                r = await c.get(fallback_url)
                if r.status_code != 200:
                    return []
                form_url = fallback_url

            html = r.text
            viewstate = _extract_hidden(html, "__VIEWSTATE")
            generator = _extract_hidden(html, "__VIEWSTATEGENERATOR")
            event_val = _extract_hidden(html, "__EVENTVALIDATION")
            if not viewstate:
                return []

            for doc_label in AUMENTUM_NOD_DOC_TYPES:
                data = {
                    "__VIEWSTATE": viewstate,
                    "__VIEWSTATEGENERATOR": generator,
                    "__EVENTVALIDATION": event_val,
                    "ctl00$cphMain$ddlDocType": doc_label,
                    "ctl00$cphMain$lstDocType": doc_label,
                    "ctl00$cphMain$txtFromDate": from_date.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtThroughDate": today.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtFromRecordDate": from_date.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtThroughRecordDate": today.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$btnSearch": "Search",
                }
                try:
                    r2 = await c.post(form_url, data=data, headers={"Referer": form_url})
                except Exception:
                    continue
                if r2.status_code != 200:
                    continue
                rows = _parse_grid(r2.text, county, state)
                if _accept(rows) and len(out) >= max_docs:
                    return out[:max_docs]
                # Refresh viewstate from response for next post
                viewstate = _extract_hidden(r2.text, "__VIEWSTATE") or viewstate
                generator = _extract_hidden(r2.text, "__VIEWSTATEGENERATOR") or generator
                event_val = _extract_hidden(r2.text, "__EVENTVALIDATION") or event_val
    except Exception:
        return out[:max_docs]
    return out[:max_docs]


async def discover_recent_sold_recordings(
    state: str,
    county: str,
    days_back: int = 90,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep AUMENTUM_POST_SALE_DOC_TYPES (Trustee's Deed Upon Sale and
    equivalents) — these are the recordings that transfer the property
    from the trustee to the auction winner. Each carries a deed-tax
    stamp from which we recover the hammer price (NC: stamp × 500 =
    consideration).

    Mirrors discover_recent_nods structure but with post-sale doc types
    + post-sale filter predicate. Default lookback 90 days (vs 60 for
    NOD) to give the foreclosure_sold_comps pool a richer history.
    """
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    form_url = f"{base}/SrchDocType.aspx"
    fallback_url = f"{base}/SrchName.aspx"
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    def _accept(rows: list[RodDoc]) -> bool:
        added_any = False
        for d in rows:
            if not _is_post_sale(d.doc_type):
                continue
            if d.recorded_date and d.recorded_date < from_date:
                continue
            # Drop recordings with no sold-price signal — they're not
            # useful as comps. (Some Trustee's Deeds are recorded for
            # corrective / re-execution reasons without consideration.)
            if d.consideration_amount is None and d.excise_tax_stamp is None:
                continue
            key = (d.book, d.page, (d.instrument_no or "").upper())
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
            added_any = True
            if len(out) >= max_docs:
                return True
        return added_any

    try:
        async with client(timeout=30.0) as c:
            r = await c.get(form_url)
            if r.status_code != 200:
                r = await c.get(fallback_url)
                if r.status_code != 200:
                    return []
                form_url = fallback_url

            html = r.text
            viewstate = _extract_hidden(html, "__VIEWSTATE")
            generator = _extract_hidden(html, "__VIEWSTATEGENERATOR")
            event_val = _extract_hidden(html, "__EVENTVALIDATION")
            if not viewstate:
                return []

            for doc_label in AUMENTUM_POST_SALE_DOC_TYPES:
                data = {
                    "__VIEWSTATE": viewstate,
                    "__VIEWSTATEGENERATOR": generator,
                    "__EVENTVALIDATION": event_val,
                    "ctl00$cphMain$ddlDocType": doc_label,
                    "ctl00$cphMain$lstDocType": doc_label,
                    "ctl00$cphMain$txtFromDate": from_date.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtThroughDate": today.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtFromRecordDate": from_date.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$txtThroughRecordDate": today.strftime("%m/%d/%Y"),
                    "ctl00$cphMain$btnSearch": "Search",
                }
                try:
                    r2 = await c.post(form_url, data=data, headers={"Referer": form_url})
                except Exception:
                    continue
                if r2.status_code != 200:
                    continue
                rows = _parse_grid(r2.text, county, state)
                if _accept(rows) and len(out) >= max_docs:
                    return out[:max_docs]
                viewstate = _extract_hidden(r2.text, "__VIEWSTATE") or viewstate
                generator = _extract_hidden(r2.text, "__VIEWSTATEGENERATOR") or generator
                event_val = _extract_hidden(r2.text, "__EVENTVALIDATION") or event_val
    except Exception:
        return out[:max_docs]
    return out[:max_docs]

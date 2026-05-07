"""Cott Systems / cotthosting.com — Polk and Rutherford NC.

Same ASP.NET form pattern as Aumentum (Cott OEMs Manatron) — share the parser.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .aumentum import (
    _extract_hidden,
    _parse_grid,
    AUMENTUM_NOD_DOC_TYPES,
    AUMENTUM_POST_SALE_DOC_TYPES,
    _is_nod,
    _is_post_sale,
)
from ..http_client import client
from .models import RodDoc

COTT_COUNTIES = {
    ("NC", "Polk"): "https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4",
    ("NC", "Rutherford"): "https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4",
}


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    form_url = f"{base}/SrchName.aspx"

    try:
        async with client(timeout=30.0) as c:
            r = await c.get(form_url)
            if r.status_code != 200:
                return []
            html = r.text
            viewstate = _extract_hidden(html, "__VIEWSTATE")
            generator = _extract_hidden(html, "__VIEWSTATEGENERATOR")
            event_val = _extract_hidden(html, "__EVENTVALIDATION")
            if not viewstate:
                return []

            last = name
            first = ""
            if "," in name:
                parts = [p.strip() for p in name.split(",", 1)]
                last, first = parts[0], parts[1] if len(parts) > 1 else ""
            elif " " in name:
                parts = name.split()
                last = parts[0]
                first = " ".join(parts[1:])

            data = {
                "__VIEWSTATE": viewstate,
                "__VIEWSTATEGENERATOR": generator,
                "__EVENTVALIDATION": event_val,
                "ctl00$cphMain$txtLastName": last,
                "ctl00$cphMain$txtFirstName": first,
                "ctl00$cphMain$btnSearch": "Search",
            }
            r2 = await c.post(form_url, data=data, headers={"Referer": form_url})
            if r2.status_code != 200:
                return []
    except Exception:
        return []
    return _parse_grid(r2.text, county, state)[:max_docs]


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Cott (Manatron OEM) recent-recordings sweep filtered by NOD doc types."""
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    form_url = f"{base}/SrchDocType.aspx"
    fallback_url = f"{base}/SrchName.aspx"
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    def _accept(rows: list[RodDoc]) -> bool:
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
            if len(out) >= max_docs:
                return True
        return False

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
    """Cott (Manatron OEM) — same form pattern as Aumentum but for
    POST-sale recordings (Trustee's Deed Upon Sale and equivalents).
    Each carries a deed-tax stamp encoding hammer price."""
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    form_url = f"{base}/SrchDocType.aspx"
    fallback_url = f"{base}/SrchName.aspx"
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()

    def _accept(rows: list[RodDoc]) -> bool:
        for d in rows:
            if not _is_post_sale(d.doc_type):
                continue
            if d.recorded_date and d.recorded_date < from_date:
                continue
            if d.consideration_amount is None and d.excise_tax_stamp is None:
                continue
            key = (d.book, d.page, (d.instrument_no or "").upper())
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
            if len(out) >= max_docs:
                return True
        return False

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

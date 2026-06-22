"""Harris 'Acclaim Web' (Harris Recording Solutions) Register-of-Deeds adapter.

AcclaimWeb is an ASP.NET app with a Telerik MVC grid. The recorded-document
index is reachable BROWSERLESS and FREE — no CAPTCHA, no anti-forgery token:
  1. GET  /AcclaimWeb/search/SearchTypeDocType          -> session cookie
  2. POST /AcclaimWeb/search/SearchTypeDocType?Length=6 (date range) -> set search
  3. POST /AcclaimWeb/Search/GridResults  (page/size)   -> JSON {data:[...], total}

Each row carries DirectName (grantor), IndirectName (grantee), DocType,
RecordDate (/Date(epoch)/), InstrumentNumber, BookType, BookPage, ParcelNumber,
Comments (legal description).

SC foreclosure is JUDICIAL (lis pendens lives in the courts — already covered by
sc_public_index_lis_pendens), so the ROD distress signal here is PROBATE
(deed of distribution / death) + LIENS (tax / mechanics). Lien releases and
satisfactions are resolutions, not distress, and are excluded.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
import structlog

from .models import RodDoc

log = structlog.get_logger()

ACCLAIM_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Pickens"): "https://www.pickensscrod.us/AcclaimWeb",
}

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
_DATE_RE = re.compile(r"/Date\((\d+)")

# Distress doc-type tokens; resolutions (release/satisfaction/etc.) excluded.
_DISTRESS = ("DIST", "DEATH", "LIEN", "MECH", "FORECLOS", "LIS PENDENS",
             "TRUSTEE", "NOTICE OF SALE", "TAX SALE")
_RESOLVED = ("REL", "SAT", "TERM", "RESC", "CANCEL", "SUBORD")


def is_distress(doc_type: str | None) -> bool:
    s = (doc_type or "").upper()
    return any(k in s for k in _DISTRESS) and not any(k in s for k in _RESOLVED)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    m = _DATE_RE.search(s)
    if not m:
        return None
    try:
        return datetime.utcfromtimestamp(int(m.group(1)) / 1000.0)
    except (ValueError, OverflowError):
        return None


def _row_to_doc(row: dict, state: str, county: str) -> RodDoc:
    bp = (row.get("BookPage") or "").split("/")
    book = bp[0].strip() if bp and bp[0].strip() else None
    page = bp[1].strip() if len(bp) > 1 and bp[1].strip() else None
    return RodDoc(
        county=county, state=state,
        doc_type=(row.get("DocType") or "").strip(),
        recorded_date=_parse_date(row.get("RecordDate")),
        book=book, page=page,
        grantor=(row.get("DirectName") or "").strip() or None,
        grantee=(row.get("IndirectName") or "").strip() or None,
        instrument_no=(row.get("InstrumentNumber") or "").strip() or None,
        parcel_id=(row.get("ParcelNumber") or "").strip() or None,
        notes=(row.get("Comments") or "").strip() or None,
        raw={"acclaim": row, "book_type": row.get("BookType")},
    )


_CHUNK_DAYS = 10  # AcclaimWeb caps results per search; ~10-day windows stay under it


def _fmt(d: datetime) -> str:
    return f"{d.month}/{d.day}/{d.year}"


async def _search_chunk(c: httpx.AsyncClient, base: str, frm: datetime,
                        to: datetime) -> list[dict]:
    """Run one date-window doc-type search; return the raw grid rows (or [])."""
    s = await c.post(f"{base}/search/SearchTypeDocType?Length=6", data={
        "DocTypes": "all", "DocTypesDisplay-input": "All", "DocTypesDisplay": "",
        "DateRangeList": " ", "RecordDateFrom": _fmt(frm),
        "DefaultFromDate": "1/1/1828", "RecordDateTo": _fmt(to), "btnSearch": "Search"})
    if "ShowError" in s.text or "exceeded" in s.text.lower():
        log.warning("acclaim.window_over_cap", frm=_fmt(frm), to=_fmt(to))
        return []  # window too large for the portal cap; caller uses small windows
    r = await c.post(f"{base}/Search/GridResults",
                     data={"page": "1", "size": "2000", "pageSize": "2000"},
                     headers={"X-Requested-With": "XMLHttpRequest"})
    if r.status_code != 200 or "json" not in r.headers.get("content-type", "").lower():
        return []
    return r.json().get("data") or []


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 400) -> list[RodDoc]:
    """Sweep recent AcclaimWeb recordings in capped date windows; return
    distress-relevant RodDocs (deduped by instrument number)."""
    base = ACCLAIM_COUNTIES.get((state, county))
    if not base:
        return []
    today = datetime.utcnow()
    earliest = today - timedelta(days=max(1, days_back))
    out: list[RodDoc] = []
    seen: set[str] = set()
    scanned = 0
    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=_UA) as c:
            await c.get(f"{base}/search/SearchTypeDocType")  # session cookie
            cur = today
            while cur > earliest and len(out) < max_docs:
                chunk_from = max(earliest, cur - timedelta(days=_CHUNK_DAYS))
                rows = await _search_chunk(c, base, chunk_from, cur)
                scanned += len(rows)
                for row in rows:
                    if not is_distress(row.get("DocType")):
                        continue
                    inst = (row.get("InstrumentNumber") or "").strip()
                    if inst and inst in seen:
                        continue
                    if inst:
                        seen.add(inst)
                    out.append(_row_to_doc(row, state, county))
                    if len(out) >= max_docs:
                        break
                cur = chunk_from - timedelta(days=1)
    except Exception:
        log.warning("acclaim.discover_failed", state=state, county=county)
        return out
    log.info("acclaim.discovered", county=county, scanned=scanned, distress=len(out))
    return out

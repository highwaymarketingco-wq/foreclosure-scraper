"""Harris 'Acclaim Web' (Harris Recording Solutions) Register-of-Deeds adapter.

AcclaimWeb is an ASP.NET app with a Telerik MVC grid. The recorded-document
index is reachable BROWSERLESS and FREE — no CAPTCHA, no anti-forgery token:
  1. GET  /AcclaimWeb/search/SearchTypeDocType          -> session cookie
  2. POST /AcclaimWeb/search/SearchTypeDocType?Length=6 (date range) -> set search
  3. POST /AcclaimWeb/Search/GridResults  (page/size)   -> JSON {data:[...], total}

Each row carries DirectName (grantor), IndirectName (grantee), DocType,
RecordDate (/Date(epoch)/), InstrumentNumber, BookType, BookPage, ParcelNumber,
Comments (legal description), AND TransactionItemId -- an internal document
id that resolves to the free, no-login scanned-document PDF; see
`document_pdf_url` below for how and the live-verification evidence. This was
previously (source_completeness_audit_2026-10-13.md) mis-flagged as
"Needs YOU logged in" on the assumption that the image only opens via a
click-driven session flow -- it does not; the id is already in this grid
response and the PDF endpoint is reachable cold.

SC foreclosure is JUDICIAL (lis pendens lives in the courts — already covered by
sc_public_index_lis_pendens), so the ROD distress signal here is PROBATE
(deed of distribution / death) + LIENS (tax / mechanics). Lien releases and
satisfactions are resolutions, not distress, and are excluded.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta

import httpx
import structlog

from ..http_client import client
from .models import RodDoc

log = structlog.get_logger()

ACCLAIM_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Pickens"): "https://www.pickensscrod.us/AcclaimWeb",
}

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


def document_pdf_url(base: str, transaction_item_id: object) -> str | None:
    """The free, no-login, no-session full scanned-document PDF for one
    AcclaimWeb grid row's internal id.

    Every `GridResults` row already carries `TransactionItemId` -- an internal
    document id, NOT the public `InstrumentNumber` -- that is otherwise only
    reachable by clicking the row open in the UI (which primes server-side
    session state before `search/Details/` will render). `Image/
    DocumentPdfAllPages/{id}` sidesteps that entirely: live-verified
    2026-10-14 against 15 fresh real documents (on top of the one instrument
    already viewed by hand in-browser earlier the same session) spanning
    every distress doc type this scraper classifies (D/DIST, D/DEATH, LIEN,
    L/MECH, M/MH LIEN AFF, L/MECH AFFIDAVIT) plus PLAT/DEED/M-SAT controls --
    a bare GET with NO prior search, NO cookies, and NO `StartImageRetrieval`
    priming call returns 200 `application/pdf` with real, differently-sized
    PDF bytes every time. (`Image/DocumentImage1/{id}` -- the OTHER endpoint
    the portal exposes -- is NOT a byte endpoint: cold it 500s with "Value cannot be
    null. Parameter name: source", and even preceded by `StartImageRetrieval`
    it returns an HTML viewer SHELL page, not an image -- that one genuinely
    needs the real browser's JS runtime, so it is not used here.)

    None when the row carries no `TransactionItemId` (shouldn't happen on a
    real grid row, but the caller's HTTP response is never fully trusted)."""
    tid = transaction_item_id
    if tid is None or (isinstance(tid, str) and not tid.strip()):
        return None
    try:
        tid_int = int(float(tid))
    except (TypeError, ValueError):
        return None
    if tid_int <= 0:
        return None
    return f"{base.rstrip('/')}/Image/DocumentPdfAllPages/{tid_int}"


def _row_to_doc(row: dict, state: str, county: str, base: str | None = None) -> RodDoc:
    bp = (row.get("BookPage") or "").split("/")
    book = bp[0].strip() if bp and bp[0].strip() else None
    page = bp[1].strip() if len(bp) > 1 and bp[1].strip() else None
    raw: dict = {"acclaim": row, "book_type": row.get("BookType")}
    if base:
        url = document_pdf_url(base, row.get("TransactionItemId"))
        if url:
            raw["document_pdf_url"] = url
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
        raw=raw,
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
        # Shared client => per-host throttle + retry/backoff + rotating UA.
        async with client(timeout=45.0) as c:
            await c.get(f"{base}/search/SearchTypeDocType")  # session cookie
            cur = today
            first = True
            while cur > earliest and len(out) < max_docs:
                if not first:
                    await asyncio.sleep(1.0)  # extra spacing between date windows
                first = False
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
                    out.append(_row_to_doc(row, state, county, base))
                    if len(out) >= max_docs:
                        break
                cur = chunk_from - timedelta(days=1)
    except Exception:
        log.warning("acclaim.discover_failed", state=state, county=county)
        return out
    log.info("acclaim.discovered", county=county, scanned=scanned, distress=len(out))
    return out


# ---------------------------------------------------------------------------
# Cloudflare-walled AcclaimWeb deployments (e.g. Clarendon County SC) — same
# vendor, same free/no-login search+document API as discover_recent_nods
# above, but the edge itself (not the AcclaimWeb app) blocks plain httpx/
# curl-cffi with a real managed-challenge/Turnstile 403 on the search POSTs
# (a bare GET of the landing page passes fine; it is the POST that is
# gated). Live-verified 2026-10-14: nodriver (wall_bypass/browser_utils'
# existing Cloudflare tier), retried in HEADED mode, clears the challenge;
# once cleared, the exact same search/GridResults + Image/
# DocumentPdfAllPages/{TransactionItemId} calls this module makes over httpx
# work identically when issued as in-page `fetch()` calls from that same
# browser tab (cookies ride along automatically) -- confirmed against 4 live
# distress documents (LIEN/MTG, MECH LIEN/MTG) + 2 controls, all 200
# application/pdf with correct %PDF-1.4 bytes.
#
# The caller (a scraper that already owns a Cloudflare-cleared nodriver tab)
# passes it in here; this module never starts a browser itself.
async def _search_chunk_via_tab(tab, base: str, frm: datetime, to: datetime) -> list[dict]:
    """Same as _search_chunk, but issued as in-page fetch() calls on an
    already-Cloudflare-cleared nodriver tab instead of an httpx client."""
    import json as _json

    js = """
    (async () => {
        const p1 = new URLSearchParams({
            DocTypes: 'all', 'DocTypesDisplay-input': 'All', DocTypesDisplay: '',
            DateRangeList: ' ', RecordDateFrom: %r,
            DefaultFromDate: '1/1/1828', RecordDateTo: %r, btnSearch: 'Search'
        });
        const r1 = await fetch(%r, {
            method: 'POST', credentials: 'same-origin',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: p1.toString(),
        });
        const t1 = await r1.text();
        if (t1.includes('ShowError') || t1.toLowerCase().includes('exceeded')) {
            return JSON.stringify({over_cap: true});
        }
        const p2 = new URLSearchParams({page: '1', size: '2000', pageSize: '2000'});
        const r2 = await fetch(%r, {
            method: 'POST', credentials: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest',
                      'Content-Type': 'application/x-www-form-urlencoded'},
            body: p2.toString(),
        });
        const t2 = await r2.text();
        return JSON.stringify({status: r2.status, body: t2});
    })()
    """ % (_fmt(frm), _fmt(to),
           f"{base}/search/SearchTypeDocType?Length=6",
           f"{base}/Search/GridResults")

    try:
        result = await tab.evaluate(js, await_promise=True, return_by_value=True)
        outer = _json.loads(result)
    except Exception as exc:
        log.warning("acclaim.tab_search_failed", error=f"{type(exc).__name__}: {exc}"[:160])
        return []
    if outer.get("over_cap"):
        log.warning("acclaim.window_over_cap", frm=_fmt(frm), to=_fmt(to))
        return []
    if outer.get("status") != 200:
        return []
    try:
        return _json.loads(outer["body"]).get("data") or []
    except (ValueError, KeyError):
        return []


async def discover_recent_nods_via_browser(
    tab, state: str, county: str, base: str,
    days_back: int = 45, max_docs: int = 400,
) -> list[RodDoc]:
    """Same sweep as discover_recent_nods, for a Cloudflare-walled AcclaimWeb
    deployment -- driven over an already-Cloudflare-cleared nodriver `tab`
    instead of a bare httpx client. See the module-level note above this
    function for the live-verification evidence."""
    today = datetime.utcnow()
    earliest = today - timedelta(days=max(1, days_back))
    out: list[RodDoc] = []
    seen: set[str] = set()
    scanned = 0
    cur = today
    first = True
    while cur > earliest and len(out) < max_docs:
        if not first:
            await asyncio.sleep(1.0)
        first = False
        chunk_from = max(earliest, cur - timedelta(days=_CHUNK_DAYS))
        rows = await _search_chunk_via_tab(tab, base, chunk_from, cur)
        scanned += len(rows)
        for row in rows:
            if not is_distress(row.get("DocType")):
                continue
            inst = (row.get("InstrumentNumber") or "").strip()
            if inst and inst in seen:
                continue
            if inst:
                seen.add(inst)
            out.append(_row_to_doc(row, state, county, base))
            if len(out) >= max_docs:
                break
        cur = chunk_from - timedelta(days=1)
    log.info("acclaim.discovered_via_browser", county=county, scanned=scanned, distress=len(out))
    return out

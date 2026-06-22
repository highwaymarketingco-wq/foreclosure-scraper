"""Cott Systems "RecordRoom" Register-of-Deeds adapter (browserless, free).

Distinct from rod/cott.py (which handles the older cotthosting.com / Manatron
ASP.NET portals for NC Polk/Rutherford). RecordRoom is the newer
recordroom.cottsystems.com app with a DataTables JSON results endpoint. Guest
access to the INDEX is fully open (document images are pay-per-view, but we only
need index metadata). Returns party NAMES + doc type + book/page — actionable
leads like the Pickens/Acclaim path. SC is judicial, so ROD distress here is
PROBATE (deed of distribution / death) + LIENS. Reusable for any RecordRoom
county via COTT_RR_COUNTIES.

Flow (verified live), through the shared cookie-persisting client:
  1. GET  /{slug}/guest/Search/records      -> .ASPXANONYMOUS + session cookies
  2. POST /{slug}/search/Records (form FromDate/ThruDate/Type=""/Page=1)
        -> 302 PRG; stores the search server-side in session
  3. POST /{slug}/Search/Records/Result/ (JSON DataTables payload; the columns
        array is REQUIRED) -> {recordsTotal, data:[{Type, PartyOne, PartyTwo,
        RecordingDate, Property, FileNumber, BookPage}, ...]}; paginate via start.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import structlog

from ..http_client import client
from .models import RodDoc

log = structlog.get_logger()

COTT_RR_HOST = "https://recordroom.cottsystems.com"
COTT_RR_COUNTIES: dict[tuple[str, str], str] = {
    ("SC", "Union"): "unionsc",
}

# Distress KindCodes (probate + liens). Matched as substrings; resolutions out.
_DISTRESS = ("DOD", "DEED OF DIST", "DEATH", "DIS STMT", "DISTRIB",
             "TAX LIEN", "LIEN", "MECH", "JUDG", "EXECUTION")
_RESOLVED = ("SAT", "REL", "TERM", "CANCEL", "RESC", "SUBORD", "WITHDRAW")

# DataTables column order the endpoint requires (3 render-only cols + fields).
_COLS = ["", "", "", "ScanPages", "RecordingDate", "Type",
         "PartyOne", "PartyTwo", "Property", "FileNumber", "BookPage"]
_DATE_RE = re.compile(r"/Date\((\d+)")


def _clean(v) -> str:
    """RecordRoom returns HTML-formatted cells (<div>, <br/>); strip to text."""
    import html as _html
    s = re.sub(r"<[^>]+>", " ", str(v or ""))
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def is_distress(doc_type: str | None) -> bool:
    s = _clean(doc_type).upper()
    return any(k in s for k in _DISTRESS) and not any(k in s for k in _RESOLVED)


def _parse_date(v) -> datetime | None:
    if not v:
        return None
    m = _DATE_RE.search(str(v))
    if m:
        try:
            return datetime.utcfromtimestamp(int(m.group(1)) / 1000)
        except (ValueError, OverflowError):
            return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v)[:10], fmt)
        except ValueError:
            continue
    return None


def _columns() -> list[dict]:
    return [{"data": d, "name": "", "searchable": True, "orderable": True,
             "search": {"value": "", "regex": False}} for d in _COLS]


async def discover_recent_nods(state: str, county: str, days_back: int = 45,
                               max_docs: int = 600) -> list[RodDoc]:
    slug = COTT_RR_COUNTIES.get((state, county))
    if not slug:
        return []
    today = datetime.utcnow()
    frm = today - timedelta(days=max(1, days_back))
    fmt = lambda d: f"{d.month}/{d.day}/{d.year}"  # noqa: E731
    base = f"{COTT_RR_HOST}/{slug}"
    out: list[RodDoc] = []
    seen: set[str] = set()
    try:
        async with client(timeout=60.0) as c:
            await c.get(f"{base}/guest/Search/records")
            await c.post(f"{base}/search/Records",
                         data={"FromDate": fmt(frm), "ThruDate": fmt(today), "Type": "", "Page": "1"},
                         headers={"X-Requested-With": "XMLHttpRequest"})
            for start in range(0, max_docs, 100):
                payload = {"draw": 1, "columns": _columns(),
                           "order": [{"column": 4, "dir": "asc"}],
                           "start": start, "length": 100,
                           "search": {"value": "", "regex": False}, "Filters": []}
                r = await c.post(f"{base}/Search/Records/Result/", json=payload,
                                 headers={"X-Requested-With": "XMLHttpRequest"})
                if r.status_code != 200:
                    break
                try:
                    rows = (r.json() or {}).get("data") or []
                except Exception:
                    break
                if not rows:
                    break
                for row in rows:
                    if not is_distress(row.get("Type")):
                        continue
                    inst = _clean(row.get("FileNumber"))
                    bp = _clean(row.get("BookPage"))
                    bm = re.findall(r"\d+", bp)
                    key = inst or bp
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    out.append(RodDoc(
                        county=county, state=state,
                        doc_type=_clean(row.get("Type")),
                        recorded_date=_parse_date(row.get("RecordingDate")),
                        book=bm[0] if bm else None, page=bm[1] if len(bm) > 1 else None,
                        grantor=_clean(row.get("PartyOne")) or None,
                        grantee=_clean(row.get("PartyTwo")) or None,
                        instrument_no=inst or None,
                        notes=_clean(row.get("Property")) or None,
                        raw={"cott_recordroom": {"type": _clean(row.get("Type"))}},
                    ))
                if len(rows) < 100:
                    break
    except Exception:
        log.warning("cott_rr.discover_failed", state=state, county=county)
        return []
    log.info("cott_rr.discovered", county=county, distress=len(out))
    return out[:max_docs]

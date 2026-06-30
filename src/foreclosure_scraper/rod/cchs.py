"""Courthouse Computer Systems (CCHS) — Burke + Cleveland NC Register of Deeds.

The legacy flat `searchonline.asp` endpoint is dead (404 sitewide). The live
app is a classic-ASP search service:
  1. session bootstrap: GET /{root}/  -> /{App}/application.asp -> /{App}/realestatesearch.asp
  2. GET /{App}/SearchService.asp?cmd=search&...instrumenttypes=FCL,LIS/P...  -> <recordcount>
  3. GET /{App}/SearchService.asp?cmd=getall&start=0&offset=N  -> <r>..</r> XML rows

Each <r> carries: da (recorded date), ki (instrument type), bk/pg (book/page),
dn (doc#), or+or1 (grantor=owner), ee+ee1 (grantee=lender), mo (money/excise),
pk (parcel). Free, plain httpx, no render. (Lincoln is a different ASP.NET-MVC
CCHS install — not handled here; returns [] gracefully.)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

from dateutil import parser as dateparser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

# (state, county) -> (host, app_slug, root_slug). Burke + Cleveland share the
# us5 classic-ASP install. Lincoln (us4 LincolnNC2, ASP.NET-MVC) is intentionally
# omitted — its flow differs; the dispatcher tolerates the miss.
CCHS_COUNTIES = {
    ("NC", "Burke"): ("us5", "BurkeNCNW", "burkenc"),
    ("NC", "Cleveland"): ("us5", "ClevelandNCNW", "clevelandnc"),
    ("NC", "Madison"): ("us4", "MadisonNCNW", "madisonnc"),
    ("NC", "Henderson"): ("us4", "HendersonNCNW", "hendersonnc"),
}

_NOD_TYPES = "FCL,LIS/P,FORECLOSURE,LIS PENDEN"
_SOLD_TYPES = "COM/D,FORECLOSURE DEED,SUBTRUSTEE DEED,TRUSTEE"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126"}

NOD_KEYWORDS = ("FORECLOS", "LIS PENDEN", "LIS/P", "FCL", "NOTICE OF SALE", "NOS", "NOD")
POST_SALE_KEYWORDS = ("TRUSTEE", "COMMISSIONER", "COM/D", "FORECLOSURE DEED", "POWER OF SALE")
_MONEY_RE = re.compile(r"([\d,]+(?:\.\d{2})?)")


def _is_nod(doc_type: str | None, ki: str = "") -> bool:
    s = (str(ki or "") + " " + str(doc_type or "")).upper()
    return any(k in s for k in NOD_KEYWORDS)


def _is_post_sale(doc_type: str | None, ki: str = "") -> bool:
    s = (str(ki or "") + " " + str(doc_type or "")).upper()
    return any(k in s for k in POST_SALE_KEYWORDS)


def _money(s: str | None) -> float | None:
    if not s:
        return None
    m = _MONEY_RE.search(s.replace("$", ""))
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return v if 0 < v <= 50_000_000 else None


def _cdata(v: str) -> str:
    return re.sub(r"<!\[CDATA\[|\]\]>", "", v or "").strip()


def _field(rec: str, tag: str) -> str:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", rec, re.S)
    return _cdata(m.group(1)) if m else ""


def _base(host: str, app: str) -> str:
    return f"https://{host}.courthousecomputersystems.com/{app}"


def search_url(state: str, county: str) -> str | None:
    cfg = CCHS_COUNTIES.get((state, county))
    return f"{_base(cfg[0], cfg[1])}/realestatesearch.asp" if cfg else None


def _parse_rows(xml: str, state: str, county: str, *, sold: bool) -> list[RodDoc]:
    out: list[RodDoc] = []
    seen: set[tuple] = set()
    for rec in re.findall(r"<r>(.*?)</r>", xml or "", re.S):
        ki = _field(rec, "ki")
        bk, pg, dn = _field(rec, "bk"), _field(rec, "pg"), _field(rec, "dn")
        key = (bk, pg, dn)
        if key in seen:
            continue
        seen.add(key)
        try:
            recorded = dateparser.parse(_field(rec, "da")) if _field(rec, "da") else None
        except (ValueError, TypeError, OverflowError):
            recorded = None
        grantor = f"{_field(rec, 'or')} {_field(rec, 'or1')}".strip() or None
        grantee = f"{_field(rec, 'ee')} {_field(rec, 'ee1')}".strip() or None
        doc = RodDoc(
            county=county, state=state, doc_type=normalize_doc_type(ki),
            recorded_date=recorded, book=bk or None, page=pg or None,
            instrument_no=dn or None, grantor=grantor, grantee=grantee,
            parcel_id=_field(rec, "pk") or None, notes=_field(rec, "de") or ki or None,
            raw={"ki": ki, "cchs": True},
        )
        if sold:
            # NC excise stamp = $1 per $500 of consideration; <mo> carries the stamp.
            stamp = _money(_field(rec, "mo"))
            if stamp:
                doc.excise_tax_stamp = stamp
                doc.consideration_amount = round(stamp * 500, 2)
        out.append(doc)
    return out


async def _cchs_fetch(state: str, county: str, instrument_types: str, from_date: datetime,
                      today: datetime, max_docs: int, *, sold: bool) -> list[RodDoc]:
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg:
        return []
    host, app, root = cfg
    base = _base(host, app)
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/realestatesearch.asp"}
    try:
        async with client(timeout=40.0, headers=_UA) as c:
            # 1) session bootstrap (cookies persist on the client)
            for u in (f"https://{host}.courthousecomputersystems.com/{root}/",
                      f"{base}/application.asp?resize=true", f"{base}/realestatesearch.asp"):
                await c.get(u, follow_redirects=True)
            # 2) search
            q = {"cmd": "search", "last": "", "given": "", "searchtype": 3, "indextype": 3,
                 "codetype": 3, "fromdate": from_date.strftime("%m/%d/%Y"),
                 "todate": today.strftime("%m/%d/%Y"), "instrumenttypes": instrument_types,
                 "description": "", "docnumber": "", "booknumber": "", "pagenumber": "",
                 "resultstype": 1, "maxrecordcount": max_docs, "sortorder": 1,
                 "sortfield": "docno", "rangetype": "doc"}
            r = await c.get(f"{base}/SearchService.asp?{urlencode(q)}", headers=xhr)
            m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
            count = int(m.group(1)) if m else 0
            if count <= 0:
                return []
            # 3) getall
            r2 = await c.get(f"{base}/SearchService.asp?cmd=getall&start=0&offset={min(count, max_docs)}",
                             headers=xhr)
            return _parse_rows(r2.text, state, county, sold=sold)
    except Exception:
        return []


async def discover_recent_nods(state: str, county: str, days_back: int = 60,
                               max_docs: int = 200) -> list[RodDoc]:
    """Recent NOD / lis-pendens / foreclosure recordings (pre-foreclosure leads)."""
    today = datetime.now()
    docs = await _cchs_fetch(state, county, _NOD_TYPES, today - timedelta(days=max(1, days_back)),
                             today, max_docs, sold=False)
    out = [d for d in docs if _is_nod(d.doc_type, d.raw.get("ki", ""))]
    return out[:max_docs]


async def discover_recent_sold_recordings(state: str, county: str, days_back: int = 90,
                                          max_docs: int = 200) -> list[RodDoc]:
    """Recent post-sale recordings (commissioner's / trustee's deed upon sale)."""
    today = datetime.now()
    docs = await _cchs_fetch(state, county, _SOLD_TYPES, today - timedelta(days=max(1, days_back)),
                             today, max_docs, sold=True)
    out = [d for d in docs if _is_post_sale(d.doc_type, d.raw.get("ki", ""))]
    return out[:max_docs]


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """All recorded docs for a grantor/grantee name (lien-stack / payoff tracing)."""
    cfg = CCHS_COUNTIES.get((state, county))
    if not cfg or not name:
        return []
    host, app, root = cfg
    base = _base(host, app)
    xhr = {**_UA, "X-Requested-With": "XMLHttpRequest", "Referer": f"{base}/realestatesearch.asp"}
    last = name.strip().split()[0] if name.strip() else ""
    try:
        async with client(timeout=40.0, headers=_UA) as c:
            for u in (f"https://{host}.courthousecomputersystems.com/{root}/",
                      f"{base}/application.asp?resize=true", f"{base}/realestatesearch.asp"):
                await c.get(u, follow_redirects=True)
            q = {"cmd": "search", "last": last, "given": "", "searchtype": 1, "indextype": 1,
                 "codetype": 0, "fromdate": "", "todate": "", "instrumenttypes": "",
                 "resultstype": 1, "maxrecordcount": max_docs, "sortorder": 1,
                 "sortfield": "docno", "rangetype": "name"}
            r = await c.get(f"{base}/SearchService.asp?{urlencode(q)}", headers=xhr)
            m = re.search(r"<recordcount>(\d+)</recordcount>", r.text, re.I)
            count = int(m.group(1)) if m else 0
            if count <= 0:
                return []
            r2 = await c.get(f"{base}/SearchService.asp?cmd=getall&start=0&offset={min(count, max_docs)}",
                             headers=xhr)
            return _parse_rows(r2.text, state, county, sold=False)[:max_docs]
    except Exception:
        return []

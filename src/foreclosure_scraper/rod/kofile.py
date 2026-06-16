"""Kofile PublicSearch — Oconee SC (only).

Greenville + Greenwood dropped per scope narrowing 2026-05.

Web app with bot-protected backend. Free read but blocks raw curl. We hit the
internal API endpoint with a real-browser-style request; if blocked, the
caller falls back to the free stealth-browser renderer (render.fetch_rendered).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Iterable

from dateutil import parser as dateparser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

KOFILE_COUNTIES = {
    ("SC", "Oconee"): "oconee.sc.publicsearch.us",
}

# Kofile-side document type tokens we care about. Their API accepts a comma
# or pipe joined list under `docTypes` — we send them all and let the server
# filter, then post-filter for safety.
KOFILE_NOD_DOC_TYPES = (
    "NOTICE OF FORECLOSURE SALE",
    "NOTICE OF SALE",
    "NOTICE OF DEFAULT",
    "LIS PENDENS",
    "FORECLOSURE",
    "NOS",
    "NOD",
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


def _is_nod(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in NOD_KEYWORDS)


def _result_to_rod(r: dict, county: str, state: str) -> RodDoc | None:
    rec = r.get("recordedDate") or r.get("recordDate")
    try:
        recorded = dateparser.parse(rec) if rec else None
    except (ValueError, TypeError):
        recorded = None
    return RodDoc(
        county=county,
        state=state,
        doc_type=normalize_doc_type(r.get("docType") or r.get("instrumentType")),
        recorded_date=recorded,
        book=str(r.get("book") or "") or None,
        page=str(r.get("page") or "") or None,
        grantor=(r.get("grantor") or "")[:200] or None,
        grantee=(r.get("grantee") or "")[:200] or None,
        instrument_no=r.get("instrumentNumber") or None,
        raw=r,
    )


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    if (state, county) not in KOFILE_COUNTIES:
        return []
    host = KOFILE_COUNTIES[(state, county)]

    # Try direct API. Kofile's search endpoint is /api/search?q=...
    api_url = f"https://{host}/api/search"
    params = {"searchValue": name, "searchType": "name"}

    try:
        async with client(timeout=20.0) as c:
            r = await c.get(
                api_url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Referer": f"https://{host}/",
                },
            )
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                data = r.json()
            else:
                # Bot-blocked. Fall back to the free stealth-browser renderer.
                from ..render import fetch_rendered

                rendered = await fetch_rendered(
                    f"https://{host}/?searchType=name&searchValue={name.replace(' ', '+')}",
                )
                if not rendered:
                    return []
                # Minimal parse: extract any visible date+book/page lines
                # (Kofile-rendered text varies; production quality requires per-county tuning)
                return _scrape_rendered(rendered, county, state, max_docs)
    except Exception:
        return []

    out: list[RodDoc] = []
    for r in (data.get("results") or [])[:max_docs]:
        rec = r.get("recordedDate")
        try:
            recorded = dateparser.parse(rec) if rec else None
        except (ValueError, TypeError):
            recorded = None
        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(r.get("docType") or r.get("instrumentType")),
                recorded_date=recorded,
                book=str(r.get("book") or ""),
                page=str(r.get("page") or ""),
                grantor=(r.get("grantor") or "")[:200] or None,
                grantee=(r.get("grantee") or "")[:200] or None,
                instrument_no=r.get("instrumentNumber") or None,
                raw=r,
            )
        )
    return out


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep recent Kofile recordings for NOD-style document types.

    Kofile's PublicSearch frontend hits an internal /api/search backend that
    accepts:
      - searchType=docType
      - docTypes=<comma-joined>
      - fromDate / toDate (MM/DD/YYYY)

    Bot protection is strict; if we get a non-JSON response we degrade to []
    rather than burning Apify quota on a discovery sweep.
    """
    if (state, county) not in KOFILE_COUNTIES:
        return []
    host = KOFILE_COUNTIES[(state, county)]
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    api_url = f"https://{host}/api/search"
    params = {
        "searchType": "docType",
        "docTypes": ",".join(KOFILE_NOD_DOC_TYPES),
        "fromDate": from_date.strftime("%m/%d/%Y"),
        "toDate": today.strftime("%m/%d/%Y"),
        "limit": str(max_docs),
    }

    try:
        async with client(timeout=20.0) as c:
            r = await c.get(
                api_url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Referer": f"https://{host}/",
                },
            )
            if r.status_code != 200:
                return []
            ctype = r.headers.get("content-type", "")
            if not ctype.startswith("application/json"):
                return []
            try:
                data = r.json()
            except (json.JSONDecodeError, ValueError):
                return []
    except Exception:
        return []

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for raw in (data.get("results") or [])[: max_docs * 3]:
        d = _result_to_rod(raw, county, state)
        if d is None:
            continue
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


def _scrape_rendered(text: str, county: str, state: str, max_docs: int) -> list[RodDoc]:
    """Last-resort parse of rag-web-browser output."""
    import re
    out: list[RodDoc] = []
    for m in re.finditer(
        r"(\d{1,2}/\d{1,2}/\d{2,4})\s+([A-Z]{2,12})\s+(?:BK|Book)\s*(\d{2,5})[^\d]+(?:PG|Page)\s*(\d{1,5})",
        text,
        re.I,
    ):
        try:
            recorded = dateparser.parse(m.group(1))
        except (ValueError, TypeError):
            continue
        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(m.group(2)),
                recorded_date=recorded,
                book=m.group(3),
                page=m.group(4),
            )
        )
        if len(out) >= max_docs:
            break
    return out

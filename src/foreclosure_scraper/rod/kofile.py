"""Kofile PublicSearch — Oconee SC (only).

Greenville + Greenwood dropped per scope narrowing 2026-05.

Web app with bot-protected backend. Free read but blocks raw curl. We hit the
internal API endpoint with a real-browser-style request; if blocked, the
caller can fall back to Apify rag-web-browser (requires APIFY_TOKEN).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

KOFILE_COUNTIES = {
    ("SC", "Oconee"): "oconee.sc.publicsearch.us",
}


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
                # Bot-blocked. Fall back to Apify rag-web-browser if token available.
                token = os.environ.get("APIFY_TOKEN")
                if not token:
                    return []
                from ..apify_helper import fetch_rendered

                rendered = await fetch_rendered(
                    f"https://{host}/?searchType=name&searchValue={name.replace(' ', '+')}",
                    token=token,
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

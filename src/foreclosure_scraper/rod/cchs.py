"""Courthouse Computer Systems (CCHS) — Burke, Lincoln, Cleveland NC.

Classic ASP form GET. URL pattern:
  https://us5.courthousecomputersystems.com/{county}{state}/searchonline.asp
The form accepts grantor/grantee name params and returns an HTML table.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

CCHS_COUNTIES = {
    ("NC", "Burke"): "burkenc",
    ("NC", "Lincoln"): "lincolnnc",
    ("NC", "Cleveland"): "clevelandnc",
}


def _build_url(county_slug: str, name: str) -> str:
    base = f"https://us5.courthousecomputersystems.com/{county_slug}/searchonline.asp"
    params = {
        "nm1": name,
        "nm2": "",
        "FromDate": (datetime.utcnow().replace(year=datetime.utcnow().year - 30)).strftime("%m/%d/%Y"),
        "ThroughDate": datetime.utcnow().strftime("%m/%d/%Y"),
        "Doctype": "ALL",
    }
    return f"{base}?{urlencode(params)}"


def _parse_results(html: str, county: str, state: str) -> list[RodDoc]:
    out: list[RodDoc] = []
    tree = HTMLParser(html)
    for row in tree.css("table tr"):
        cells = [c.text(strip=True) for c in row.css("td")]
        if len(cells) < 5:
            continue
        # CCHS column layout (varies slightly by county): Date | Type | Book/Page | Grantor | Grantee | ...
        date_idx = next((i for i, c in enumerate(cells) if re.match(r"\d{1,2}/\d{1,2}/\d{2,4}", c)), None)
        if date_idx is None:
            continue
        try:
            recorded = dateparser.parse(cells[date_idx])
        except (ValueError, TypeError):
            continue
        # Doc type is usually next cell
        doc_type_raw = cells[date_idx + 1] if len(cells) > date_idx + 1 else ""
        # Book/page might be combined "BK1234/PG567"
        book = page = None
        for c in cells:
            m = re.search(r"\b(\d{2,5})\s*/\s*(\d{1,5})\b", c)
            if m:
                book, page = m.group(1), m.group(2)
                break
        # Grantor / grantee — take any cell with all-uppercase words and an ampersand or comma
        grantor = grantee = None
        name_cells = [c for c in cells if re.search(r"^[A-Z]{2,}", c) and len(c) > 6]
        if len(name_cells) >= 1:
            grantor = name_cells[0][:200]
        if len(name_cells) >= 2:
            grantee = name_cells[1][:200]

        out.append(
            RodDoc(
                county=county,
                state=state,
                doc_type=normalize_doc_type(doc_type_raw),
                recorded_date=recorded,
                book=book,
                page=page,
                grantor=grantor,
                grantee=grantee,
                raw={"row": " | ".join(cells)[:400]},
            )
        )
    return out


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Look up all recorded documents for a grantor/grantee name in a CCHS county."""
    if (state, county) not in CCHS_COUNTIES:
        return []
    slug = CCHS_COUNTIES[(state, county)]
    url = _build_url(slug, name)
    try:
        async with client(timeout=30.0) as c:
            r = await c.get(url)
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:
        return []
    return _parse_results(html, county, state)[:max_docs]

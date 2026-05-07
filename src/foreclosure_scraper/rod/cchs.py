"""Courthouse Computer Systems (CCHS) — Burke, Lincoln, Cleveland NC.

Classic ASP form GET. URL pattern:
  https://us5.courthousecomputersystems.com/{county}{state}/searchonline.asp
The form accepts grantor/grantee name params and returns an HTML table.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
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

# CCHS exposes a "Doctype" param that maps to short codes. Most installs
# accept "FOR" (foreclosure) or take the human label literally; we try a
# few candidates and merge results, then post-filter on doc_type to be safe.
NOD_DOC_TYPE_CODES = ("FOR", "NFS", "NOS", "NOD", "LP", "ALL")

# POST-sale recording codes — these are the documents that transfer
# property to the foreclosure-auction winner. CCHS short codes vary by
# install; we try common ones and post-filter on keyword.
POST_SALE_DOC_TYPE_CODES = ("TD", "STD", "FD", "TRD", "CD", "DEED", "ALL")

POST_SALE_KEYWORDS = (
    "TRUSTEE",
    "FORECLOSURE DEED",
    "COMMISSIONER",
    "POWER OF SALE",
)


def _is_post_sale(doc_type: str | None) -> bool:
    if not doc_type:
        return False
    s = doc_type.upper()
    return any(kw in s for kw in POST_SALE_KEYWORDS)


_MONEY_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _money(s: str | None) -> float | None:
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

# What we consider a "NOD-like" recorded document after parsing.
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


def _build_doctype_url(
    county_slug: str,
    doctype: str,
    from_date: datetime,
    through_date: datetime,
) -> str:
    """Recent-recordings sweep filtered by document type code."""
    base = f"https://us5.courthousecomputersystems.com/{county_slug}/searchonline.asp"
    params = {
        "nm1": "",
        "nm2": "",
        "FromDate": from_date.strftime("%m/%d/%Y"),
        "ThroughDate": through_date.strftime("%m/%d/%Y"),
        "Doctype": doctype,
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

        # CCHS sometimes shows a Consideration / Amount column with a
        # dollar value. Catch ANY $-prefixed cell — the largest is most
        # likely the consideration on a Trustee's Deed (vs incidental
        # transfer-tax amounts).
        amounts = [_money(c) for c in cells if "$" in (c or "")]
        amounts = [a for a in amounts if a is not None]
        consideration = max(amounts) if amounts else None

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
                consideration_amount=consideration,
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


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Sweep recent recordings in a CCHS county for NOD/NOS/Lis Pendens docs.

    CCHS supports a `Doctype` URL param. We try a small set of plausible
    codes (FOR / NFS / NOS / NOD / LP) and finally fall back to ALL with a
    post-hoc keyword filter, since not every county install honors the
    short codes the same way.
    """
    if (state, county) not in CCHS_COUNTIES:
        return []
    slug = CCHS_COUNTIES[(state, county)]
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    try:
        async with client(timeout=30.0) as c:
            for code in NOD_DOC_TYPE_CODES:
                url = _build_doctype_url(slug, code, from_date, today)
                try:
                    r = await c.get(url)
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                rows = _parse_results(r.text, county, state)
                for d in rows:
                    if not _is_nod(d.doc_type):
                        continue
                    if d.recorded_date and d.recorded_date < from_date:
                        continue
                    key = (d.book, d.page, (d.doc_type or "").upper())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(d)
                    if len(out) >= max_docs:
                        return out
    except Exception:
        return out
    return out[:max_docs]


async def discover_recent_sold_recordings(
    state: str,
    county: str,
    days_back: int = 90,
    max_docs: int = 100,
) -> list[RodDoc]:
    """CCHS sweep for POST-sale recordings (Trustee's Deed Upon Sale and
    equivalents). Same URL pattern as discover_recent_nods but with
    POST_SALE_DOC_TYPE_CODES + post-sale keyword filter."""
    if (state, county) not in CCHS_COUNTIES:
        return []
    slug = CCHS_COUNTIES[(state, county)]
    today = datetime.utcnow()
    from_date = today - timedelta(days=max(1, days_back))

    out: list[RodDoc] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    try:
        async with client(timeout=30.0) as c:
            for code in POST_SALE_DOC_TYPE_CODES:
                url = _build_doctype_url(slug, code, from_date, today)
                try:
                    r = await c.get(url)
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                rows = _parse_results(r.text, county, state)
                for d in rows:
                    if not _is_post_sale(d.doc_type):
                        continue
                    if d.recorded_date and d.recorded_date < from_date:
                        continue
                    if d.consideration_amount is None:
                        continue
                    key = (d.book, d.page, (d.doc_type or "").upper())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(d)
                    if len(out) >= max_docs:
                        return out
    except Exception:
        return out
    return out[:max_docs]

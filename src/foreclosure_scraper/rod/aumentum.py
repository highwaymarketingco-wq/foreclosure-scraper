"""Aumentum / Manatron LandRecords — Mecklenburg, Buncombe, Gaston NC.

ASP.NET WebForms with __VIEWSTATE. URL pattern:
  https://{rod-host}/External/LandRecords/protected/v4/SrchName.aspx
The form must POST __VIEWSTATE + __EVENTVALIDATION + name fields.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ..http_client import client
from .models import RodDoc, normalize_doc_type

AUMENTUM_COUNTIES = {
    ("NC", "Mecklenburg"): "https://meckrod.manatron.com/External/LandRecords/protected/v4",
    ("NC", "Buncombe"): "https://registerofdeeds.buncombecounty.org/External/LandRecords/protected/v4",
    ("NC", "Gaston"): "https://deeds.gastongov.com/external/LandRecords/protected/v4",
}


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
            )
        )
    return out


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    """Two-stage ASP.NET fetch: GET the form to get __VIEWSTATE, POST with name."""
    if (state, county) not in AUMENTUM_COUNTIES:
        return []
    base = AUMENTUM_COUNTIES[(state, county)]
    form_url = f"{base}/SrchName.aspx"

    try:
        async with client(timeout=30.0) as c:
            # Stage 1: get the form (acquire viewstate cookies)
            r = await c.get(form_url)
            if r.status_code != 200:
                return []
            html = r.text
            viewstate = _extract_hidden(html, "__VIEWSTATE")
            generator = _extract_hidden(html, "__VIEWSTATEGENERATOR")
            event_val = _extract_hidden(html, "__EVENTVALIDATION")
            if not viewstate:
                return []

            # Stage 2: POST the form with name fields
            # Aumentum form uses ctl00$cphMain$txtLastName etc.
            # Heuristic: split "LAST FIRST" or "LAST, FIRST"
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

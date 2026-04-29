"""Cott Systems / cotthosting.com — Polk and Rutherford NC.

Same ASP.NET form pattern as Aumentum (Cott OEMs Manatron) — share the parser.
"""
from __future__ import annotations

from .aumentum import _extract_hidden, _parse_grid
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

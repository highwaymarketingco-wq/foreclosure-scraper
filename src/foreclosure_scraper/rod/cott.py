"""Cott Systems / cotthosting.com — Polk and Rutherford NC.

Same Cott eSearch v4 ASP.NET WebForms app as rod/aumentum.py (Cott OEMs/powers
Aumentum's county deployments too — Buncombe/Gaston run the identical app on a
county .gov domain). Polk/Rutherford just happen to be hosted on
cotthosting.com instead.

2026-10-02 RE-VERIFIED LIVE, REWRITTEN: this module used to carry its own
separate POST flow (real __VIEWSTATE/__EVENTVALIDATION tokens scraped from the
page, field names like `ctl00$cphMain$txtLastName`/`ctl00$cphMain$btnSearch`)
built against a generic ASP.NET WebForms template. Live-probed against Polk:
__VIEWSTATE is EMPTY/absent on this app exactly like Buncombe/Gaston (the
session lives in cookies — ASP.NET_SessionId + CottSqlAuthCookie — not
viewstate; see aumentum.py's module docstring for the full handshake), and
none of the field names this module posted actually exist on the real page —
so every POST here just re-rendered the blank search form and both
search_by_name and discover_recent_nods silently returned [] for both
counties. Confirmed the fix by calling rod.aumentum's OWN (live-verified)
protocol straight against Polk's base URL: real 2026 recordings came back
immediately. This module now delegates entirely to the `*_at()` entry points
in rod/aumentum.py instead of maintaining a second, broken copy of the same
vendor's protocol — including aumentum's October 2026 fix for the Date-Range
sweep's 30-day vendor cap + 500-row page cap (see aumentum.py's docstring),
which Polk/Rutherford share too.
"""
from __future__ import annotations

from . import aumentum
from .models import RodDoc

COTT_COUNTIES = {
    ("NC", "Polk"): "https://cotthosting.com/ncpolkexternal/LandRecords/protected/v4",
    ("NC", "Rutherford"): "https://cotthosting.com/NCRUTHERFORDEXTERNAL/LandRecords/protected/v4",
}


async def search_by_name(state: str, county: str, name: str, max_docs: int = 50) -> list[RodDoc]:
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    return await aumentum._search_by_name_at(base, county, state, name, max_docs)


async def discover_recent_nods(
    state: str,
    county: str,
    days_back: int = 60,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Cott (Cott eSearch v4) recent-recordings sweep filtered by NOD doc
    types, via rod/aumentum.py's Date-Range sweep (see that module's
    docstring for the 30-day vendor cap + 500-row page cap it now handles)."""
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    return await aumentum.discover_recent_nods_at(base, county, state, days_back, max_docs)


async def discover_recent_sold_recordings(
    state: str,
    county: str,
    days_back: int = 90,
    max_docs: int = 100,
) -> list[RodDoc]:
    """Cott (Cott eSearch v4) — post-sale recordings (Trustee's Deed Upon Sale
    and equivalents) via rod/aumentum.py's Date-Range sweep."""
    if (state, county) not in COTT_COUNTIES:
        return []
    base = COTT_COUNTIES[(state, county)]
    return await aumentum.discover_recent_sold_recordings_at(base, county, state, days_back, max_docs)

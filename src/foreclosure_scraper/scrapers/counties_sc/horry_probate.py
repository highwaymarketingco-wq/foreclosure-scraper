"""Horry County SC Probate Court estate cases (Spartan public portal, JSON).

Source
------
Horry County Probate Court's public case search runs on the Spartan Computer
Services portal:

    page   https://scportal.hostedbyspartan.com/HorryPublicProbate/pages/CaseSearchPage.aspx
    data   https://scportal.hostedbyspartan.com/HorryPublicProbate/Handlers/Data.asmx/CaseSearch

The page's own DataTables grid calls the data handler with a GET (``Content-Type:
application/json``) carrying the form fields as query parameters; the answer is
``{"d": "<json string>"}`` with ``recordsTotal`` and ``aaData`` rows. No login, no
CAPTCHA, no terms page, no robots.txt on the host (404). Estate case numbers carry
the year and agency: ``2026ES26nnnnn`` (AgencyId 26500 = "Horry Probate Estate").

Read live 2026-10-07 with one 10-row request: 3,184 estate cases filed in 2026 so
far. Full live proof the same day (9 data requests, 30 s): 4,016 estates filed in the
last 365 days (3,176 from 2026, 840 from late 2025). Row fields: WARANTNO (case number), CseFilDt (filed), PPTYNAME (primary party,
"LAST, FIRST M"), PPTYTYPE ("Deceased Person"), CseTypIn, CMSCASE/PPTYSEQ (detail
keys) and the judicial assistant's name and code (not kept). The detail page
(CaseDetailPage.aspx) has the decedent's address and representative, but reading it
would cost one request per case, so it is NOT fetched; the decedent's name and the
county go to the downstream owner-name resolver like every other probate source.

Pagination: iDisplayStart / iDisplayLength (500 per request), so a year of Horry
estates is about 7 requests. By default the current and the previous year are read
and rows filed more than HORRY_PROBATE_LOOKBACK_DAYS (365) ago are dropped.

First documented in docs/county_breadth_research_2026-09-21.md (section 4); built
2026-10-07 (docs/new_sources_2026-10-07_liens_courts.md, SC-HORRY-PROBATE).
Gate with FORECLOSURE_HORRY_PROBATE=0.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://scportal.hostedbyspartan.com/HorryPublicProbate/"
PAGE_URL = BASE + "pages/CaseSearchPage.aspx"
DATA_URL = BASE + "Handlers/Data.asmx/CaseSearch"
AGENCY_ID = "26500"
PAGE_SIZE = 500
MAX_PAGES_PER_YEAR = 20          # 10,000 rows; Horry files about 4,000 estates a year
ENV_OFF = "FORECLOSURE_HORRY_PROBATE"
LOOKBACK_ENV = "HORRY_PROBATE_LOOKBACK_DAYS"
_PAUSE_S = 1.7
_AJAX_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": PAGE_URL,
}


def search_params(year: int, start: int, length: int = PAGE_SIZE) -> dict[str, str]:
    """The query string the page's own grid sends for an estate case-number prefix."""
    return {
        "sEcho": "1", "iColumns": "5", "iDisplayStart": str(start), "iDisplayLength": str(length),
        "AgencyId": AGENCY_ID, "CaseNumber": f"{year}ES26", "CaseType": "", "ClerkCode": "",
        "LastName": "", "FirstName": "", "DispositionStatus": "",
    }


def decode(payload: Any) -> dict[str, Any]:
    """ASMX ``{"d": "<json>"}`` -> the DataTables object ({} when malformed)."""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("d")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            return {}
    return inner if isinstance(inner, dict) else {}


def _s(v: Any) -> str | None:
    s = re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    return s or None


def _filed(v: Any) -> datetime | None:
    try:
        return datetime.strptime(str(v).strip(), "%m/%d/%Y")
    except (TypeError, ValueError):
        return None


def build_listing(row: dict[str, Any], *, now: datetime) -> Listing | None:
    """One grid row -> a PROBATE_NOTICE lead, or None for a non-decedent / unnamed row."""
    case = _s(row.get("WARANTNO"))
    name = _s(row.get("PPTYNAME"))
    party_type = _s(row.get("PPTYTYPE"))
    if not case or not name:
        return None
    if party_type and "deceased" not in party_type.lower():
        return None
    filed = _filed(row.get("CseFilDt"))
    if filed and filed > now + timedelta(days=400):
        filed = None    # keying slips exist (one live row read 3025); a future date is not a date
    return Listing(
        source=HorryProbate.slug,
        source_url=PAGE_URL,
        listing_type=ListingType.PROBATE_NOTICE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county="Horry",
        case_number=case,
        owner_name=name,          # the decedent; the owner->GIS resolver finds the property
        description=f"Horry County SC estate {case} opened {filed.date().isoformat() if filed else '?'} "
                    f"for {name} (deceased)",
        first_seen=now,
        last_seen=now,
        raw={"probate": {
            "decedent": name,
            "case_number": case,
            "filing_date": filed.date().isoformat() if filed else None,
            "court": "Horry County Probate Court",
            "party_type": party_type,
            "case_type": _s(row.get("CseTypIn")),
            "detail_keys": {"agency": _s(row.get("APPCODE")), "case_id": row.get("CMSCASE"),
                            "party_seq": row.get("PPTYSEQ")},
            "source": "horry_spartan_portal",
        }},
    )


class HorryProbate(BaseScraper):
    slug = "counties_sc.horry_probate"
    name = "Horry County (SC) Probate Court estate cases (Spartan portal)"
    category = "probate"
    timeout_s = 180.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("horry_probate.disabled")
            return []
        now = datetime.utcnow()
        lookback = int(os.environ.get(LOOKBACK_ENV, "365"))
        cutoff = now - timedelta(days=lookback)
        out: list[Listing] = []
        seen: set[str] = set()
        async with client(timeout=45.0) as http:
            try:
                await http.get(PAGE_URL)       # the page the grid lives on, as a browser loads it
            except Exception as exc:  # noqa: BLE001
                log.warning("horry_probate.page_failed", error=str(exc)[:160])
                return []
            for year in (now.year, now.year - 1):
                if datetime(year, 12, 31) < cutoff:
                    continue
                start = 0
                for _ in range(MAX_PAGES_PER_YEAR):
                    await asyncio.sleep(_PAUSE_S)
                    try:
                        r = await http.get(DATA_URL, params=search_params(year, start), headers=_AJAX_HEADERS)
                        data = decode(r.json()) if r.status_code == 200 else {}
                    except Exception as exc:  # noqa: BLE001
                        log.warning("horry_probate.page_error", year=year, start=start, error=str(exc)[:160])
                        break
                    if data.get("Error"):
                        log.warning("horry_probate.server_error", year=year, error=str(data["Error"])[:160])
                        break
                    rows = data.get("aaData") or []
                    for row in rows:
                        li = build_listing(row, now=now)
                        if li is None or li.case_number in seen:
                            continue
                        filed = (li.raw["probate"].get("filing_date") or "")
                        if filed and datetime.fromisoformat(filed) < cutoff:
                            continue
                        seen.add(li.case_number)
                        out.append(li)
                    total = int(data.get("recordsFiltered") or data.get("recordsTotal") or 0)
                    start += len(rows)
                    if not rows or start >= total:
                        break
                log.info("horry_probate.year_done", year=year, kept=len(out))
        return out


if __name__ == "__main__":
    from collections import Counter

    async def _main() -> None:
        s = HorryProbate()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print("by filing month", sorted(Counter((li.raw["probate"]["filing_date"] or "?")[:7] for li in rows).items())[-6:])

    asyncio.run(_main())

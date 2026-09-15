"""FEMA Disaster Declarations — federal disaster declaration list, per
declared county.

Rewritten 2026-09-15 (national.* zero-row audit): the old target
(fema.gov/disaster/declarations, scraped as HTML) is now behind an Akamai
Bot Manager JS-challenge interstitial even with impersonate=True — a real
challenge page, not real content, confirmed live. FEMA's own OpenFEMA v2
REST API is free, unauthenticated, not Akamai-walled, and gives cleaner,
PER-COUNTY data than the HTML page ever did (the old page only had a
statewide-or-nothing granularity; every row here carries a real
`designatedArea` county).

  https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries
  ?$filter=(state eq 'NC' or state eq 'SC') and declarationDate gt '<cutoff>'

This is a distress signal for property intelligence: properties in
federally-declared disaster counties may have storm/flood/fire damage,
insurance disputes, or FEMA buyout potential — all motivated-seller
indicators. DISTRESSED, not a scheduled sale — admitted anywhere in NC/SC
per config.in_scope_distressed(), no sale_date (dateless by nature).

Free, public, no login.
Slug: national.fema_disasters
Category: national_aggregator
ListingType: DISTRESSED
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API_URL = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
# How far back to pull declarations. FEMA's archive goes back decades; a
# multi-year-old disaster is no longer a live distress signal for today's
# property intelligence.
_LOOKBACK_DAYS = 730


def _row_to_listing(row: dict) -> Listing | None:
    designated = (row.get("designatedArea") or "").strip()
    # Blank designatedArea is the only truly unusable case. Non-county
    # designations ("Statewide", tribal areas, etc.) pass through as-is --
    # "Statewide" specifically matches in_scope_distressed()'s carve-out.
    if not designated:
        return None
    county = designated.replace("(County)", "").strip() or designated

    decl_date = None
    raw_date = row.get("declarationDate")
    if raw_date:
        try:
            decl_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, TypeError):
            pass

    fema_id = row.get("femaDeclarationString")
    title = row.get("declarationTitle") or "Disaster declaration"
    incident_type = row.get("incidentType") or ""

    return Listing(
        source="national.fema_disasters",
        source_url=f"https://www.fema.gov/disaster/{row.get('disasterNumber')}" if row.get("disasterNumber") else API_URL,
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.UNKNOWN,
        state=(row.get("state") or "").upper() or None,
        county=county,
        description=f"{title} ({incident_type}) — {fema_id or ''}".strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"fema_disaster": {
            "fema_id": fema_id,
            "disaster_number": row.get("disasterNumber"),
            "declaration_type": row.get("declarationType"),
            "incident_type": incident_type,
            "declaration_date": raw_date,
            "designated_area": designated,
            "ih_program": row.get("ihProgramDeclared"),
            "ia_program": row.get("iaProgramDeclared"),
        }},
    )


class FEMADisasters(BaseScraper):
    slug = "national.fema_disasters"
    name = "FEMA Disaster Declarations (OpenFEMA API, per county)"
    category = "national_aggregator"
    timeout_s = 60.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        cutoff = (datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        params = {
            "$filter": f"(state eq 'NC' or state eq 'SC') and declarationDate gt '{cutoff}'",
            "$top": "2000",
            "$format": "json",
        }
        out: list[Listing] = []
        try:
            async with client(timeout=45.0) as c:
                r = await c.get(API_URL, params=params, timeout=45.0)
                if r.status_code != 200:
                    log.warning("fema_disasters.http_error", status=r.status_code)
                    return out
                data = r.json()
        except Exception as exc:
            log.warning("fema_disasters.fetch_fail", error=str(exc)[:160])
            return out

        rows = data.get("DisasterDeclarationsSummaries") or []
        for row in rows:
            li = _row_to_listing(row)
            if li:
                out.append(li)

        log.info("fema_disasters.done", count=len(out), api_rows=len(rows))
        return out

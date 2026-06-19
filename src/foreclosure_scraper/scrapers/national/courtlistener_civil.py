"""CourtListener federal civil-docket scraper — foreclosure / real-property cases.

CourtListener (free public mirror of PACER) has the entire federal civil
docket. Most foreclosure activity in NC + SC happens in state court, but
federal civil real-property cases catch:

  * Mortgage-fraud and quiet-title actions filed in federal court
  * RESPA / TILA violations as defendants in foreclosure
  * Federal lender (Fannie / Freddie / FDIC / HUD) plaintiff cases
  * Multi-state mortgage class actions touching NC/SC properties

Volume is much smaller than bankruptcy (most foreclosure stays in
state court) but each hit is a high-quality, specific lead.

Filter: federal courts in NC + SC + nature_of_suit codes for real
property:

  220  Foreclosure
  230  Rent Lease & Ejectment
  240  Torts to Land
  290  Other Real Property
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

# Reuse the helper functions from the bankruptcy scraper — same auth,
# same pagination, same county-from-text recovery.
from .courtlistener_bankruptcy import (
    API_BASE,
    LOOKBACK_DAYS,
    MAX_PAGES_PER_COURT,
    PAGE_SIZE,
    _county_from_text,
    _load_token,
)

log = structlog.get_logger()


# Federal District Courts covering NC + SC
CIVIL_COURTS = ("nced", "ncmd", "ncwd", "scd")

CIVIL_COURT_STATE = {"nced": "NC", "ncmd": "NC", "ncwd": "NC", "scd": "SC"}

# Nature-of-suit codes for real-property civil cases. CourtListener
# stores these as strings on the docket record.
REAL_PROPERTY_NOS = {
    "220": "Foreclosure",
    "230": "Rent Lease & Ejectment",
    "240": "Torts to Land",
    "245": "Tort Product Liability — Real Property",
    "290": "All Other Real Property",
}


def _is_real_property_case(docket: dict) -> bool:
    """Return True if the docket's nature_of_suit OR cause text matches a
    real-property pattern. Both fields are checked because CourtListener
    is inconsistent — older dockets often have nature_of_suit empty but
    a populated cause string."""
    # NOS code or NOS label
    nos = (docket.get("nature_of_suit") or "").strip()
    if nos:
        if nos in REAL_PROPERTY_NOS:
            return True
        nos_lower = nos.lower()
        if any(label.lower() in nos_lower for label in REAL_PROPERTY_NOS.values()):
            return True
    # Cause-of-action text fallback (common in older dockets / civil rights cases)
    cause = (docket.get("cause") or "").lower()
    if cause and any(kw in cause for kw in (
        "foreclos", "real property", "quiet title",
        "ejectment", "lis pendens",
    )):
        return True
    return False


async def _fetch_court_civil(c, court: str, token: str) -> list[dict]:
    """Pull recent civil dockets from one federal district court."""
    cutoff = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    out: list[dict] = []
    next_url: str | None = (
        f"{API_BASE}/dockets/?court={court}&date_filed__gte={cutoff}"
        f"&page_size={PAGE_SIZE}"
    )
    page = 0
    while next_url and page < MAX_PAGES_PER_COURT:
        try:
            r = await c.get(
                next_url,
                headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            )
            if r.status_code != 200:
                log.warning("courtlistener_civil.error",
                            court=court, status=r.status_code)
                break
            data = r.json()
            results = data.get("results") or []
            # Pre-filter to real-property cases at the page level — saves
            # the orchestrator from parsing irrelevant dockets.
            for d in results:
                if _is_real_property_case(d):
                    out.append(d)
            next_url = data.get("next")
            page += 1
        except Exception as exc:
            log.warning("courtlistener_civil.fetch_error",
                        court=court, error=str(exc)[:120])
            break
    return out


class CourtListenerCivil(BaseScraper):
    """Federal civil dockets in NC + SC filtered to real-property cases."""

    slug = "national.courtlistener_civil"
    name = "CourtListener federal civil — real property (NC + SC)"
    category = "federal_court"
    expected_min_count = 0   # Volume is small; weeks may have 0
    requires_apify = False
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        token = _load_token()
        if not token:
            log.info("courtlistener_civil.no_token")
            return []

        out: list[Listing] = []
        seen_keys: set[tuple[str, str]] = set()

        async with client(timeout=20.0) as c:
            for court in CIVIL_COURTS:
                dockets = await _fetch_court_civil(c, court, token)
                state_default = CIVIL_COURT_STATE.get(court, "NC")

                for d in dockets:
                    case_name = d.get("case_name") or ""
                    docket_no = d.get("docket_number") or ""
                    if not case_name and not docket_no:
                        continue

                    # Per-court dedup (same as the bankruptcy scraper)
                    if docket_no:
                        key = (court, docket_no.strip())
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)

                    state_match, county_match = _county_from_text(case_name)
                    state = state_match or state_default
                    county = county_match

                    nos = (d.get("nature_of_suit") or "").strip()
                    cause = (d.get("cause") or "").strip()
                    date_filed = d.get("date_filed")

                    desc = (
                        f"Federal civil real-property case ({court.upper()}) — "
                        f"NOS {nos or '?'}; filed {date_filed or '?'}"
                        + (f" — {case_name[:120]}" if case_name else "")
                    )[:500]

                    out.append(Listing(
                        source=self.slug,
                        source_url=("https://www.courtlistener.com" + d["absolute_url"]) if d.get("absolute_url") else "",
                        listing_type=ListingType.LIS_PENDENS,
                        property_kind=PropertyKind.UNKNOWN,
                        state=state,
                        county=county,
                        case_number=docket_no or None,
                        defendant=case_name[:200] or None,
                        description=desc,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"courtlistener_civil": {
                            "court": court,
                            "nature_of_suit": nos,
                            "cause": cause,
                            "case_name": case_name,
                            "date_filed": date_filed,
                            "absolute_url": d.get("absolute_url"),
                        }},
                    ))

        log.info("courtlistener_civil.done",
                 listings=len(out), courts=len(CIVIL_COURTS),
                 lookback_days=LOOKBACK_DAYS)
        return out

"""County jail booking scraper — current in-custody inmate rosters.

Queries public county jail booking systems across our NC/SC footprint and
extracts inmate name, booking date, charges, and DOB (where available).
Returns Listing objects with listing_type=UNKNOWN (these are lead-discovery
signals, not property listings — the orchestrator cross-references inmate
names against property owner records downstream).

Supported systems (all free, public, no auth):
  - CentralSquare P2C (policetocitizen.com) — Buncombe NC (modern SPA variant
    with XSRF token handshake, ~540 in custody)
  - CentralSquare P2C jqGrid — Cleveland NC (classic ASP.NET jqGrid)
  - Zuercher Portal — Cherokee SC, Anderson SC (JSON API)

Each system returns current in-custody inmates. We extract:
  - Inmate name (last, first)
  - DOB (if exposed — Buncombe redacts, Cleveland/Cherokee expose it)
  - Booking/arrest date
  - Primary charge description

The scraper follows the BaseScraper pattern with async fetch() returning
Iterable[Listing]. Uses curl_cffi (chrome impersonation) for systems that
fingerprint-block plain httpx, and the shared http_client for rate limiting.

Robots.txt: These are public-records APIs, not crawlable web pages. The
endpoints are the same JSON XHRs the public search UIs use. We check
robots.txt on the host anyway and fail-closed if disallowed.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urljoin

import httpx
import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# County roster configurations
# ---------------------------------------------------------------------------
# (state, county, vendor, target)
# vendor: "p2c_centralsquare" | "p2c_jqgrid" | "zuercher"
# target: Zuercher subdomain, P2C base URL, or "host|listId" for modern P2C

ROSTERS: list[tuple[str, str, str, str]] = [
    # Buncombe NC — CentralSquare P2C modern (policetocitizen.com SPA)
    # Verified live 2026-07-01: 542 in custody. XSRF token handshake.
    ("NC", "Buncombe", "p2c_centralsquare",
     "https://buncombecountyso.policetocitizen.com|23"),

    # Cleveland NC — CentralSquare P2C jqGrid (classic ASP.NET)
    # Verified live: jqGrid JSON endpoint at /jqHandler.ashx?op=s
    ("NC", "Cleveland", "p2c_jqgrid", "http://74.218.167.200/p2c"),

    # Cherokee SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Cherokee", "zuercher", "cherokee-so-sc"),

    # Anderson SC — Zuercher Portal
    # Verified live: JSON API at /api/portal/inmates/load
    ("SC", "Anderson", "zuercher", "anderson-so-sc"),
]

# ---------------------------------------------------------------------------
# Name parsing helpers
# ---------------------------------------------------------------------------

def _norm_alpha(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _split_comma_name(name: str) -> tuple[str, str] | None:
    """'Smith, John Michael' -> ('SMITH', 'JOHN')."""
    if not name or "," not in name:
        return None
    last, _, rest = name.partition(",")
    toks = rest.strip().split()
    if not toks or not last.strip():
        return None
    return last.strip().upper(), toks[0].strip().upper()


def _parse_date(s: str | None) -> datetime | None:
    """Parse common date formats from jail rosters."""
    if not s:
        return None
    s = str(s).strip()
    # ISO format (Zuercher/ArrestDate)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 5], fmt) if "T" in fmt else datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    # US format
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Vendor fetchers — each returns a list of inmate dicts
# ---------------------------------------------------------------------------

async def _fetch_zuercher(subdomain: str) -> list[dict]:
    """Fetch current in-custody roster from a Zuercher Portal instance.

    API: POST https://{subdomain}.zuercherportal.com/api/portal/inmates/load
    Returns JSON with 'records' array. Each record has name, dob, charges,
    arrest_date.
    """
    from curl_cffi.requests import AsyncSession

    url = f"https://{subdomain}.zuercherportal.com/api/portal/inmates/load"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "name": "", "race": "all", "sex": "all", "cell_block": "all",
        "held_for_agency": "any", "in_custody": now,
        "paging": {"count": 2000, "start": 0},
        "sorting": {"sort_by_column_tag": "name", "sort_descending": False},
    }
    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.post(url, json=body, timeout=30)
            recs = (r.json() or {}).get("records") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.zuercher_fail", subdomain=subdomain,
                    error=str(exc)[:120])
        return []

    for rec in recs:
        parts = _split_comma_name(rec.get("name") or "")
        if not parts:
            continue
        last, first = parts
        charges = rec.get("hold_reasons") or rec.get("charges") or ""
        if isinstance(charges, list):
            charges = "; ".join(str(x) for x in charges)[:300]
        out.append({
            "last": last, "first": first,
            "dob": rec.get("dob"),
            "arrest_date": rec.get("arrest_date"),
            "charge": str(charges)[:300],
        })
    log.info("jail_scraper.zuercher_ok", subdomain=subdomain, count=len(out))
    return out


async def _fetch_p2c_jqgrid(base: str) -> list[dict]:
    """Fetch current in-custody roster from a CentralSquare P2C jqGrid system.

    Handshake: GET /jailinmates.aspx to seed session cookie, then POST to
    /jqHandler.ashx?op=s with jqGrid parameters. Returns JSON with 'rows'
    array.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(f"{base}/jailinmates.aspx", timeout=20)
            r = await s.post(
                f"{base}/jqHandler.ashx?op=s",
                data={
                    "t": "ii", "_search": "false", "rows": "2000",
                    "page": "1", "sidx": "disp_name", "sord": "asc",
                },
                timeout=30,
            )
            rows = (r.json() or {}).get("rows") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_jqgrid_fail", base=base,
                    error=str(exc)[:120])
        return []

    for rw in rows:
        last = (rw.get("lastname") or "").strip().upper()
        first = (rw.get("firstname") or "").strip().upper()
        if not last or not first:
            continue
        out.append({
            "last": last, "first": first,
            "dob": rw.get("dob"),
            "arrest_date": rw.get("disp_arrest_date"),
            "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:300],
        })
    log.info("jail_scraper.p2c_jqgrid_ok", base=base, count=len(out))
    return out


async def _fetch_p2c_centralsquare(target: str) -> list[dict]:
    """Fetch current in-custody roster from modern CentralSquare P2C (policetocitizen.com).

    Handshake: GET an app route (/en/Inmates) to obtain the XSRF-TOKEN
    cookie, then echo it as X-XSRF-TOKEN header on the JSON search POST to
    /api/Inmates/<listId>. Page in blocks of 200 until a short page.
    DOB is redacted on the public feed; Age + ArrestDate survive.
    """
    from curl_cffi.requests import AsyncSession

    host, _, list_id = target.partition("|")
    list_id = list_id or "23"
    api = f"{host}/api/Inmates/{list_id}"
    page_size = 200
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            # 1) Establish XSRF-TOKEN cookie via app-route GET
            await s.get(f"{host}/en/Inmates", timeout=25)
            token = s.cookies.get("XSRF-TOKEN")
            if not token:
                log.warning("jail_scraper.p2c_cs_no_token", host=host)
                return []
            hdr = {
                "X-XSRF-TOKEN": token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Referer": f"{host}/en/Inmates",
                "Origin": host,
            }
            skip = 0
            while True:
                body = {
                    "FilterOptionsParameters": {
                        "IntersectionSearch": True, "SearchText": "",
                        "Parameters": [],
                    },
                    "IncludeCount": True,
                    "PagingOptions": {
                        "SortOptions": [{
                            "Name": "ArrestDate",
                            "SortDirection": "Descending",
                            "Sequence": 1,
                        }],
                        "Take": page_size, "Skip": skip,
                    },
                }
                r = await s.post(api, headers=hdr, json=body, timeout=60)
                recs = (r.json() or {}).get("Inmates") or []
                if not recs:
                    break
                for rec in recs:
                    last = (rec.get("LastName") or "").strip().upper()
                    first = (rec.get("FirstName") or "").strip().upper()
                    if not last or not first:
                        continue
                    out.append({
                        "last": last, "first": first,
                        "dob": rec.get("DateOfBirth"),
                        "age": rec.get("Age"),
                        "arrest_date": rec.get("ArrestDate"),
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:300],
                    })
                if len(recs) < page_size:
                    break
                skip += page_size
                if skip > 5000:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.p2c_cs_fail", host=host,
                    error=str(exc)[:120])
        return []

    log.info("jail_scraper.p2c_cs_ok", host=host, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Vendor dispatcher
# ---------------------------------------------------------------------------

async def _fetch_roster(state: str, county: str, vendor: str, target: str) -> list[dict]:
    """Dispatch to the correct vendor fetcher."""
    try:
        if vendor == "zuercher":
            return await _fetch_zuercher(target)
        elif vendor == "p2c_jqgrid":
            return await _fetch_p2c_jqgrid(target)
        elif vendor == "p2c_centralsquare":
            return await _fetch_p2c_centralsquare(target)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.fetch_error", county=county, vendor=vendor,
                    error=str(exc)[:160])
    return []


# ---------------------------------------------------------------------------
# Listing builder
# ---------------------------------------------------------------------------

def _to_listing(rec: dict, state: str, county: str) -> Listing:
    """Convert an inmate record to a Listing object."""
    last = rec.get("last", "")
    first = rec.get("first", "")
    full_name = f"{last}, {first}" if last and first else (last or first)

    booking_date = _parse_date(rec.get("arrest_date"))

    # Build a source URL — link to the county's public search page
    if state == "NC" and county == "Buncombe":
        source_url = "https://buncombecountyso.policetocitizen.com/en/Inmates"
    elif state == "NC" and county == "Cleveland":
        source_url = "http://74.218.167.200/p2c/jailinmates.aspx"
    elif state == "SC" and county == "Cherokee":
        source_url = "https://cherokee-so-sc.zuercherportal.com/"
    elif state == "SC" and county == "Anderson":
        source_url = "https://anderson-so-sc.zuercherportal.com/"
    else:
        source_url = ""

    charge = rec.get("charge") or ""

    return Listing(
        source="national.jail_bookings",
        source_url=source_url,
        listing_type=ListingType.UNKNOWN,
        property_kind=PropertyKind.UNKNOWN,
        defendant=full_name,
        county=county,
        state=state,
        sale_date=booking_date,  # re-purposed as booking date
        description=charge or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "jail_booking": {
                "county": county,
                "state": state,
                "inmate_name": full_name,
                "last_name": last,
                "first_name": first,
                "dob": rec.get("dob"),
                "age": rec.get("age"),
                "booking_date": booking_date.isoformat() if booking_date else None,
                "charge": charge,
                "vendor": "jail_bookings_scraper",
            },
        },
    )


# ---------------------------------------------------------------------------
# Scraper class
# ---------------------------------------------------------------------------

class JailBookingsScraper(BaseScraper):
    """Scrape current in-custody jail rosters across NC/SC counties.

    Returns Listing objects with listing_type=UNKNOWN — these are name-only
    lead signals for cross-referencing against property owner records.
    """

    slug = "national.jail_bookings"
    name = "County Jail Bookings (NC/SC)"
    category = "jail_bookings"
    expected_min_count = 0
    timeout_s = 120.0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []

        # Fetch all rosters concurrently
        tasks = [
            _fetch_roster(state, county, vendor, target)
            for state, county, vendor, target in ROSTERS
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for (state, county, vendor, target), inmates in zip(ROSTERS, results):
            if isinstance(inmates, Exception):
                log.warning("jail_scraper.county_error",
                            county=county, error=str(inmates)[:160])
                continue
            if not inmates:
                continue
            for rec in inmates:
                out.append(_to_listing(rec, state, county))

        log.info("jail_scraper.done", total=len(out),
                 counties=sum(1 for r in results if isinstance(r, list) and r))
        return out

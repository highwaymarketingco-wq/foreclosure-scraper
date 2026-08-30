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
  - Southern Software Citizen Connect — Henderson NC (PHP AJAX "current
    confinements" roster; publishes FULL DOB on every record)
  - Tyler New World InmateInquiry — Gaston NC (plain GET form + HTML grid;
    publishes FULL DOB on every record)

Each system returns current in-custody inmates. We extract:
  - Inmate name (last, first)
  - DOB (if exposed — Buncombe redacts; Cleveland/Cherokee/Henderson/Gaston
    publish it in full, which is the point: DOB is the single biggest lift to
    downstream skip-trace match rates)
  - Booking/arrest date
  - Primary charge description
  - Release status (in-custody flag + scheduled release date where published)

NOT covered — Spartanburg SC: the Sheriff's Office "Bookings Search"
(spartanburgsheriff.org/258/Bookings-Search) 302s to
http://mugshots.spartanburgsheriff.org/, a legacy PHP roster
(/myscripts/mugshot_card.php?number=<id>) whose host stopped answering on both
:80 and :443. DNS still resolves (34.239.50.64) but the ports are closed, and
the Internet Archive's last successful capture is 2026-03-08 — i.e. the portal
is offline, not bot-walled. Spartanburg is not a Zuercher / P2C / JailTracker
tenant either, so there is no substitute host today. Re-check the redirect
target periodically; when it answers again, add a roster entry here.

The scraper follows the BaseScraper pattern with async fetch() returning
Iterable[Listing]. Uses curl_cffi (chrome impersonation) for systems that
fingerprint-block plain httpx, and the shared http_client for rate limiting.

Robots.txt: These are public-records APIs, not crawlable web pages. The
endpoints are the same JSON XHRs the public search UIs use. We check
robots.txt on the host anyway and fail-closed if disallowed.
"""
from __future__ import annotations

import asyncio
import html
import math
import re
from datetime import datetime, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# County roster configurations
# ---------------------------------------------------------------------------
# (state, county, vendor, target)
# vendor: "p2c_centralsquare" | "p2c_jqgrid" | "zuercher" | "citizen_connect"
#         | "tyler_inmate_inquiry"
# target: Zuercher subdomain, P2C base URL, "host|listId" for modern P2C,
#         "AgencyID|JMSAgencyID" for Citizen Connect, or the app base URL for
#         Tyler New World InmateInquiry.

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

    # Henderson NC — Southern Software Citizen Connect
    # Verified live 2026-07-31: 182 in custody, full DOB on 182/182.
    ("NC", "Henderson", "citizen_connect", "HendersonCoNC|NC0450000"),

    # Gaston NC — Tyler New World InmateInquiry (replaces the retired
    # newworld.aegis.webportal InmateInquiry.aspx, which now 302s away).
    # Verified live 2026-07-31: 695 in custody, full DOB on 695/695.
    ("NC", "Gaston", "tyler_inmate_inquiry",
     "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"),
]

# Southern Software hosts every Citizen Connect tenant off one origin; the
# AgencyID query param selects the agency and seeds the PHP session.
CITIZEN_CONNECT_BASE = "https://cc.southernsoftware.com"

# Charge-string cap. Was 300, which truncated multi-charge rosters mid-charge
# (a booking can list 10+ counts). 2000 keeps the full charge list.
_CHARGE_CAP = 2000

# Generational suffixes to drop before deciding which token is the surname.
_NAME_SUFFIXES = frozenset(
    {"JR", "SR", "II", "III", "IV", "V", "JUNIOR", "SENIOR"})

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


def _split_space_name(name: str) -> tuple[str, str] | None:
    """'MICHAEL LEE ABSHER' -> ('ABSHER', 'MICHAEL').

    Citizen Connect prints one flat "first middle last" string. The first token
    is the given name and the last the surname; trailing generational suffixes
    are dropped first so 'BOBBY DEAN ABEE JR' still yields ('ABEE', 'BOBBY').
    Compound surnames collapse to their final word, which is what the owner-name
    normalizer downstream does too.
    """
    toks = [t for t in re.split(r"\s+", (name or "").strip().upper()) if t]
    while len(toks) > 2 and _norm_alpha(toks[-1]) in _NAME_SUFFIXES:
        toks.pop()
    if len(toks) < 2:
        return None
    return toks[-1], toks[0]


def _strip_tags(fragment: str) -> str:
    """Flatten an HTML fragment to collapsed, entity-decoded plain text."""
    txt = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


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
    # US format — bare dates, 24h stamps (Citizen Connect) and 12h stamps
    # (Tyler New World).
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m/%d/%Y %H:%M",
                "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"):
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
            charges = "; ".join(str(x) for x in charges)[:_CHARGE_CAP]
        # Extra Zuercher fields (live-verified present): race/sex/cell_block,
        # a release date, and a mugshot ref. Carry them through for skip-trace.
        cell_block = rec.get("cell_block")
        release_date = (rec.get("release_date")
                        or rec.get("actual_release_date")
                        or rec.get("projected_release_date"))
        # Refine the otherwise-hardcoded in_custody flag from cell_block/release.
        if release_date:
            release_status = f"release_scheduled {release_date}"
        elif cell_block:
            release_status = f"in_custody cell_block={cell_block}"
        else:
            release_status = "in_custody"
        out.append({
            "last": last, "first": first,
            "dob": rec.get("dob"),
            "arrest_date": rec.get("arrest_date"),
            "charge": str(charges)[:_CHARGE_CAP],
            "race": rec.get("race"),
            "sex": rec.get("sex"),
            "cell_block": cell_block,
            "release_date": release_date,
            "mugshot": rec.get("mugshot") or rec.get("image") or rec.get("photo"),
            "release_status": release_status,
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
            "charge": (rw.get("chrgdesc") or rw.get("disp_charge") or "")[:_CHARGE_CAP],
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
                        "charge": (rec.get("PrimaryChargeDescription") or "")[:_CHARGE_CAP],
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
# Southern Software Citizen Connect (Henderson NC)
# ---------------------------------------------------------------------------

_CC_CARD_SPLIT = '<div class="card booking-card">'
_CC_NAME_RE = re.compile(r'<h5 class="mb-0">([^<]+)</h5>')
_CC_ROW_RE = re.compile(
    r'<span class="detail-label">([^<]*)</span>\s*'
    r'<span class="detail-value[^"]*">([^<]*)</span>')
_CC_CHARGE_RE = re.compile(
    r'<div class="charge-details"><div>(.*?)<span class="charge-agency"', re.S)
_CC_TOTAL_RE = re.compile(r"Total Inmates:.*?>(\d+)<", re.S)
_CC_SHOWING_RE = re.compile(r"Showing\s+\d+-(\d+)\s+of\s+(\d+)\s+inmates")
_CC_PAGE_SIZE = 20


def _parse_citizen_connect_cards(html_text: str) -> list[dict]:
    """Parse the booking cards out of one fetch_current_confinements.php page."""
    out: list[dict] = []
    for card in (html_text or "").split(_CC_CARD_SPLIT)[1:]:
        nm = _CC_NAME_RE.search(card)
        if not nm:
            continue
        parts = _split_space_name(html.unescape(nm.group(1)))
        if not parts:
            continue
        last, first = parts
        fields = {k.strip().rstrip(":"): html.unescape(v).strip()
                  for k, v in _CC_ROW_RE.findall(card)}
        charges = [_strip_tags(c) for c in _CC_CHARGE_RE.findall(card)]
        charges = [c for c in charges if c]
        # "36 years / W / M" -> "36"
        age = (fields.get("Demographics", "").split(" years")[0].strip()
               or None)
        out.append({
            "last": last, "first": first,
            "dob": fields.get("Date of Birth") or None,
            "age": age,
            "arrest_date": (fields.get("Booked")
                            or fields.get("Arrest Date/Time") or None),
            "charge": "; ".join(charges)[:_CHARGE_CAP],
            # This feed is the CURRENT-confinements list, so every row is a
            # person still in custody; the vendor publishes no release column.
            "release_status": "in_custody",
            # Forward the full label:value card dict (Demographics, Booked,
            # Facility, etc.) — the parser reads few of these but they carry
            # extra skip-trace signal.
            "fields": fields,
        })
    return out


async def _fetch_citizen_connect(target: str) -> list[dict]:
    """Southern Software Citizen Connect current-confinements roster.

    target is "<AgencyID>|<JMSAgencyID>", e.g. "HendersonCoNC|NC0450000".

    Handshake: the AJAX endpoint answers 500 "Session AgencyID not set" unless a
    PHP session has already been seeded, so GET the booking-search page once
    (?AgencyID=...) and reuse the session cookie. Page 1 posts JMSAgencyID; the
    vendor's own pager then posts IDX=<1-based page> against the same session.
    Full DOB is published on every card. Free + compliant: this is the page's
    own XHR, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    agency, _, jms = target.partition("|")
    page_url = f"{CITIZEN_CONNECT_BASE}/bookingsearch/index.php?AgencyID={agency}"
    api = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/fetchesforajax/"
           "fetch_current_confinements.php")
    hdr = {"X-Requested-With": "XMLHttpRequest", "Referer": page_url}
    out: list[dict] = []

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            await s.get(page_url, timeout=30)
            r = await s.post(api, headers=hdr, timeout=60, data={
                "JMSAgencyID": jms, "search": "", "agency": "", "sort": "name"})
            body = r.text or ""
            if "booking-card" not in body:
                log.warning("jail_scraper.citizen_connect_empty", agency=agency)
                return []
            out.extend(_parse_citizen_connect_cards(body))

            tm = _CC_TOTAL_RE.search(body)
            sm = _CC_SHOWING_RE.search(body)
            total = int(tm.group(1)) if tm else (
                int(sm.group(2)) if sm else len(out))
            pages = min(math.ceil(total / _CC_PAGE_SIZE) if total else 1, 60)
            for page in range(2, pages + 1):
                await asyncio.sleep(0.3)  # polite pacing
                pr = await s.post(api, headers=hdr, timeout=60, data={
                    "IDX": page, "search": "", "agency": "", "sort": "name"})
                recs = _parse_citizen_connect_cards(pr.text or "")
                if not recs:
                    break
                out.extend(recs)
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.citizen_connect_fail", agency=agency,
                    error=str(exc)[:120])
        return out

    log.info("jail_scraper.citizen_connect_ok", agency=agency, count=len(out))
    return out


# ---------------------------------------------------------------------------
# Tyler New World InmateInquiry (Gaston NC)
# ---------------------------------------------------------------------------

_TNW_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TNW_CELL_RE = re.compile(r'<td class="([A-Za-z]+)">(.*?)</td>', re.S)
_TNW_DETAIL_RE = re.compile(r"Inmate/Detail/(\d+)")
_TNW_SHOWING_RE = re.compile(
    r"Showing\s*(\d+)\s*to\s*(\d+)\s*of\s*(\d+)", re.S)
_TNW_FIELD_RE = re.compile(r'<span id=([A-Za-z]+)>(.*?)</span>', re.S)
_TNW_MAX_PAGES = 30


def _parse_tyler_rows(html_text: str) -> list[dict]:
    """Parse the in-custody grid of a Tyler New World InmateInquiry page."""
    out: list[dict] = []
    for rowm in _TNW_ROW_RE.finditer(html_text or ""):
        row = rowm.group(1)
        cells = {k: _strip_tags(v) for k, v in _TNW_CELL_RE.findall(row)}
        if not cells.get("Name"):
            continue
        parts = _split_comma_name(html.unescape(cells["Name"]))
        if not parts:
            continue
        last, first = parts
        in_custody = cells.get("InCustody", "").upper() == "YES"
        if not in_custody:
            continue
        det = _TNW_DETAIL_RE.search(row)
        sched = cells.get("ScheduledReleaseDate") or None
        out.append({
            "last": last, "first": first,
            "dob": cells.get("DateOfBirth") or None,
            "arrest_date": None,   # booking date lives on the detail page
            "charge": "",          # charges live on the detail page
            "release_status": (f"scheduled_release {sched}" if sched
                               else "in_custody"),
            "scheduled_release": sched,
            "facility": cells.get("HousingFacility") or None,
            "detail_id": det.group(1) if det else None,
            # Forward the full parsed grid-cell dict (Name/DateOfBirth/
            # InCustody/HousingFacility/ScheduledReleaseDate/...).
            "cells": cells,
        })
    return out


def _parse_tyler_detail(html_text: str) -> dict:
    """Pull booking date + charge list off one Inmate/Detail page.

    The page lists the subject's whole booking history newest-first; the open
    booking is the first one with an empty Release Date.
    """
    body = html_text or ""
    charges = [_strip_tags(v) for _, v in
               re.findall(r'<td class="(ChargeDescription)">(.*?)</td>', body, re.S)]
    charges = [c for c in charges if c]
    booking_date = None
    for block in body.split('<div class="Booking">')[1:]:
        fields = {k: _strip_tags(v) for k, v in _TNW_FIELD_RE.findall(block)}
        if fields.get("ReleaseDate"):
            continue
        booking_date = fields.get("BookingDate") or None
        break
    return {"arrest_date": booking_date, "charge": "; ".join(charges)[:_CHARGE_CAP]}


async def _fetch_tyler_detail(base: str, detail_id: str) -> dict:
    """Fetch one Tyler Inmate/Detail page and return {arrest_date, charge}.

    Kept standalone so the enricher can hydrate only the rows it actually
    matched to an owner (one GET each) instead of the whole 700-row roster.
    """
    from curl_cffi.requests import AsyncSession

    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            r = await s.get(f"{base}/Inmate/Detail/{detail_id}", timeout=45)
        return _parse_tyler_detail(r.text or "")
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_detail_fail", detail_id=detail_id,
                    error=str(exc)[:120])
        return {}


async def _fetch_tyler_inmate_inquiry(base: str, detail_limit: int = 0) -> list[dict]:
    """Tyler New World InmateInquiry current in-custody roster.

    The search form is a plain GET, so `?InCustody=True&Page=<n>` returns the
    whole roster 100 rows at a time. The grid carries FULL DOB, the in-custody
    flag and the scheduled release date. Booking date and charges are only on
    the per-inmate detail page, so they are fetched for at most `detail_limit`
    records (0 = grid only) to keep one run to a handful of requests.

    Free + compliant: a public GET form, no login, no CAPTCHA, no WAF token.
    """
    from curl_cffi.requests import AsyncSession

    out: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome", verify=False) as s:
            page = 1
            while page <= _TNW_MAX_PAGES:
                r = await s.get(f"{base}?InCustody=True&Page={page}", timeout=60)
                body = r.text or ""
                recs = _parse_tyler_rows(body)
                if not recs:
                    break
                out.extend(recs)
                sm = _TNW_SHOWING_RE.search(body)
                if not sm or int(sm.group(2)) >= int(sm.group(3)):
                    break
                page += 1
                await asyncio.sleep(0.3)  # polite pacing

            for rec in out[:max(detail_limit, 0)]:
                if not rec.get("detail_id"):
                    continue
                await asyncio.sleep(0.3)
                dr = await s.get(f"{base}/Inmate/Detail/{rec['detail_id']}",
                                 timeout=45)
                rec.update(_parse_tyler_detail(dr.text or ""))
    except Exception as exc:  # noqa: BLE001
        log.warning("jail_scraper.tyler_fail", base=base, error=str(exc)[:120])
        return out

    log.info("jail_scraper.tyler_ok", base=base, count=len(out))
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
        elif vendor == "citizen_connect":
            return await _fetch_citizen_connect(target)
        elif vendor == "tyler_inmate_inquiry":
            return await _fetch_tyler_inmate_inquiry(target)
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
    elif state == "NC" and county == "Henderson":
        source_url = (f"{CITIZEN_CONNECT_BASE}/bookingsearch/"
                      "index.php?AgencyID=HendersonCoNC")
    elif state == "NC" and county == "Gaston":
        source_url = ("https://tepsweb.cityofgastonia.com/"
                      "NewWorld.InmateInquiry/GastonCounty?InCustody=True")
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
                "release_status": rec.get("release_status") or "in_custody",
                "scheduled_release": rec.get("scheduled_release"),
                "facility": rec.get("facility"),
                # Zuercher demographics + release detail (dropped before).
                "race": rec.get("race"),
                "sex": rec.get("sex"),
                "cell_block": rec.get("cell_block"),
                "release_date": rec.get("release_date"),
                "mugshot": rec.get("mugshot"),
                # Full vendor field/cell dicts (Citizen-Connect / Tyler).
                "fields": rec.get("fields"),
                "cells": rec.get("cells"),
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

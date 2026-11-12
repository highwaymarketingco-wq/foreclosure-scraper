"""Anderson County SC ACPASS — login-walled property owner search.

ACPASS (acpass.andersoncountysc.org) is Anderson County's official property
tax/assessment system. The public GIS (propertyviewer.andersoncountysc.org)
has NO owner-name column — TAXOWNSTR holds tax-district codes, not owner names.
This leaves Anderson leads with no owner-name search backend.

ACPASS requires a login (credentials in .env: ACPASS_EMAIL / ACPASS_PASSWORD).

FLOW (PHP/CGI, NOT ASP.NET):
1. GET real_prop.htm → redirects to loginreg3/login.php (sets PHPSESSID).
2. POST credentials to loginreg3/login.php → JS redirect to welcome.htm.
3. GET real_prop_search.htm → search form.
4. POST asrmain.cgi with QryName → result list (NAME, TAXMAPNO, mapno links).
5. GET asrdetail1.cgi?mapno=NNNN → property detail (owner, address, value, sales).

Capped to a wall-clock budget and a consecutive-failure breaker.

Free, credentials in .env. No paid services.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Optional

import httpx
import structlog

log = structlog.get_logger()

_BASE = "https://acpass.andersoncountysc.org"
_LOGIN_URL = f"{_BASE}/loginreg3/login.php"
_SEARCH_PAGE = f"{_BASE}/real_prop_search.htm"
_SEARCH_CGI = f"{_BASE}/asrmain.cgi"
_DETAIL_CGI = f"{_BASE}/asrdetail1.cgi"

# Wall-clock budget for the entire ACPASS step.
_ACPASS_MAX_SECONDS = float(os.environ.get("ACPASS_MAX_SECONDS", "600"))
# Per-request timeout.
_ACPASS_TIMEOUT = 30.0
# Consecutive failure breaker.
_ACPASS_BREAKER_FAILS = int(os.environ.get("ACPASS_BREAKER_FAILS", "5"))

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# TMS format: 123-45-67-890 (Anderson County tax map number).
_TMS_RE = re.compile(r"\b(\d{3}-\d{2}-\d{2}-\d{3}(?:-\d{3})?)\b")
# mapno is a 16-digit zero-padded string used in detail links.
_MAPNO_RE = re.compile(r"mapno=(\d+)")


class _ACPASSSession:
    """Holds an authenticated httpx client (cookies stored on the client)."""

    def __init__(self):
        self.client: Optional[httpx.AsyncClient] = None
        self.logged_in = False


_session: Optional[_ACPASSSession] = None


def _get_credentials() -> tuple[str, str] | None:
    """Read ACPASS credentials from environment."""
    email = os.environ.get("ACPASS_EMAIL", "")
    password = os.environ.get("ACPASS_PASSWORD", "")
    if not email or not password:
        log.warning("acpass.no_credentials")
        return None
    return email, password


async def _login() -> bool:
    """Log into ACPASS and store an authenticated client. Returns True on success."""
    global _session

    creds = _get_credentials()
    if not creds:
        return False

    email, password = creds
    _session = _ACPASSSession()

    try:
        c = httpx.AsyncClient(
            timeout=_ACPASS_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        )
        _session.client = c

        # Step 1: GET real_prop.htm → redirects to login page, sets PHPSESSID.
        r = await c.get(f"{_BASE}/real_prop.htm")
        if r.status_code not in (200, 302):
            log.warning("acpass.login_page_fail", status=r.status_code)
            await c.aclose()
            return False

        # Step 2: POST credentials.
        r2 = await c.post(
            _LOGIN_URL,
            data={"email": email, "password": password, "login": "Login"},
            headers={
                "Referer": _LOGIN_URL,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": _BASE,
            },
        )

        # Success indicator: JS redirect to welcome.htm in the response body.
        if r2.status_code == 200 and "welcome.htm" in r2.text:
            _session.logged_in = True
            log.info("acpass.login_ok")
            return True

        log.warning(
            "acpass.login_rejected",
            status=r2.status_code,
            body_snippet=r2.text[:200],
        )
        await c.aclose()
        return False

    except Exception as exc:
        log.warning("acpass.login_error", error=str(exc)[:200])
        if _session and _session.client:
            await _session.client.aclose()
        return False


def _parse_results(html: str) -> list[dict]:
    """Parse asrmain.cgi result list into property records.

    Each result row has: checkbox (mapno), owner-name link, TMS, owner-count.
    """
    # Strategy: find all <a href="asrdetail1.cgi?mapno=NNNN">NAME</a> links,
    # then find TMS numbers (NNN-NN-NN-NNN) near each link.
    results: list[dict] = []
    link_re = re.compile(
        r'asrdetail1\.cgi\?mapno=(\d+)[^>]*>([^<]+)</a>',
    )
    tms_re = re.compile(r"\b(\d{3}-\d{2}-\d{2}-\d{3})\b")

    for m in link_re.finditer(html):
        mapno = m.group(1)
        name = m.group(2).strip()
        # Search for TMS in the 500 chars after this link.
        after = html[m.end(): m.end() + 500]
        tms_m = tms_re.search(after)
        tms = tms_m.group(1) if tms_m else ""
        results.append(
            {
                "mapno": mapno,
                "tms": tms,
                "parcel_id": tms,
                "owner_name": name,
                "detail_url": f"{_DETAIL_CGI}?mapno={mapno}",
            }
        )

    return results


def _parse_detail(html: str) -> dict:
    """Parse asrdetail1.cgi property detail page.

    Extracts: owner name, mailing address, physical address, market value,
    prior value, tax value, sale price, sale date, deed book/page, subdivision.

    The HTML uses table cells with labels split across lines (e.g. "Physical"
    then "Address" then the value). We flatten to a text-line array and scan
    for label patterns.
    """
    info: dict = {}

    # Strip tags, preserve text as lines.
    clean = re.sub(r"<[^>]+>", "\n", html)
    clean = re.sub(r"&nbsp;", " ", clean)
    lines = [l.strip() for l in clean.split("\n") if l.strip()]

    # Join multi-word labels: "Physical\nAddress" → "Physical Address"
    # Then the value is on the next line.
    def _find_value(label_parts: list[str], start: int = 0) -> str | None:
        """Find a value following a multi-line label."""
        joined = " ".join(label_parts).lower()
        for i in range(start, len(lines) - len(label_parts)):
            chunk = " ".join(lines[i : i + len(label_parts)]).lower()
            if chunk == joined:
                # Value is on the next non-empty line after the label.
                val_idx = i + len(label_parts)
                if val_idx < len(lines):
                    return lines[val_idx]
        return None

    # Owner name (Current Owner → Name → value).
    # Pattern: "Current" "Owner" ... "Name" VALUE
    for i, line in enumerate(lines):
        if line.lower() == "current owner" or (line.lower() == "current" and i + 1 < len(lines) and lines[i + 1].lower() == "owner"):
            # Find "Name" after this point.
            for j in range(i + 1, min(i + 5, len(lines))):
                if lines[j].lower() == "name" and j + 1 < len(lines):
                    info["owner_name"] = lines[j + 1]
                    break
            break

    # Mailing address (Owner section: "Address" VALUE).
    # Distinguish from "Physical Address" by checking we're before "Property Information".
    prop_info_idx = None
    for i, line in enumerate(lines):
        if "property" in line.lower() and i + 1 < len(lines) and "information" in lines[i + 1].lower():
            prop_info_idx = i
            break

    for i, line in enumerate(lines):
        if line.lower() == "address" and i + 1 < len(lines):
            # Skip if this is in the "Physical Address" section.
            if prop_info_idx and i >= prop_info_idx:
                continue
            val = lines[i + 1]
            if val and not val.lower().startswith("address"):
                info["mailing_address"] = val
                break

    # City, State (mailing).
    for i, line in enumerate(lines):
        if "city" in line.lower() and "state" in line.lower() and i + 1 < len(lines):
            if prop_info_idx and i >= prop_info_idx:
                continue
            val = lines[i + 1]
            # Format: "ANDERSON               SC"
            sc_match = re.search(r"(.+?)\s+SC\s*$", val, re.I)
            if sc_match:
                info["mailing_city"] = sc_match.group(1).strip()
                info["mailing_state"] = "SC"
            break

    # Zip (mailing).
    for i, line in enumerate(lines):
        if line.lower() == "zip" and i + 1 < len(lines):
            if prop_info_idx and i >= prop_info_idx:
                continue
            val = lines[i + 1]
            if re.match(r"\d{5}(-\d{4})?", val):
                info["mailing_zip"] = val
                break

    # Physical Address (after Property Information).
    if prop_info_idx:
        for i in range(prop_info_idx, len(lines) - 1):
            if lines[i].lower() == "physical" and lines[i + 1].lower() == "address":
                if i + 2 < len(lines):
                    val = lines[i + 2].strip()
                    # Skip if the "address" is actually another label.
                    if val.lower() not in ("market", "market value", "prior", "tax", "subdivision", "value", "exempt", "legal", "m/h"):
                        info["street_address"] = val
                break

    # Market Value.
    for i, line in enumerate(lines):
        if "market value" in line.lower() and i + 1 < len(lines):
            val = lines[i + 1].replace(",", "").replace("$", "").strip()
            if val.isdigit():
                info["market_value"] = int(val)
            break
        # Also check multi-line: "Market" then "Value"
        if line.lower() == "market" and i + 1 < len(lines) and lines[i + 1].lower() == "value":
            if i + 2 < len(lines):
                val = lines[i + 2].replace(",", "").replace("$", "").strip()
                if val.isdigit():
                    info["market_value"] = int(val)
            break

    # Prior Value.
    for i, line in enumerate(lines):
        if "prior value" in line.lower() and i + 1 < len(lines):
            val = lines[i + 1].replace(",", "").replace("$", "").strip()
            if val.isdigit():
                info["prior_value"] = int(val)
            break
        if line.lower() == "prior" and i + 1 < len(lines) and lines[i + 1].lower() == "value":
            if i + 2 < len(lines):
                val = lines[i + 2].replace(",", "").replace("$", "").strip()
                if val.isdigit():
                    info["prior_value"] = int(val)
            break

    # Tax Value.
    for i, line in enumerate(lines):
        if "tax value" in line.lower() and i + 1 < len(lines):
            val = lines[i + 1].replace(",", "").replace("$", "").strip()
            if val.isdigit():
                info["tax_value"] = int(val)
            break
        if line.lower() == "tax" and i + 1 < len(lines) and lines[i + 1].lower() == "value":
            if i + 2 < len(lines):
                val = lines[i + 2].replace(",", "").replace("$", "").strip()
                if val.isdigit():
                    info["tax_value"] = int(val)
            break

    # Subdivision (skip header matches; value must not be another label).
    for i, line in enumerate(lines):
        if "subdivision" in line.lower() and i + 1 < len(lines):
            val = lines[i + 1].strip()
            if val and val.lower() not in ("subdivision", "&nbsp;", "tax", "district", "legal"):
                info["subdivision"] = val
                break

    # Sales info — find "Sales Information" section, then first sale row.
    for i, line in enumerate(lines):
        if "sales" in line.lower() and i + 1 < len(lines) and "information" in lines[i + 1].lower():
            # Find the "Purchaser" header that marks end of column headers.
            purchaser_idx = None
            for j in range(i + 1, min(i + 20, len(lines))):
                if lines[j].lower() == "purchaser":
                    purchaser_idx = j
                    break
            if purchaser_idx is not None and purchaser_idx + 4 < len(lines):
                # Sale row: Date, Book#, Page#, Price, Purchaser name.
                date_m = re.match(r"\d{1,2}/\d{1,2}/\d{4}", lines[purchaser_idx + 1])
                if date_m:
                    info["sale_date"] = lines[purchaser_idx + 1]
                    info["deed_book"] = lines[purchaser_idx + 2]
                    info["deed_page"] = lines[purchaser_idx + 3]
                    price_str = lines[purchaser_idx + 4].replace(",", "").replace("$", "").strip()
                    try:
                        price_val = float(price_str)
                        # Sanity check: real sale prices are > 100.
                        if price_val > 100:
                            info["sale_price"] = price_val
                    except ValueError:
                        pass
            break

    # TMS from the detail page header.
    tms_match = _TMS_RE.search(clean)
    if tms_match:
        info["tms"] = tms_match.group(1)
        info["parcel_id"] = tms_match.group(1)

    return info


async def _search_owner(owner_name: str) -> list[dict]:
    """Search ACPASS for properties by owner name. Returns list of result dicts."""
    if not _session or not _session.logged_in or not _session.client:
        return []

    # Use last name for search (ACPASS matches on surname prefix).
    parts = owner_name.split(",", 1)
    last_name = parts[0].strip() if parts else owner_name.strip()
    # If name is "First Last", use the last word.
    if " " in last_name and "," not in owner_name:
        last_name = last_name.split()[-1]

    if len(last_name) < 3:
        return []

    results: list[dict] = []
    try:
        c = _session.client

        # GET search page first (maintains session).
        await c.get(_SEARCH_PAGE, headers={"Referer": f"{_BASE}/real_prop.htm"})

        # POST search.
        r = await c.post(
            _SEARCH_CGI,
            data={"QryName": last_name.upper(), "QryMapNo": "", "QryStreet": ""},
            headers={
                "Referer": _SEARCH_PAGE,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": _BASE,
            },
        )

        if r.status_code != 200 or len(r.text) < 500:
            log.warning("acpass.search_fail", status=r.status_code, size=len(r.text))
            return []

        results = _parse_results(r.text)

        # Fetch detail for all results (concurrently with cap).
        if results:
            sem = asyncio.Semaphore(3)

            async def _fetch_detail(rec: dict):
                async with sem:
                    try:
                        dr = await c.get(rec["detail_url"], headers={"Referer": _SEARCH_CGI})
                        if dr.status_code == 200:
                            detail = _parse_detail(dr.text)
                            rec.update(detail)
                    except Exception as exc:
                        log.warning("acpass.detail_error", url=rec.get("detail_url"), error=str(exc)[:120])

            await asyncio.gather(*[_fetch_detail(r) for r in results])

        # Filter results to approximate name match.
        if results:
            filtered = []
            for r in results:
                owner = r.get("owner_name", "").upper()
                # Check if last name appears in the owner field.
                if last_name.upper() in owner:
                    filtered.append(r)
            if filtered:
                results = filtered

    except Exception as exc:
        log.warning("acpass.search_error", name=owner_name, error=str(exc)[:160])

    return results


async def search_anderson_owner(owner_name: str) -> list[dict]:
    """Public API: search ACPASS for an owner name.

    Returns list of property records (dicts with tms, parcel_id, address, etc.).
    Handles login lazily on first call.
    """
    global _session

    if not owner_name or len(owner_name.strip()) < 3:
        return []

    # Lazy login.
    if not _session or not _session.logged_in:
        ok = await _login()
        if not ok:
            return []

    return await _search_owner(owner_name)


async def enrich(listings: list) -> dict:
    """Enrichment entry point: resolve Anderson SC leads via ACPASS.

    Called from main.py enrichment pipeline. Finds Anderson leads that have a
    defendant/owner name but no parcel_id or street_address, searches ACPASS,
    and fills in the parcel_id, address, and market value.
    """
    start = time.monotonic()

    stats = {
        "targets": 0,
        "resolved": 0,
        "blocked": 0,
        "errors": 0,
    }

    # Filter to Anderson SC leads with a name but no parcel/address.
    targets = []
    for li in listings:
        if getattr(li, "state", "") != "SC" or getattr(li, "county", "") != "Anderson":
            continue
        if getattr(li, "parcel_id", None) or getattr(li, "street_address", None):
            continue
        name = getattr(li, "defendant", None) or getattr(li, "owner_name", None) or ""
        if not name or len(name.strip()) < 3:
            continue
        targets.append(li)

    stats["targets"] = len(targets)
    if not targets:
        log.info("acpass.no_targets")
        return stats

    # Check credentials before starting.
    if not _get_credentials():
        log.warning("acpass.no_credentials_skip")
        stats["blocked"] = len(targets)
        return stats

    consecutive_fails = 0
    for li in targets:
        if time.monotonic() - start > _ACPASS_MAX_SECONDS:
            log.warning("acpass.budget_exceeded", resolved=stats["resolved"])
            stats["blocked"] = len(targets) - stats["resolved"]
            break

        name = getattr(li, "defendant", None) or getattr(li, "owner_name", None) or ""
        try:
            results = await search_anderson_owner(name)
            if results:
                # Take the first result (best match).
                r = results[0]
                if r.get("parcel_id"):
                    li.parcel_id = r["parcel_id"]
                if r.get("street_address"):
                    li.street_address = r["street_address"]
                if r.get("mailing_address"):
                    if not hasattr(li, "owner_mailing_address") or not li.owner_mailing_address:
                        li.owner_mailing_address = r["mailing_address"]
                    if r.get("mailing_city"):
                        li.owner_mailing_city = r["mailing_city"]
                    if r.get("mailing_zip"):
                        li.owner_mailing_zip = r["mailing_zip"]
                if r.get("market_value"):
                    if not getattr(li, "market_value", None):
                        li.market_value = r["market_value"]
                if r.get("sale_price"):
                    if not getattr(li, "opening_bid", None):
                        li.opening_bid = r["sale_price"]
                if isinstance(getattr(li, "raw", None), dict):
                    li.raw["acpass_resolved"] = {
                        k: v for k, v in r.items() if k != "detail_url"
                    }
                stats["resolved"] += 1
                consecutive_fails = 0
            else:
                consecutive_fails += 1

        except Exception as exc:
            log.warning("acpass.enrich_error", name=name[:50], error=str(exc)[:160])
            stats["errors"] += 1
            consecutive_fails += 1

        if consecutive_fails >= _ACPASS_BREAKER_FAILS:
            log.warning("acpass.breaker_tripped", fails=consecutive_fails)
            stats["blocked"] = len(targets) - stats["resolved"] - stats["errors"]
            break

    # Cleanup session.
    if _session and _session.client:
        await _session.client.aclose()
        _session = None

    elapsed = time.monotonic() - start
    log.info("acpass.done", **stats, elapsed_s=round(elapsed, 1))
    return stats

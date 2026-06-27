"""USDA Rural Development resale properties — federal REO source.

USDA RD lists single-family + multi-family + farm/ranch properties
foreclosed by Rural Development. Free, no auth, plain HTML.

The public site (resales.usda.gov) is a JSP app whose search is NOT a
plain GET(?state=XX). It's a two-step, session-scoped flow:

  1. GET /resales/public/search{KIND}    -> establishes the form session
     and (on the SFH page) renders the active-states dropdown:
       <option value="45">South Carolina (1)</option>   # FIPS, count
  2. GET /resales/public/getCountiesOfStateWithActiveProperties
         ?stateCode=<FIPS>&searchFormName=<KIND>
     with Accept: application/json + X-Requested-With -> JSON list of
     active counties [{"countyCode","countyName":"Lexington (1)"}].
     NOTE: when a state has 0 active properties for that kind the endpoint
     returns an HTML *error* page (not JSON) — we treat that as 0 counties.
  3. POST /resales/public/search{KIND} with stateCode, countyCode,
     propertyType, listingType=All Types, Search=Search -> the results
     page whose #propertySummariesTable <tbody> <tr> rows are the data.
     (listingType MUST be "All Types" — an empty listingType returns 0 rows.)

Columns (verified 2026-06): Photo | Listing Type | Street Address | City |
State | County | Zip | Price/Bid | Beds | Baths | Sq. Ft., with a
"Details" anchor to /resales/public/{KIND}PropertyDetail?id=NNN.

Volume is small (typically 0-10 per state) but the listings are
high-quality and clean: USDA RD pre-vets title before listing, so
they're closer to retail-ready than sheriff sales.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()


_BASE = "https://www.resales.usda.gov/resales/public"

# State -> FIPS state code the site uses in stateCode= and the dropdown.
_STATE_FIPS = {"NC": "37", "SC": "45"}
_FIPS_STATE = {v: k for k, v in _STATE_FIPS.items()}

# Kind -> (path segment, searchFormName the active-counties endpoint wants,
#          propertyType POST value, PropertyKind, listing label).
_KINDS = {
    "SFH": ("searchSFH", "SFH", "Single Family", PropertyKind.SINGLE_FAMILY),
    "MFH": ("searchMFH", "MFH", "Multi-Family", PropertyKind.MULTI_FAMILY),
    "FSA": ("searchFSA", "FSA", "Farm & Ranch", PropertyKind.LAND),
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}
_JSON_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
# "Lexington (1)" -> "Lexington"; the trailing "(N)" is the active count.
_COUNT_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*$")


def _clean_num(text: str | None) -> float | None:
    """Parse a numeric cell (beds/baths/sqft) into a float, defensively."""
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _cell(row, idx: int):
    tds = row.css("td")
    return tds[idx] if 0 <= idx < len(tds) else None


def _cell_text(row, idx: int) -> str:
    td = _cell(row, idx)
    return (td.text(separator=" ").strip() if td is not None else "")


async def _active_counties(c, state: str, kind: str) -> list[str]:
    """Return active county codes for a state+kind, or [] (never raises).

    Establishes the form session with a GET to the kind's search page, then
    asks the active-counties JSON endpoint. A non-JSON / non-list body means
    the state has no active inventory for that kind -> [].
    """
    path, form_name, _pt, _pk = _KINDS[kind]
    fips = _STATE_FIPS.get(state)
    if not fips:
        return []
    ref = f"{_BASE}/{path}"
    try:
        await c.get(ref, headers=_HEADERS)
        url = (f"{_BASE}/getCountiesOfStateWithActiveProperties"
               f"?stateCode={fips}&searchFormName={form_name}")
        r = await c.get(url, headers={**_HEADERS, **_JSON_HEADERS, "Referer": ref})
    except Exception as exc:
        log.warning("usda_rd.counties_failed", state=state, kind=kind,
                    error=str(exc)[:200])
        return []
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "json" not in ctype.lower():
        # HTML error page = 0 active counties for this state+kind.
        return []
    try:
        data = r.json()
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    codes: list[str] = []
    for item in data:
        if isinstance(item, dict):
            code = item.get("countyCode")
            if code:
                codes.append(str(code))
    return codes


async def _search_county(c, state: str, kind: str, county_code: str) -> list[Listing]:
    """POST the search form for one active county and parse the result rows."""
    path, _form_name, prop_type, prop_kind = _KINDS[kind]
    fips = _STATE_FIPS[state]
    ref = f"{_BASE}/{path}"
    form = {
        "city": "",
        "zipCode": "",
        "propertyType": prop_type,
        "stateCode": fips,
        "countyCode": county_code,
        "listingType": "All Types",   # empty listingType returns 0 rows
        "minPrice": "",
        "maxPrice": "",
        "bedrooms": "",
        "bathrooms": "",
        "squareFootage": "",
        "Search": "Search",
    }
    headers = {
        **_HEADERS,
        "Referer": ref,
        "Origin": "https://www.resales.usda.gov",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        r = await c.post(ref, data=form, headers=headers)
    except Exception as exc:
        log.warning("usda_rd.search_failed", state=state, kind=kind,
                    county=county_code, error=str(exc)[:200])
        return []
    if r.status_code != 200:
        return []

    tree = HTMLParser(r.text)
    table = tree.css_first("#propertySummariesTable")
    if table is None:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    for row in table.css("tbody tr"):
        # Detail anchor lives in the first (Photo) cell.
        detail_href = ""
        for a in row.css("a"):
            href = a.attributes.get("href", "") or ""
            if "PropertyDetail" in href:
                detail_href = href
                break

        # Columns: 0 Photo, 1 Listing Type, 2 Street, 3 City, 4 State,
        #          5 County, 6 Zip, 7 Price/Bid, 8 Beds, 9 Baths, 10 Sq.Ft.
        # The Street cell also carries a "Map" link + text; take the first
        # non-empty text line as the address.
        street_td = _cell(row, 2)
        street = ""
        if street_td is not None:
            for piece in street_td.text(separator="|").split("|"):
                piece = piece.strip()
                if piece and piece.lower() != "map":
                    street = piece
                    break
        if not street:
            continue

        city = _cell_text(row, 3)
        st_abbr = _FIPS_STATE.get(fips, state)
        county = _COUNT_SUFFIX_RE.sub("", _cell_text(row, 5)).strip() or None
        zip_code = (_cell_text(row, 6) or "").strip() or None
        listing_label = (_cell_text(row, 1) or "").strip()

        price = None
        pm = _PRICE_RE.search(_cell_text(row, 7))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

        beds = _clean_num(_cell_text(row, 8))
        baths = _clean_num(_cell_text(row, 9))
        sqft = _clean_num(_cell_text(row, 10))

        full_url = (
            detail_href if detail_href.startswith("http")
            else f"{_BASE}/{detail_href.lstrip('/').removeprefix('resales/public/')}"
            if detail_href else ref
        )
        dedupe = full_url if detail_href else f"{street}|{zip_code}"
        if dedupe in seen:
            continue
        seen.add(dedupe)

        out.append(Listing(
            source="reo.usda_rd",
            source_url=full_url,
            listing_type=ListingType.REO,
            property_kind=prop_kind,
            state=st_abbr,
            street_address=street,
            city=city or None,
            county=county,
            zip_code=zip_code,
            opening_bid=price,
            bedrooms=beds,
            bathrooms=baths,
            living_sqft=sqft,
            description=(
                f"USDA Rural Development {kind} "
                f"{listing_label or 'REO'} ({st_abbr})"
            ),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"usda_rd": {
                "kind": kind,
                "listing_label": listing_label,
                "county_code": county_code,
            }},
        ))
    log.info("usda_rd.county_done", state=state, kind=kind,
             county=county_code, count=len(out))
    return out


async def _fetch_state(state: str, kind: str = "SFH") -> list[Listing]:
    """Pull one state+kind: discover active counties, then search each."""
    out: list[Listing] = []
    async with client(timeout=30.0) as c:
        codes = await _active_counties(c, state, kind)
        if not codes:
            log.info("usda_rd.state_done", state=state, kind=kind, count=0)
            return out
        for code in codes:
            try:
                out.extend(await _search_county(c, state, kind, code))
            except Exception as exc:  # noqa: BLE001
                log.warning("usda_rd.county_failed", state=state, kind=kind,
                            county=code, error=str(exc)[:200])
    log.info("usda_rd.state_done", state=state, kind=kind, count=len(out))
    return out


class USDARuralDevelopment(BaseScraper):
    slug = "reo.usda_rd"
    name = "USDA Rural Development REO (NC + SC)"
    category = "federal_reo"
    expected_min_count = 0  # Often 0 in either state
    requires_apify = False
    disabled = True
    disabled_reason = ("froze the concurrent run on 2026-06-27 (no completion in 2h47m; "
                       "an event-loop-blocking call evades safe_run's wait_for, freezing "
                       "every scraper). National REO, minimal in-footprint value. Re-enable "
                       "after isolating the blocking call or running it via asyncio.to_thread.")
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in ("NC", "SC"):
            for kind in ("SFH", "MFH", "FSA"):
                try:
                    out.extend(await _fetch_state(state, kind))
                except Exception as exc:  # noqa: BLE001
                    log.warning("usda_rd.state_failed", state=state, kind=kind,
                                error=str(exc)[:200])
        log.info("usda_rd.done", total=len(out))
        return out

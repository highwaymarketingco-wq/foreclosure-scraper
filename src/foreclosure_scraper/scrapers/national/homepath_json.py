"""Fannie Mae HomePath — paginated-depth complement to the bbox grid scraper.

REWRITTEN 2026-10-01 (national/reo per-source audit). This module's original
premise -- a separate ``search-listings`` endpoint taking ``state`` /
``zipcode`` / ``page`` params -- is confirmed FALSE two ways, live:

1. ``GET .../cfl/property-inventory/search-listings`` (the documented URL)
   returns HTTP 404 (RFC7807 problem+json). It does not exist.
2. The URL this module actually called instead -- plain
   ``.../cfl/property-inventory/search`` with ``state``/``zipcode``/``page``
   params and NO ``bounds`` -- silently IGNORES all four of those params:
   page 1, 2 and 3 for "NC" each returned the byte-identical first 400
   properties of an unfiltered 648,044-row NATIONWIDE list (confirmed via
   matching propertyUuids across pages). ``_to_listing``'s own state filter
   then dropped everything outside NC/SC, so this scraper was returning
   22 near-random rows (whatever happened to be NC/SC in that arbitrary
   400-row slice) instead of a genuine state-wide paginated sweep -- a
   "silently returns wrong/incomplete data" bug, not a crash.

Also confirmed live: THIS endpoint (the real, only working one, same host
``fannie_homepath.py``'s bbox scraper uses) honors ``page``/``pageSize``
pagination CORRECTLY as long as ``bounds`` is present -- different pages
return different, real, geographically-filtered properties. So the genuine
complementary value this module can add over the sibling bbox scraper
(which fetches only PAGE 1 of each of its 4x4 grid cells, no further
pagination within a cell) is PAGINATION DEPTH: this module queries the same
NC/SC state bboxes WITHOUT subdividing them into a grid, and pages through
as many results as PAGES_CAP allows, which independently re-covers the
state and would catch anything a saturated (>400 properties) grid cell in
the sibling might miss. Response shape (unchanged):

  {
    "properties": [
      { "propertyUuid", "reoId", "mlsId", "addressLine1", "city",
        "state", "zipCode", "county", "propertyType",
        "bedrooms", "bathrooms", "sqft", "yearBuilt",
        "price", "listingStartDate", "retailStatus",
        "geoPoint": {"latitude", "longitude"},
        "primHiResImageUrl", "onlineOfferOnly", "firstLookProgramIndicator"
      }, ...
    ],
    "totalProperties": N,
  }

case_number now uses the SAME "fannie-{uuid}" prefix as
``fannie_homepath.py`` (was "homepath-json-{uuid}", a mismatch that broke
this module's own docstring claim that overlapping properties "merge in via
the normal dedupe path (case_number collision)" -- they never could, with
two different id schemes for the same propertyUuid).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...county_name import canonical_county
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

# The SAME endpoint fannie_homepath.py's bbox scraper uses -- confirmed live
# 2026-10-01 to be the only one that actually exists and actually filters.
API = "https://homepath.fanniemae.com/cfl/property-inventory/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://homepath.fanniemae.com/",
}

STATES = ("NC", "SC")
# Same state bboxes as fannie_homepath.py's BBOXES (sw_lat, sw_lng, ne_lat,
# ne_lng), duplicated here (not imported) so this module stays independent
# of the sibling's internals -- only the confirmed-stable host/URL/response
# shape is shared knowledge, not code.
_STATE_BBOX: dict[str, tuple[float, float, float, float]] = {
    "NC": (33.75, -84.50, 36.60, -75.30),
    "SC": (32.00, -83.40, 35.25, -78.50),
}
PAGE_SIZE = 100
# Hard cap on pages per state. HomePath nationwide has ~27k listings; NC+SC
# combined are ~500-800, so 20 pages (2000 listings) is a generous ceiling.
PAGES_CAP = 20

_PROP_KIND_MAP = {
    "Single Family": PropertyKind.SINGLE_FAMILY,
    "Condominium": PropertyKind.CONDO,
    "Condo": PropertyKind.CONDO,
    "Townhouse": PropertyKind.TOWNHOUSE,
    "Multi-Family": PropertyKind.MULTI_FAMILY,
    "Manufactured Home": PropertyKind.MOBILE,
    "Mobile Home": PropertyKind.MOBILE,
    "Land": PropertyKind.LAND,
    "Commercial": PropertyKind.COMMERCIAL,
}


def _safe_float(v):
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_listing(p: dict, slug: str) -> Listing | None:
    """Convert a HomePath search-listings API property row to a Listing."""
    state = (p.get("state") or "").strip().upper()
    if state not in STATES:
        return None

    addr = (p.get("addressLine1") or "").strip()
    if not addr:
        return None

    uuid = p.get("propertyUuid") or p.get("reoId") or p.get("mlsId")
    geo = p.get("geoPoint") or {}
    img_url = p.get("primHiResImageUrl") or p.get("primaryImageUrl")
    photos = (
        [img_url]
        if isinstance(img_url, str) and img_url.startswith("http")
        else []
    )

    listing_ms = p.get("listingStartDate")
    first_seen = datetime.utcnow()
    if isinstance(listing_ms, (int, float)) and listing_ms > 0:
        try:
            first_seen = (
                datetime.fromtimestamp(listing_ms / 1000, tz=timezone.utc)
                .replace(tzinfo=None)
            )
        except (ValueError, OSError):
            pass

    price = _safe_float(p.get("price"))
    lat = geo.get("latitude") if isinstance(geo.get("latitude"), (int, float)) else None
    lng = (
        geo.get("longitude")
        if isinstance(geo.get("longitude"), (int, float))
        else None
    )

    year_built_raw = p.get("yearBuilt")
    try:
        year_built = int(year_built_raw) if year_built_raw else None
    except (TypeError, ValueError):
        year_built = None

    return Listing(
        source=slug,
        source_url=(
            f"https://homepath.fanniemae.com/property/{uuid}"
            if uuid
            else "https://homepath.fanniemae.com/"
        ),
        listing_type=ListingType.REO,
        property_kind=_PROP_KIND_MAP.get(
            (p.get("propertyType") or "").strip(), PropertyKind.UNKNOWN
        ),
        state=state,
        county=canonical_county((p.get("county") or "").replace(" COUNTY", "")) or None,
        city=(p.get("city") or "").title() or None,
        zip_code=(p.get("zipCode") or "").strip() or None,
        street_address=addr,
        case_number=f"fannie-{uuid}" if uuid else None,
        latitude=lat,
        longitude=lng,
        opening_bid=price,
        # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 17):
        # bedrooms/bathrooms/sqft/year_built are real first-class fields on
        # the Listing model (confirmed via web_artifact._SLIM_TOP) but this
        # scraper only ever stuffed them into the flat `raw` dict below,
        # where NONE of them (nor mls_id/property_uuid/retail_status/
        # online_offer_only/first_look) were ever in web_artifact.RAW_KEEP --
        # a direct _slim_raw() round-trip confirmed only `reo_id` and
        # `images` survived publish; every other field silently dropped on
        # every one of this scraper's ~4,605 live rows since its 2026-10-01
        # rewrite. Same fix pattern as batch 16's hud_homestore finding:
        # promote the property-characteristic fields to first-class Listing
        # kwargs (always serialized, sidesteps RAW_KEEP entirely) and
        # namespace the rest under a new registered "homepath_json" key.
        bedrooms=_safe_float(p.get("bedrooms")),
        bathrooms=_safe_float(p.get("bathrooms")),
        living_sqft=_safe_float(p.get("sqft")),
        year_built=year_built,
        description=(
            f"HomePath REO {p.get('propertyType') or ''} "
            f"{int(p['bedrooms']) if p.get('bedrooms') else ''}bd/"
            f"{int(p['bathrooms']) if p.get('bathrooms') else ''}ba "
            f"{int(p['sqft']) if p.get('sqft') else ''} sqft"
        ).strip(),
        first_seen=first_seen,
        last_seen=datetime.utcnow(),
        raw={
            "reo_id": p.get("reoId"),
            "images": {"real": photos} if photos else {},
            "homepath_json": {
                "mls_id": p.get("mlsId"),
                "property_uuid": p.get("propertyUuid"),
                "retail_status": p.get("retailStatus"),
                "online_offer_only": p.get("onlineOfferOnly"),
                "first_look": bool(p.get("firstLookProgramIndicator")),
            },
        },
    )


async def _fetch_state(
    state: str, slug: str, partial_sink: list[Listing] | None = None
) -> list[Listing]:
    """Page through the HomePath property-inventory endpoint for one state's
    FULL (un-gridded) bbox.

    Paginates with ?bounds=<state bbox>&page=N&pageSize=100 until a page
    returns fewer than PAGE_SIZE rows (last page) or we hit PAGES_CAP.
    ``bounds`` is required -- confirmed live 2026-10-01, without it the API
    silently ignores page/state/zipcode and returns the same fixed,
    unfiltered nationwide slice on every call (see module docstring).
    Dedupes by case_number (propertyUuid) within this state's results; the
    state-wide (not gridded) bbox means a single saturated page here would
    show up as exactly PAGES_CAP pages all full, which is its own signal the
    cap needs raising -- unlike the sibling's per-cell single page, which has
    no such signal if a cell saturates silently.

    NOTE: the server returns up to 400 properties per page regardless of the
    requested pageSize (confirmed live) -- PAGE_SIZE's `len(props) <
    PAGE_SIZE` check therefore never fires as a "that was the last page"
    signal in practice; termination instead relies on `new_this_page == 0`
    (every row on this page was already seen) or PAGES_CAP, both of which
    are exercised and confirmed live (NC stopped at page 12, SC at page 14,
    2026-10-01, both via the dedupe path).

    If `partial_sink` is given (the scraper's own self.partial), each page's
    newly-kept rows are appended to it immediately, so a soft-timeout
    cancellation mid-sweep still ships whatever pages already completed
    instead of discarding the whole state -- this rewrite made a full sweep
    take ~2 minutes (up from the old, broken ~5s no-op), so that salvage path
    is no longer theoretical."""
    out: list[Listing] = []
    seen: set[str] = set()
    bbox = _STATE_BBOX[state]
    bounds = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"

    async with client(timeout=30.0) as c:
        for page in range(1, PAGES_CAP + 1):
            params = {
                "bounds": bounds,
                "page": str(page),
                "pageSize": str(PAGE_SIZE),
            }
            try:
                r = await c.get(
                    API, params=params, headers=HEADERS, follow_redirects=True
                )
            except Exception as exc:
                log.warning(
                    "homepath_json.fetch_failed",
                    state=state, page=page, error=str(exc)[:200],
                )
                break

            if r.status_code != 200:
                log.warning(
                    "homepath_json.bad_status",
                    state=state, page=page, code=r.status_code,
                )
                break

            try:
                payload = r.json()
            except Exception:
                log.warning("homepath_json.bad_json", state=state, page=page)
                break

            # The search-listings endpoint wraps results in 'properties'.
            # Some HomePath API variants use 'data' or 'results' — handle all.
            props = (
                payload.get("properties")
                or payload.get("data")
                or payload.get("results")
                or []
            )
            if not isinstance(props, list):
                break

            new_this_page = 0
            for p in props:
                if not isinstance(p, dict):
                    continue
                li = _to_listing(p, slug)
                if li is None:
                    continue
                key = li.case_number or li.source_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)
                if partial_sink is not None:
                    partial_sink.append(li)
                new_this_page += 1

            total = payload.get("total")
            log.info(
                "homepath_json.page_done",
                state=state, page=page,
                props=len(props), kept=new_this_page,
                total_reported=total, running=len(out),
            )

            # Stop on last page (fewer than PAGE_SIZE returned) or empty page.
            if len(props) < PAGE_SIZE or new_this_page == 0:
                break

    log.info("homepath_json.state_done", state=state, count=len(out))
    return out


class HomePathJSON(BaseScraper):
    """Fannie Mae HomePath REO via state/zipcode JSON search API.

    A complement to ``fannie_homepath`` (the per-cell, single-page bbox grid
    scraper): this module paginates DEPTH-first through each state's full,
    un-gridded bbox, so it independently re-covers the state and would catch
    anything a saturated grid cell in the sibling misses.
    """

    slug = "national.homepath_json"
    name = "Fannie Mae HomePath (REO, paginated bbox depth sweep)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # MEASURED 2026-10-01, live, right after this module's rewrite from a
    # broken no-op (ignored params, ~5s, 22 near-random rows) to a real
    # paginated full-state sweep (4,605 real rows): one full NC+SC sweep took
    # ~120s wall-clock -- right at the old timeout_s=120 floor, so a slightly
    # slower day would have silently lost the whole run to OUTCOME_TIMEOUT.
    # 240s gives real headroom; self.partial below (see _fetch_state's
    # partial_sink param) means even a timeout past that ships whatever pages
    # had already completed instead of discarding everything.
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        # Fetch both states concurrently — each state does its own pagination
        # but the two states are independent, so we parallelize them.
        # self.partial is the SAME list both _fetch_state calls append into
        # as each page completes (see its partial_sink param), so
        # base_scraper.safe_run()'s existing timeout-salvage path has real
        # rows to ship if timeout_s fires mid-sweep.
        out = self.partial
        tasks = [_fetch_state(state, self.slug, out) for state in STATES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # NOTE: each _fetch_state call already appended its rows into `out`
        # (== self.partial) as it went via partial_sink -- do NOT also
        # out.extend(result) here, that would double every row (once from
        # the live partial_sink append, once more from the returned list).
        # `results` is only inspected for exceptions below.
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning(
                    "homepath_json.state_failed",
                    state=STATES[i], error=str(result)[:200],
                )
        log.info("homepath_json.done", total=len(out))
        return out

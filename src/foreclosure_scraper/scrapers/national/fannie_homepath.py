"""Fannie Mae HomePath REO — direct JSON API by bounding box.

Fannie's HomePath SPA queries an unauthenticated JSON endpoint:

  GET https://homepath.fanniemae.com/cfl/property-inventory/search
      ?bounds={lat_sw},{lng_sw},{lat_ne},{lng_ne}

Returns up to ~400 properties per request inside the bbox with:
  addressLine1, city, county, state, zipCode, bedrooms, bathrooms, sqft,
  yearBuilt, price, propertyType, reoId, mlsId, primHiResImageUrl, geoPoint,
  listingStartDate (epoch ms), retailStatus, onlineOfferOnly, ...

We query NC and SC bboxes (slightly tight to limit out-of-state spillover)
and filter results by state. Listings include TN/VA edge cases when the
bbox overlaps; the post-fetch state filter drops them.

Fannie's own `county` field is sometimes blank (confirmed live 2026-10-03,
national/reo per-column audit for lt_reo: 67/857 NC+SC rows, 7.8%) even
though `city`/`zipCode`/`geoPoint` are present -- e.g. "94 Crestview
Heights, Franklin, NC 28734" (Macon County) and "45 Sugar Cove Road,
Weaverville, NC" (Buncombe County, one of our 18 footprint counties). REO
is a FLIP listing type (main._FLIP_LISTING_TYPES), which gates on the
narrow in_scope(county, state) check -- and in_scope(None, state) is
unconditionally False -- so a blank county here silently drops a real
in-footprint lead at the scope gate exactly the way zillow_foreclosures.py
documented and fixed for the same reason (2026-10-01 national/reo audit).
Fall back to the same WNC/upstate-footprint gazetteer that fix uses, then
the full 146-county bankruptcy-caption gazetteer (Fannie's bboxes are
genuinely statewide, not footprint-only, so the narrower gazetteer alone
leaves most non-footprint counties unresolved), then the coastal gazetteer
for parity with zillow_foreclosures.py's fallback chain.
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
from ..._bankruptcy_city_to_county import bankruptcy_county_for
from ..._coastal_city_to_county import coastal_county_for
from ..._upstate_city_to_county import upstate_county_for

log = structlog.get_logger()

API = "https://homepath.fanniemae.com/cfl/property-inventory/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://homepath.fanniemae.com/",
}

# (state, lat_sw, lng_sw, lat_ne, lng_ne) — bbox boundaries for our 2-state scope.
# Fannie's API caps at 400 properties per request. A single NC+SC bbox returns
# ~400 but totalProperties is 26,955 nationwide. We subdivide each state into
# a grid of smaller bboxes so we stay under the 400-per-request ceiling and
# capture every listing. Grid cells are ~0.7 degrees (~50mi) which yields
# 10-80 properties per cell in NC/SC density.
BBOXES = (
    ("NC", 33.75, -84.50, 36.60, -75.30),
    ("SC", 32.00, -83.40, 35.25, -78.50),
)

# Grid subdivision: split each state bbox into NxM cells to stay under the
# 400-per-request API cap. Tuned so no cell in NC/SC exceeds ~200 results.
#
# That tuning assumption is STALE -- confirmed live 2026-10-01 (national/reo
# per-source audit): 13 of the 32 current NC+SC cells return EXACTLY 400
# properties (the hard per-request cap), several of them 400 on the nose,
# which is precisely the "a round number is a cap until proven otherwise"
# smell CLAUDE.md calls out by name. _fetch_bbox now pages within each cell
# (see MAX_PAGES_PER_CELL below) instead of trusting a single page=1 request
# to be the whole cell.
_GRID_ROWS = 4
_GRID_COLS = 4

# A single page's hard cap, confirmed live 2026-10-01 (every request, every
# cell, regardless of the pageSize value sent). Used to detect "this page was
# full, there may be more" rather than hardcoding 400 in two places.
_PAGE_CAP = 400
# Safety ceiling on pages fetched per cell.
#
# MEASURED 2026-10-01, live: on a saturated cell, repeated paging is NOT a
# stable non-overlapping offset (the API shuffles results -- the same top
# property reappeared on all 15 pages tried), so each extra page has
# diminishing but real returns: a live union-of-distinct-propertyUuids probe
# on one cell went 400 -> 544 -> 638 -> 658 -> 667 -> 671 (pages 1-6), i.e.
# most of the easy gain lands in the first few pages. Raising this past 4
# was tried first (10) and MEASURED to regress the whole scraper: 32 cells
# each doing up to 10 sequential pages blew the then-150s timeout_s, and
# self.partial salvaged only 83 rows -- far WORSE than the pre-fix baseline
# (thousands of rows, OUTCOME_OK, finishing in ~30-50s) despite the fix
# being individually correct. 4 pages/cell (1,600 theoretical ceiling per
# cell) plus the timeout_s increase below keeps a full run finishing
# OUTCOME_OK while still recovering most of the previously-lost rows on
# saturated cells.
MAX_PAGES_PER_CELL = 4


def _subdivide(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
               rows: int = _GRID_ROWS, cols: int = _GRID_COLS) -> list[tuple[float, float, float, float]]:
    """Split a bbox into a rows x cols grid of smaller bboxes."""
    dlat = (ne_lat - sw_lat) / rows
    dlng = (ne_lng - sw_lng) / cols
    cells: list[tuple[float, float, float, float]] = []
    for r in range(rows):
        for c in range(cols):
            cells.append((
                sw_lat + r * dlat,
                sw_lng + c * dlng,
                sw_lat + (r + 1) * dlat,
                sw_lng + (c + 1) * dlng,
            ))
    return cells


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
    state = (p.get("state") or "").strip().upper()
    if state not in ("NC", "SC"):
        return None
    addr = (p.get("addressLine1") or "").strip() or None
    if not addr:
        return None
    uuid = p.get("propertyUuid") or p.get("reoId") or p.get("mlsId")
    geo = p.get("geoPoint") or {}
    img_url = p.get("primHiResImageUrl") or p.get("primaryImageUrl")
    photos = [img_url] if img_url and isinstance(img_url, str) and img_url.startswith("http") else []
    listing_ms = p.get("listingStartDate")
    first_seen = datetime.utcnow()
    if isinstance(listing_ms, (int, float)) and listing_ms > 0:
        try:
            first_seen = datetime.fromtimestamp(listing_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OSError):
            pass
    year_built_raw = p.get("yearBuilt")
    try:
        year_built = int(year_built_raw) if year_built_raw else None
    except (TypeError, ValueError):
        year_built = None
    city = (p.get("city") or "").strip() or None
    county = canonical_county((p.get("county") or "").replace(" COUNTY", "")) or None
    if not county:
        # Fannie's own county field is blank for a real chunk of rows (see module
        # docstring) -- fall back to a city->county gazetteer the same way
        # zillow_foreclosures.py already does for this identical bug class.
        county = (
            upstate_county_for(city, state)
            or bankruptcy_county_for(city, state)
            or coastal_county_for(city, state)
        )
    return Listing(
        source=slug,
        source_url=f"https://homepath.fanniemae.com/property/{uuid}" if uuid else "https://homepath.fanniemae.com/",
        listing_type=ListingType.REO,
        property_kind=_PROP_KIND_MAP.get((p.get("propertyType") or "").strip(), PropertyKind.UNKNOWN),
        state=state,
        county=county,
        city=city.title() if city else None,
        zip_code=(p.get("zipCode") or "").strip() or None,
        street_address=addr,
        case_number=f"fannie-{uuid}" if uuid else None,
        latitude=geo.get("latitude") if isinstance(geo.get("latitude"), (int, float)) else None,
        longitude=geo.get("longitude") if isinstance(geo.get("longitude"), (int, float)) else None,
        opening_bid=p.get("price") if isinstance(p.get("price"), (int, float)) else None,
        # FOUND 2026-10-04 (HERMES extraction-completeness audit, batch 18):
        # identical bug to the sibling national.homepath_json (fixed batch
        # 17, commit c81124b6) -- this module's raw dict is line-for-line the
        # same shape, and NONE of bedrooms/bathrooms/sqft/year_built/mls_id/
        # retail_status/online_offer_only/first_look were ever registered in
        # web_artifact.RAW_KEEP, so every one of them was silently dropped at
        # publish on every row this scraper has ever produced (live-verified
        # 2026-10-04: a real current Waynesville, NC / Haywood County row
        # carries bedrooms=3.0, bathrooms=5.0, sqft=3531, yearBuilt=2005, all
        # genuinely populated on the live API). Same fix pattern: promote the
        # property-characteristic fields to first-class Listing kwargs
        # (always serialized, sidesteps RAW_KEEP entirely).
        bedrooms=_safe_float(p.get("bedrooms")),
        bathrooms=_safe_float(p.get("bathrooms")),
        living_sqft=_safe_float(p.get("sqft")),
        year_built=year_built,
        description=(
            f"Fannie Mae HomePath REO "
            f"{p.get('propertyType') or ''} "
            f"{int(p.get('bedrooms')) if p.get('bedrooms') else ''}bd/"
            f"{int(p.get('bathrooms')) if p.get('bathrooms') else ''}ba "
            f"{int(p.get('sqft')) if p.get('sqft') else ''} sqft"
        ).strip(),
        first_seen=first_seen,
        last_seen=datetime.utcnow(),
        raw={
            "reo_id": p.get("reoId"),
            "images": {"real": photos} if photos else {},
            "fannie_homepath": {
                "mls_id": p.get("mlsId"),
                "property_uuid": p.get("propertyUuid"),
                "retail_status": p.get("retailStatus"),
                "online_offer_only": p.get("onlineOfferOnly"),
                "first_look": bool(p.get("firstLookProgramIndicator")),
            },
        },
    )


async def _fetch_bbox(state: str, sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float, slug: str) -> list[Listing]:
    """Fetch one grid cell, paginating with page=N for as long as a page
    comes back full (== _PAGE_CAP) -- a full page means the cell may hold
    more than one request's worth. Confirmed live 2026-10-01: with `bounds`
    present, `page` genuinely returns distinct, correctly geo-filtered
    results (unlike the sibling national.homepath_json's confirmed-broken
    bare state/zipcode/page call, which the API silently ignores -- bounds
    is what makes page real).

    The API's pagination is NOT a stable, non-overlapping offset -- confirmed
    live on a saturated cell: the top-ranked property reappeared on every one
    of 15 consecutive pages, and consecutive pages overlapped 40-70% rather
    than being disjoint. It does still surface real NEW properties as paging
    continues (a 15-page live probe found the union of distinct propertyUuids
    growing from 400 -> 915 with diminishing but nonzero new-per-page counts,
    not a hard plateau at 400), so paging past page 1 is still a real net
    gain -- it just means this function must dedupe by propertyUuid WITHIN a
    cell itself, not only rely on the caller's cross-cell dedup."""
    bounds = f"{sw_lat},{sw_lng},{ne_lat},{ne_lng}"
    out: list[Listing] = []
    seen_uuid: set[str] = set()
    total_in_bbox = 0
    nationwide_total = None
    async with client(timeout=30.0) as c:
        for page in range(1, MAX_PAGES_PER_CELL + 1):
            params = {"bounds": bounds, "page": str(page)}
            try:
                r = await c.get(API, params=params, headers=HEADERS, follow_redirects=True)
            except Exception as exc:
                log.warning("fannie_homepath.fetch_failed", state=state, page=page,
                            error=str(exc)[:200])
                break
            if r.status_code != 200:
                log.warning("fannie_homepath.bad_status", state=state, page=page,
                            code=r.status_code)
                break
            try:
                payload = r.json()
            except Exception:
                break
            props = payload.get("properties") or []
            total_in_bbox += len(props)
            for p in props:
                uuid = p.get("propertyUuid") or p.get("reoId") or p.get("mlsId")
                if uuid and uuid in seen_uuid:
                    continue
                li = _to_listing(p, slug)
                if li is None:
                    continue
                if uuid:
                    seen_uuid.add(uuid)
                out.append(li)
            if page == 1:
                nationwide_total = payload.get("totalProperties")
            if len(props) < _PAGE_CAP:
                break  # a short page is the last page
            log.info("fannie_homepath.cell_page_full", state=state, page=page,
                      props=len(props), cap=_PAGE_CAP,
                      note="page was full, fetching page+1 in case the cell has more")
    log.info(
        "fannie_homepath.bbox_done", state=state,
        in_bbox=total_in_bbox, kept_in_state=len(out),
        total_nationwide=nationwide_total,
    )
    return out


async def _fetch_bbox_indexed(
    i: int, state: str, cell: tuple[float, float, float, float], slug: str
) -> tuple[int, list[Listing] | Exception]:
    """Wrap `_fetch_bbox` so `asyncio.as_completed` results can still be
    attributed to a cell index for logging, and so one cell's exception
    doesn't cancel its siblings (mirrors the old gather(return_exceptions=True)
    behavior, but per-cell instead of per-state -- see fetch()'s docstring)."""
    try:
        return i, await _fetch_bbox(state, cell[0], cell[1], cell[2], cell[3], slug)
    except Exception as exc:  # noqa: BLE001
        return i, exc


class FannieHomePath(BaseScraper):
    slug = "national.fannie_homepath"
    name = "Fannie Mae HomePath (REO, JSON API)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # 2026-09-22: measured 53s to complete a full NC+SC bbox sweep when run ALONE (the
    # enrichment_reo_freshness.prune_stale_reo call, 09:42:06-09:42:59, 8,277 rows). The
    # SAME sweep inside scripts/daily_api_refresh.py's 14-way asyncio.gather timed out at
    # 60s every day (network/event-loop contention from the other 13 scrapers running at
    # once), so this source read 0 and was carried over daily -- defeating the refresh's
    # stated purpose of clearing sold REO 404s (audit 2026-09-21, O6).
    #
    # 2026-10-01 (national/reo per-source audit): _fetch_bbox now pages within
    # a saturated cell (MAX_PAGES_PER_CELL, see its own comment for why the
    # old single-page-per-cell approach silently dropped real rows on 13 of
    # 32 cells hitting the 400 cap). MEASURED live, run alone: a full sweep
    # now takes ~152s (up from 53s) and returns 10,186 rows (up from the old
    # single-page ceiling's 8,277) with zero duplicates. First tried
    # MAX_PAGES_PER_CELL=10, which MEASURED at 150s+ and only salvaged 83
    # rows via timeout -- worse than doing nothing. 4 pages/cell plus 300s
    # here (roughly 2x the clean-run measurement, matching this project's
    # usual contention margin, e.g. national.homepath_json's ~110s clean run
    # -> 240s timeout_s) is the balance that was actually measured to finish
    # OUTCOME_OK rather than degrade to a timeout-salvaged partial.
    timeout_s = 300.0

    async def fetch(self) -> Iterable[Listing]:
        # Bank rows into self.partial PER CELL, as each of the 32 bbox fetches
        # completes -- not only after a whole state's asyncio.gather returns.
        #
        # MEASURED 2026-09-22/23 (logs/local-run-20260922T111425.log, lines
        # 41-224; docs/full_run_execution_audit_2026-09-23.md section "fannie_
        # homepath fix -- did it behave as expected?"): the 09/22 main-scrape-
        # phase run of this scraper started 15:14:34.475753Z and did NOT hit its
        # own timeout_s=150 deadline on schedule -- it fired at 15:23:19.851313Z,
        # 8m45s later. In that same window, exactly ONE other event source
        # (national.foreclosure_dot_com, which ran back-to-back per-city fetches
        # for ~8 minutes straight) logged anything at all; every other in-flight
        # scraper, and this one's own remaining SC bbox cells, produced NO log
        # output until foreclosure_dot_com finished -- at which point FOUR
        # scrapers' timeouts (this one included) and several scraper.start events
        # all fired within the same ~50ms. That is event-loop starvation by a
        # sibling scraper, not this scraper needing more time: by 15:15:01 (27s
        # in) it had already cleanly fetched all 16 NC cells (~6,000+ rows) plus
        # the first SC cell -- comfortably inside even the OLD 60s budget -- and
        # then simply never got scheduled again until it was cancelled.
        #
        # Raising timeout_s further would not fix starvation (the deadline itself
        # fires late, however large it is) -- see test_fannie_homepath_timeout.py,
        # which pins the existing 150s floor/ceiling and is intentionally NOT
        # touched here for lack of evidence a bigger number would help. What WAS
        # a real, fixable bug: `fetch()` only returned data at the very end, so
        # the eventual cancellation discarded the entire NC pull it had already
        # collected. Appending to self.partial as each cell resolves means a
        # future timeout -- from genuine slowness OR another starvation episode --
        # ships whatever was already fetched (base_scraper's existing
        # OUTCOME_PARTIAL salvage path in safe_run()) instead of 0 rows.
        out = self.partial
        seen: set[str] = {li.case_number for li in out if li.case_number}
        for state, sw_lat, sw_lng, ne_lat, ne_lng in BBOXES:
            cells = _subdivide(sw_lat, sw_lng, ne_lat, ne_lng)
            tasks = [
                _fetch_bbox_indexed(i, state, c, self.slug)
                for i, c in enumerate(cells)
            ]
            for coro in asyncio.as_completed(tasks):
                i, result = await coro
                if isinstance(result, Exception):
                    log.warning("fannie_homepath.cell_failed", state=state,
                                cell=i, error=str(result)[:200])
                    continue
                for li in result:
                    if li.case_number and li.case_number in seen:
                        continue
                    if li.case_number:
                        seen.add(li.case_number)
                    out.append(li)
        log.info("fannie_homepath.done", total=len(out), cells=len(BBOXES) * _GRID_ROWS * _GRID_COLS)
        return out

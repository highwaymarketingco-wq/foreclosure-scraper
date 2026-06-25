"""Crexi multifamily / apartment listings for NC + SC via Scrapling stealth.

Fills the MULTIFAMILY / APARTMENT track. Before this scraper there were ZERO
dedicated multifamily sources — the dashboard "Multifamily" tab was just
incidental Fannie/distressed single-family rows, and RAW_KEEP referenced a
"loopnet" source that never existed (LoopNet hard-blocks: plain + stealth
fetches both return HTTP 403).

Source selection (researched + verified 2026-06-24):
  * auction.com /residential/ has no usable multifamily category (its JSON-LD
    is all ``SingleFamilyResidence``; the residential DOM barely references
    "multi"). Its multifamily/commercial inventory lives on Ten-X → LoopNet,
    which is login-gated + 403-walled. Not viable free.
  * HUD's "Weekly Listing of Multifamily Properties for Sale"
    (hud.gov/helping-americans/mf-properties-list) is genuinely free but is a
    NATIONAL list that currently holds ~2 properties, neither in NC/SC. Almost
    never in-footprint — not worth a dedicated scraper (kept as a documented
    fallback).
  * Crexi exposes a free, no-login, state-scoped multifamily search at
    ``/properties/{ST}/Multifamily``. It renders fully via the local Scrapling
    stealth browser (Cloudflare-challenged, but StealthyFetcher passes), 200 OK,
    ~60 listings/page, real pagination via ``?page=N`` (page 2 returned 52 net-
    new ids in testing). NC and SC each return 60+ multifamily listings on page
    1. This single channel includes auction/distressed rows inline. The
    ``/properties/{ST}/Auctions/Multifamily`` sub-channel was tested too but is
    flaky — for some states it 302-redirects to a ``/search/...`` page with a
    different DOM that carries no ``/properties/`` slugs — so it is NOT used;
    the general channel already surfaces those listings.

Capture model (same approach as auction_dot_com.py — slug capture):
  The Angular SPA renders listing cards client-side and does NOT embed an
  address/units JSON blob in the page source. What IS in the rendered DOM is
  the full set of detail-link slugs:
      /properties/<id>/<state-name>-<human-title-slug>
  e.g. ``/properties/2489600/north-carolina-1110-1112-clark-street``,
       ``/properties/.../north-carolina-4489-orphanage-road---126-units---charlotte-msa``,
       ``/properties/.../south-carolina-columbia-sc-brick-quadraplex-for-sale``.
  The slug carries the state, almost always a street address or property name,
  and frequently a unit count ("126-units") and/or city. We parse those out of
  the slug (defensively) and keep the detail URL as a reachable link. Per-
  listing detail pages DO carry Units / Cap Rate / Price / Year Built as
  labeled fields, but each detail page is a ~90s stealth render, so fetching
  120+ of them per run is impractical — slug parsing + the detail link is the
  right cost/coverage tradeoff (a downstream enricher can hydrate specifics).

Listing typing:
  * All rows -> ListingType.DISTRESSED (motivated-seller / investment / value-
    add signal). These are CRE for-sale multifamily listings — the closest free
    analog to a multifamily distress pipeline — and the general channel already
    folds in the auction-flagged rows (e.g. "15-fisher-triplex" appears in both
    the auctions sub-channel and the general feed). The slug carries no reliable
    auction marker, so we don't over-claim AUCTION.
  property_kind is always MULTI_FAMILY.

Free, no auth, no Apify, no CAPTCHA/login defeat.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ..._upstate_city_to_county import KNOWN_CITIES, upstate_county_for
from ..._coastal_city_to_county import coastal_county_for

log = structlog.get_logger()

BASE = "https://www.crexi.com"

# (state_code, full-state slug prefix Crexi bakes into detail slugs)
STATES = (
    ("NC", "north-carolina"),
    ("SC", "south-carolina"),
)

# Single robust channel: the state-scoped general multifamily for-sale feed,
# which renders reliably for both NC and SC and includes auction rows inline.
CHANNEL = "Multifamily"

# Pages to crawl per state (~60 listings/page). Each page is a ~90s stealth
# render, so keep this modest by default to fit the soft timeout — bump via
# CREXI_MULTIFAMILY_PAGES for a deeper crawl.
PAGES_CAP = 2

# Re-render attempts per page when Crexi serves an empty grid / redirect.
ATTEMPTS_PER_PAGE = 2

# /properties/<id>/<slug>
DETAIL_RE = re.compile(r"/properties/(\d+)/([a-z0-9][a-z0-9-]*)")
# "126-units" / "58-unit" / "14 unit" within a slug
UNITS_RE = re.compile(r"(\d{1,4})[-\s]?units?\b", re.I)
# leading street number + street body (defensive; multifamily slugs often lead
# with the address e.g. "1110-1112-clark-street", "4489-orphanage-road")
STREET_RE = re.compile(
    r"^(\d[\d-]*\s+.*?\b(?:road|rd|street|st|drive|dr|lane|ln|avenue|ave|"
    r"boulevard|blvd|highway|hwy|circle|cir|court|ct|way|place|pl|trail|trl|"
    r"parkway|pkwy|terrace|ter|run|loop|crossing|xing)\b)",
    re.I,
)

# Filler tokens we never want to treat as a city when guessing from the slug.
_NON_CITY = {
    "nc", "sc", "for", "sale", "msa", "investment", "property", "opportunity",
    "portfolio", "development", "apartments", "apartment", "townhomes",
    "townhome", "quadraplex", "quadplex", "triplex", "duplex", "fourplex",
    "units", "unit", "the", "at", "of", "in", "and", "new", "former",
    "redevelopment", "luxury", "student", "housing", "rental", "site",
    "approved", "fully", "prime", "historic", "assemblage", "lofts",
}


def _deslug(slug: str) -> str:
    """`brick-quadraplex-for-sale` -> `Brick Quadraplex For Sale`."""
    return re.sub(r"-{2,}", " ", slug).replace("-", " ").strip().title()


def _parse_slug(slug: str, state_prefix: str) -> dict:
    """Pull street / city / units / name out of a Crexi detail slug.

    Defensive: any field it can't recover stays None. The detail URL is always
    kept by the caller, so a low-confidence parse still yields a usable lead.
    """
    out: dict = {"street": None, "city": None, "units": None, "name": None}
    if not slug:
        return out
    body = slug
    # Strip the leading "<state-name>-" prefix Crexi prepends.
    if body.startswith(state_prefix + "-"):
        body = body[len(state_prefix) + 1:]
    out["name"] = _deslug(body) or None

    # Units, e.g. "126-units".
    um = UNITS_RE.search(body)
    if um:
        try:
            out["units"] = int(um.group(1))
        except (TypeError, ValueError):
            out["units"] = None

    # Street address: convert the slug body back to spaced text and look for a
    # leading "<number> <name> <suffix>".
    spaced = re.sub(r"-{2,}", " | ", body).replace("-", " ")
    sm = STREET_RE.search(spaced)
    if sm:
        out["street"] = re.sub(r"\s+", " ", sm.group(1)).strip().title()

    # City detection. Crexi slugs embed the city in many irregular shapes:
    #   "columbia-sc-brick-quadraplex"            (city then state code)
    #   "redevelopment-...-greenville-sc"         (city late, before state code)
    #   "spartanburg-greenville-multifamily-..."  (city as the lead token)
    #   "the-seneca-14" / "2nd-gen-...-clinton"   (city anywhere)
    #   "...-hartsville-sc-29550"                 (city then state then zip)
    # The token[1]==state heuristic alone missed almost everything, leaving
    # county None and the whole source filtered out at ingest. Instead, scan the
    # slug text for any KNOWN footprint/metro city (longest names first so
    # "north-charleston" / "boiling-springs" beat their single-token suffixes).
    spaced_full = re.sub(r"-+", " ", body).strip().lower()
    padded = f" {spaced_full} "
    for city in KNOWN_CITIES:
        if f" {city} " in padded:
            out["city"] = city.title()
            break
    if out["city"] is None:
        # Fallback to the original lead-token-before-state-code heuristic.
        toks = [t for t in body.split("-") if t]
        if len(toks) >= 2 and toks[1] in ("nc", "sc") \
                and toks[0] not in _NON_CITY:
            out["city"] = toks[0].title()
    return out


def _derive_county(city: str | None, state: str) -> str | None:
    """Map a parsed city to its county for footprint scoping. Tries the
    upstate/WNC gazetteer first, then the coastal lookup (oceanfront override).
    Returns the real county even when out-of-footprint, so the orchestrator's
    deny-set filters it deterministically instead of the blank-county zip
    fallback letting it slip through."""
    if not city:
        return None
    return (upstate_county_for(city, state)
            or coastal_county_for(city, state))


def _extract(html: str, state: str, state_prefix: str) -> dict[str, Listing]:
    """All in-state multifamily listings on one rendered page, keyed by id."""
    out: dict[str, Listing] = {}
    for m in DETAIL_RE.finditer(html):
        pid, slug = m.group(1), m.group(2)
        # Only keep this state's listings (slug is state-prefixed).
        if not slug.startswith(state_prefix):
            continue
        if pid in out:
            continue
        parsed = _parse_slug(slug, state_prefix)
        link = f"{BASE}/properties/{pid}/{slug}"
        # Prefer a real street address; else use the property name as the
        # street_address so the row still displays + dedupes on something.
        street = parsed["street"] or parsed["name"]
        if not street:
            continue
        # Derive county from the parsed city so the orchestrator's _in_scope
        # gate (which runs at INGEST, before the geocode/GIS enrichers) keeps
        # the upstate/WNC rows and denies the statewide Charlotte/Columbia/etc.
        county = _derive_county(parsed["city"], state)
        out[pid] = Listing(
            source="national.crexi_multifamily",
            source_url=link,
            listing_type=ListingType.DISTRESSED,
            property_kind=PropertyKind.MULTI_FAMILY,
            street_address=street,
            city=parsed["city"],
            county=county,
            state=state,
            case_number=f"crexi-{pid}",
            description=(
                "Crexi multifamily for-sale (CRE investment/value-add)"
                + (f" — {parsed['units']} units" if parsed["units"] else "")
            ),
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            raw={"loopnet": {  # RAW_KEEP whitelists "loopnet" for MF cap-rate/units
                "crexi_id": pid,
                "units": parsed["units"],
                "name": parsed["name"],
                "channel": "for_sale",
                "address_is_name": parsed["street"] is None,
            }},
        )
    return out


async def _render(url: str) -> tuple[str, str]:
    """Render ``url`` with the stealth browser; return (html, final_url).

    final_url lets the caller detect Crexi's intermittent A/B redirect of
    ``/properties/{ST}/Multifamily`` to a ``/search/...`` SEO landing page that
    carries no listing grid.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("crexi_multifamily.scrapling_missing")
        return "", url

    async def page_action(page):
        # Crexi sits behind Cloudflare and the Angular grid renders slowly +
        # variably (sometimes ~8s, sometimes 20s+). Wait generously for a
        # state-prefixed detail anchor specifically (not just any /properties/
        # link, which also appears in nav/footer), then scroll to trigger lazy
        # rows and let them settle.
        try:
            await page.wait_for_selector(
                "a[href*='/properties/2'], a[href*='/properties/1']",
                timeout=30000,
            )
        except Exception:
            pass
        try:
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(3500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=90000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("crexi_multifamily.fetch_fail", url=url,
                    error=str(exc)[:200])
        return "", url
    body = getattr(result, "body", b"")
    html = (
        body.decode("utf-8", errors="replace")
        if isinstance(body, bytes) else str(body or "")
    )
    final = getattr(result, "url", None) or url
    if not html or len(html) < 5000:
        return "", final
    return html, final


def _is_listing_page(final_url: str) -> bool:
    """True if the rendered URL is the canonical /properties/ listing grid
    (not the /search/ SEO landing page Crexi sometimes redirects to)."""
    return "/search/" not in (final_url or "")


async def _fetch_state(state: str, state_prefix: str,
                       pages_cap: int) -> dict[str, Listing]:
    out: dict[str, Listing] = {}
    for page in range(1, pages_cap + 1):
        # Pin mapZoom — the canonical listing grid always lands on
        # ...Multifamily?mapZoom=N; supplying it up front reduces the odds of
        # the /search/ redirect.
        zoom = 7 if state == "NC" else 8
        base_url = f"{BASE}/properties/{state}/{CHANNEL}?mapZoom={zoom}"
        if page > 1:
            base_url += f"&page={page}"

        # Crexi is flaky two ways: (a) intermittent A/B redirect to a /search/
        # SEO page with no grid, and (b) the grid sometimes hasn't rendered
        # when we read the DOM (Cloudflare + slow Angular). Both manifest as
        # zero in-state rows. Retry the render up to ATTEMPTS times until we get
        # a real grid.
        rows: dict[str, Listing] = {}
        for attempt in range(1, ATTEMPTS_PER_PAGE + 1):
            html, final = await _render(base_url)
            if html and _is_listing_page(final):
                rows = _extract(html, state, state_prefix)
                if rows:
                    break
            log.info("crexi_multifamily.retry", state=state, page=page,
                     attempt=attempt, landed=final, got=len(rows))
        if not rows:
            log.info("crexi_multifamily.no_grid", state=state, page=page)
            break
        new_this_page = 0
        for pid, li in rows.items():
            if pid in out:
                continue
            out[pid] = li
            new_this_page += 1
        log.info("crexi_multifamily.page_done", state=state,
                 page=page, found=len(rows), new=new_this_page, total=len(out))
        # No new ids -> exhausted the result set for this state.
        if new_this_page == 0:
            break
    return out


class CrexiMultifamily(BaseScraper):
    slug = "national.crexi_multifamily"
    name = "Crexi Multifamily (NC/SC)"
    category = "national_multifamily"
    expected_min_count = 0
    requires_apify = False
    requires_render = True
    # 2 states x PAGES_CAP pages x up-to-ATTEMPTS renders at ~90s each, plus
    # headroom. The common path (first attempt succeeds) is ~4 renders.
    timeout_s = 600.0

    async def fetch(self) -> Iterable[Listing]:
        pages_cap = int(
            os.environ.get("CREXI_MULTIFAMILY_PAGES", str(PAGES_CAP))
        )
        merged: dict[str, Listing] = {}
        for state, prefix in STATES:
            try:
                rows = await _fetch_state(state, prefix, pages_cap)
            except Exception as exc:
                log.warning("crexi_multifamily.state_failed",
                            state=state, error=str(exc)[:200])
                continue
            merged.update(rows)
            log.info("crexi_multifamily.state_done", state=state,
                     count=len(rows))
        out = list(merged.values())
        log.info("crexi_multifamily.done", total=len(out))
        return out

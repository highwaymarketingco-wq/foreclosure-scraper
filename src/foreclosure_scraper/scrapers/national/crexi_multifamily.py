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

ADDED 2026-10-13 (source-completeness audit, Pattern B): the slug-only
capture above never looked at a photo at all (not even one from a card/
JSON-LD teaser -- there's no such teaser on this Angular SPA's search
response). Live-confirmed against 3 real NC multifamily detail pages
(ids 2346159 / 2734804 / 2198267) that each one's own rendered detail page
carries a real multi-photo gallery (39 / 100 / 43 unique images
respectively) at ``https://crexi.com/images/format=auto,width=W,height=H/
assets/<this-listing-id>/<hash>.<ext>`` -- no login/paywall. The SAME CDN
also serves the "similar properties" sidebar's thumbnails and agent/user-
account headshots on that same page, under a *different* numeric id in the
path, so extraction must scope strictly to this listing's own id (see
``_extract_gallery_photos``).
Cost tradeoff: a detail page needs the identical ~20-90s Cloudflare-walled
stealth render as a search page (no cheap-httpx shortcut like
freddie_homesteps' plain-GET detail pages), so enriching every listing this
scraper can produce in one run (up to ~240) is flatly impractical. A small,
separately time-and-count-budgeted enrichment pass (see
``DETAIL_PHOTO_CAP`` / ``DETAIL_PHOTO_BUDGET_S``) fetches real photos for a
handful of listings per state; every other listing keeps today's behavior
(no ``images`` key) rather than the run stalling or losing listings.
"""
from __future__ import annotations

import os
import re
import time
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

# Photo-gallery detail-page enrichment budget (see module docstring and
# fetch()). Each detail render costs the same ~20-90s stealth fetch as a
# search-grid page (live-timed 2026-10-13: 14s / 14s / 71s across 3 live
# samples), so this is deliberately small -- a bounded handful of listings
# per state, inside a separate time ceiling, not "every listing." Override
# via env for a deeper enrichment pass if ever needed.
DETAIL_PHOTO_CAP = int(os.environ.get("CREXI_MULTIFAMILY_PHOTO_CAP", "6"))
DETAIL_PHOTO_BUDGET_S = float(
    os.environ.get("CREXI_MULTIFAMILY_PHOTO_BUDGET_S", "240")
)
# Max real photos to keep per listing, matching freddie_homesteps.py's cap.
GALLERY_CAP = 8

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


# A rendered detail page's real photo-gallery CDN URL, e.g.
#   https://crexi.com/images/format=auto,width=3000,height=2000/assets/
#   2346159/5efd8b736c264db681ac424e395d1c8f.JPG
# The same srcset repeats each photo at several widths (300/900/1200/1500/
# 3000 observed live) -- group(1) captures the width so the biggest variant
# per photo can be kept; group(2) is the numeric asset/listing id the photo
# belongs to (NOT necessarily this listing -- the same page also serves the
# "similar properties" sidebar's thumbnails under other listings' ids, and
# agent/user-account headshots under /user-accounts/<id>/, off the same CDN
# host); group(3) is the photo's own content hash + extension, which is
# stable across crop sizes and is what we dedupe on.
_GALLERY_RE = re.compile(
    r"https://crexi\.com/images/format=auto,width=(\d+),height=\d+"
    r"[^\"'\s)]*?/assets/(\d+)/([a-f0-9]{16,40}\.[A-Za-z]{3,4})"
)


def _extract_gallery_photos(html: str, pid: str, cap: int = GALLERY_CAP) -> list[str]:
    """This listing's own real photo gallery from its rendered detail page.

    Scoped strictly to ``/assets/{pid}/`` (live-confirmed 2026-10-13: a
    single detail page references up to a dozen *different* numeric asset
    ids -- this listing's own gallery plus the "similar properties" sidebar
    -- all off the identical CDN host/path shape, so matching the pattern
    without the id filter would silently attribute other listings' photos
    to this one). Multiple crop-size URLs sharing the same hash are the same
    photo; keep only the highest-resolution ("widest") variant, sorted
    widest-first so the cap keeps the best images.
    """
    best: dict[str, tuple[int, str]] = {}
    for m in _GALLERY_RE.finditer(html):
        width_s, asset_id, filename = m.group(1), m.group(2), m.group(3)
        if asset_id != pid:
            continue
        key = filename.lower()
        try:
            width = int(width_s)
        except ValueError:
            continue
        if key not in best or width > best[key][0]:
            best[key] = (width, m.group(0))
    ordered = sorted(best.values(), key=lambda t: -t[0])
    return [url for _, url in ordered[:cap]]


async def _fetch_detail_photos(pid: str, detail_url: str) -> list[str]:
    """Render ``detail_url`` and pull out this listing's own gallery.

    Any failure (fetch error, Cloudflare redirect, empty/short body, bad
    parse) degrades to an empty list -- the caller already has a usable
    listing from the search-grid slug; a failed photo fetch must never drop
    it or raise.
    """
    try:
        html, final = await _render(detail_url)
    except Exception as exc:
        log.warning("crexi_multifamily.photo_render_failed", pid=pid,
                    error=str(exc)[:160])
        return []
    if not html or not _is_listing_page(final):
        return []
    try:
        return _extract_gallery_photos(html, pid)
    except Exception as exc:
        log.warning("crexi_multifamily.photo_parse_failed", pid=pid,
                    error=str(exc)[:160])
        return []


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
    # 2 states x PAGES_CAP pages x up-to-ATTEMPTS renders at ~90s each for the
    # search grid (common path ~4 renders, ~360s), PLUS the bounded photo-
    # gallery enrichment pass added 2026-10-13 (up to DETAIL_PHOTO_BUDGET_S =
    # 240s more, each render costing the same ~20-90s stealth fetch as a
    # search page). Bumped from 600s to 900s to give the enrichment pass real
    # room without routinely tripping the soft timeout on the common path; if
    # it ever does, self.partial still ships whatever was banked so far.
    timeout_s = 900.0

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
            # Bank after each state: if the soft timeout fires mid-run,
            # base_scraper ships self.partial instead of discarding everything.
            self.partial[:] = list(merged.values())
            log.info("crexi_multifamily.state_done", state=state,
                     count=len(rows))

        # Bounded photo-gallery enrichment (see module docstring + the
        # DETAIL_PHOTO_CAP/DETAIL_PHOTO_BUDGET_S constants): a small handful
        # of listings per state get a real detail-page render for photos;
        # everything else keeps the pre-fix behavior (no "images" key) so a
        # listing is never dropped or the run stalled chasing every gallery.
        photo_deadline = time.monotonic() + DETAIL_PHOTO_BUDGET_S
        for state, _prefix in STATES:
            state_listings = [li for li in merged.values() if li.state == state]
            enriched = 0
            for li in state_listings[:DETAIL_PHOTO_CAP]:
                if time.monotonic() > photo_deadline:
                    log.info("crexi_multifamily.photo_budget_spent",
                             state=state, enriched=enriched)
                    break
                pid = (li.raw.get("loopnet") or {}).get("crexi_id")
                if not pid or not li.source_url:
                    continue
                try:
                    photos = await _fetch_detail_photos(pid, li.source_url)
                except Exception as exc:
                    # Belt-and-suspenders: _fetch_detail_photos already
                    # catches its own render/parse failures internally, but
                    # this listing must survive even if that helper itself
                    # has a bug -- a photo-enrichment failure is never
                    # allowed to take down the whole run.
                    log.warning("crexi_multifamily.photo_enrich_failed",
                                pid=pid, error=str(exc)[:160])
                    continue
                if photos:
                    li.raw["images"] = {"real": photos}
                    enriched += 1
                # Re-bank so a soft-timeout mid-enrichment ships any photos
                # already attached, not just the pre-enrichment rows.
                self.partial[:] = list(merged.values())
            log.info("crexi_multifamily.photo_enrichment_done", state=state,
                     attempted=min(len(state_listings), DETAIL_PHOTO_CAP),
                     enriched=enriched)

        out = list(merged.values())
        log.info("crexi_multifamily.done", total=len(out))
        return out

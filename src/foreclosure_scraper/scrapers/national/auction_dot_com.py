"""Auction.com via Scrapling stealth (no Apify, no paid).

Auction.com is a major foreclosure auction site. SPA-rendered, no public
JSON endpoint. Scrapling's StealthyFetcher renders the search page, then
we parse properties from the DOM.

Capture model (verified 2026-06-24):
  * The state search page embeds the FULL result set as detail-link slugs in
    the DOM, e.g. ``/details/1402-tom-pepper-rd-creswell-nc-2045737`` — every
    slug carries the ``-{state}-{id}`` tail, so street + city parse straight
    out of the slug (NC ~342, SC ~168). This is far more than the ~14 cards
    that render with a full address node.
  * One embedded JSON-LD block (``@graph`` of ``SingleFamilyResidence``)
    carries ~50 of those with rich data (zip / price / geo / specs); we join
    it onto the slug set by detail-URL to enrich where available.
  * There is no URL-addressable pagination (the SPA "Load More"s in place and
    embeds the whole set on page 1). We still wrap the fetch in a page loop on
    auction.com's path-pagination token as a best-effort, dedupe by
    detail-URL, and stop as soon as a page yields no new hrefs.

FIXED 2026-10-01 (national-auction-tier audit, batch 4): the JSON-LD
``address.addressLocality`` field is actually the COUNTY name, not the city
(verified live against every row on both state pages — e.g.
``addressLocality: "Gaston"`` for a Bessemer City, NC property) -- so
``city`` was silently wrong on every enriched row, and ``county`` (a real
Listing field) was never populated at all. ``node["name"]`` carries the
correct full line instead (``"<street> <City>, <ST> <ZIP>, <County>
County"``); see ``_parse_name_city_county``.

FIX 2026-10-04 (extraction-completeness audit, continued): the slug-fallback
path used for rows with NO JSON-LD node (only ~50 of ~510 statewide rows get
one, per the 2026-06-24 capture-model note above -- the fallback is the
MAJORITY case) took only the LAST hyphen token as the city, silently
truncating every multi-word city to its last word: live-verified real
in-footprint examples in the current NC render --
``165-fernwood-dr-forest-city`` (Forest City, Rutherford County) would have
produced city="City"; ``212-burton-farm-rd-browns-summit`` -> "Summit";
``152-scotland-ridge-dr-winston-salem`` -> "Salem". This run those three
happened to also have a JSON-LD node and so didn't hit the bug in practice,
but the fallback path itself was still broken for the next run where they
(or Lake Lure / Black Mountain / Old Fort / Mount Holly -- all real
in-footprint multi-word NC places) don't. Fixed using the SAME proven
longest-match-first city gazetteer `scrapers.national.crexi_multifamily`
already uses for its own slug-city extraction (``_upstate_city_to_county.
KNOWN_CITIES``) instead of a blind last-token split, and used the now-
accurate city to also backfill ``county`` via ``upstate_county_for`` for
fallback rows (previously always None -- only JSON-LD-enriched rows ever
got a county at all).

AUDITED, NOT FIXED (scoped out, documented rather than silently skipped):
  * ``opening_bid`` is null on every current row. This is NOT a parsing bug
    -- live-checked the raw JSON-LD on both state pages (100 rows) and
    NONE carry an ``offers`` key any more (confirmed previously-working
    extraction code is simply fed no data to extract). There is also no
    embedded JS state blob with pricing on the list page. The price now
    only appears to show on the per-LISTING DETAIL page, which this
    scraper does not fetch (only the two state list pages). Also found on
    the detail page: real, per-property PDFs under
    ``propertyDocuments/{id}/PURCHASE_AGREEMENT/`` and
    ``.../LOCAL_DISCLOSURE/`` (plus boilerplate ``globalDocuments/`` PDFs
    shared across every listing, not property-specific). Wiring either of
    these means fetching ~100+ individual detail pages per run through
    Scrapling's full stealth browser (several seconds each) -- a real
    architecture/runtime-cost change, not a field left unwired by mistake,
    so left as a flagged follow-up rather than rushed into this batch.

Free, no auth required.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Iterable

import structlog

from ..._upstate_city_to_county import KNOWN_CITIES, upstate_county_for
from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.auction.com/residential/nc/"),
    ("SC", "https://www.auction.com/residential/sc/"),
)

# Path-style pagination token auction.com uses internally, e.g.
# /residential/nc/page_2_p/ . Page 1 is the bare state URL.
PAGES_CAP = 25

JSONLD_RE = re.compile(
    r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S
)
# /details/<street-city-slug>-<st>-<id>
DETAIL_RE = re.compile(r"/details/([a-z0-9][a-z0-9-]*)-([a-z]{2})-(\d+)")
PRICE_RE = re.compile(r"\$([\d,]+)")


def _kind(raw: str | None) -> PropertyKind:
    if not raw:
        return PropertyKind.UNKNOWN
    s = str(raw).lower()
    if "single" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "land" in s or "lot" in s:
        return PropertyKind.LAND
    if "commercial" in s:
        return PropertyKind.COMMERCIAL
    if "mobile" in s or "manufactured" in s:
        return PropertyKind.MOBILE
    return PropertyKind.UNKNOWN


def _ltype_from_status(s: str) -> ListingType:
    s = (s or "").lower()
    if "auction" in s:
        return ListingType.AUCTION
    if "reo" in s or "bank" in s:
        return ListingType.REO
    if "fore" in s:
        return ListingType.FORECLOSURE_SALE
    return ListingType.AUCTION


def _split_slug_address(slug: str) -> tuple[str | None, str | None]:
    """Recover (street, city) from a detail slug like
    ``1402-tom-pepper-rd-creswell``. The city is always the trailing
    token(s); the rest is the street. Best-effort and defensive — returns
    (None, None) if it can't make sense of the slug.

    Checks KNOWN_CITIES (the same longest-match-first NC/SC gazetteer
    scrapers.national.crexi_multifamily already uses for this exact
    problem) FIRST, so a real multi-word city name (e.g. "Forest City",
    "Winston Salem", "Browns Summit") is recognized whole instead of
    silently truncated to its last word -- a bare last-token split would
    turn "forest-city" into just "City". Falls back to the last-token
    heuristic only when no known city matches the slug's tail.
    """
    if not slug:
        return None, None
    words = [w for w in slug.split("-") if w]
    if len(words) < 2:
        return None, None
    padded = f" {' '.join(words)} "
    for cand in KNOWN_CITIES:
        if padded.endswith(f" {cand} "):
            n = len(cand.split())
            if n < len(words):  # leave at least one street token
                city = cand.title()
                street = " ".join(words[:-n]).title()
                if len(street) >= 2:
                    return street, city
            break  # longest match found but unusable; don't fall through to a shorter false match
    # No known multi-word city matched — fall back to the last-token split.
    city = words[-1].title()
    street = " ".join(words[:-1]).title()
    if len(street) < 2:
        return None, None
    return street, city


def _jsonld_index(html: str, state: str) -> dict[str, dict]:
    """Map detail-id -> rich node dict for SingleFamilyResidence entries in
    the given state. Defensive: bad JSON is skipped."""
    idx: dict[str, dict] = {}
    for m in JSONLD_RE.finditer(html):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        graph = data.get("@graph", []) if isinstance(data, dict) else []
        for node in graph:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "SingleFamilyResidence":
                continue
            addr = node.get("address") or {}
            if not isinstance(addr, dict):
                continue
            if (addr.get("addressRegion") or "").upper() != state:
                continue
            url = node.get("url") or node.get("@id") or ""
            dm = DETAIL_RE.search(url)
            if not dm:
                continue
            idx[dm.group(3)] = node
    return idx


def _parse_name_city_county(name: str | None, street: str | None) -> tuple[str | None, str | None]:
    """auction.com's JSON-LD ``address.addressLocality`` is populated with
    the COUNTY name, not the city (verified live 2026-10-01 against every
    row on both state pages, e.g. ``addressLocality: "Gaston"`` for a
    Bessemer City, NC property) -- so ``city`` was silently wrong on every
    row, and ``county`` (a real Listing field) was never populated at all.
    The node's ``name`` field carries the correct, full line instead:
    ``"<street> <City>, <ST> <ZIP>, <County> County"``. Strip the already-
    known ``street`` prefix (case-insensitively -- ``name`` and
    ``address.streetAddress`` don't always match casing) and parse the
    remainder. Returns (city, county), either/both None if the shape
    doesn't match."""
    if not name:
        return None, None
    remainder = name.strip()
    if street and remainder.lower().startswith(street.strip().lower()):
        remainder = remainder[len(street.strip()):].strip()
    m = re.match(
        r"^(?P<city>.+?),\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?,\s*(?P<county>.+?)\s+County\s*$",
        remainder,
    )
    if not m:
        return None, None
    return m.group("city").strip() or None, m.group("county").strip() or None


def _node_listing(detail_id: str, slug: str, state: str,
                  node: dict | None) -> Listing | None:
    """Build a Listing for one detail-id, preferring JSON-LD ``node`` data
    and falling back to slug-parsed street/city."""
    link = (
        f"https://www.auction.com/details/{slug}-{state.lower()}-{detail_id}"
    )

    street = city = zip_code = county = None
    price = None
    images: list[str] = []
    kind = PropertyKind.UNKNOWN
    lat = lng = None
    beds = baths = sqft = year = None

    if node:
        addr = node.get("address") or {}
        if isinstance(addr, dict):
            street = addr.get("streetAddress") or None
            city = addr.get("addressLocality") or None
            zip_code = addr.get("postalCode") or None
        # FIXED 2026-10-01: addressLocality above is actually the county
        # (see _parse_name_city_county docstring) -- recover the real city
        # and the county (previously never captured) from node["name"].
        name_city, name_county = _parse_name_city_county(node.get("name"), street)
        if name_city:
            city = name_city
        county = name_county
        geo = node.get("geo") or {}
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lng = geo.get("longitude")
        beds = node.get("numberOfBedrooms")
        baths = node.get("numberOfBathroomsTotal")
        year = node.get("yearBuilt")
        fs = node.get("floorSize") or {}
        if isinstance(fs, dict):
            sqft = fs.get("value")
        kind = _kind(node.get("@type"))

        # Opening bid — the JSON-LD offer price. Was never read, so
        # opening_bid was null on every enriched row. offers can be a dict
        # or a list of dicts; price may be numeric or a "$123,456" string.
        offers = node.get("offers")
        raw_price = None
        if isinstance(offers, dict):
            raw_price = offers.get("price")
        elif isinstance(offers, list):
            for off in offers:
                if isinstance(off, dict) and off.get("price") is not None:
                    raw_price = off.get("price")
                    break
        if isinstance(raw_price, (int, float)):
            price = float(raw_price)
        elif isinstance(raw_price, str):
            pm = PRICE_RE.search(raw_price)
            if pm:
                try:
                    price = float(pm.group(1).replace(",", ""))
                except (TypeError, ValueError):
                    price = None

        # Property image(s) — node.image can be a string or list of strings.
        img = node.get("image")
        if isinstance(img, str) and img:
            images.append(img)
        elif isinstance(img, list):
            images.extend(str(i) for i in img if isinstance(i, str) and i)

    # Fall back to slug-derived street/city when JSON-LD absent.
    if not street:
        s_street, s_city = _split_slug_address(slug)
        street = s_street
        if not city:
            city = s_city
    if not street:
        return None

    # Fallback rows never got a county at all before (only the JSON-LD path
    # sets one, via _parse_name_city_county). Now that the slug-derived city
    # is accurate (see _split_slug_address's 2026-10-04 fix), backfill county
    # from the same gazetteer scrapers.national.crexi_multifamily uses — a
    # cheap, free win for every in-footprint fallback row.
    if not county and city:
        county = upstate_county_for(city, state)

    def _flt(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return Listing(
        source="national.auction_dot_com",
        source_url=link,
        listing_type=ListingType.AUCTION,
        property_kind=kind,
        street_address=street,
        city=city,
        county=county,
        state=state,
        zip_code=zip_code,
        opening_bid=price,
        latitude=_flt(lat),
        longitude=_flt(lng),
        case_number=f"auctioncom-{detail_id}",
        description="Auction.com foreclosure",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"auction_dot_com": {
            "detail_id": detail_id,
            "beds": _int(beds),
            "baths": _flt(baths),
            "sqft": _int(sqft),
            "year_built": _int(year),
            "enriched": node is not None,
            "images": images or None,
        }},
    )


def _extract_page(html: str, state: str) -> dict[str, Listing]:
    """All NC/SC listings on one rendered page, keyed by detail-id."""
    ld = _jsonld_index(html, state)
    out: dict[str, Listing] = {}
    # Slug hrefs are the full result set; iterate them and enrich from JSON-LD.
    for m in DETAIL_RE.finditer(html):
        slug, st, detail_id = m.group(1), m.group(2).upper(), m.group(3)
        if st != state:
            continue
        if detail_id in out:
            continue
        li = _node_listing(detail_id, slug, state, ld.get(detail_id))
        if li is not None:
            out[detail_id] = li
    return out


async def _render(url: str) -> str:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        log.warning("auction_dot_com.scrapling_missing")
        return ""

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "a[href*='/details/'], [data-elm-id*='property'], "
                "[data-testid*='property']",
                timeout=30000,
            )
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await page.wait_for_timeout(2500)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("auction_dot_com.fetch_fail", url=url,
                    error=str(exc)[:200])
        return ""
    body = getattr(result, "body", b"")
    html = (
        body.decode("utf-8", errors="replace")
        if isinstance(body, bytes) else str(body or "")
    )
    if not html or len(html) < 5000:
        return ""
    return html


async def _fetch_state(state: str, url: str, pages_cap: int) -> list[Listing]:
    out: dict[str, Listing] = {}
    for page in range(1, pages_cap + 1):
        # Page 1 is the bare state URL; subsequent pages use the path token.
        page_url = url if page == 1 else f"{url}page_{page}_p/"
        html = await _render(page_url)
        if not html:
            break
        page_rows = _extract_page(html, state)
        new_this_page = 0
        for detail_id, li in page_rows.items():
            if detail_id in out:
                continue
            out[detail_id] = li
            new_this_page += 1
        log.info("auction_dot_com.page_done", state=state, page=page,
                 found=len(page_rows), new=new_this_page, total=len(out))
        # No new detail-hrefs -> we've exhausted the (single-page) result set.
        if new_this_page == 0:
            break
    return list(out.values())


class AuctionDotCom(BaseScraper):
    slug = "national.auction_dot_com"
    name = "Auction.com"
    category = "national_auction"
    expected_min_count = 0
    requires_apify = False
    # FIX 2026-10-04: this scraper uses Scrapling StealthyFetcher (see
    # _render() above) like its law_firms.{korn,zacchaeus,
    # mcmichael_taylor_gray} siblings, all of which declare this -- it was
    # just never set here. main.py reads it in two places that both matter:
    # (1) carryover.carryover_for_zeroed_sources skips replaying stale data
    # for render-required sources (their own docstring: "zero is
    # acknowledged (paywall/apify/render-blocked)"), and (2) the run-report
    # buckets a render-required source's bad run as an ACKNOWLEDGED failure
    # mode rather than a REGRESSED alert. Without this, a flaky stealth-
    # browser run against auction.com's anti-bot defenses (expected for this
    # class of source) would have fired a false REGRESSED alarm instead of
    # being silently acknowledged like its siblings.
    requires_render = True
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        pages_cap = int(
            os.environ.get("AUCTION_DOT_COM_PAGES", str(PAGES_CAP))
        )
        out: list[Listing] = []
        for state, url in URLS:
            try:
                listings = await _fetch_state(state, url, pages_cap)
                out.extend(listings)
                log.info("auction_dot_com.state_done", state=state,
                         count=len(listings))
            except Exception as exc:
                log.warning("auction_dot_com.state_failed", state=state,
                            error=str(exc)[:200])
        return out

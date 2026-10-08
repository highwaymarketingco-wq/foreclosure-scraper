"""USDA Rural Development eligible homes + REO resales — usdaproperties.com.

usdaproperties.com aggregates USDA-eligible / Rural-Development resale homes
nationwide behind clean, server-rendered per-property URLs:

    https://usdaproperties.com/property/<state>/<zip>/<id>/

The site indexes inventory by county at

    https://www.usdaproperties.com/property/sc/county/<county-slug>/

and each county page server-renders a grid (``div#hgGrid``) of ``div.card``
tiles — no JS required. Every tile carries the full record in HTML +
data-attributes:

    <div class="card" data-price="55000" data-beds="3" data-baths="1.0"
         data-type="home" data-elig="1" data-zip="29372">
      <a class="lc-imgwrap" href="/property/sc/29372/6461163737/"> ...img... </a>
      <a class="lc-body-link" href="/property/sc/29372/6461163737/"><div class="cbody">
        <div class="cprice">$55,000</div>
        <div class="caddr">131 Sycamore St</div>
        <div class="cfacts">3 bd &middot; 1 ba &middot; 1,040 sqft</div>
      </div></a>
    </div>

Because we fetch by county page, every tile on a page is definitively in that
county, so we tag ``county`` directly (no derivation guesswork) and stay inside
the in-footprint SC scope. We only crawl the upstate-SC footprint counties
(config.SC_COUNTIES); the orchestrator scope-filter would drop anything else
anyway. REO listings carry no sale date, so the slug is in
main.DATELESS_OK_SOURCES.

FOUND 2026-10-04 (HERMES extraction-completeness audit, national batch 5),
both confirmed live against the real current site:

1. **A RAW_KEEP silent-drop**: `usda_eligible` (a real USDA zero-down-
   financing qualification flag, confirmed live True/False per card's own
   `data-elig` attribute) and `usda_data_type`/`facts` were all flat
   top-level `raw` keys with no RAW_KEEP entry -- silently dropped at every
   publish since this scraper was built. Fixed by namespacing under a new
   registered `"usda_properties"` key.
2. **A real, richly-detailed per-row miss, textbook HERMES sec 8 case**:
   each card's own detail page (e.g. `/property/sc/29323/9435895293/`,
   already derivable from the card but never fetched) is actually a
   syndicated Realtor.com/MLS listing page carrying, free, no login (plain
   curl-cffi impersonation, same as the county list page): the FULL photo
   gallery (confirmed live: 5 real `ap.rdcpix.com` photos on a sampled
   listing vs. the single thumbnail the list card carries), lot size in
   both acres and sqft, year built, a new-construction flag, garage spaces,
   HOA association + fee, a property-condition string ("Under
   construction"), and the listing brokerage/team name (a contactability
   signal, though usdaproperties.com's own CTA funnels through its own
   lead form rather than a direct agent phone). Wired as a best-effort
   per-row fetch capped at `DETAIL_FETCH_CAP` per county (the real card
   count runs 40-50+ per county across 7 counties -- an uncapped per-row
   fetch would mean 300+ extra requests per run).
"""
from __future__ import annotations

import html as html_lib
import re
import time
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

BASE = "https://www.usdaproperties.com"

# Upstate-SC footprint counties (mirrors config.SC_COUNTIES). The site slugs are
# the lowercase county name. Every card on a county page belongs to that county.
SC_COUNTY_SLUGS = (
    "spartanburg",
    "anderson",
    "pickens",
    "oconee",
    "cherokee",
    "union",
    "laurens",
)

_PRICE_RE = re.compile(r"([\d,]+)")
_SQFT_RE = re.compile(r"([\d,]+)\s*sqft", re.IGNORECASE)
_HREF_RE = re.compile(r"/property/([a-z]{2})/(\d{5})/(\d+)/")

# FOUND 2026-10-04 (batch 5, see module docstring): each card's own detail
# page is a richer syndicated MLS page. Capped per county -- real card
# counts run 40-50+ per county across 7 counties, so an uncapped per-row
# fetch would add 300+ requests per run.
DETAIL_FETCH_CAP = 15
_DETAIL_LABEL_RE = {
    "lot_sqft": re.compile(r"Lot Size Square Feet:\s*([\d,]+)"),
    "lot_acres": re.compile(r"Lot Size Acres:\s*([\d.]+)"),
    "year_built": re.compile(r"Year Built:\s*(\d{4})"),
    "new_construction": re.compile(r"New Construction:\s*(Yes|No)", re.I),
    "garage_spaces": re.compile(r"Garage Spaces:\s*(\d+)"),
    "hoa": re.compile(r"Association:\s*(Yes|No)", re.I),
    "hoa_fee": re.compile(r"Calculated Total Monthly Association Fees:\s*([\d,.]+)"),
    "condition": re.compile(r"Property Condition:\s*([^<]+?)</li>"),
}
_LISTED_BY_RE = re.compile(
    r'<div class="la-name"><a[^>]*>([^<]+)</a></div>\s*'
    r'<div class="la-office">([^<]+)</div>',
)


def _kind(data_type: str | None, facts: str | None) -> PropertyKind:
    t = (data_type or "").strip().lower()
    if t == "land" or (facts and "land" in facts.lower()):
        return PropertyKind.LAND
    if facts:
        f = facts.lower()
        if "condo" in f:
            return PropertyKind.CONDO
        if "town" in f:
            return PropertyKind.TOWNHOUSE
        if "manufactured" in f or "mobile" in f:
            return PropertyKind.MOBILE
    if t == "home":
        # USDA RD Section 502 inventory is single-family housing.
        return PropertyKind.SINGLE_FAMILY
    return PropertyKind.UNKNOWN


def _num(val: str | None) -> float | None:
    if not val:
        return None
    m = _PRICE_RE.search(val)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_card(card, county: str, slug: str) -> Listing | None:
    """Parse a single ``div.card`` tile. Returns None for unparseable rows."""
    link = card.css_first("a[href*='/property/']")
    href = link.attributes.get("href") if link is not None else None
    if not href:
        return None
    m = _HREF_RE.search(href)
    if not m:
        return None
    st, zip_code, prop_id = m.group(1).upper(), m.group(2), m.group(3)
    if st != "SC":
        return None
    source_url = f"https://usdaproperties.com/property/sc/{zip_code}/{prop_id}/"

    addr_node = card.css_first("div.caddr")
    street = addr_node.text(strip=True) if addr_node is not None else None
    if not street:
        img = card.css_first("img[alt]")
        street = img.attributes.get("alt") if img is not None else None
    street = re.sub(r"\s+", " ", street).strip() if street else None
    if not street:
        return None

    price_node = card.css_first("div.cprice")
    price = _num(price_node.text(strip=True)) if price_node is not None else None
    if price is None:
        price = _num(card.attributes.get("data-price"))

    facts_node = card.css_first("div.cfacts")
    facts = (
        re.sub(r"\s+", " ", facts_node.text(separator=" ", strip=True))
        if facts_node is not None
        else None
    )
    sqft = None
    if facts:
        sm = _SQFT_RE.search(facts)
        if sm:
            try:
                sqft = float(sm.group(1).replace(",", ""))
            except ValueError:
                sqft = None

    beds = _num(card.attributes.get("data-beds"))
    baths = _num(card.attributes.get("data-baths"))
    data_type = card.attributes.get("data-type")
    img_node = card.css_first("img[src]")
    img_url = img_node.attributes.get("src") if img_node is not None else None
    photos = [img_url] if img_url and img_url.startswith("http") else []

    return Listing(
        source=slug,
        source_url=source_url,
        listing_type=ListingType.REO,
        property_kind=_kind(data_type, facts),
        state="SC",
        county=county.title(),
        zip_code=zip_code,
        street_address=street,
        opening_bid=price,
        living_sqft=sqft,
        bedrooms=beds,
        bathrooms=baths,
        description=" ".join(
            p for p in ("USDA Rural Development eligible / REO resale.", facts) if p
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "usda_property_id": prop_id,
            "images": {"real": photos} if photos else {},
            # FOUND 2026-10-04 (batch 5): usda_data_type/usda_eligible/facts
            # were all flat top-level raw keys with no RAW_KEEP entry --
            # silently dropped at every publish since this scraper was
            # built. Namespaced under a new registered "usda_properties"
            # key; detail-page fields (see _fetch_detail) are merged in
            # by the caller.
            "usda_properties": {
                "data_type": data_type,
                "eligible": card.attributes.get("data-elig") == "1",
                "beds": beds,
                "baths": baths,
                "sqft": sqft,
                "facts": facts,
            },
        },
    )


async def _fetch_detail(detail_url: str) -> dict:
    """Best-effort enrichment from a usdaproperties.com card's own detail
    page -- a syndicated Realtor.com/MLS listing page carrying a full photo
    gallery, lot/garage/HOA/condition specs, and the listing brokerage.
    Returns {} on any failure; callers must treat this as optional."""
    out: dict = {}
    try:
        html = await get_text(detail_url, impersonate=True, timeout=20.0)
    except Exception as exc:
        log.warning("usda_properties.detail_fetch_fail", url=detail_url, error=str(exc)[:160])
        return out
    if not html or len(html) < 2000:
        return out
    try:
        tree = HTMLParser(html)
        photos = []
        for img in tree.css("img[src*='rdcpix.com']"):
            src = (img.attributes.get("src") or "").strip()
            if src.startswith("http") and src not in photos:
                photos.append(src)
        if photos:
            out["photos"] = photos
        for key, pattern in _DETAIL_LABEL_RE.items():
            m = pattern.search(html)
            if m:
                out[key] = m.group(1).strip()
        lb_m = _LISTED_BY_RE.search(html)
        if lb_m:
            out["listed_by"] = html_lib.unescape(lb_m.group(1).strip())
            out["brokerage"] = html_lib.unescape(lb_m.group(2).strip())
    except Exception as exc:  # noqa: BLE001
        log.warning("usda_properties.detail_parse_fail", url=detail_url, error=str(exc)[:160])
    return out


def _apply_detail(li: Listing, detail: dict) -> None:
    """Merge best-effort detail-page fields onto an already-built Listing."""
    if not detail:
        return
    photos = detail.get("photos")
    if photos:
        li.raw.setdefault("images", {})["real"] = photos
    lot_sqft = detail.get("lot_sqft")
    if lot_sqft:
        try:
            li.lot_size_sqft = float(str(lot_sqft).replace(",", ""))
        except ValueError:
            pass
    year_built = detail.get("year_built")
    if year_built:
        try:
            li.year_built = int(year_built)
        except ValueError:
            pass
    usda_ns = li.raw.setdefault("usda_properties", {})
    for k in ("lot_acres", "new_construction", "garage_spaces", "hoa",
              "hoa_fee", "condition", "listed_by", "brokerage"):
        if detail.get(k) is not None:
            usda_ns[k] = detail[k]


#: Share of timeout_s the per-card detail pages may use, split evenly across the counties. The
#: county's card rows are kept whether or not their detail page was reached in time.
DETAIL_BUDGET_SHARE = 0.75


async def _fetch_county(slug_scraper: str, county_slug: str,
                        deadline: float | None = None, keep=None) -> list[Listing]:
    """One county page's cards. Detail pages (at most DETAIL_FETCH_CAP) stop once
    time.monotonic() passes `deadline`; the remaining cards are kept without one. `keep(li)`, when
    given, is called on each parsed card BEFORE its detail page: it records the row (the scraper's
    partial list) and returns False for a duplicate, which is then skipped."""
    url = f"{BASE}/property/sc/county/{county_slug}/"
    try:
        html = await get_text(url, impersonate=True, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("usda_properties.fetch_failed", county=county_slug, error=str(exc)[:200])
        return []
    if not html or len(html) < 5000:
        return []
    tree = HTMLParser(html)
    cards = tree.css("div#hgGrid div.card") or tree.css("div.card")
    out: list[Listing] = []
    detail_fetches = 0
    for card in cards:
        try:
            li = _parse_card(card, county_slug, slug_scraper)
        except Exception:  # noqa: BLE001
            continue
        if li is None:
            continue
        if keep is not None and not keep(li):
            continue
        if detail_fetches < DETAIL_FETCH_CAP and (deadline is None or time.monotonic() < deadline):
            detail_fetches += 1
            try:
                detail = await _fetch_detail(li.source_url)
            except Exception:  # noqa: BLE001
                detail = {}
            _apply_detail(li, detail)
        out.append(li)
    log.info("usda_properties.county_done", county=county_slug, cards=len(cards),
             kept=len(out), detail_fetches=detail_fetches)
    return out


class USDAProperties(BaseScraper):
    slug = "national.usda_properties"
    name = "USDA Properties (Rural Development eligible / REO, SC)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # 120 s until 2026-10-08. Seven county pages plus up to DETAIL_FETCH_CAP detail pages each (up
    # to 112 requests to one host, spaced by the shared client) ran past it on alternate runs since
    # the detail pages were added 2026-10-04, and a timeout shipped 0 rows (336 on the runs that
    # finished). The detail budget below stops in time, and every finished county's rows are in
    # self.partial, so a cut-off ships them.
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out = self.partial
        seen: set[str] = set()

        def keep(li: Listing) -> bool:
            pid = li.raw.get("usda_property_id")
            if pid and pid in seen:
                return False
            if pid:
                seen.add(pid)
            out.append(li)          # before its detail page: a cut-off still ships the card
            return True

        start, budget = time.monotonic(), self.timeout_s * DETAIL_BUDGET_SHARE
        n = len(SC_COUNTY_SLUGS)
        for i, county_slug in enumerate(SC_COUNTY_SLUGS):
            try:
                await _fetch_county(self.slug, county_slug,
                                    deadline=start + budget * (i + 1) / n, keep=keep)
            except Exception as exc:  # noqa: BLE001
                log.warning("usda_properties.county_failed", county=county_slug, error=str(exc)[:200])
                continue
        log.info("usda_properties.done", total=len(out))
        return list(out)

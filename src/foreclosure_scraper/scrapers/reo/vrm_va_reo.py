"""VRM Properties — VA REO listings (federal source).

VRM Properties is the prime contractor managing VA-foreclosed properties
nationwide. Their public search at https://vrmproperties.com/ exposes
listings with a state filter and paginated server-rendered HTML — no
auth, no JS required (Bootstrap + jQuery only).

Volume is small per state but the listings are vet-foreclosure REO,
which often haven't yet hit MLS.

URL format:
  /Properties-For-Sale?state={NC|SC}&currentPage={N}&orderBy=default+desc&orderByText=Default

Each listing card has:
  - <a href="/Property-For-Sale/{id}/{slug}">
  - <h6 class="card-subtitle">$132,000</h6>
  - <p class="card-text properCase">street<br>city, ST  zip</p>
  - beds / baths / sqft as <span class="font-weight-bold">N&nbsp;<i ...></i></span>

We walk pages until we see no new listing-IDs (or a hard cap of 30 pages).
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

BASE = "https://vrmproperties.com"
STATES = ("NC", "SC")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
}

PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
NUM_RE = re.compile(r"([\d,]+)")
DETAIL_HREF_RE = re.compile(r"^/Property-For-Sale/(\d+)/")


def _parse_card(card, state: str, slug: str) -> Listing | None:
    a = card.css_first("a[href^='/Property-For-Sale/']")
    if not a:
        return None
    href = a.attributes.get("href", "")
    m = DETAIL_HREF_RE.match(href)
    if not m:
        return None
    listing_id = m.group(1)

    # Photo: <img class="img-fit" src="...">
    photos: list[str] = []
    img_node = card.css_first("img.img-fit, .img-ratio img")
    if img_node is not None:
        src = (img_node.attributes.get("src") or "").strip()
        # VRM uses a placeholder on error — drop that
        if src.startswith("http") and "featured-listing-house" not in src:
            photos.append(src)

    body = card.css_first(".card-body")
    if body is None:
        body = card

    addr_node = body.css_first("p.card-text.properCase")
    street = city = zip_code = None
    if addr_node is not None:
        raw = addr_node.html or ""
        # split on the <br>
        parts = re.split(r"<br\s*/?>", raw, flags=re.I)
        street = re.sub(r"<[^>]+>", "", parts[0]).strip().rstrip(",") if parts else None
        if len(parts) > 1:
            second = re.sub(r"<[^>]+>", "", parts[1]).strip()
            cm = re.match(r"^(.+?),\s*([A-Z]{2})\s+(\d{5})", second)
            if cm:
                city, _st, zip_code = cm.group(1).strip(), cm.group(2), cm.group(3)

    price = None
    price_node = body.css_first("h6.card-subtitle")
    if price_node is not None:
        pm = PRICE_RE.search(price_node.text(strip=True))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

    beds = baths = sqft = None
    for span in body.css("p.card-text.specs span"):
        txt = span.text(strip=True)
        i = span.css_first("i")
        title = (i.attributes.get("title") or "").lower() if i is not None else ""
        nm = NUM_RE.search(txt)
        if not nm:
            continue
        n = nm.group(1).replace(",", "")
        try:
            n_int = int(n)
        except ValueError:
            continue
        if "bed" in title:
            beds = n_int
        elif "bath" in title:
            baths = n_int
        elif "feet" in title or "ruler" in title:
            sqft = n_int

    return Listing(
        source=slug,
        source_url=f"{BASE}{href}",
        listing_type=ListingType.REO,
        property_kind=PropertyKind.SINGLE_FAMILY,  # VRM is overwhelmingly SFR
        state=state,
        city=city,
        zip_code=zip_code,
        street_address=street,
        case_number=f"vrm-{listing_id}",
        opening_bid=price,
        description=(
            f"VRM VA REO listing #{listing_id}"
            + (f" — {beds}bd/{baths}ba" if beds and baths else "")
        ),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={
            "vrm_id": listing_id,
            "beds": beds,
            "baths": baths,
            "sqft": sqft,
            "list_price": price,
            "images": {"real": photos} if photos else {},
        },
    )


async def _fetch_state(state: str, slug: str) -> list[Listing]:
    out: list[Listing] = []
    seen_ids: set[str] = set()
    async with client(timeout=30.0) as c:
        for page in range(1, 31):
            url = (
                f"{BASE}/Properties-For-Sale?state={state}&currentPage={page}"
                f"&orderBy=default+desc&orderByText=Default"
            )
            try:
                r = await c.get(url, headers=HEADERS, follow_redirects=True)
            except Exception as exc:
                log.warning("vrm.fetch_failed", state=state, page=page,
                            error=str(exc)[:200])
                break
            if r.status_code != 200 or len(r.text) < 1000:
                break
            tree = HTMLParser(r.text)
            cards = tree.css("div.card")
            new_this_page = 0
            for card in cards:
                if card.css_first("a[href^='/Property-For-Sale/']") is None:
                    continue
                li = _parse_card(card, state, slug)
                if li is None:
                    continue
                if li.case_number in seen_ids:
                    continue
                seen_ids.add(li.case_number)
                out.append(li)
                new_this_page += 1
            if new_this_page == 0:
                # No new listings on this page — we walked off the end.
                break
    log.info("vrm.state_done", state=state, count=len(out))
    return out


class VRMPropertiesVAREO(BaseScraper):
    slug = "reo.vrm_va_reo"
    name = "VRM Properties — VA REO (NC + SC)"
    category = "federal_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    disabled = True
    disabled_reason = ("froze the concurrent run on 2026-06-27 (in-flight at the 2h47m hang). "
                       "National VA REO, minimal in-footprint value. Re-enable after isolating "
                       "the blocking call or running it via asyncio.to_thread.")
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        for state in STATES:
            try:
                out.extend(await _fetch_state(state, self.slug))
            except Exception as exc:
                log.warning("vrm.state_failed", state=state, error=str(exc)[:200])
        log.info("vrm.done", total=len(out))
        return out

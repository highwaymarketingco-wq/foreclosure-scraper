"""Freddie Mac HomeSteps REO inventory.

The /listing/search page is server-rendered — no JS required for the
results list. The real filter is the free-text `?search=` param (the old
`?state=` param is ignored and returns the full nationwide list), so we
query `?search=NC` and `?search=SC`. Each result is a `div.property-teaser`
card wrapped in an `a[href^="/listingdetails/"]` anchor, with address,
price and beds/baths/sqft in `.property-address`, `.property-price` and
`.property-details`.

ADDED 2026-10-04 (national.* extraction-completeness audit, batch 16):
every listing's own `/listingdetails/<slug>` page (already captured as
`source_url`, but never fetched) carries real data the search-result card
never does — live-confirmed against a current NC listing (small volume:
13 NC + 14 SC today, so one extra request per listing is cheap):
  * **County** — the card has NO county at all today; the detail page's
    "Property Tax Roll Information" block states it plainly (e.g.
    "CALDWELL"). National/REO rows with no county get dropped outright by
    `main._countyless_national()`, so this isn't cosmetic — it is the
    difference between the row surviving to the board or not.
  * **4 more real photos** — the card/JSON-LD teaser only ever surfaces
    the FIRST image; the detail page's gallery has up to 5 (confirmed
    live: `...-1.jpg` through `...-5.jpg`), 80% of which were never seen.
  * **Precise lat/lng** (a `propertyLatLng` JS object on the page) and
    **listing-agent name + phone + email** — a real, free, direct contact
    channel (HERMES sec 9's #1 ceiling), confirmed live
    ("Damion Patton", "(828) 403-1756",
    "damionpattonrealestate@gmail.com"). The email is Cloudflare-
    obfuscated in the raw HTML (`/cdn-cgi/l/email-protection#<hex>`) but
    decodes with the standard single-byte XOR cipher — no login, no
    bypass, just reading what the page already sends every visitor's
    browser (the browser's own JS does the identical decode to render it).
  * Also captured: year built, lot size (acres), full baths, basement,
    exterior, heating/AC, parking — real structured specs that only ever
    reached the card as unstructured free text (or not at all).
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.homesteps.com/listing/search?search=NC"),
    ("SC", "https://www.homesteps.com/listing/search?search=SC"),
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
}

_PRICE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_NUM_RE = re.compile(r"([\d,]+)")
_ADDR_RE = re.compile(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?")
# "2 beds, 2 baths, 1,296 sq. ft." -- the only place beds/baths/sqft live on
# the card; found 2026-10-01 (national/reo per-source audit) never parsed
# into the Listing's own structured bedrooms/bathrooms/living_sqft fields
# (only kept as free text inside description).
_BBS_RE = re.compile(
    r"(\d+)\s*beds?,\s*(\d+(?:\.\d+)?)\s*baths?,\s*([\d,]+)\s*sq\.?\s*ft",
    re.I,
)
# The property-type badge this selector originally targeted is gone from the
# live markup (confirmed 2026-10-01: a kind_node match never fires on any of
# 26 live NC+SC cards, site redesign). The MLS photo filename still encodes
# it ("mls-homes/single-family-property/...", "mobile-manufactured-property",
# "condo-property", ...), so that is the fallback source for property type.
_IMG_KIND_RE = re.compile(r"/([a-z][a-z-]*-property)/")


def _kind(label: str | None) -> PropertyKind:
    if not label:
        return PropertyKind.UNKNOWN
    s = label.lower()
    if "single" in s or "detached" in s:
        return PropertyKind.SINGLE_FAMILY
    if "condo" in s:
        return PropertyKind.CONDO
    if "town" in s:
        return PropertyKind.TOWNHOUSE
    if "multi" in s or "duplex" in s:
        return PropertyKind.MULTI_FAMILY
    if "manufactured" in s or "mobile" in s:
        return PropertyKind.MOBILE
    if "land" in s:
        return PropertyKind.LAND
    return PropertyKind.UNKNOWN


def _photo_and_kind(row) -> tuple[str | None, str | None]:
    """The card's real listing photo (div.property-image img) and, as a
    fallback for the now-missing type badge, the MLS-feed type slug baked
    into that same image's filename. "no_photos.svg" is the site's own
    generic placeholder for a listing with no photo on file -- confirmed
    live on several SC rows -- and must not be reported as a real image."""
    img = row.css_first("div.property-image img, [class*='property-image'] img")
    if img is None:
        return None, None
    src = (img.attributes.get("src") or "").strip()
    if not src or src.endswith(".svg") or "no_photos" in src.lower():
        return None, None
    if src.startswith("//"):
        src = f"https:{src}"
    elif src.startswith("/"):
        src = f"https://www.homesteps.com{src}"
    km = _IMG_KIND_RE.search(src)
    return src, (km.group(1) if km else None)


def _wrapping_href(row) -> str | None:
    """Find the /listingdetails/ href for a card — either on the wrapping
    anchor (the card is nested inside <a>) or on an anchor inside the card."""
    inner = row.css_first("a.no-decoration[href^='/listingdetails/']") or row.css_first(
        "a[href^='/listingdetails/']"
    )
    if inner is not None:
        return inner.attributes.get("href")
    node = row.parent
    depth = 0
    while node is not None and depth < 5:
        if node.tag == "a":
            href = node.attributes.get("href")
            if href and "/listingdetails/" in href:
                return href
        node = node.parent
        depth += 1
    return None


def _parse_row(row, state: str) -> Listing | None:
    """Parse a single property-teaser card. Returns None for any unparseable
    row (no address)."""
    addr_node = row.css_first(
        "div.property-address, [class*='address'], .field--name-field-address"
    )
    if addr_node is None:
        addr = row.text(separator=" ", strip=True)
    else:
        addr = addr_node.text(separator=" ", strip=True)
    # The markup puts street/city/state/zip on separate lines, so collapse all
    # whitespace (incl. newlines) to single spaces BEFORE the address regex.
    addr = re.sub(r"\s+", " ", addr or "").strip()
    m = _ADDR_RE.search(addr)
    if not m:
        return None
    street, city, st, z = m.group(1).strip(), m.group(2).strip(), m.group(3), m.group(4)
    if st != state:
        return None

    price_node = row.css_first("div.property-price, [class*='price']")
    price = None
    if price_node is not None:
        pm = _PRICE_RE.search(price_node.text(strip=True))
        if pm:
            try:
                price = float(pm.group(1).replace(",", ""))
            except ValueError:
                price = None

    details_node = row.css_first("div.property-details")
    details_text = (
        re.sub(r"\s+", " ", details_node.text()).strip()
        if details_node is not None
        else None
    )

    kind_node = row.css_first("[class*='type'], [class*='property-type']")
    kind_text = kind_node.text(strip=True) if kind_node is not None else None

    photo, img_kind_slug = _photo_and_kind(row)
    # The badge kind_node was looking for no longer exists on the live page
    # (see _IMG_KIND_RE's comment) -- fall back to the type slug baked into
    # the photo filename so property_kind isn't UNKNOWN on every single row.
    kind_for_mapping = kind_text or img_kind_slug

    beds = baths = sqft = None
    bm = _BBS_RE.search(details_text or "")
    if bm:
        try:
            beds = int(bm.group(1))
            baths = float(bm.group(2))
            sqft = float(bm.group(3).replace(",", ""))
        except ValueError:
            beds = baths = sqft = None

    link = _wrapping_href(row) or "https://www.homesteps.com/"
    if link and not link.startswith("http"):
        link = f"https://www.homesteps.com{link}"

    li = Listing(
        source="national.freddie_homesteps",
        source_url=link,
        listing_type=ListingType.REO,
        property_kind=_kind(kind_for_mapping),
        state=st,
        city=city,
        zip_code=z,
        street_address=street,
        opening_bid=price,
        bedrooms=beds,
        bathrooms=baths,
        living_sqft=sqft,
        description=" ".join(
            p for p in ("Freddie Mac HomeSteps REO.", kind_text, details_text) if p
        ).strip(),
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"homesteps_kind": kind_text, "homesteps_details": details_text,
             "homesteps_img_kind_slug": img_kind_slug},
    )
    if photo:
        li.raw["images"] = {"real": [photo]}
    return li


_LATLNG_RE = re.compile(r"propertyLatLng:\s*\{\s*lat:\s*([\-\d.]+)\s*,\s*lng:\s*([\-\d.]+)")
_PHONE_RE = re.compile(r"Phone:\s*([\(\)\d\-\s]{7,20})")
_ACRES_RE = re.compile(r"([\d.]+)\s*acres?", re.I)
_GALLERY_IMG_RE = re.compile(r"rbimages\.blob\.core\.windows\.net")


def _decode_cfemail(hex_str: str) -> str | None:
    """Cloudflare's "email protection" obfuscation is a single-byte XOR
    cipher (the first hex byte is the key) -- the same decode the page's
    own JS runs client-side to render the address for a human visitor.
    Not a login/CAPTCHA bypass: this is the plain content the site already
    sends to every browser."""
    try:
        raw = bytes.fromhex(hex_str.strip())
        if not raw:
            return None
        key = raw[0]
        decoded = bytes(b ^ key for b in raw[1:])
        text = decoded.decode("utf-8", errors="strict")
        return text if "@" in text else None
    except (ValueError, UnicodeDecodeError):
        return None


def _parse_detail_page(html: str) -> dict:
    """Everything the card/JSON-LD teaser never carries: county, the full
    photo gallery, precise lat/lng, listing-agent contact, and the
    structured specs (year built, lot acres, full baths, etc.) that only
    ever reach the card as unstructured free text."""
    out: dict = {}
    tree = HTMLParser(html)

    specs: dict[str, str] = {}
    for li in tree.css("ul.detail-list li"):
        label_el = li.css_first("span")
        value_el = li.css_first("strong")
        if label_el is None or value_el is None:
            continue
        label = label_el.text(strip=True).rstrip(":").strip().lower()
        value = value_el.text(strip=True)
        if label and value and value.lower() != "none":
            specs[label] = value
    out["specs"] = specs

    county = specs.get("county")
    out["county"] = county.title() if county else None
    yb = specs.get("year built")
    if yb and yb.isdigit():
        out["year_built"] = int(yb)
    lot = specs.get("lot size") or ""
    am = _ACRES_RE.search(lot)
    if am:
        try:
            out["acreage"] = float(am.group(1))
        except ValueError:
            pass

    m = _LATLNG_RE.search(html)
    if m:
        try:
            out["latitude"] = float(m.group(1))
            out["longitude"] = float(m.group(2))
        except ValueError:
            pass

    # Full photo gallery -- the card/JSON-LD teaser only ever surfaces the
    # first image under this same CDN path.
    photos: list[str] = []
    for img in tree.css("img"):
        src = (img.attributes.get("src") or "").strip()
        if src and _GALLERY_IMG_RE.search(src) and src not in photos:
            photos.append(src)
    out["photos"] = photos[:8]

    # Listing-agent contact -- the one real, free, direct contactability
    # channel on this page (HERMES sec 9's #1 ceiling).
    agent: dict = {}
    for h2 in tree.css("h2"):
        if h2.text(strip=True) != "Agent Information":
            continue
        card = h2.parent
        if card is None:
            break
        p_el = card.css_first("p")
        if p_el is not None:
            text = p_el.text(separator="\n")
            first_line = next((l.strip() for l in text.split("\n") if l.strip()), None)
            if first_line:
                agent["name"] = first_line
            pm = _PHONE_RE.search(text)
            if pm:
                agent["phone"] = pm.group(1).strip()
        mail_a = card.css_first('a[href*="email-protection#"]')
        if mail_a is not None:
            href = mail_a.attributes.get("href") or ""
            frag = href.split("#", 1)[-1]
            email = _decode_cfemail(frag)
            if email:
                agent["email"] = email
        break
    out["agent"] = agent
    return out


#: Share of timeout_s the per-listing detail pages may use, split evenly across the states. The
#: list-page rows are handed to the scraper's partial list before any detail page, so a cut-off
#: ships them.
DETAIL_BUDGET_SHARE = 0.8


async def _fetch_state(state: str, url: str, sink: list | None = None,
                       deadline: float | None = None) -> list[Listing]:
    """One state's listings. `sink` (the scraper's self.partial) receives the list-page rows
    before the detail pages are fetched; detail pages stop once time.monotonic() passes
    `deadline`."""
    async with client(timeout=30.0) as c:
        try:
            r = await c.get(url, headers=HEADERS, follow_redirects=True)
        except Exception as exc:
            log.warning("freddie.fetch_failed", state=state, error=str(exc)[:200])
            return []
        if r.status_code != 200 or len(r.text) < 5000:
            return []
        tree = HTMLParser(r.text)
        out: list[Listing] = []
        cards = tree.css("div.property-teaser") or tree.css(
            ".views-row, [class*='property-listing'] article, [class*='listing-tile']"
        )
        # Only honor a "no results" short-circuit when there are genuinely no cards
        # — the phrase can appear in inert page chrome even when results exist.
        if not cards and ("No results found" in r.text or "no-results" in r.text):
            return []
        for row in cards:
            try:
                li = _parse_row(row, state)
            except Exception:
                continue
            if li is not None:
                out.append(li)
        if sink is not None:
            sink.extend(out)

        # Per-listing detail-page enrichment (county / full gallery /
        # lat-lng / agent contact — see module docstring). Small volume
        # (13 NC + 14 SC live 2026-10-04), one extra request each, same
        # client/connection reused.
        for n, li in enumerate(out):
            if deadline is not None and time.monotonic() > deadline:
                log.info("freddie.detail_budget_spent", state=state, fetched=n,
                         skipped=len(out) - n)
                break
            if not li.source_url or not li.source_url.startswith(
                "https://www.homesteps.com/listingdetails/"
            ):
                continue
            try:
                dr = await c.get(li.source_url, headers=HEADERS, follow_redirects=True)
            except Exception as exc:
                log.warning("freddie.detail_fetch_failed", url=li.source_url,
                            error=str(exc)[:160])
                continue
            if dr.status_code != 200 or len(dr.text) < 1000:
                continue
            try:
                detail = _parse_detail_page(dr.text)
            except Exception as exc:
                log.warning("freddie.detail_parse_failed", url=li.source_url,
                            error=str(exc)[:160])
                continue
            if detail.get("county") and not li.county:
                li.county = detail["county"]
            if detail.get("year_built") and not li.year_built:
                li.year_built = detail["year_built"]
            if detail.get("acreage") and not li.acreage:
                li.acreage = detail["acreage"]
            if detail.get("latitude") and detail.get("longitude") and not li.latitude:
                li.latitude = detail["latitude"]
                li.longitude = detail["longitude"]
            photos = detail.get("photos") or []
            if photos:
                have = li.raw.setdefault("images", {}).setdefault("real", [])
                for p in photos:
                    if p not in have:
                        have.append(p)
            if detail.get("agent"):
                li.raw["homesteps_agent"] = detail["agent"]
            if detail.get("specs"):
                li.raw["homesteps_specs"] = detail["specs"]
    return out


class FreddieHomeSteps(BaseScraper):
    slug = "national.freddie_homesteps"
    name = "Freddie Mac HomeSteps (REO)"
    category = "national_reo"
    expected_min_count = 0
    requires_apify = False
    requires_render = False
    # 60 s until 2026-10-08: the detail page added 2026-10-04 is one request per listing (~27),
    # spaced by the shared client, and the source timed out with 0 rows on every run since.
    timeout_s = 150.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        start, budget = time.monotonic(), self.timeout_s * DETAIL_BUDGET_SHARE
        for i, (state, url) in enumerate(URLS):
            try:
                listings = await _fetch_state(
                    state, url, sink=self.partial,
                    deadline=start + budget * (i + 1) / len(URLS))
                out.extend(listings)
                log.info("freddie.state_done", state=state, count=len(listings))
            except Exception as exc:
                log.warning("freddie.state_failed", state=state, error=str(exc)[:200])
        return out

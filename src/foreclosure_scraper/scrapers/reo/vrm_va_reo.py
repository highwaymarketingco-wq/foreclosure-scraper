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

EXTRACTION-COMPLETENESS AUDIT (2026-10-04, final batch). Two confirmed live
findings, both fixed here, on this batch's highest-volume source (193 real
current NC+SC rows):

1. **A 9th+ instance of the RAW_KEEP silent-drop pattern this whole 21-batch
   audit kept finding.** ``_parse_card()`` wrote ``raw["beds"]``/
   ``raw["baths"]``/``raw["sqft"]``/``raw["list_price"]`` as flat top-level
   keys -- ``_slim_raw()`` (web_artifact.py) only keeps a top-level key if
   it is literally named in ``RAW_KEEP``, and none of those 4 were.
   ``vrm_id``/``images`` happened to already be registered so they survived;
   the other 4 were silently dropped on every one of 193 real rows, every
   run, since this scraper existed. Fixed by namespacing them under a new
   registered ``raw["vrm_va_reo"]`` key (the repo's standard pattern for
   this exact bug class).
2. **Each listing's own detail page carries a lot never captured**,
   live-confirmed on a real current NC row: a FULL photo gallery (28 real
   photos vs. the single card thumbnail), the REAL listing agent's name /
   phone / email / license (HERMES sec 9's #1 priority -- free
   contactability, server-rendered, no login), the full narrative
   description (vs. the generic placeholder this scraper always built), an
   MLS ID, a parcel number (when known -- often literally "Unknown"), a
   refined property type (Townhome/Condo/etc, vs. the card's hardcoded
   SINGLE_FAMILY default), HOA, stories, and year built. Wired as a capped
   per-row detail fetch (real volume is large -- 193 rows -- so this is
   genuinely budgeted, unlike this batch's other, tiny-volume REO sources).
"""
from __future__ import annotations

import html
import os
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

# Real nationwide/NC+SC volume here is large (193 rows live-confirmed
# 2026-10-04), unlike this batch's other, tiny-volume REO sources -- so this
# cap is a genuine, deliberate limiter, not pure defensive headroom. Raise
# via env if a future run needs deeper coverage.
_DETAIL_FETCH_CAP = int(os.environ.get("VRM_DETAIL_CAP", "40"))

# The detail page's "House Facts" AND "Brokerage / Agent Information"
# sections share this exact col-6/col-6 label/value div-pair markup --
# live-confirmed stable across both sections on a real current NC listing.
_LABEL_VALUE_RE = re.compile(
    r'<div class="col-6[^"]*">([^<]*)</div>\s*<div class="col-6[^"]*">([^<]*)</div>',
    re.I,
)
_HOUSE_FACT_LABELS = {
    "mls id": "mls_id", "status": "status", "stories": "stories",
    "property type": "property_type", "hoa": "hoa",
    "parcel number": "parcel_number", "lot": "lot_text",
    "year built": "year_built_text",
}
_AGENT_LABELS = {
    "name": "agent_name", "phone": "agent_phone",
    "email": "agent_email", "license": "agent_license",
}
_GALLERY_IMG_RE = re.compile(r'<img[^>]+src="(https://media\.vrmproperties\.com[^"]+)"', re.I)
_LONG_DESC_RE = re.compile(r'<p id="longDesc"[^>]*>(.*?)</p>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ACRES_RE = re.compile(r"([\d,.]+)\s*acres?\b", re.I)
_SQFT_TEXT_RE = re.compile(r"([\d,.]+)\s*(?:sq\.?\s*ft|sf)\b", re.I)
_PROPERTY_KIND_MAP = {
    "single family": PropertyKind.SINGLE_FAMILY,
    "townhome": PropertyKind.TOWNHOUSE,
    "townhouse": PropertyKind.TOWNHOUSE,
    "condo": PropertyKind.CONDO,
    "condominium": PropertyKind.CONDO,
    "multi-family": PropertyKind.MULTI_FAMILY,
    "multi family": PropertyKind.MULTI_FAMILY,
    "mobile": PropertyKind.MOBILE,
    "manufactured": PropertyKind.MOBILE,
    "land": PropertyKind.LAND,
    "commercial": PropertyKind.COMMERCIAL,
}


def _parse_lot_sqft(text: str | None) -> float | None:
    """'544 SF' / '0.75 Acres' -> sqft. None on an unrecognized unit (never
    guesses -- a wrong unit silently poisons valuation math)."""
    if not text:
        return None
    sm = _SQFT_TEXT_RE.search(text)
    if sm:
        try:
            return float(sm.group(1).replace(",", ""))
        except ValueError:
            return None
    am = _ACRES_RE.search(text)
    if am:
        try:
            return float(am.group(1).replace(",", "")) * 43560.0
        except ValueError:
            return None
    return None


def _parse_detail_page(html_text: str) -> dict:
    """House-facts + agent-contact + description + gallery off one
    Property-For-Sale detail page. Best-effort -- any field the page
    doesn't carry is simply absent; never raises.

    The "Brokerage / Agent Information" accordion holds TWO side-by-side
    sub-blocks sharing the SAME Name/Phone/Email/License labels -- one for
    the individual Agent, one for the Brokerage firm -- live-confirmed on a
    real listing (agent "Jeff Sweyer" vs. brokerage "Berkshire Hathaway
    HomeServices..."). Each sub-block's own bold, value-less header row
    ("Agent" / "Brokerage") is the only signal distinguishing them, so it is
    tracked as state across the loop rather than matched standalone (a
    naive flat dict would let the brokerage's own "Name" silently overwrite
    the individual agent's -- caught live while verifying this fix)."""
    out: dict = {}
    section: str | None = None  # "agent" | "brokerage" | None
    for raw_label, raw_value in _LABEL_VALUE_RE.findall(html_text):
        label = html.unescape(raw_label).strip().lower()
        value = re.sub(r"\s+", " ", html.unescape(raw_value)).strip()
        if label in ("agent", "brokerage"):
            section = label  # the bold sub-section header; its own value is always empty
            continue
        if not value:
            continue
        if label in _HOUSE_FACT_LABELS:
            out[_HOUSE_FACT_LABELS[label]] = value
        elif label in _AGENT_LABELS and section == "agent":
            out[_AGENT_LABELS[label]] = value
        elif label in _AGENT_LABELS and section == "brokerage":
            out[f"brokerage_{label}"] = value

    dm = _LONG_DESC_RE.search(html_text)
    if dm:
        text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", html.unescape(dm.group(1)))).strip()
        if text:
            out["description"] = text

    gallery = list(dict.fromkeys(_GALLERY_IMG_RE.findall(html_text)))
    if gallery:
        out["gallery"] = gallery
    return out


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
            # Namespaced under a registered key -- beds/baths/sqft/
            # list_price were flat, unregistered RAW_KEEP keys before this
            # fix (silently dropped on every one of 193 real rows).
            "vrm_va_reo": {"beds": beds, "baths": baths, "sqft": sqft, "list_price": price},
            "images": {"real": photos} if photos else {},
        },
    )


async def _enrich_from_detail(c, li: Listing) -> None:
    """Best-effort per-listing detail-page pull -- full photo gallery, real
    listing-agent contact, narrative description, MLS ID, parcel number,
    year built, property-type refinement (see module docstring finding #2).
    Never raises -- a failure here must not cost the card-level row this
    scraper already built."""
    try:
        r = await c.get(li.source_url, headers=HEADERS, follow_redirects=True)
        if r.status_code != 200 or len(r.text) < 1000:
            return
        fields = _parse_detail_page(r.text)
    except Exception as exc:  # noqa: BLE001
        log.info("vrm.detail_failed", url=li.source_url, error=str(exc)[:160])
        return
    if not fields:
        return

    if fields.get("description"):
        li.description = fields["description"][:2000]
    if fields.get("year_built_text"):
        try:
            y = int(fields["year_built_text"])
            if 1700 <= y <= datetime.utcnow().year + 1:
                li.year_built = y
        except ValueError:
            pass
    lot = _parse_lot_sqft(fields.get("lot_text"))
    if lot is not None:
        li.lot_size_sqft = lot
    parcel = fields.get("parcel_number")
    if parcel and parcel.strip().lower() != "unknown":
        li.parcel_id = parcel.strip()
    ptype = (fields.get("property_type") or "").strip().lower()
    if ptype in _PROPERTY_KIND_MAP:
        li.property_kind = _PROPERTY_KIND_MAP[ptype]

    extra = li.raw.setdefault("vrm_va_reo", {})
    for k in ("mls_id", "status", "stories", "hoa", "property_type",
              "agent_name", "agent_phone", "agent_email", "agent_license",
              "brokerage_name", "brokerage_phone", "brokerage_email",
              "brokerage_license"):
        if fields.get(k):
            extra[k] = fields[k]

    gallery = fields.get("gallery")
    if gallery:
        have = li.raw.setdefault("images", {}).setdefault("real", [])
        for u in gallery:
            if u not in have:
                have.append(u)


async def _fetch_state(state: str, slug: str, detail_budget: list[int] | None = None) -> list[Listing]:
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
                if detail_budget is not None and detail_budget[0] > 0:
                    detail_budget[0] -= 1
                    await _enrich_from_detail(c, li)
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
    disabled = False  # re-enabled 2026-06-29: isolated re-test returns 161 rows in <100s;
    # the 2026-06-27 hang was the enrichment phase (since fixed via idempotent gis_attrs +
    # photo/reverse-geo caps), not this scraper. timeout_s=240 caps it so it can't hang a run.
    disabled_reason = ("re-enabled 2026-06-29; previously disabled for the 2026-06-27 concurrent hang.")
    timeout_s = 180.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        detail_budget = [_DETAIL_FETCH_CAP]  # shared mutable counter, whole run
        for state in STATES:
            try:
                out.extend(await _fetch_state(state, self.slug, detail_budget=detail_budget))
            except Exception as exc:
                log.warning("vrm.state_failed", state=state, error=str(exc)[:200])
        log.info("vrm.done", total=len(out))
        return out

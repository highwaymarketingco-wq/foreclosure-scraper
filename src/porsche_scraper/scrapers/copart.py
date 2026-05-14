"""Copart — salvage / rebuilt-title Porsches.

Copart's HTML is gated, but their Solr endpoint accepts unauthenticated
JSON POSTs (some queries get throttled — use proxies if so):

    POST https://www.copart.com/public/data/lotdetails/solr/lotSearch
    Body: {"query":["porsche"],"filter":{"MAKE":["PORSCHE"],
            "LCY":["2014..2030"]},"sort":["auction_date_utc asc"],
            "page":N,"size":100}

Response: data.results.content[] with mkn(make), lcy(year), mmd(model),
dynamicLotDetails.currentBid/buyItNowPrice, orr(odometer), td(title:
"CLEAR","SALVAGE","REBUILT","PARTS ONLY"). All Copart cars are salvage-
or insurance-auction; treat as salvage_auction.
"""
from __future__ import annotations

import logging

from selectolax.parser import HTMLParser

from ..base import BaseScraper
from ..http_client import fetch_browser_api, fetch_json, fetch_rendered
from ..models import (
    Listing,
    TitleStatus,
    infer_drivable,
    infer_title_status,
    parse_miles,
    parse_price,
    parse_year,
)

log = logging.getLogger(__name__)

BASE = "https://www.copart.com"
SEARCH_URL = f"{BASE}/public/data/lotdetails/solr/lotSearch"
EXCLUDED_MODELS_UPPER = ("PANAMERA", "MACAN")


def _td_to_status(td: str | None) -> TitleStatus:
    if not td:
        return TitleStatus.UNKNOWN
    s = td.upper()
    if "REBUILT" in s or "RECONSTRUCTED" in s:
        return TitleStatus.REBUILT
    if "PARTS" in s:
        return TitleStatus.PARTS_ONLY
    if "SALVAGE" in s or "JUNK" in s:
        return TitleStatus.SALVAGE
    if "FLOOD" in s or "WATER" in s:
        return TitleStatus.FLOOD
    if "CLEAR" in s or "CLEAN" in s:
        return TitleStatus.CLEAN
    return TitleStatus.UNKNOWN


def _drivable_from_copart(d: dict, status: TitleStatus, title: str) -> bool | None:
    """Copart marks "Run & Drive" as a boolean / icon. dynamic.runAndDriveYn=Y."""
    dyn = d.get("dynamicLotDetails") or {}
    if dyn.get("runAndDriveYn") == "Y" or d.get("rd") == "Y":
        return True
    if dyn.get("runAndDriveYn") == "N" or d.get("rd") == "N":
        return False
    return infer_drivable(title, status)


def _lot_to_listing(d: dict) -> Listing | None:
    if not d:
        return None
    # Copart's /public/lots/search-results uses short field names:
    #   lm  = model ("911"), lmg = same, lmtd = "911 CARRERA 2"
    #   ltd = trim ("CARRERA 2"), lcy = year, mkn = make
    #   ln/lotNumberStr = lot number, td = title type
    #   orr = odometer, fv = vin, lurl = image url
    # Legacy mmd field comes from the older Solr endpoint — keep both
    # for compatibility.
    model = (d.get("mmd") or d.get("lm") or d.get("lmg") or "").strip()
    if model.upper() in EXCLUDED_MODELS_UPPER:
        return None  # Drop excluded models server-side too.
    lot_no = d.get("lotNumberStr") or d.get("ln")
    if not lot_no:
        return None
    url = f"{BASE}/lot/{lot_no}"
    trim = (d.get("ltd") or "").strip() or None
    title = " ".join(filter(None, [str(d.get("lcy") or ""), "Porsche", model, trim or ""]))
    dyn = d.get("dynamicLotDetails") or {}
    price = parse_price(dyn.get("buyItNowPrice") or d.get("buyItNowPrice"))
    bid = parse_price(dyn.get("currentBid") or d.get("currentBid") or d.get("hb"))
    status = _td_to_status(d.get("td") or d.get("ts"))
    listing = Listing(
        source="copart",
        source_url=url,
        listing_id=str(lot_no),
        lot_number=str(lot_no),
        vin=d.get("fv") or d.get("vin"),
        title=title,
        year=int(d["lcy"]) if str(d.get("lcy") or "").isdigit() else None,
        model=model or None,
        trim=trim,
        price_usd=price,
        current_bid_usd=bid,
        mileage=parse_miles(d.get("orr") or d.get("odometer")),
        location=d.get("yn") or d.get("yardName") or d.get("locState"),
        photo_url=d.get("lurl") or d.get("lotImageUrl"),
        title_status=status,
        seller_type="salvage_auction",
        raw={"copart": d},
    )
    listing.drivable = _drivable_from_copart(d, status, title)
    return listing


def parse_solr_response(payload: dict) -> list[Listing]:
    data = (payload or {}).get("data") or {}
    results = data.get("results") or {}
    content = results.get("content") or []
    out: list[Listing] = []
    seen: set[str] = set()
    for d in content:
        listing = _lot_to_listing(d)
        if listing and listing.listing_id not in seen:
            seen.add(listing.listing_id)
            out.append(listing)
    return out


class CopartScraper(BaseScraper):
    slug = "copart"
    name = "Copart (salvage)"
    timeout_s = 180.0

    def __init__(self, *, year_min: int = 2014, year_max: int = 2030, max_pages: int = 5):
        self.year_min = year_min
        self.year_max = year_max
        self.max_pages = max_pages

    async def fetch(self) -> list[Listing]:
        """Try browser-session API first (yields all 91+ lots per model
        with full data in one POST). Fall back to Solr direct, then
        HTML scrape. Verified 2026-05-13: the browser-API path returns
        100+ listings vs ~20 from the HTML-render path.
        """
        out = await self._fetch_browser_api()
        if out:
            return out
        out = await self._fetch_solr()
        if out:
            return out
        return await self._fetch_html()

    async def _fetch_browser_api(self) -> list[Listing]:
        """Use a Scrapling-rendered session to POST against the public
        search-results API. The site gates the API behind session cookies
        a fresh curl can't set — but page.evaluate() inside the rendered
        page carries the credentials transparently."""
        # Per-model queries. Generic "porsche" returns 1000+ hits dominated
        # by Panamera/Macan, so the 5-page window never reaches the sports
        # cars. Each specific query returns its full match set (911=91,
        # cayman=28, boxster=59, 718=1, taycan=~40, cayenne=~150).
        # 911-variants (GT3, Turbo, Carrera, etc.) all show as model=911
        # in the API so a single query covers them. Same for Cayman/GT4.
        queries = [
            "porsche 911", "porsche cayman", "porsche boxster",
            "porsche 718", "porsche taycan", "porsche cayenne",
        ]
        out: list[Listing] = []
        seen: set[str] = set()
        for q in queries:
            warmup = (f"{BASE}/lotSearchResults?free=true"
                      f"&query={q.replace(' ', '%20')}"
                      f"&from={self.year_min}&to={self.year_max}")
            body = {
                "query": [q],
                "filter": {"LCY": [f"{self.year_min}..{self.year_max}"]},
                "sort": ["lot_number asc"],
                "page": 0, "size": 200,
                "watchListOnly": False, "freeFormSearch": False,
            }
            payload = await fetch_browser_api(
                warmup_url=warmup,
                api_path="/public/lots/search-results",
                body=body,
                timeout=60,
                wait_for_selector="a[href*='/lot/']",
            )
            if not payload:
                log.info("copart browser-api %s: no payload", q)
                continue
            content = (payload.get("data") or {}).get("results", {}).get("content") or []
            # `returnCode` is an integer that's 0 on success, but some
            # successful responses return non-zero codes with `Success`
            # in returnCodeDesc — treat presence of content as the real
            # success signal.
            if not content:
                log.info("copart browser-api %s empty: returnCode=%s desc=%s",
                         q, payload.get("returnCode"), payload.get("returnCodeDesc"))
                continue
            log.info("copart browser-api %s: %d lots", q, len(content))
            for d in content:
                listing = _lot_to_listing(d)
                if listing is None:
                    continue
                if listing.year and listing.year < self.year_min:
                    continue
                if listing.source_url in seen:
                    continue
                seen.add(listing.source_url)
                out.append(listing)
        return out

    async def _fetch_solr(self) -> list[Listing]:
        out: list[Listing] = []
        for page in range(self.max_pages):
            body = {
                "query": ["porsche"],
                "filter": {
                    "MAKE": ["PORSCHE"],
                    "LCY": [f"{self.year_min}..{self.year_max}"],
                },
                "sort": ["auction_date_utc asc"],
                "page": page, "size": 100,
                "watchListOnly": False, "freeFormSearch": False,
            }
            try:
                payload = await fetch_json(
                    SEARCH_URL, method="POST", json_body=body, timeout=45,
                    headers={"Accept": "application/json", "Content-Type": "application/json",
                             "Origin": BASE,
                             "Referer": f"{BASE}/lotSearchResults?free=true&query=porsche"},
                )
            except Exception as exc:  # noqa: BLE001
                log.info("copart solr page %d: %s", page, exc)
                return out
            if payload.get("returnCode") not in (0, None):
                log.info("copart solr blocked: %s", payload.get("returnCodeDesc"))
                return out
            listings = parse_solr_response(payload)
            if not listings:
                break
            out.extend(listings)
        return out

    async def _fetch_html(self) -> list[Listing]:
        # Query each wanted model separately. A generic `query=porsche`
        # is dominated by Cayenne/Macan/Panamera (verified 2026-05-13:
        # 1,000+ "porsche" results, top pages all Cayenne/Macan) — by
        # the time the 5-page window runs out we've seen ~0 of the
        # 911/Cayman/Boxster/718 listings the user actually wants.
        # Per-model queries returned 91 results for "porsche 911" alone
        # and similar counts for cayman/boxster.
        queries = [
            "porsche 911", "porsche cayman", "porsche boxster",
            "porsche 718", "porsche taycan", "porsche cayenne",
        ]
        out: list[Listing] = []
        seen: set[str] = set()
        for q in queries:
            # Copart's lotSearchResults page renders the entire result set
            # (e.g. 91 911s) into one DOM, lazily — the `page=N` URL param
            # is ignored. Verified 2026-05-13: page=0 and page=2 return
            # identical HTML. One fetch per query with aggressive scrolling
            # (4 passes × 2.2s wait) gives all lots time to mount before
            # we read the HTML.
            url = (f"{BASE}/lotSearchResults/?free=true"
                   f"&query={q.replace(' ', '%20')}"
                   f"&from={self.year_min}&to={self.year_max}")
            try:
                html = await fetch_rendered(
                    url, timeout=120,
                    wait_for_selector="a[href*='/lot/']",
                    scroll_iterations=4,
                    post_scroll_wait_ms=2200,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("copart html %s: %s", q, exc)
                continue
            tree = HTMLParser(html)
            anchors = tree.css("a[href*='/lot/']")
            if not anchors:
                # One bad query shouldn't kill the others — move on.
                continue
            for a in anchors:
                href = a.attributes.get("href") or ""
                if "/lot/" not in href:
                    continue
                full = href if href.startswith("http") else f"{BASE}{href}"
                if full in seen:
                    continue
                seen.add(full)
                # The slug carries year+model: /lot/12345678/salvage-2015-porsche-911-...
                slug = href.rstrip("/").rsplit("/", 1)[-1].lower()
                if any(em in slug for em in ("panamera", "macan")):
                    continue
                title = a.text(strip=True)
                if not title or "porsche" not in title.lower():
                    # The label might be empty (icon-only anchor); use slug.
                    if "porsche" not in slug:
                        continue
                    title = slug.replace("-", " ").replace("salvage ", "").title()
                # Extract model from the slug. Copart slugs look like
                # "salvage-2015-porsche-911-carrera-ca-stockton" or
                # "1985-porsche-944-..." — match the most common Porsche
                # model tokens. Order: longer specific names first so e.g.
                # "boxster-s" matches "boxster" not "s".
                model = None
                slug_tokens = slug.replace("salvage-", "").split("-")
                for tok in slug_tokens:
                    upper = tok.lower()
                    if upper in ("911", "718", "928", "944", "924", "968", "959", "356"):
                        model = upper
                        break
                    if upper in ("cayman", "boxster", "carrera", "taycan", "cayenne"):
                        model = upper.title()
                        break
                # Client-side year filter — Copart's HTML page ignores the
                # from/to URL params (verified 2026-05-13: requested 2014+,
                # got 1985 928 / 1985 944 back). Drop pre-year_min here so
                # downstream dedupe+filter doesn't waste cycles.
                year = parse_year(title) or parse_year(slug)
                if year and year < self.year_min:
                    continue
                lot_no = href.rstrip("/").rsplit("/")[-2]
                listing = Listing(
                    source="copart",
                    source_url=full,
                    listing_id=lot_no,
                    lot_number=lot_no,
                    title=title,
                    year=year,
                    model=model,
                    title_status=(infer_title_status(slug) if "salvage" in slug or "rebuilt" in slug
                                  else TitleStatus.SALVAGE),
                    seller_type="salvage_auction",
                )
                listing.drivable = infer_drivable(title, listing.title_status)
                out.append(listing)
        return out

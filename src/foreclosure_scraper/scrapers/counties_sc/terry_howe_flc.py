"""Terry Howe & Associates — SC Forfeited Land Commission (FLC) auctions.

SC counties liquidate tax-failed / FLC inventory through third-party auctioneers;
Terry Howe is the main one for the upstate. The county FLC pages don't list the
parcels, but Terry Howe publishes them — and exposes the whole catalog via a free
unauthenticated WordPress REST endpoint (no key, no render):
  GET /wp-json/wp/v2/auctions?per_page=100  -> [{title, link, content(html)}, ...]

Each in-scope auction title is "{County} County, SC – N Properties for {County}
County Forfeited Land Commission"; the property street addresses are in the
content body. FLC parcels are quitclaim-only, no title search — prime cheap
distressed inventory. Free, no Apify/proxy/render.
"""
from __future__ import annotations

import re
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import ALL_COUNTIES
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

API = "https://terryhowe.com/wp-json/wp/v2/auctions?per_page=100&_fields=id,title,link,content"
_SC_COUNTIES = {c.name.lower() for c in ALL_COUNTIES if c.state == "SC"}

_TITLE_COUNTY = re.compile(r"([A-Za-z][A-Za-z ]+?)\s+County,\s*SC", re.I)
_ADDR = re.compile(
    r"\b(\d{1,5}\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+){0,4}?\s+"
    r"(?:Rd|Road|St|Street|Ln|Lane|Dr|Drive|Ave|Avenue|Hwy|Highway|Ct|Court|"
    r"Way|Blvd|Cir|Circle|Pl|Place|Ter|Terrace|Trl|Trail|Pkwy|Loop))\b\.?", re.I)
_FLC_MARK = re.compile(r"forfeited\s+land|FLC|delinquent\s+tax", re.I)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _county_of(title: str) -> str | None:
    m = _TITLE_COUNTY.search(title or "")
    if not m:
        return None
    c = m.group(1).strip()
    return c if c.lower() in _SC_COUNTIES else None


def _clean_addresses(body: str) -> list[str]:
    """Pull clean street addresses out of an FLC auction body.

    The list prefixes a 1-2 digit item number ("00 817 Saxon Ave"); strip it when
    a real house number follows, and drop vague "Off X" locators (no house #).
    """
    addrs: list[str] = []
    for m in _ADDR.finditer(body or ""):
        ad = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".")
        ad = re.sub(r"(?i)^\d{1,2}\s+(?=\d|off\b)", "", ad)
        if re.match(r"(?i)off\b", ad) or not re.match(r"\d", ad):
            continue
        if ad not in addrs:
            addrs.append(ad)
    return addrs


class TerryHoweFLC(BaseScraper):
    slug = "counties_sc.terry_howe_flc"
    name = "Terry Howe FLC auctions (SC Forfeited Land Commission)"
    category = "county_tax"
    expected_min_count = 0
    requires_apify = False
    timeout_s = 60.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        async with client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0 Chrome/126"}) as c:
            try:
                r = await c.get(API, follow_redirects=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("terry_howe_flc.fetch_failed", error=str(exc)[:160])
                return []
            if r.status_code != 200:
                log.warning("terry_howe_flc.bad_status", status=r.status_code)
                return []
            try:
                auctions = r.json()
            except ValueError:
                log.warning("terry_howe_flc.json_failed")
                return []

        seen: set[tuple] = set()
        for a in auctions if isinstance(auctions, list) else []:
            t = a.get("title") or {}
            title = (t.get("rendered") if isinstance(t, dict) else t) or ""
            county = _county_of(title)
            if not county:
                continue  # not an in-footprint SC county auction
            link = a.get("link") or ""
            cb = a.get("content") or {}
            body = _strip_html(cb.get("rendered") if isinstance(cb, dict) else cb)
            if not _FLC_MARK.search(title + " " + body):
                continue  # keep FLC / tax-failed auctions only
            addrs = _clean_addresses(body)
            if addrs:
                for ad in addrs:
                    key = (county, ad.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(Listing(
                        source=self.slug, source_url=link, listing_type=ListingType.TAX_SALE,
                        state="SC", county=county, street_address=ad,
                        property_kind=PropertyKind.UNKNOWN,
                        raw={"flc": {"auctioneer": "Terry Howe", "auction_title": title[:200],
                                     "source": "forfeited_land_commission"}},
                    ))
            else:
                # No parseable address — still surface the county FLC auction as a lead.
                key = (county, link)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Listing(
                    source=self.slug, source_url=link, listing_type=ListingType.TAX_SALE,
                    state="SC", county=county,
                    description=title[:200],
                    raw={"flc": {"auctioneer": "Terry Howe", "auction_title": title[:200],
                                 "source": "forfeited_land_commission", "bundle": True}},
                ))
        log.info("terry_howe_flc.done", count=len(out))
        return out

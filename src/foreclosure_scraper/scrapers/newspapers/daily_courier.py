"""The Daily Courier (Forest City, NC) legal classifieds — foreclosure notices.

Rutherford County, NC. The paper hosts public legal notices in TownNews TNCMS
classifieds. Each notice gets its own /classifieds/.../ad_<uuid>.html detail
page. The detail page renders ad text in <meta name="description"> and the H1
holds the notice title.

URL: https://www.thedigitalcourier.com/classifieds/community/announcements/legal/

Listing page links to ad_<uuid>.html detail pages. Each detail page has:
  - <h1> with notice title (often FORECLOSURE / NOTICE OF SALE / NOTICE TO CREDITORS)
  - <meta name="description"> with first ~300 chars of the ad body
  - file/case # and address inside that body when present
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

BASE = "https://www.thedigitalcourier.com"
#: TownNews caps this classifieds index at the ~9 currently-active legal ads and
#: ignores paging params (verified live 2026-08-13: ``?o=10&l=10``, ``?page=2``,
#: ``?l=40`` all return the SAME 9 ads). The old three-URL offset list implied
#: 30-ad coverage it never delivered — one URL is the honest surface. NOTE: this
#: means a foreclosure Notice of Sale is only reachable here while it is one of
#: the ~9 live ads; once it rolls off (e.g. a property already past sale and into
#: the upset-bid period) this source can no longer see it. Deeper/older notices
#: need the statewide ncnotices.com archive (see public_notices.nc_notices_counties).
LISTING_URLS = [
    "https://www.thedigitalcourier.com/classifieds/community/announcements/legal/",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

FILE_RE = re.compile(r"\b(\d{2}\s*(?:SP|M|CVD|CVS)\s*\d{1,5})\b", re.I)
ADDR_RE = re.compile(
    r"(?:Property\s+address|known\s+as|located\s+at)[:\s]+([0-9][^.\n<]*?(?:NC\s*\d{5})?)",
    re.I,
)
SALE_DATE_RE = re.compile(
    r"(?:will\s+(?:be\s+)?(?:offer|expose|sell)|sale\s+(?:will|on)|on)\s+(?:[a-z\s]{0,40}?on\s+)?"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}(?:,?\s+at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))?)",
    re.I,
)
SALE_DATE_FALLBACK = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
TRUSTEE_RE = re.compile(
    r"(?:Substitute\s+Trustee|the\s+Trustee|Trustee[,]):\s*([A-Z][A-Za-z &,.'-]+(?:LLC|LLP|PA|PC|Inc|PLLC|Carolinas|Law Firm)[^.\n]*)",
    re.I,
)
PLAINTIFF_RE = re.compile(
    r"(?:Lien\s+filed[^.]*?by|secured\s+by[^.]*?lien\s+held\s+by|in\s+favor\s+of)\s+([A-Z][A-Za-z0-9 &,.'-]+(?:LLC|Inc|Bank|N\.?A\.?|Trust|Association|Mortgage|Servicing)[^.,\n]*)",
    re.I,
)
DEFENDANT_RE = re.compile(
    r"Present\s+Owner\(?s?\)?:\s*([^.\n]+?)(?:\.|The\s+sale)",
    re.I,
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _is_foreclosure(title: str, body: str) -> bool:
    t = (title + " " + body[:500]).lower()
    return (
        "foreclos" in t
        or "notice of sale" in t
        or "substitute trustee" in t
        or "trustee's sale" in t
        or "deed of trust" in t
    )


class DailyCourierForeclosures(BaseScraper):
    slug = "newspapers.daily_courier"
    name = "The Daily Courier Legal Classifieds (Rutherford NC)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 1
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        ad_links: set[str] = set()
        async with client(timeout=20.0) as c:
            for url in LISTING_URLS:
                try:
                    r = await c.get(url, headers=HEADERS)
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                # Extract /classifieds/community/announcements/legal/<slug>/ad_<uuid>.html
                for m in re.finditer(
                    r'href="(/classifieds/community/announcements/legal/[^"]+/ad_[^"]+\.html)"',
                    r.text,
                ):
                    ad_links.add(urljoin(BASE, m.group(1)))

            out: list[Listing] = []
            seen: set[str] = set()
            for ad_url in ad_links:
                try:
                    rr = await c.get(ad_url, headers=HEADERS)
                except Exception:
                    continue
                if rr.status_code != 200:
                    continue
                html = rr.text
                tree = HTMLParser(html)
                h1 = tree.css_first("h1")
                title = _clean(h1.text()) if h1 else ""
                # body text from meta description + visible asset-body text
                desc = ""
                meta = tree.css_first('meta[name="description"]')
                if meta:
                    desc = meta.attributes.get("content", "") or ""
                # Also pull any visible asset body text as backup
                body_node = tree.css_first(".asset-body, .asset-content, .ad-body, .item-content")
                body_visible = _clean(body_node.text()) if body_node else ""
                body = _clean(desc + " " + body_visible)
                if not body:
                    continue
                if not _is_foreclosure(title, body):
                    continue

                key = ad_url
                if key in seen:
                    continue
                seen.add(key)

                file_m = FILE_RE.search(title) or FILE_RE.search(body)
                case_number = file_m.group(1) if file_m else None
                if case_number:
                    case_number = re.sub(r"\s+", " ", case_number).upper()

                addr_m = ADDR_RE.search(body)
                address = addr_m.group(1).strip() if addr_m else None
                if address:
                    address = re.sub(r"\s+", " ", address).rstrip(".,").strip()[:300]
                    if len(address) < 10:
                        address = None

                zip_m = re.search(r"NC\s*(\d{5})", body)
                zip_code = zip_m.group(1) if zip_m else None
                city_m = re.search(
                    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*(?:NC|North\s+Carolina)",
                    address or "",
                )
                city = city_m.group(1) if city_m else None

                sale_date = None
                d_m = SALE_DATE_RE.search(body) or SALE_DATE_FALLBACK.search(body)
                if d_m:
                    try:
                        sale_date = dateparser.parse(d_m.group(1), fuzzy=True)
                    except (ValueError, TypeError):
                        pass

                trustee = None
                t_m = TRUSTEE_RE.search(body)
                if t_m:
                    trustee = t_m.group(1).strip()[:200]

                plaintiff = None
                p_m = PLAINTIFF_RE.search(body)
                if p_m:
                    plaintiff = p_m.group(1).strip()[:200]

                defendant = None
                d_m2 = DEFENDANT_RE.search(body)
                if d_m2:
                    defendant = d_m2.group(1).strip()[:200]

                # Precision gate: a foreclosure notice with neither a court file
                # nor a usable street address is not an actionable lead — it was
                # emitting one junk Rutherford row per run (zip-only, no address,
                # no case #). Require at least one property identifier.
                if not case_number and not address:
                    continue

                out.append(
                    Listing(
                        source=self.slug,
                        source_url=ad_url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county="Rutherford",
                        street_address=address,
                        city=city,
                        zip_code=zip_code,
                        sale_date=sale_date,
                        sale_location="Rutherford County Courthouse, Rutherfordton NC",
                        case_number=case_number,
                        plaintiff=plaintiff,
                        defendant=defendant,
                        trustee=trustee,
                        description=title[:500] or None,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"daily_courier": {
                            "title": title,
                            "body_preview": body[:1500],
                        }},
                    )
                )
        return out

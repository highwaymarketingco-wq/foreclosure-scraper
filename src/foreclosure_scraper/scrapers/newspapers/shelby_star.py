"""The Shelby Star (Cleveland County, NC) — foreclosure notices.

Cleveland County, NC. The Shelby Star is part of the Gannett / USA Today
network and does not host a public classifieds / legal notices section on its
own domain (the Gannett platform routes legal advertising to the
localiq / publicnoticesnc.com regional aggregators instead).

This module probes the home page for any present-day legal-notices link
(structure has changed before) and parses a TownNews-style listing if one is
found. If the section is absent (current state as of build), it returns an
empty list — the pattern is in place so that if Gannett later adds a public
notices index, only the LISTING_URL list needs to be edited.

Cross-county foreclosures filed in Cleveland County are also picked up by the
Brock & Scott / Hutchens / Aldridge law firm scrapers and the NC ROD search,
so this source is supplementary.
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

BASE = "https://www.shelbystar.com"
HOME_URL = "https://www.shelbystar.com/"
# Probe candidates — kept here so future structure changes are a one-line edit.
CANDIDATE_LISTING_URLS = [
    "https://www.shelbystar.com/legal-notices/",
    "https://www.shelbystar.com/public-notices/",
    "https://www.shelbystar.com/classifieds/",
    "https://www.shelbystar.com/section/legal-notices/",
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
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}(?:,?\s+at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))?)",
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
    )


class ShelbyStarForeclosures(BaseScraper):
    slug = "newspapers.shelby_star"
    name = "The Shelby Star Legal Classifieds (Cleveland NC)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 1
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        ad_pages: list[tuple[str, str]] = []  # (url, html)

        async with client(timeout=20.0) as c:
            # 1. Try each candidate listing URL — first one returning 200 wins.
            listing_html = None
            listing_url = None
            for url in CANDIDATE_LISTING_URLS:
                try:
                    r = await c.get(url, headers=HEADERS)
                except Exception:
                    continue
                if r.status_code == 200 and len(r.text) > 5000:
                    listing_html = r.text
                    listing_url = url
                    break

            # 2. If none worked, scan the home page for legal/notice links.
            if listing_html is None:
                try:
                    r = await c.get(HOME_URL, headers=HEADERS)
                except Exception:
                    return out
                if r.status_code != 200:
                    return out
                home_html = r.text
                hrefs = re.findall(
                    r'href="([^"]*(?:legal|public-notice|classified)[^"]*)"',
                    home_html,
                    re.I,
                )
                for h in hrefs:
                    candidate = urljoin(HOME_URL, h)
                    if "shelbystar.com" not in candidate:
                        continue
                    try:
                        rr = await c.get(candidate, headers=HEADERS)
                    except Exception:
                        continue
                    if rr.status_code == 200 and len(rr.text) > 5000:
                        listing_html = rr.text
                        listing_url = candidate
                        break

            if listing_html is None:
                # No public legal-notices section currently exists. Pattern is
                # in place; if Gannett adds one, populate CANDIDATE_LISTING_URLS.
                return out

            # 3. Two parsing modes:
            #    a) TownNews ad detail pages /ad_<uuid>.html (if migrated)
            #    b) WordPress / Gannett article pages with foreclosure body
            ad_hrefs = set(
                re.findall(
                    r'href="([^"]+/ad_[a-f0-9-]+\.html)"',
                    listing_html,
                )
            )
            for h in list(ad_hrefs)[:50]:
                u = urljoin(listing_url, h)
                try:
                    rr = await c.get(u, headers=HEADERS)
                except Exception:
                    continue
                if rr.status_code == 200:
                    ad_pages.append((u, rr.text))

            # If no /ad_*.html links, treat the listing page itself as a single
            # body and slice it on h2/h3 boundaries.
            if not ad_pages:
                ad_pages.append((listing_url, listing_html))

        seen: set[str] = set()
        for ad_url, html in ad_pages:
            tree = HTMLParser(html)
            h1 = tree.css_first("h1")
            title = _clean(h1.text()) if h1 else ""
            desc = ""
            meta = tree.css_first('meta[name="description"]')
            if meta:
                desc = meta.attributes.get("content", "") or ""
            body_node = tree.css_first(".asset-body, .asset-content, .article-body, article")
            body_visible = _clean(body_node.text()) if body_node else _clean(html[:30000])
            body = _clean(desc + " " + body_visible)
            if not body or len(body) < 100:
                continue
            if not _is_foreclosure(title, body):
                continue

            key = ad_url + "|" + title[:100]
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
            d_m = SALE_DATE_RE.search(body)
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

            out.append(
                Listing(
                    source=self.slug,
                    source_url=ad_url,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Cleveland",
                    street_address=address,
                    city=city,
                    zip_code=zip_code,
                    sale_date=sale_date,
                    sale_location="Cleveland County Courthouse, Shelby NC",
                    case_number=case_number,
                    plaintiff=plaintiff,
                    defendant=defendant,
                    trustee=trustee,
                    description=title[:500] or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"shelby_star": {
                        "title": title,
                        "body_preview": body[:1500],
                    }},
                )
            )
        return out

"""Tryon Daily Bulletin (Polk County, NC) — foreclosure notices.

Polk County, NC. The Tryon Daily Bulletin runs on WordPress (CMG/Adams
Publishing chain). There is no dedicated TownNews classifieds platform — legal
notices are published as articles, often under /category/legal-notices/ or
mixed into the news feed. Reliable retrieval is via the WP search endpoint
?s=foreclosure+sale.

We hit:
  - /?s=foreclosure+sale
  - /category/legal-notices/

For each search result page we follow the dated article URL
(/YYYY/MM/DD/<slug>/), pull the H1 + article body, and extract case#, address,
sale date with the same regexes used for Hendersonville Lightning.
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

BASE = "https://tryondailybulletin.com"
SEARCH_URLS = [
    "https://tryondailybulletin.com/?s=foreclosure+sale",
    "https://tryondailybulletin.com/?s=substitute+trustee",
    "https://tryondailybulletin.com/category/legal-notices/",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

ARTICLE_HREF_RE = re.compile(
    r'href="(https://tryondailybulletin\.com/\d{4}/\d{2}/\d{2}/[^"#?]+/?)"'
)

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

# Drop very old result hits — search returns going back >10 years
RECENT_YEAR_CUTOFF = datetime.utcnow().year - 2


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _is_foreclosure(title: str, body: str) -> bool:
    t = (title + " " + body[:1000]).lower()
    return (
        "foreclos" in t
        or "notice of sale" in t
        or "substitute trustee" in t
        or "trustee's sale" in t
        or "deed of trust" in t
    )


def _extract_year(url: str) -> int | None:
    m = re.search(r"/(\d{4})/", url)
    return int(m.group(1)) if m else None


class TryonBulletinForeclosures(BaseScraper):
    slug = "newspapers.tryon_bulletin"
    name = "Tryon Daily Bulletin Legal Notices (Polk NC)"
    category = "newspaper_legal"
    requires_apify = False
    # Polk NC has weeks with zero foreclosure-related notices in the
    # Tryon Bulletin. Real regression here = URL discovery breaks; an
    # empty count is genuine data, not a scraper failure.
    expected_min_count = 0
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        article_urls: set[str] = set()
        async with client(timeout=20.0) as c:
            for url in SEARCH_URLS:
                try:
                    r = await c.get(url, headers=HEADERS)
                except Exception:
                    continue
                if r.status_code != 200:
                    continue
                for m in ARTICLE_HREF_RE.finditer(r.text):
                    u = m.group(1).rstrip("/") + "/"
                    yr = _extract_year(u)
                    if yr is None or yr < RECENT_YEAR_CUTOFF:
                        continue
                    article_urls.add(u)

            out: list[Listing] = []
            seen: set[str] = set()
            for art_url in article_urls:
                try:
                    rr = await c.get(art_url, headers=HEADERS)
                except Exception:
                    continue
                if rr.status_code != 200:
                    continue
                tree = HTMLParser(rr.text)
                h1 = tree.css_first("h1.entry-title, h1.post-title, h1")
                title = _clean(h1.text()) if h1 else ""
                article = tree.css_first(
                    ".entry-content, .post-content, article .content, article"
                )
                body = _clean(article.text()) if article else ""
                if not body or len(body) < 200:
                    continue
                if not _is_foreclosure(title, body):
                    continue

                key = art_url
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

                out.append(
                    Listing(
                        source=self.slug,
                        source_url=art_url,
                        listing_type=ListingType.FORECLOSURE_SALE,
                        property_kind=PropertyKind.UNKNOWN,
                        state="NC",
                        county="Polk",
                        street_address=address,
                        city=city,
                        zip_code=zip_code,
                        sale_date=sale_date,
                        sale_location="Polk County Courthouse, Columbus NC",
                        case_number=case_number,
                        plaintiff=plaintiff,
                        defendant=defendant,
                        trustee=trustee,
                        description=title[:500] or None,
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        raw={"tryon_bulletin": {
                            "title": title,
                            "body_preview": body[:1500],
                        }},
                    )
                )
        return out

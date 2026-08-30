"""Hendersonville Lightning legal classifieds — foreclosure notices.

NC law requires foreclosure sales to be advertised in a newspaper of general
circulation 30+ days before the sale. The Lightning hosts these for Henderson
County. Page is plain HTML, free, no auth.

URL: https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html

Each notice is an <h3 class="title"> followed by <p> blocks. Body contains:
  - File # (e.g. "21 SP 34", "20 M 248")
  - Property address ("Property address: Lot 140 Woodhen Way, Horse Shoe, NC 28742")
  - Sale date ("July 28, 2021, at 2:00 PM")
  - Sale location ("Henderson County Courthouse")
  - Plaintiff (HOA / lender / county)
  - Defendant (current owner)
  - Trustee (substitute trustee firm)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from .column_legal_notices import _notice_email

URL = "https://www.hendersonvillelightning.com/legal-ads/130-foreclosures.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

FILE_RE = re.compile(r"\b(\d{2}\s*(?:SP|M|CVD)\s*\d{1,5})\b", re.I)
ADDR_RE = re.compile(
    r"Property\s+address:\s*([^.\n<]+?(?:NC\s*\d{5})?)", re.I
)
SALE_DATE_RE = re.compile(
    r"(?:will\s+(?:be\s+)?expose|sale\s+(?:will|on))\s+for\s+sale[^.]+?on\s+"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}(?:,?\s+at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))?)",
    re.I,
)
SALE_DATE_FALLBACK = re.compile(
    r"\bon\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
TRUSTEE_RE = re.compile(
    r"(?:Substitute\s+Trustee|the\s+Trustee|Trustee[,]):\s*([A-Z][A-Za-z &,.'-]+(?:LLC|LLP|PA|PC|Inc|PLLC|Carolinas|Law Firm)[^.\n]*)",
    re.I,
)
PLAINTIFF_RE = re.compile(
    r"(?:Lien\s+filed[^.]*?by|secured\s+by[^.]*?lien\s+held\s+by)\s+([A-Z][A-Za-z0-9 &,.'-]+(?:LLC|Inc|Bank|N\.?A\.?|Trust|Association|Mortgage|Servicing)[^.,\n]*)",
    re.I,
)
DEFENDANT_RE = re.compile(
    r"Present\s+Owner\(?s?\)?:\s*([^.\n]+?)(?:\.|The\s+sale)",
    re.I,
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


class HendersonvilleLightningForeclosures(BaseScraper):
    slug = "newspapers.hendersonville_lightning"
    name = "Hendersonville Lightning Legal Classifieds (Henderson NC)"
    category = "newspaper_legal"
    expected_min_count = 3
    timeout_s = 30.0

    async def fetch(self) -> Iterable[Listing]:
        async with client(timeout=20.0) as c:
            r = await c.get(URL, headers=HEADERS)
            if r.status_code != 200:
                return []
            html = r.text

        out: list[Listing] = []
        seen: set[str] = set()

        # Slice the HTML on <h3 class="title"> boundaries. Each chunk is one notice.
        chunks = re.split(r'<h3\s+class="title">', html)
        for chunk in chunks[1:]:  # skip the prefix before the first h3
            # title is everything up to </h3>
            title_end = chunk.find("</h3>")
            if title_end < 0:
                continue
            title = _clean(chunk[:title_end])
            if "foreclos" not in title.lower() and "sale" not in title.lower():
                continue
            # body is the rest until the next <h3 class="title"> boundary OR end
            body_html = chunk[title_end:]
            # cap to ~6KB to keep regex reasonable
            body = _clean(body_html[:6000])
            if len(body) < 200:
                continue

            file_m = FILE_RE.search(title) or FILE_RE.search(body)
            case_number = file_m.group(1) if file_m else None
            if case_number:
                case_number = re.sub(r"\s+", " ", case_number).upper()
            key = case_number or title[:80]
            if key in seen:
                continue
            seen.add(key)

            addr_m = ADDR_RE.search(body)
            address = addr_m.group(1).strip() if addr_m else None
            if address:
                address = re.sub(r"\s+", " ", address).rstrip(".,").strip()

            zip_m = re.search(r"NC\s*(\d{5})", body)
            zip_code = zip_m.group(1) if zip_m else None
            city_m = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),\s*(?:NC|North\s+Carolina)", address or "")
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

            # Attorney/trustee phone + email from the full notice body (a
            # reachable case contact). Reuses the Column extractor so parcel-PIN
            # digit runs can't leak in as a phantom phone.
            raw = {"hendersonville_lightning": {
                "title": title,
                "body_preview": body[:1500],
            }}
            contact = _notice_email(body)
            if contact:
                raw["notice_contact"] = contact

            out.append(
                Listing(
                    source=self.slug,
                    source_url=URL,
                    listing_type=ListingType.FORECLOSURE_SALE,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC",
                    county="Henderson",
                    street_address=address,
                    city=city,
                    zip_code=zip_code,
                    sale_date=sale_date,
                    sale_location="Henderson County Courthouse, Hendersonville NC",
                    case_number=case_number,
                    plaintiff=plaintiff,
                    defendant=defendant,
                    trustee=trustee,
                    description=title[:500],
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw=raw,
                )
            )
        return out

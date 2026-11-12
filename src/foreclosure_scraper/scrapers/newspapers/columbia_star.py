"""The Columbia Star (Columbia SC): weekly Master-in-Equity sale notices for Richland County.

Source
------
Richland County's Master-in-Equity page posts no sale list (it tells bidders to review
the docket), and the county's court roster sits behind the SC Public Index challenge.
The Columbia Star, a weekly legal organ, prints every Richland MIE sale notice in one
article per issue ("Master's Sales"), and its public "Public Notices" category feed
carries each article's full text:

    https://www.thecolumbiastar.com/category/public-notices/feed/          (page 1)
    https://www.thecolumbiastar.com/category/public-notices/feed/?paged=2  (older)

(The site's REST endpoint for these articles answers 403 "restricted to authorized IPs
only"; this module does not touch it. The category feed is the ordinary public RSS any
reader subscribes to.)

Read live 2026-10-07 (one GET): the feed's 10 newest items included the October 1,
2026 "Master's Sales" article with 12 notices. Each notice carries the civil action
number (``C/A No. 2026CP4002231`` -- CP 40 is Richland), the caption (plaintiff vs.
defendants), "I, the undersigned Master for Richland County, will sell on <date>",
the legal description, ``Property Address:`` / ``ADDRESS OF PROPERTY:``, the TMS
number and whether a deficiency judgment is demanded or waived.

Every notice is a judicial foreclosure sale with a date; it ships as FORECLOSURE_SALE
where the county is in the flip footprint and as LIS_PENDENS (a pending foreclosure,
sale date kept) everywhere else, the same remap the NC notice scrapers use, so the
board's flip-footprint gate does not drop it. Gate with FORECLOSURE_COLUMBIA_STAR=0.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

import structlog
from dateutil import parser as dateparser

from ...base_scraper import BaseScraper
from ...config import in_scope
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

FEED = "https://www.thecolumbiastar.com/category/public-notices/feed/"
ENV_OFF = "FORECLOSURE_COLUMBIA_STAR"
MAX_FEED_PAGES = int(os.environ.get("COLUMBIA_STAR_FEED_PAGES", "2"))
_PAUSE_S = 1.7

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S | re.I)
_CONTENT_RE = re.compile(r"<content:encoded>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</content:encoded>", re.S | re.I)
_SPLIT_RE = re.compile(r"(?=MASTER[’'`]?S\s+SALE)", re.I)
# Docket number in any of the printed forms: "C/A No. 2026CP4002231", "Civil Action No.
# 2025-CP-40-01804" (sometimes with a stray space after a hyphen) or bare after the heading.
_CASE_RE = re.compile(r"\b(\d{4}\s*-?\s*CP\s*-?\s*\d{2}\s*-?\s*\d{3,6})\b", re.I)
_CAPTION_RE = re.compile(
    r"(?:in\s+the\s+(?:case|matter)\s+of\s*:?)\s*(.+?)\s+(?:vs?\.|versus|against)\s+(.+?)"
    r"(?:;?\s*,?\s*(?:C\s*/\s*A|Civil\s+Action)\b|,?\s*I,?\s+the\s+undersigned|,?\s+the\s+undersigned)", re.I | re.S)
_MASTER_COUNTY_RE = re.compile(r"Master(?:\s+in\s+Equity)?\s+for\s+([A-Z][a-z]+)\s+County", re.I)
_SALE_DATE_RE = re.compile(
    r"will\s+sell\s+on\s+(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})", re.I)
_ADDRESS_RE = re.compile(
    r"(?:Property\s+Address|Address\s+of\s+(?:the\s+)?Property)\s*:\s*(.+?)"
    r"(?=\s+(?:TMS|Tax\s+Map|TERMS\s+OF\s+SALE|Derivation|PIN)\b|$)", re.I | re.S)
_TMS_RE = re.compile(r"\bTMS(?:\s*/\s*PIN)?\s*(?:#|No\.?|Number)?\s*:?\s*#?\s*([A-Z]?\d{4,6}-\d{2}-\d{2,3}[A-Z]?)", re.I)
_CITY_ZIP_RE = re.compile(r",\s*([A-Za-z .]+?),\s*SC\s+(\d{5})\s*$", re.I)
_DEFICIENCY_RE = re.compile(r"deficiency\s+judgment\s+being\s+(expressly\s+)?(waived|demanded)", re.I)


def notice_texts(content_html: str) -> list[str]:
    """One "Master's Sales" article -> the plain text of each notice in it."""
    txt = html.unescape(re.sub(r"<[^>]+>", " ", content_html or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    return [p.strip() for p in _SPLIT_RE.split(txt) if re.match(r"MASTER", p.strip(), re.I)]


def _clean(v: str | None, limit: int = 200) -> str | None:
    s = re.sub(r"\s+", " ", v or "").strip(" ,;:.")
    return s[:limit] or None


def _first_party(defendants: str | None) -> str | None:
    """'Jane Q Sample; John Sample; Any Bank, N.A.' -> 'Jane Q Sample'."""
    if not defendants:
        return None
    first = re.split(r";|\s+and\s+|,\s+(?=[A-Z][a-z]+\s+[A-Z])", defendants)[0]
    first = re.sub(r"\b(?:a/k/a|aka)\b.*$", "", first, flags=re.I)
    return _clean(first, 120)


def parse_notice(text: str) -> dict[str, Any] | None:
    case_m = _CASE_RE.search(text)
    if not case_m:
        return None
    case = re.sub(r"\s|-", "", case_m.group(1)).upper()
    cap = _CAPTION_RE.search(text)
    plaintiff = _clean(cap.group(1)) if cap else None
    defendants = _clean(cap.group(2), 400) if cap else None
    county_m = _MASTER_COUNTY_RE.search(text)
    sale_m = _SALE_DATE_RE.search(text)
    sale = None
    if sale_m:
        try:
            sale = dateparser.parse(sale_m.group(1))
        except (ValueError, OverflowError):
            sale = None
    addr_m = _ADDRESS_RE.search(text)
    address = _clean(addr_m.group(1), 160) if addr_m else None
    street, city, zip_code = address, None, None
    if address:
        cz = _CITY_ZIP_RE.search(address)
        if cz:
            street, city, zip_code = _clean(address[:cz.start()], 120), cz.group(1).strip().title(), cz.group(2)
    tms_m = _TMS_RE.search(text)
    deficiency_m = _DEFICIENCY_RE.search(text)
    return {
        "case_number": case,
        "plaintiff": plaintiff,
        "defendants": defendants,
        "owner": _first_party(defendants),
        "county": county_m.group(1).title() if county_m else ("Richland" if case[4:8] == "CP40" else None),
        "sale_date": sale,
        "street": street,
        "city": city,
        "zip": zip_code,
        "tms": tms_m.group(1).upper() if tms_m else None,
        "deficiency": deficiency_m.group(2).lower() if deficiency_m else None,
    }


def build_listing(rec: dict[str, Any], *, article_url: str, published: datetime | None,
                  text: str, now: datetime) -> Listing | None:
    county = rec.get("county")
    if not county:
        return None
    flip_ok = in_scope(county, "SC")
    return Listing(
        source=ColumbiaStarMastersSales.slug,
        source_url=article_url,
        listing_type=ListingType.FORECLOSURE_SALE if flip_ok else ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",
        county=county,
        street_address=rec.get("street"),
        city=rec.get("city"),
        zip_code=rec.get("zip"),
        parcel_id=rec.get("tms"),
        sale_date=rec.get("sale_date"),
        foreclosure_process="judicial",
        plaintiff=rec.get("plaintiff"),
        defendant=rec.get("owner"),
        owner_name=rec.get("owner"),
        case_number=rec["case_number"],
        description=(f"{county} County SC Master-in-Equity sale {rec['case_number']}"
                     + (f" on {rec['sale_date'].date().isoformat()}" if rec.get("sale_date") else "")
                     + f": {rec.get('plaintiff') or '?'} v. {rec.get('owner') or '?'}")[:300],
        first_seen=now,
        last_seen=now,
        raw={"public_notice": {
            "site": "thecolumbiastar.com",
            "article": article_url,
            "published_at": published.isoformat() if published else None,
            "kind": "mie_sale",
            "defendants": rec.get("defendants"),
            "deficiency_judgment": rec.get("deficiency"),
            "preview_text": text[:4000],
            "preview_truncated": len(text) > 4000,
        }},
    )


def parse_feed(xml: str) -> list[dict[str, Any]]:
    """Feed -> [{title, link, published, content}] for every item."""
    out: list[dict[str, Any]] = []
    for item in _ITEM_RE.findall(xml or ""):
        title = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", item, re.S) or [None, ""])[1])).strip()
        link = (re.search(r"<link>(.*?)</link>", item, re.S) or [None, ""])[1].strip()
        pub = (re.search(r"<pubDate>(.*?)</pubDate>", item, re.S) or [None, ""])[1].strip()
        try:
            published = parsedate_to_datetime(pub).replace(tzinfo=None) if pub else None
        except (TypeError, ValueError):
            published = None
        cm = _CONTENT_RE.search(item)
        out.append({"title": title, "link": link, "published": published, "content": cm.group(1) if cm else ""})
    return out


def is_masters_sales(title: str) -> bool:
    return bool(re.match(r"\s*master[’'`]?s\s+sales?\b", title or "", re.I))


class ColumbiaStarMastersSales(BaseScraper):
    slug = "newspapers.columbia_star"
    name = "The Columbia Star: Richland County Master-in-Equity sale notices"
    category = "newspaper"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("columbia_star.disabled")
            return []
        now = datetime.utcnow()
        out: list[Listing] = []
        seen: set[str] = set()
        async with client(timeout=45.0) as http:
            for page in range(1, max(1, MAX_FEED_PAGES) + 1):
                if page > 1:
                    await asyncio.sleep(_PAUSE_S)
                url = FEED if page == 1 else f"{FEED}?paged={page}"
                try:
                    r = await http.get(url)
                except Exception as exc:  # noqa: BLE001
                    log.warning("columbia_star.fetch_failed", page=page, error=str(exc)[:160])
                    break
                if r.status_code != 200 or "<rss" not in r.text[:600].lower():
                    log.warning("columbia_star.not_rss", page=page, status=r.status_code)
                    break
                for item in parse_feed(r.text):
                    if not is_masters_sales(item["title"]):
                        continue
                    for text in notice_texts(item["content"]):
                        rec = parse_notice(text)
                        if not rec or rec["case_number"] in seen:
                            continue
                        li = build_listing(rec, article_url=item["link"], published=item["published"],
                                           text=text, now=now)
                        if li is not None:
                            seen.add(rec["case_number"])
                            out.append(li)
        log.info("columbia_star.parsed", listings=len(out))
        return out


if __name__ == "__main__":
    from collections import Counter

    async def _main() -> None:
        s = ColumbiaStarMastersSales()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print("types", Counter(li.listing_type.value for li in rows).most_common(),
              "counties", Counter(li.county for li in rows).most_common())
        print("with_address", sum(1 for li in rows if li.street_address),
              "with_tms", sum(1 for li in rows if li.parcel_id),
              "with_sale_date", sum(1 for li in rows if li.sale_date),
              "with_owner", sum(1 for li in rows if li.owner_name))

    asyncio.run(_main())

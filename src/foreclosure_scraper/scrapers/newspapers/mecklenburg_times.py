"""The Mecklenburg Times: real-estate legal notices (Mecklenburg, Union, Iredell NC) via RSS.

Source
------
The Mecklenburg Times is the legal organ for Charlotte. Its public-notice section
(https://mecktimes.com/public-notice/) groups notices by index group and exports each
group as RSS, 30 items a page:

    https://mecktimes.com/public-notice/export-rss/?feeds=real_estate&pageindex=1

Each item: <title> is the property address ("10400 Example Rd Charlotte"), <link> the
notice detail page, <pubDate> the publication date, and <description> the first ~550
characters of the notice, starting "Auction Date: MM/DD/YYYY Description: NOTICE OF ...".
Read live 2026-10-07 (one GET): 30 items, every one with an auction date. Kinds seen:
power-of-sale foreclosures ("NOTICE OF FORECLOSURE SALE", "NOTICE OF SUBSTITUTE
TRUSTEE'S FORECLOSURE SALE", amended notices), HOA lien foreclosures ("NOTICE OF SALE OF
REAL ESTATE UNDER CLAIM OF LIEN"), and court-ordered sales ("NOTICE OF SALE ... IN THE
GENERAL COURT OF JUSTICE", "NOTICE OF SALE REAL PROPERTY 22CVD..."). The special-
proceeding or civil case number is usually in the preview; the record owner is when the
notice uses the labelled form ("Record Owner:") or names the deed-of-trust grantor.

The NC eCourts portal's foreclosure hearings sit behind a CAPTCHA and ncnotices.com
(already read) put only a handful of Mecklenburg rows on the board, so this is the open
route to Charlotte-area power-of-sale notices. Mecklenburg, Union and Iredell are outside
the flip footprint, so sale notices ship as LIS_PENDENS with the auction date kept (the
same remap the NC notice scrapers use); tax-foreclosure sales ship as TAX_SALE.

Access: open RSS, no login. Up to MECKTIMES_MAX_PAGES (default 4) GETs per run, 1.7 s
apart, stopping at the first empty page or once items are older than 60 days. Live proof
2026-10-07: 64 items -> 63 leads (44 power-of-sale, 10 court sales, 9 HOA lien sales;
Mecklenburg 56, Union 4, Iredell 2, Rowan 1; 60 with case number, 62 with auction date).
CAUTION: after four proof runs inside about two minutes (about 12 GETs) the host began
answering 403; this module treats a 403 as BLOCKED and stops, and is meant to run once a
day. Do not loop it.
Gate with FORECLOSURE_MECKTIMES=0.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

import structlog

from ...base_scraper import BaseScraper
from ...config import in_scope
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ...validation import NC_COUNTIES
from ..public_notices.nc_notices_counties import (
    _BOOK_PAGE_RE,
    _CASE_RE,
    _CASE_SPACED_RE,
    _GRANTOR_RE,
    _RECORD_OWNER_RE,
    _tidy_name,
    title_action,
)

log = structlog.get_logger()

FEED = "https://mecktimes.com/public-notice/export-rss/?feeds=real_estate&pageindex={page}"
ENV_OFF = "FORECLOSURE_MECKTIMES"
MAX_PAGES = int(os.environ.get("MECKTIMES_MAX_PAGES", "4"))
LOOKBACK_DAYS = 60
_PAUSE_S = 1.7

#: Postal city -> county for the paper's three counties (and neighbours that appear).
CITY_COUNTY = {
    "charlotte": "Mecklenburg", "matthews": "Mecklenburg", "huntersville": "Mecklenburg",
    "cornelius": "Mecklenburg", "davidson": "Mecklenburg", "mint hill": "Mecklenburg",
    "pineville": "Mecklenburg",
    "monroe": "Union", "indian trail": "Union", "waxhaw": "Union", "wingate": "Union",
    "marshville": "Union", "stallings": "Union", "weddington": "Union", "wesley chapel": "Union",
    "marvin": "Union", "mineral springs": "Union", "unionville": "Union", "fairview": "Union",
    "statesville": "Iredell", "mooresville": "Iredell", "troutman": "Iredell", "harmony": "Iredell",
    "concord": "Cabarrus", "kannapolis": "Cabarrus", "harrisburg": "Cabarrus", "midland": "Cabarrus",
    "gastonia": "Gaston", "belmont": "Gaston", "mount holly": "Gaston",
}
_CITY_RE = re.compile(r"\s+(" + "|".join(sorted((re.escape(c) for c in CITY_COUNTY), key=len, reverse=True))
                      + r")\s*$", re.I)
_COUNTY_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(c) for c in NC_COUNTIES), key=len, reverse=True))
                        + r")\s+COUNTY\b", re.I)
_AUCTION_RE = re.compile(r"Auction\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_TRUSTEE_RE = re.compile(r"\bTrustee:\s*(.+?)\s+(?:Date\s+of\s+Sale|Time\s+of\s+Sale|Place\s+of\s+Sale)", re.I)
_ADDRESS_LABEL_RE = re.compile(
    r"Address\s+of\s+Property:\s*(.+?)(?=\s+(?:Deed\s+of\s+Trust|Date\s+of|Tax|Parcel|PIN|Present)\b|$)", re.I)
_LABEL_OWNER_RE = re.compile(
    r"Record\s+Owners?\(?s?\)?\s*:\s*(.+?)\s+(?=Address\s+of\s+Property|Deed\s+of\s+Trust|Date\s+of|"
    r"Tax\s+(?:Parcel|ID)|Parcel|PIN\b|$)", re.I)
# The labelled form prints "Deed of Trust: Book : 38514 Page: 168".
_BOOK_PAGE_LABEL_RE = re.compile(r"Book\s*:?\s*([0-9A-Za-z]{1,8}),?\s+(?:at\s+)?Page\s*:?\s*([0-9A-Za-z]{1,8})", re.I)
_ADDR_TAIL_RE = re.compile(r"^(.*?),?\s*(?:NC|North Carolina)\s+(\d{5})", re.I)


def classify(text: str) -> str | None:
    t = text.lower()
    if "claim of lien" in t:
        return "hoa_lien"
    if re.search(r"\btax(?:es)?\b", t) and ("foreclos" in t or "delinquent" in t):
        return "tax_foreclosure"
    if re.search(r"foreclos|substitute\s+trustee|deed\s+of\s+trust", t):
        return "foreclosure"
    if re.search(r"notice\s+of\s+(?:re-?)?sale", t):
        return "court_sale"
    return None


def _clean(v: str | None, limit: int = 160) -> str | None:
    s = re.sub(r"\s+", " ", v or "").strip(" ,;:.")
    return s[:limit] or None


def split_title(title: str) -> tuple[str | None, str | None]:
    """'10400 Example Rd Charlotte' -> ('10400 Example Rd', 'Charlotte')."""
    t = re.sub(r"\s+", " ", title or "").strip()
    m = _CITY_RE.search(t)
    if m and m.start() > 0:
        return t[:m.start()].strip() or None, m.group(1).title()
    return (t or None), None


def parse_item(item: dict[str, Any]) -> dict[str, Any] | None:
    desc = item["description"]
    kind = classify(desc)
    if not kind:
        return None
    street, city = split_title(item["title"])
    zip_code = None
    lab = _ADDRESS_LABEL_RE.search(desc)
    if lab:
        tail = _ADDR_TAIL_RE.match(_clean(lab.group(1), 200) or "")
        if tail:
            pre, zip_code = tail.group(1).strip(" ,"), tail.group(2)
            s2, c2 = split_title(pre)
            if c2 is None and "," in pre:
                s2, c2 = pre.rsplit(",", 1)[0], pre.rsplit(",", 1)[1].strip().title()
            street, city = _clean(s2, 120), (c2 or city)
    county = None
    cm = _COUNTY_RE.search(desc)
    if cm:
        county = next((c for c in NC_COUNTIES if c.lower() == cm.group(1).lower()), None)
    if not county and city:
        county = CITY_COUNTY.get(city.lower())
    case_m = _CASE_RE.search(desc) or _CASE_SPACED_RE.search(desc)
    case = re.sub(r"\s+", "", case_m.group(1)).upper() if case_m else None
    owner = None
    for rx in (_LABEL_OWNER_RE, _RECORD_OWNER_RE, _GRANTOR_RE):
        m = rx.search(desc)
        if m:
            owner = _tidy_name(m.group(1))
            if owner:
                break
    auction = None
    am = _AUCTION_RE.search(desc)
    if am:
        try:
            auction = datetime.strptime(am.group(1), "%m/%d/%Y")
        except ValueError:
            auction = None
    book = _BOOK_PAGE_RE.search(desc) or _BOOK_PAGE_LABEL_RE.search(desc)
    trustee = _TRUSTEE_RE.search(desc)
    return {
        "kind": kind, "street": street, "city": city, "zip": zip_code, "county": county,
        "case_number": case, "owner": owner, "auction_date": auction,
        "trustee": _clean(trustee.group(1), 120) if trustee else None,
        "deed_of_trust": {"book": book.group(1), "page": book.group(2)} if book else None,
        "title_action": title_action(desc),
    }


def build_listing(rec: dict[str, Any], item: dict[str, Any], *, now: datetime) -> Listing | None:
    county = rec.get("county")
    if not county or not (rec.get("street") or rec.get("case_number")):
        return None
    kind = rec["kind"]
    if kind == "tax_foreclosure":
        lt, process = ListingType.TAX_SALE, "tax"
    elif kind == "hoa_lien":
        lt, process = (ListingType.HOA_SALE if in_scope(county, "NC") else ListingType.LIS_PENDENS), "power_of_sale"
    elif kind == "foreclosure":
        lt, process = (ListingType.FORECLOSURE_SALE if in_scope(county, "NC") else ListingType.LIS_PENDENS), "power_of_sale"
    else:
        lt, process = ListingType.LIS_PENDENS, "judicial"
    published = item.get("published")
    block: dict[str, Any] = {
        "site": "mecktimes.com",
        "detail_url": item.get("link"),
        "publication": "The Mecklenburg Times",
        "published_at": published.isoformat() if published else None,
        "kind": kind,
        "trustee": rec.get("trustee"),
        "preview_text": item["description"][:4000],
        "preview_truncated": True,
    }
    if rec.get("deed_of_trust"):
        block["deed_of_trust"] = rec["deed_of_trust"]
    if rec.get("title_action"):
        block["title_action"] = rec["title_action"]
    when = rec["auction_date"].date().isoformat() if rec.get("auction_date") else "?"
    return Listing(
        source=MecklenburgTimesNotices.slug,
        source_url=item.get("link") or FEED.format(page=1),
        listing_type=lt,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county=county,
        street_address=rec.get("street"),
        city=rec.get("city"),
        zip_code=rec.get("zip"),
        sale_date=rec.get("auction_date"),
        foreclosure_process=process,
        trustee=rec.get("trustee"),
        defendant=rec.get("owner"),
        owner_name=rec.get("owner"),
        case_number=rec.get("case_number"),
        description=(f"{county} County NC {kind.replace('_', ' ')} notice, auction {when}: "
                     f"{rec.get('street') or ''} ({rec.get('case_number') or 'no case number in preview'})")[:300],
        first_seen=now,
        last_seen=now,
        raw={"public_notice": block},
    )


def parse_feed(xml: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in re.findall(r"<item>(.*?)</item>", xml or "", re.S | re.I):
        def tag(name: str) -> str:
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", raw, re.S | re.I)
            v = html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))) if m else ""
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", v)).strip()
        pub = tag("pubDate")
        try:
            published = parsedate_to_datetime(pub).replace(tzinfo=None) if pub else None
        except (TypeError, ValueError):
            published = None
        out.append({"title": tag("title"), "link": tag("link"), "description": tag("description"),
                    "published": published})
    return out


class MecklenburgTimesNotices(BaseScraper):
    slug = "newspapers.mecklenburg_times"
    name = "The Mecklenburg Times: real-estate legal notices (RSS)"
    category = "newspaper"
    timeout_s = 120.0
    expected_min_count = 0
    optional = True

    async def fetch(self) -> Iterable[Listing]:
        if os.environ.get(ENV_OFF, "1") == "0":
            log.info("mecktimes.disabled")
            return []
        now = datetime.utcnow()
        cutoff = now - timedelta(days=LOOKBACK_DAYS)
        out: list[Listing] = []
        seen: set[str] = set()
        async with client(timeout=45.0) as http:
            for page in range(1, max(1, MAX_PAGES) + 1):
                if page > 1:
                    await asyncio.sleep(_PAUSE_S)
                try:
                    r = await http.get(FEED.format(page=page))
                except Exception as exc:  # noqa: BLE001
                    log.warning("mecktimes.fetch_failed", page=page, error=str(exc)[:160])
                    break
                if r.status_code != 200 or "<rss" not in r.text[:600].lower():
                    log.warning("mecktimes.not_rss", page=page, status=r.status_code)
                    break
                items = parse_feed(r.text)
                if not items:
                    break
                for item in items:
                    key = item.get("link") or item.get("title")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rec = parse_item(item)
                    li = build_listing(rec, item, now=now) if rec else None
                    if li is not None:
                        out.append(li)
                newest = max((i["published"] for i in items if i.get("published")), default=None)
                if newest is not None and newest < cutoff:
                    break
        log.info("mecktimes.parsed", listings=len(out), items=len(seen))
        return out


if __name__ == "__main__":
    from collections import Counter

    async def _main() -> None:
        s = MecklenburgTimesNotices()
        rows = await s.safe_run()
        print(f"outcome={s.last_outcome} count={len(rows)}")
        print("kinds", Counter(li.raw["public_notice"]["kind"] for li in rows).most_common(),
              "types", Counter(li.listing_type.value for li in rows).most_common(),
              "counties", Counter(li.county for li in rows).most_common())
        print("with_case", sum(1 for li in rows if li.case_number), "with_owner", sum(1 for li in rows if li.owner_name),
              "with_street", sum(1 for li in rows if li.street_address), "with_sale_date", sum(1 for li in rows if li.sale_date),
              "future_sale", sum(1 for li in rows if li.sale_date and li.sale_date >= datetime.utcnow()))

    asyncio.run(_main())

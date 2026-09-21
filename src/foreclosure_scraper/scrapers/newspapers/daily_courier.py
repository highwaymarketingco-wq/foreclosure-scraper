"""The Daily Courier (Forest City, NC) legal classifieds — foreclosure notices.

Rutherford County, NC. The paper hosts public legal notices in TownNews TNCMS
classifieds. Each notice gets its own /classifieds/.../ad_<uuid>.html detail
page.

URL: https://www.thedigitalcourier.com/classifieds/community/announcements/legal/

Listing page: ~10 currently-active legal ads, each a card with only a title and a date
("NORTH CAROLINA RUTHERFORD COUNTY" for a foreclosure or other court notice, "NOTICE TO
CREDITORS", "NOTICE OF PUBLIC HEARING ..."). Paging params are ignored.

REVIVAL 2026-09-21 -- WHAT BROKE AND WHAT CHANGED
  The scraper returned zero in every logged run although the page is fine and carried
  two live foreclosure sales on the day of the fix. Three separate things had drifted:

  1. FILE NUMBER. NC special-proceeding numbers now print as ``26SP000130-800`` (2 digit
     year, ``SP``, SIX digits, ``-800`` = Rutherford's county code). The old pattern allowed
     1 to 5 digits then a word boundary, so it could never match and ``case_number`` was
     always empty.
  2. ADDRESS / OWNER LABELS. The notices now read ``Address of Property: 2831 Cove Road
     Rutherfordton, NC 28139`` and ``Record Owners: ...``; the old patterns looked for
     ``Property address`` / ``known as`` / ``Present Owner(s)``. With no case number AND no
     address the precision gate dropped every row.
  3. BODY TEXT. The meta description is cut at ~270 characters and its words are run
     together ("NOTICE OFFORECLOSURE SALEDate of Sale:September 22, 2026"). The full notice
     (6 KB) is the ``itemprop="description"`` element; it is read with a space separator.

  Also: the host answers HTTP 429 ("Too Many Requests", plain text, no Retry-After) after a
  handful of requests in a few seconds, and the old loop skipped a 429'd ad silently. Fetches
  are now paced (``DAILY_COURIER_DELAY_S``, default 6 s), a 429 is retried with a growing
  wait, and cards whose title says NOTICE TO CREDITORS / PUBLIC HEARING / etc. are not
  fetched at all (8 of 10 cards on 2026-09-21), so a run is ~3 detail requests.

  The listing shows only ~10 live ads, so a notice is visible here only until it rolls off
  (project memory: the Rutherford upset-bid gap). NOTICE TO CREDITORS estate notices are
  deliberately NOT emitted: they are dateless and this slug is not in
  ``main.DATELESS_OK_SOURCES``. Adding them is one line there plus a PROBATE_NOTICE branch.
"""
from __future__ import annotations

import asyncio
import email.utils
import os
import re
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

import structlog
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind
from ..counties_nc.rutherford_tax import _split_situs

log = structlog.get_logger()

BASE = "https://www.thedigitalcourier.com"
#: TownNews caps this classifieds index at the ~10 currently-active legal ads and
#: ignores paging params (verified live 2026-08-13 and 2026-09-21).
LISTING_URLS = [
    "https://www.thedigitalcourier.com/classifieds/community/announcements/legal/",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
}

#: Seconds between requests to this host. It 429s a burst of ~4 requests in a few seconds.
DELAY_S = float(os.environ.get("DAILY_COURIER_DELAY_S", "6"))
MAX_ATTEMPTS = 3
MAX_ADS = 14

#: NC file numbers: 26SP000130-800, 25 SP 123, 24CVD1234, 26M000412. Year + type + digits,
#: with an optional ``-NNN`` county code that is not part of the case identity.
FILE_RE = re.compile(
    r"\b(\d{2})\s*(SP|M|CVD|CVS|CVM)\s*(\d{1,7})(?:\s*-\s*(\d{3}))?\b", re.I)
ADDR_LABEL_RE = re.compile(
    r"(?:Address\s+of\s+(?:the\s+)?Property|Property\s+address|known\s+as|located\s+at)\s*[:\s]\s*"
    r"([0-9][^\n]*?\bNC\s*\d{5})", re.I)
ADDR_FALLBACK_RE = re.compile(
    r"(?:Property\s+address|known\s+as|located\s+at)[:\s]+([0-9][^.\n<]*?(?:NC\s*\d{5})?)", re.I)
SALE_DATE_LABEL_RE = re.compile(
    r"Date\s+of\s+Sale\s*:\s*((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})", re.I)
SALE_TIME_RE = re.compile(r"Time\s+of\s+Sale\s*:\s*(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)", re.I)
SALE_PLACE_RE = re.compile(
    r"Place\s+of\s+Sale\s*:\s*(.+?)(?=\s+(?:Description|Record|Address|Deed|CONDITIONS)\b|$)", re.I)
SALE_DATE_RE = re.compile(
    r"(?:will\s+(?:be\s+)?(?:offer|expose|sell)|sale\s+(?:will|on)|on)\s+(?:[a-z\s]{0,40}?on\s+)?"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}(?:,?\s+at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM|a\.?m\.?|p\.?m\.?))?)",
    re.I,
)
SALE_DATE_FALLBACK = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
TRUSTEE_LABEL_RE = re.compile(
    r"(?:Substitute\s+)?Trustee\s*:\s*([A-Z][A-Za-z.'\- ]{2,80}?)"
    r"(?=\s+(?:NOTICE|Date|Time|Place|Description|Record|Address|Deed)\b|\s*$)")
TRUSTEE_RE = re.compile(
    r"(?:Substitute\s+Trustee|the\s+Trustee|Trustee[,]):\s*([A-Z][A-Za-z &,.'-]+(?:LLC|LLP|PA|PC|Inc|PLLC|Carolinas|Law Firm)[^.\n]*)",
    re.I,
)
BENEFICIARY_RE = re.compile(
    r"(?:Original\s+)?Beneficiary\s*:\s*(.+?)(?=\s+(?:CONDITIONS|This\s+sale|Deed\s+of\s+Trust|Grantors|"
    r"Address|Record|Dated|Book)\b|$)", re.I)
PLAINTIFF_RE = re.compile(
    r"(?:Lien\s+filed[^.]*?by|secured\s+by[^.]*?lien\s+held\s+by|in\s+favor\s+of)\s+([A-Z][A-Za-z0-9 &,.'-]+(?:LLC|Inc|Bank|N\.?A\.?|Trust|Association|Mortgage|Servicing)[^.,\n]*)",
    re.I,
)
OWNERS_LABEL_RE = re.compile(
    r"(?:Record\s+Owners?|Present\s+Owner\(?s?\)?|Owners?\s+of\s+Record)\s*:\s*(.+?)"
    r"(?=\s+(?:Address|Deed|Description|Grantors?|Original|CONDITIONS|The\s+sale)\b|$)", re.I)
DEED_RE = re.compile(
    r"Deed\s+of\s+Trust\s*:\s*Book\s*:?\s*(\d+)\s*Page\s*:?\s*(\d+)"
    r"(?:\s*Dated\s*:?\s*((?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}))?", re.I)

#: A card whose TITLE says one of these is never a foreclosure; it is not fetched.
_SKIP_TITLE_RE = re.compile(
    r"creditors|public\s+hearing|hearing|ordinance|budget|zoning|rezoning|invitation\s+to\s+bid|"
    r"request\s+for\s+(?:proposals|qualifications)|advertisement\s+for\s+bid|name\s+change|"
    r"meeting|election|resolution|abandoned|surplus", re.I)

_TITLE_MAX = 200


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _is_foreclosure(title: str, body: str) -> bool:
    t = (title + " " + body[:800]).lower()
    return (
        "foreclos" in t
        or "notice of sale" in t
        or "substitute trustee" in t
        or "trustee's sale" in t
        or "deed of trust" in t
    )


def _worth_fetching(title: str) -> bool:
    """False for a card whose title already says it is not a foreclosure notice."""
    return not _SKIP_TITLE_RE.search(title or "")


def parse_listing_cards(html: str) -> list[tuple[str, str]]:
    """(absolute detail URL, card title) per legal-notice card on the index page, deduped,
    in page order. Falls back to bare href discovery if the card markup changes."""
    tree = HTMLParser(html or "")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for card in tree.css("article.card"):
        a = card.css_first("a[href*='/ad_']")
        if a is None:
            continue
        href = (a.attributes.get("href") or "").strip()
        if not re.search(r"/classifieds/community/announcements/legal/[^\"']+/ad_[^\"']+\.html", href):
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        seen.add(url)
        h = card.css_first(".card-title, h3, h4")
        title = _clean(h.text()) if h else ""
        out.append((url, title))
    if out:
        return out
    for m in re.finditer(
            r'href="(/classifieds/community/announcements/legal/[^"]+/ad_[^"]+\.html)"', html or ""):
        url = urljoin(BASE, m.group(1))
        if url not in seen:
            seen.add(url)
            out.append((url, ""))
    return out


def _notice_text(tree: HTMLParser) -> str:
    """Full notice text: the itemprop=description element (6 KB, real word breaks), else the
    truncated meta description."""
    node = tree.css_first('[itemprop="description"]')
    if node is not None:
        txt = _clean(node.text(separator=" "))
        if txt:
            return txt
    meta = tree.css_first('meta[name="description"]')
    return _clean(meta.attributes.get("content", "")) if meta else ""


def _split_address(addr: str) -> tuple[str | None, str | None, str | None]:
    """'2831 Cove Road Rutherfordton, NC 28139' -> ('2831 Cove Road', 'Rutherfordton', '28139')."""
    street, city, zipc, _legal = _split_situs(addr)
    return street, city, zipc


def parse_notice(html: str, ad_url: str, now: datetime | None = None) -> Listing | None:
    """One foreclosure notice detail page -> Listing, or None when it is not a foreclosure
    or carries neither a court file number nor a usable address."""
    tree = HTMLParser(html or "")
    h1 = tree.css_first("h1")
    title = _clean(h1.text()) if h1 else ""
    body = _notice_text(tree)
    if not body or not _is_foreclosure(title, body):
        return None

    case_number = case_full = None
    fm = FILE_RE.search(body) or FILE_RE.search(title)
    if fm:
        yy, kind, num, county_code = fm.group(1), fm.group(2).upper(), fm.group(3), fm.group(4)
        case_number = f"{yy}{kind}{num}"
        case_full = case_number + (f"-{county_code}" if county_code else "")

    address = None
    am = ADDR_LABEL_RE.search(body)
    if am:
        address = am.group(1)
    else:
        am = ADDR_FALLBACK_RE.search(body)
        if am:
            address = am.group(1)
    street = city = zip_code = None
    if address:
        address = re.sub(r"\s+", " ", address).rstrip(".,").strip()[:300]
        if len(address) < 10:
            address = None
        else:
            street, city, zip_code = _split_address(address)
            street = street or address
    if not zip_code:
        zm = re.search(r"NC\s*(\d{5})", body)
        zip_code = zm.group(1) if zm else None

    # Precision gate: a foreclosure notice with neither a court file nor a usable street
    # address is not an actionable lead.
    if not case_number and not address:
        return None

    sale_date = None
    dm = SALE_DATE_LABEL_RE.search(body) or SALE_DATE_RE.search(body) or SALE_DATE_FALLBACK.search(body)
    if dm:
        try:
            sale_date = dateparser.parse(re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", dm.group(1)), fuzzy=True)
        except (ValueError, TypeError):
            sale_date = None
    tm = SALE_TIME_RE.search(body)
    sale_time = tm.group(1).strip() if tm else None
    pm_ = SALE_PLACE_RE.search(body)
    sale_place = pm_.group(1).strip(" .") if pm_ else None

    trustee = None
    t_m = TRUSTEE_LABEL_RE.search(body) or TRUSTEE_RE.search(body)
    if t_m:
        trustee = t_m.group(1).strip()[:200]

    plaintiff = None
    b_m = BENEFICIARY_RE.search(body)
    if b_m:
        plaintiff = b_m.group(1).strip(" .,")[:200] or None
    if not plaintiff:
        p_m = PLAINTIFF_RE.search(body)
        if p_m:
            plaintiff = p_m.group(1).strip()[:200]

    defendant = None
    o_m = OWNERS_LABEL_RE.search(body)
    if o_m:
        defendant = o_m.group(1).strip(" .,")[:200] or None

    deed = None
    dd = DEED_RE.search(body)
    if dd:
        deed = {"book": dd.group(1), "page": dd.group(2), "dated": dd.group(3)}

    when = now or datetime.utcnow()
    return Listing(
        source="newspapers.daily_courier",
        source_url=ad_url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        foreclosure_process="power_of_sale",
        state="NC",
        county="Rutherford",
        street_address=street,
        city=city,
        zip_code=zip_code,
        sale_date=sale_date,
        sale_time=sale_time,
        sale_location=sale_place or "Rutherford County Courthouse, Rutherfordton NC",
        case_number=case_number,
        plaintiff=plaintiff,
        defendant=defendant,
        owner_name=defendant,
        trustee=trustee,
        description=title[:_TITLE_MAX] or None,
        first_seen=when,
        last_seen=when,
        raw={"daily_courier": {
            "title": title,
            "case_number_full": case_full,
            "deed_of_trust": deed,
            "body_preview": body[:1500],
        }},
    )


def _retry_after_s(headers, default: float) -> float:
    raw = (headers.get("retry-after") or "").strip() if headers is not None else ""
    if not raw:
        return default
    try:
        return max(0.0, min(float(raw), 120.0))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
        return max(0.0, min((when - datetime.now(when.tzinfo)).total_seconds(), 120.0))
    except (TypeError, ValueError):
        return default


async def _polite_get(c, url: str) -> str | None:
    """GET with a growing wait on 429. Returns the body, or None if it never succeeded."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = await c.get(url, headers=HEADERS)
        if r.status_code == 200:
            return r.text
        if r.status_code == 429:
            wait = _retry_after_s(r.headers, default=20.0 * attempt)
            log.warning("daily_courier.rate_limited", url=url[-60:], attempt=attempt,
                        wait_s=round(wait, 1))
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(wait)
            continue
        log.warning("daily_courier.bad_status", url=url[-60:], status=r.status_code)
        return None
    return None


class DailyCourierForeclosures(BaseScraper):
    slug = "newspapers.daily_courier"
    name = "The Daily Courier Legal Classifieds (Rutherford NC)"
    category = "newspaper_legal"
    requires_apify = False
    expected_min_count = 1
    #: ~3 detail fetches at 6 s plus the listing, with room for two 429 back-offs.
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        cards: list[tuple[str, str]] = []
        out: list[Listing] = []
        seen: set[str] = set()
        async with client(timeout=25.0) as c:
            for url in LISTING_URLS:
                html = await _polite_get(c, url)
                if not html:
                    continue
                for card in parse_listing_cards(html):
                    if card[0] not in {x[0] for x in cards}:
                        cards.append(card)

            skipped = 0
            fetched = 0
            for ad_url, title in cards[:MAX_ADS]:
                if not _worth_fetching(title):
                    skipped += 1
                    continue
                await asyncio.sleep(DELAY_S)
                html = await _polite_get(c, ad_url)
                fetched += 1
                if not html:
                    continue
                li = parse_notice(html, ad_url)
                if li is None:
                    continue
                key = li.case_number or li.source_url
                if key in seen:
                    continue
                seen.add(key)
                out.append(li)
                self.partial.append(li)      # a soft timeout still ships what was read
            log.info("daily_courier.done", cards=len(cards), skipped_by_title=skipped,
                     fetched=fetched, notices=len(out))
        return out

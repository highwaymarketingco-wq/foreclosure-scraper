"""The Coastland Times (Manteo, NC) — Dare County public-notice foreclosures.

The Coastland Times is the legal-notice paper of record for Dare County, NC
(the Outer Banks: Manteo, Nags Head, Kill Devil Hills, Rodanthe, Hatteras) —
part of the coastal NC footprint. Its public-notices section carries the NC
substitute-trustee foreclosure-sale notices ("NOTICE OF FORECLOSURE SALE" /
"NOTICE OF SALE") published days-to-weeks BEFORE the auction — the pre-auction
signal we want.

Unlike most of our newspaper sources, the Coastland Times does NOT run on
TownNews/RSS — it's a custom pubgen.ai CMS. The notice index lives at
`/tags/public-notices` (mirrored at `/sections/public-notices`); each notice is
a `/public-notices/<slug>-<hash>` detail page whose body is server-rendered
inside the `<main>` element (no JS needed for the data we read).

Compliance note: the index 403s on a bare httpx request (no `User-Agent`). It
serves normally once we present a real desktop-browser header set — this is the
exact same StealthyFetcher-style fingerprint the shared client already uses, NOT
a CAPTCHA/WAF solver. We pass that header set through `get_text(headers=...)`;
plain GETs over HTTP/2 with a real UA clear the 403 (verified live).

NC substitute-trustee notices reliably carry, in prose:
  - the property street address ("said property being located at
    22083 Sea Gull Street, Rodanthe, North Carolina");
  - the county Register of Deeds / sale courthouse ("courthouse door in Manteo,
    Dare County, North Carolina");
  - the sale date + time ("at 10:30 AM on June 23, 2026");
  - the substitute trustee ("Substitute Trustee Services, Inc.");
  - the county tax parcel ("Dare County Parcel Number 012458006").

Verified live (2026-06-26): the public-notices index listed two current
foreclosure notices; the foreclosure-sale notice parsed to 22083 Sea Gull St,
Rodanthe (Dare NC), sale 2026-06-23 10:30 AM, trustee Substitute Trustee
Services Inc., parcel 012458006 — a clean pre-auction coastal lead.

Free, no login, no WAF solver, no JS for the data we read.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...http_client import get_text
from ...models import Listing, ListingType, PropertyKind
from ._townnews import NC_CASE_RE
from .column_legal_notices import _notice_email

BASE = "https://www.thecoastlandtimes.com"
# Both the tag view and the section view list the same notices; we read both and
# dedupe by detail URL so a layout change to one doesn't silently zero the run.
INDEX_URLS = (
    f"{BASE}/tags/public-notices",
    f"{BASE}/sections/public-notices",
)

# Real desktop-browser header set. The bare default httpx request (no UA) gets a
# 403 from the CMS edge; presenting a normal browser fingerprint serves the page
# (compliant — no solver, no challenge bypass). Mirrors http_client.DEFAULT_HEADERS.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": f"{BASE}/",
    "Upgrade-Insecure-Requests": "1",
}

# A detail link under /public-notices/. We keep only those whose slug hints at a
# foreclosure / trustee sale (the body is re-checked on the detail page anyway).
DETAIL_RE = re.compile(r'href="(/public-notices/[^"#?]+)"', re.I)
FORECLOSURE_SLUG_HINTS = ("foreclosure", "notice-of-sale", "trustee", "substitute")

# Phrases that confirm a detail page is actually a foreclosure/trustee sale.
FORECLOSURE_BODY_HINTS = (
    "foreclos",
    "substitute trustee",
    "power of sale",
    "deed of trust",
    "trustee will offer for sale",
    "offered for sale",
)

# "said property being located at 22083 Sea Gull Street, Rodanthe, North Carolina"
LOCATED_AT_RE = re.compile(
    r"located\s+at\s+(\d{1,6}\s+[A-Za-z0-9][\w .'\-]*?),\s*"
    r"([A-Za-z][A-Za-z .'\-]+?),\s*(?:North Carolina|NC)\b",
    re.I,
)
# Fallback bare street address anywhere in the body.
_SUFFIX = (
    r"Road|Rd|Street|St|Drive|Dr|Lane|Ln|Avenue|Ave|Highway|Hwy|Boulevard|Blvd|"
    r"Circle|Cir|Court|Ct|Way|Place|Pl|Trail|Trl|Parkway|Pkwy|Terrace|Ter|Loop|Cove"
)
ADDR_RE = re.compile(
    rf"\b(\d{{1,6}}\s+[A-Za-z][\w .'\-]*?\s+(?:{_SUFFIX})\.?)\b", re.I
)
# "Dare County Parcel Number 012458006" / "Parcel Number: 012458006"
PARCEL_RE = re.compile(
    r"(?:County\s+)?Parcel\s+(?:Number|No\.?|ID)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-\.]{4,20})",
    re.I,
)
# "at 10:30 AM on June 23, 2026"  -> capture time + date together.
SALE_DT_RE = re.compile(
    r"at\s+(\d{1,2}:\d{2}\s*(?:AM|PM))\s+on\s+"
    r"((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
# Bare date fallback ("on June 23, 2026").
DATE_RE = re.compile(
    r"\b((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4})",
    re.I,
)
SALE_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b", re.I)
ZIP_RE = re.compile(r"\b(27\d{3})(?:-\d{4})?\b")  # Dare/OBX zips are all 27xxx
# Substitute-trustee / firm name. The borrower's own LLC also appears ("made by
# Sea Strand LLC"), so we DON'T do a generic firm-suffix grab. Instead we anchor
# directly on the named trustee-service firms (self-contained names; no arbitrary
# leading capture that could swallow the preceding clause). Up to 3 capitalized
# name tokens may precede the "...Trustee Services, Inc." tail.
TRUSTEE_NAMED_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z.'\-]+\s+){0,3}"
    r"(?:Substitute\s+)?Trustee\s+Services,?\s*Inc\.?)",
)
# "Substitute Trustee: <Firm>" label form, firm ends in a corporate suffix and
# is limited to 4 name tokens so it can't run into the next sentence.
TRUSTEE_LABEL_RE = re.compile(
    r"Substitute\s+Trustee[:\s]+"
    r"((?:[A-Z][A-Za-z.'\-]+[,\s]+){1,4}"
    r"(?:Inc\.?|LLC|LLP|PLLC|P\.?A\.?|P\.?C\.?|Law\s+Offices?))",
)
# Grantor of the foreclosed Deed of Trust = the current record owner ("...Deed
# of Trust executed and delivered by Jackie H. Willis" / "made by Sea Strand LLC").
# Stop at the clause boundary so we don't swallow "to <Trustee>, dated ...".
GRANTOR_RE = re.compile(
    r"(?:executed(?:\s+and\s+delivered)?|made|given)\s+by\s+"
    r"([A-Z][A-Za-z0-9.'\- ]{2,70}?)"
    r"(?:\s*\(|,|;|\s+(?:dated|to\s+[A-Z]|and\s+recorded|in\s+favor|"
    r"as\s+grantor|Trustee)|$)",
    re.I,
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_foreclosure(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in FORECLOSURE_BODY_HINTS)


def _extract_body(html: str) -> tuple[str, str]:
    """Return (headline, body_text) from a notice detail page.

    Body = concatenated <p> text inside <main> (the rendered notice). JSON-LD
    blobs and page chrome are dropped first so they don't pollute the parse.
    """
    tree = HTMLParser(html)
    for tag in tree.css("script, style, nav, header, footer"):
        tag.decompose()
    h1 = tree.css_first("h1")
    headline = _clean(h1.text(strip=True)) if h1 else ""
    main = tree.css_first("main") or tree.body
    if main is None:
        return headline, ""
    paras = [
        _clean(p.text(separator=" "))
        for p in main.css("p")
        if len(_clean(p.text(separator=" "))) > 15
    ]
    return headline, " ".join(paras)


def _parse_detail(html: str, url: str, slug: str) -> Listing | None:
    headline, body = _extract_body(html)
    blob = f"{headline} {body}".strip()
    if not blob or not _is_foreclosure(blob):
        return None

    # Address: prefer the explicit "located at <street>, <city>, NC" phrasing.
    street = city = None
    m = LOCATED_AT_RE.search(body)
    if m:
        street = _clean(m.group(1)).rstrip(".,")
        cand_city = _clean(m.group(2)).rstrip(".,")
        if cand_city.isupper():
            cand_city = cand_city.title()
        if 2 <= len(cand_city) <= 40:
            city = cand_city
    if not street:
        am = ADDR_RE.search(body)
        if am:
            cand = _clean(am.group(1)).rstrip(".,")
            if len(cand) >= 6 and re.search(r"[A-Za-z]{3,}", cand):
                street = cand

    zip_code = None
    zm = ZIP_RE.search(body)
    if zm:
        zip_code = zm.group(1)

    parcel = None
    pm = PARCEL_RE.search(body)
    if pm:
        cand = pm.group(1).strip().rstrip(".,")
        if re.search(r"\d", cand):
            parcel = cand

    # Sale date + time: the combined "at <time> on <date>" form is the trustee
    # sale; fall back to a bare date if the combined form isn't present.
    sale_date = None
    sale_time = None
    dt_m = SALE_DT_RE.search(body)
    if dt_m:
        sale_time = _clean(dt_m.group(1)).upper().replace(" ", " ")
        try:
            sale_date = dateparser.parse(dt_m.group(2), fuzzy=True)
        except (ValueError, TypeError, OverflowError):
            sale_date = None
    if sale_date is None:
        dm = DATE_RE.search(body)
        if dm:
            try:
                sale_date = dateparser.parse(dm.group(1), fuzzy=True)
            except (ValueError, TypeError, OverflowError):
                sale_date = None
    if sale_time is None:
        tm = SALE_TIME_RE.search(body)
        if tm:
            sale_time = _clean(tm.group(1)).upper()

    trustee = None
    tr_m = TRUSTEE_NAMED_RE.search(body) or TRUSTEE_LABEL_RE.search(body)
    if tr_m:
        cand = _clean(tr_m.group(1))[:160]
        # Strip a leading "the"/"undersigned" the named-form may carry in.
        cand = re.sub(r"^(?:the|undersigned)\s+", "", cand, flags=re.I).strip()
        if len(cand) > 4 and cand.lower() not in {"the", "this"}:
            trustee = cand

    # NC Special-Proceedings case number ("26 SP 000132-110").
    case_number = None
    cn_m = NC_CASE_RE.search(blob)
    if cn_m:
        case_number = re.sub(r"\s+", "", cn_m.group(1)).upper()

    # Grantor of the foreclosed Deed of Trust = the current record owner.
    owner_name = None
    defendant = None
    g_m = GRANTOR_RE.search(body)
    if g_m:
        cand = _clean(g_m.group(1)).rstrip(",.;: ")
        if len(cand) >= 3 and re.search(r"[A-Za-z]{2}", cand):
            owner_name = cand
            defendant = cand

    # Attorney/trustee phone + email printed in the notice foot (a reachable
    # case contact, NOT the owner). Reuses the Column gold-standard extractor
    # so parcel-PIN / case-number digit runs can't leak in as a phantom phone.
    raw = {
        "coastland_times": {
            "headline": headline,
            "body": body[:1500],
        }
    }
    contact = _notice_email(body)
    if contact:
        raw["notice_contact"] = contact

    # SC mortgage-foreclosure summons would be lis-pendens-stage; these Dare
    # notices are power-of-sale trustee SALES, so classify as the sale itself.
    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="NC",
        county="Dare",
        street_address=street,
        city=city,
        zip_code=zip_code,
        parcel_id=parcel,
        sale_date=sale_date,
        sale_time=sale_time,
        sale_location="Dare County Courthouse, Manteo NC",
        foreclosure_process="power_of_sale",
        case_number=case_number,
        owner_name=owner_name,
        defendant=defendant,
        trustee=trustee,
        description=(headline or body)[:500] or None,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw=raw,
    )


def _index_detail_urls(html: str) -> list[str]:
    """Foreclosure-looking /public-notices/ detail URLs from an index page."""
    out: list[str] = []
    seen: set[str] = set()
    for m in DETAIL_RE.finditer(html):
        path = m.group(1)
        low = path.lower()
        if not any(h in low for h in FORECLOSURE_SLUG_HINTS):
            continue
        url = f"{BASE}{path}"
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


class CoastlandTimesForeclosures(BaseScraper):
    slug = "newspapers.coastland_times"
    name = "The Coastland Times Public Notices (Dare NC)"
    category = "newspaper_legal"
    requires_apify = False
    # Legal-notice volume swings week to week; a quiet week with 0 foreclosure
    # notices is data reality. A real regression is the index 403ing again (the
    # block-signal classifier surfaces that separately) or the detail layout
    # changing so no body parses.
    expected_min_count = 0
    timeout_s = 120.0

    async def fetch(self) -> Iterable[Listing]:
        out: list[Listing] = []
        seen_urls: set[str] = set()
        detail_urls: list[str] = []
        for index_url in INDEX_URLS:
            try:
                html = await get_text(index_url, timeout=30.0, headers=BROWSER_HEADERS)
            except Exception:
                continue
            for u in _index_detail_urls(html):
                if u not in seen_urls:
                    seen_urls.add(u)
                    detail_urls.append(u)

        for url in detail_urls:
            try:
                page = await get_text(url, timeout=30.0, headers=BROWSER_HEADERS)
            except Exception:
                continue
            li = _parse_detail(page, url, self.slug)
            if li is not None:
                out.append(li)
        return out

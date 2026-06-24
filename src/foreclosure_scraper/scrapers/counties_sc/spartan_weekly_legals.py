"""Spartan Weekly News legal notices — the FREE, bulk, no-WAF route to
Spartanburg-County foreclosure / probate / tax leads.

Why this source exists alongside sc_public_notices.py:
  * The SC court Public Index (lis pendens) is Rule-610 prohibited for commercial
    bulk + WAF-defended — not a free/legal bulk route.
  * Spartanburg ROD (search.spartanburgdeeds.com, newer Logan) is in a county-side
    empty-index state AND holds only POST-sale deeds (see rod/logan.py).
  * scpublicnotices.com's per-county advanced search 500s server-side and
    publicnoticesc.com has a challenge-response that defeats httpx + Scrapling.
  * Spartanburg's legal notices are ALSO published by The Spartan Weekly (the
    paper the Master-in-Equity uses), at /legal-notices/?page=N — plain paginated
    HTML, no anti-bot, address in the URL slug, case # + notice type in the row.

Mechanism (browserless, verified 2026-06-24):
  GET {HOST}/legal-notices/?page=N  ->  repeated article blocks:
    <div class="article ..."><h6>{TYPE}</h6>
      <h4><a href="/legal-notices/{slug}">{STREET ADDRESS}</a></h4>
      <p> Case #:{2025CP42…}<br> {Mon DD, YYYY} </p></div>
  TYPE is "Master In Equity" (foreclosure), "Probate Court", or "All Other".
  Detail page ({HOST}{href}) carries the full legal text -> defendant (vs.) and,
  for sale notices, the sale date/amount. We page until a page adds no new rows,
  then best-effort enrich each kept notice from its detail page (failures are
  non-fatal — list-row data already yields address + case# + type).
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Iterable

import structlog

from ...base_scraper import BaseScraper
from ...http_client import client
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

_HOST = "https://www.spartanweeklyonline.com"
_LIST = _HOST + "/legal-notices/?page={page}"
_MAX_PAGES = 40          # safety cap; loop also stops when a page adds nothing new
_ENRICH_DETAILS = True   # follow each notice to its detail page for the body text
_MAX_DETAIL_FETCH = 250  # bound detail fetches so a big run never blows timeout_s

_ARTICLE_RE = re.compile(
    r'<div class="article[^"]*">\s*'
    r'<h6>\s*(?P<type>[^<]*?)\s*</h6>\s*'
    r'<h4>\s*<a href="(?P<href>/legal-notices/[^"]+)">\s*(?P<addr>[^<]+?)\s*</a>\s*</h4>\s*'
    r'<p>(?P<meta>.*?)</p>',
    re.S,
)
_CASE_RE = re.compile(r"Case\s*#?:?\s*(20\d{2}CP\d{6,9})", re.I)
_DATE_RE = re.compile(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})")
# defendant from the legal-notice body: "...Plaintiff, vs. <NAME>, Defendant(s)..."
# SC Master-in-Equity sale notices read: "...in the case of PLAINTIFF v.
# DEFENDANTS, I, the undersigned as Master-in-Equity ... will sell on DATE...".
# Capture the defendant block between "v." and the "I, the undersigned" / "will
# sell" close — keeps multi-party lists and middle initials ("Thomas J. Lee").
_VS_RE = re.compile(
    # opener: "v." / "vs." / "against"; SC captions also read "... against NAME et al"
    r"\b(?:vs?\.?|against)\s+([A-Z][A-Za-z0-9 .,;'&#/()-]{3,250}?)"
    # close on the caption terminator — "; et.al.", ", I, the undersigned/Master", "will sell"
    r"\s*[;,]?\s*(?:et\.?\s*al\.?|I,?\s+the\s+(?:undersigned|Master)|the\s+undersigned"
    r"|will\s+sell|TO THE\b)",
    re.I,
)
_ESTATE_RE = re.compile(
    r"(?:estate of|in re:?|decedent:?)\s+([A-Z][A-Za-z .,'-]{3,70}?)"
    r"(?:,|\s+deceased|\s+date of death|\s*\()",
    re.I,
)
_SALE_RE = re.compile(r"\b(master'?s sale|notice of sale|will be sold|will sell|public auction|sold to the highest)\b", re.I)
# "will sell on Monday, July 6, 2026 ..." / "will sell on July 6, 2026" — skip the
# optional weekday between "on" and the month-name date, then capture "Month D, YYYY".
_SALEDATE_RE = re.compile(
    r"will\s+sell\b.{0,40}?\b((?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4})", re.I)
_AMOUNT_RE = re.compile(r"\$[\d,]{4,}(?:\.\d{2})?")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")
                  .replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")).strip()


def _classify(notice_type: str) -> tuple[ListingType, str]:
    t = (notice_type or "").lower()
    if "master" in t or "equity" in t or "foreclos" in t:
        return ListingType.LIS_PENDENS, "foreclosure"
    if "probate" in t or "estate" in t:
        return ListingType.PROBATE_NOTICE, "probate"
    if "tax" in t:
        return ListingType.TAX_SALE, "tax"
    return ListingType.UNKNOWN, "other"


def _defendant(body: str, kind: str) -> str | None:
    m = _ESTATE_RE.search(body) if kind == "probate" else _VS_RE.search(body)
    return _clean(m.group(1)) if m else None


class SpartanWeeklyLegals(BaseScraper):
    slug = "counties_sc.spartan_weekly_legals"
    name = "Spartan Weekly legal notices (Spartanburg foreclosure/probate/tax)"
    category = "public_notices"
    expected_min_count = 0
    timeout_s = 240.0

    async def fetch(self) -> Iterable[Listing]:
        rows: list[dict] = []
        seen: set[str] = set()
        async with client(timeout=60.0) as c:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    r = await c.get(_LIST.format(page=page))
                except Exception:
                    log.warning("spartan_weekly.page_fetch_failed", page=page)
                    break
                if r.status_code != 200:
                    break
                page_rows = [m.groupdict() for m in _ARTICLE_RE.finditer(r.text)]
                fresh = 0
                for row in page_rows:
                    key = row["href"].strip()
                    if key in seen:
                        continue
                    seen.add(key)
                    fresh += 1
                    rows.append(row)
                if not page_rows or fresh == 0:   # clamped/empty -> end of notices
                    break

            listings: list[Listing] = []
            for i, row in enumerate(rows):
                enrich = _ENRICH_DETAILS and i < _MAX_DETAIL_FETCH
                li = await self._row_to_listing(row, c, enrich)
                if li:
                    listings.append(li)
        log.info("spartan_weekly.done", notices=len(rows), leads=len(listings))
        return listings

    async def _row_to_listing(self, row: dict, c, enrich: bool) -> Listing | None:
        lt, kind = _classify(row["type"])
        meta = _clean(row["meta"])
        case_m = _CASE_RE.search(meta)
        date_m = _DATE_RE.search(meta)
        address = _clean(row["addr"])
        source_url = _HOST + row["href"]

        body, defendant, sale_date, amount = "", None, None, None
        if enrich:
            try:
                d = await c.get(source_url)
                if d.status_code == 200:
                    body = _clean(d.text)
                    defendant = _defendant(body, kind)
                    if kind == "foreclosure" and _SALE_RE.search(body):
                        lt = ListingType.FORECLOSURE_SALE
                        sm = _SALEDATE_RE.search(body)
                        sale_date = sm.group(1) if sm else None
                        am = _AMOUNT_RE.search(body)
                        amount = am.group(0) if am else None
            except Exception:
                log.debug("spartan_weekly.detail_failed", url=source_url[:120])

        raw: dict = {"public_notice": {
            "source": "spartanweeklyonline.com",
            "notice_type": row["type"].strip(),
            "published": (date_m.group(1) if date_m else None),
            "sale_date": sale_date, "amount_text": amount,
            "address_slug": row["href"].rsplit("/", 1)[-1],
        }}
        if body:
            raw["public_notice"]["text"] = body[:4000]
        if kind == "probate":
            raw["relationship_signal"] = {"kind": "probate", "keyword": "public_notice",
                                          "tagged_at": datetime.utcnow().isoformat() + "Z"}

        return Listing(
            source=self.slug, source_url=source_url,
            listing_type=lt, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Spartanburg",
            defendant=defendant,
            street_address=address or None,
            case_number=(case_m.group(1) if case_m else None),
            description=(f"{row['type'].strip()} — {address}"
                         + (f" — {defendant}" if defendant else "")),
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )

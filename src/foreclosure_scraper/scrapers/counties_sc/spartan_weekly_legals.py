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
import time
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
_DETAIL_BUDGET_S = 150   # hard wall-clock cap on the (throttled) detail-enrich pass

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
# Probate "Notice to Creditors" fields: "Estate: <DECEDENT> Date of Death: <DATE>
# Case Number: <ES#> Personal Representative: <PR NAME> <PR ADDRESS>".
_PROBATE_ESTATE = re.compile(
    r"\bEstate:\s*([A-Z][A-Za-z .,'\-]{3,60}?)\s+(?:Date of Death|Case Number|a/?k/?a|aka)\b", re.I)
_PROBATE_DOD = re.compile(r"Date of Death:\s*([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
# PR name + mailing address. Accepts ANY US state (executors who inherited often
# live out of state — an absentee heir is a STRONGER seller, not one to drop) and
# PO-Box mailing addresses (the old SC|NC|GA + house-number-only pattern dropped
# ~28% of PRs: out-of-state IA/DC/etc. and "Post Office Box N" lines).
_PROBATE_PR = re.compile(
    r"Personal Representative[s]?:?\s*([A-Z][A-Za-z .,'\-]{3,55}?)\s+"
    r"((?:P\.?\s*O\.?\s*Box|Post\s+Office\s+Box|\d{1,6})"
    r"[A-Za-z0-9 .,'#\-]*?,?\s*[A-Z]{2}\.?\s*\d{5})", re.I)
_ES_CASE_RE = re.compile(r"\b(20\d{2}ES\d{6,9})\b")


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

            # 1) Emit a base lead for EVERY notice FIRST (network-free), so all of
            #    them land even if detail enrichment is slow or cut off. The old
            #    single loop detail-fetched sequentially under the per-host throttle
            #    and stalled before reaching the probate notices (which sit later in
            #    the list) — dropping every Spartanburg probate lead.
            listings: list[Listing] = [
                await self._row_to_listing(row, c, enrich=False) for row in rows
            ]

            # 2) Best-effort, TIME-BOXED detail enrichment — PROBATE FIRST (those need
            #    the decedent/PR/address from the body; foreclosure rows already carry
            #    an address from the list row). A slow/failed fetch never drops a lead.
            if _ENRICH_DETAILS:
                order = sorted(
                    range(len(rows)),
                    key=lambda j: 0 if _classify(rows[j]["type"])[1] == "probate" else 1,
                )
                t0 = time.monotonic()
                enriched_n = 0
                for j in order[:_MAX_DETAIL_FETCH]:
                    if time.monotonic() - t0 > _DETAIL_BUDGET_S:
                        break
                    try:
                        full = await self._row_to_listing(rows[j], c, enrich=True)
                    except Exception:
                        full = None
                    if full:
                        listings[j] = full
                        enriched_n += 1
                log.info("spartan_weekly.enriched", enriched=enriched_n, of=len(rows))
        listings = [li for li in listings if li]
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
        probate = None
        es_case = None
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
                    if kind == "probate":
                        em = _PROBATE_ESTATE.search(body)
                        decedent = _clean(em.group(1)) if em else defendant
                        if decedent:
                            # The DECEDENT is the property owner — putting them in
                            # `defendant` lets enrichment_address_backfill resolve the
                            # property by owner-name (the notice has no address).
                            defendant = decedent
                        prm = _PROBATE_PR.search(body)
                        dod = _PROBATE_DOD.search(body)
                        esm = _ES_CASE_RE.search(body)
                        es_case = esm.group(1) if esm else None
                        probate = {
                            "decedent": decedent or None,
                            "date_of_death": (dod.group(1) if dod else None),
                            "personal_representative": (_clean(prm.group(1)) if prm else None),
                            "pr_address": (_clean(prm.group(2)) if prm else None),
                            "es_case_number": es_case,
                        }
                        # No property address in a probate notice — clear the notice
                        # title so the owner-name backfill fires on the decedent.
                        address = None
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
            if probate:
                raw["probate"] = probate

        return Listing(
            source=self.slug, source_url=source_url,
            listing_type=lt, property_kind=PropertyKind.UNKNOWN,
            state="SC", county="Spartanburg",
            defendant=defendant,
            street_address=address or None,
            case_number=(es_case or (case_m.group(1) if case_m else None)),
            description=(f"{row['type'].strip()}"
                         + (f" — {address}" if address else "")
                         + (f" — {defendant}" if defendant else "")),
            first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
            raw=raw,
        )

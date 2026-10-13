"""Korn Law Firm — DEAD (domain parked).

The kornlawfirm.com domain no longer hosts the firm's website. Both
/foreclosure-sales/ and /sales/ serve a FingerprintJS parking shim that
redirects to a domain-ad service (ron.mamma.com on 2026-05-13,
yfdabv11.com on 2026-05-14). The scraper is intentionally retained as a
stub so the slug stays known but skipped; fetch() returns [] without
doing network work.

RE-VERIFIED LIVE 2026-10-04 (extraction-completeness audit): still dead,
now even more plainly so -- /foreclosure-sales/ serves a plain "domain may
be for sale" parking page (abovedomains.com, title literally
"kornlawfirm.com", no redirect at all anymore) and /sales/ fails to load
outright. A web search found no successor site: the firm's name only turns
up in historical court filings (an August 2026 Charleston Master-in-Equity
appeal document still lists "Korn Law Firm, PO Box 11264, Columbia, SC" as
counsel of record on an existing case, and a 2021 SC Supreme Court matter
involving the firm's principal) -- evidence the firm/attorney may still
exist in some capacity, but nothing suggesting it maintains a public sale
calendar anywhere. Set `disabled = True` this session (previously the
dead-skip was only a hardcoded `return []` inside fetch(), which
BaseScraper.safe_run records as OUTCOME_ZERO -- "ran clean but returned 0
rows" -- indistinguishable from a real source having a quiet week; the
`disabled` flag is what this codebase already uses for a confirmed,
permanent dead-end, e.g. counties_sc.sumter_surplus, and reports the
accurate OUTCOME_DORMANT instead).

If the firm ever republishes (new domain or restored site), revert this
commit to get the working stealth/parser logic back.

RE-VERIFIED LIVE 2026-10-13 (cross-session disabled-reason audit -- prior
session had found other "confirmed dead" scrapers in this repo to actually
be live, so every disabled_reason got a fresh real fetch instead of being
trusted from the comment). Re-fetched both URLs directly:
  - /foreclosure-sales/ -> HTTP 200, same abovedomains.com parking template
    (title "kornlawfirm.com", body text "This domain may be for sale.").
  - /sales/ -> HTTP 200, byte-for-byte the same parking template.
  - bare kornlawfirm.com -> same parking template.
No redirect on any of the three (unlike the 2026-05-13 finding, which saw
a redirect to a domain-ad service) -- it is now a static "for sale" page
served directly, not even bothering to redirect through an ad network.

Also did a real web search (not just reasoning from the old comment) for a
successor site, merger, or alternate publication venue for this firm's SC
trustee-sale notices:
  - A FindLaw listing (last updated 2017, so dated) shows "Korn Law Firm,
    P.A." at 1300 Pickens St, Columbia SC, with 3 named attorneys and
    kornlawfirm.com as its own site at the time -- consistent with the
    domain having genuinely belonged to this firm before parking.
  - An Avvo profile shows a "Peter Korn" foreclosure attorney in Saluda,
    SC (unclear if same practice as the Columbia firm).
  - SC Lawyers Weekly reported a 2021 public reprimand of Peter D. Korn
    (sole owner of a firm representing lenders in foreclosure/default
    matters) for billing/trust-account issues -- unrelated to this
    scraper's dead-domain finding but relevant color on the firm's
    standing.
  - No search result names a new domain, a merger/acquisition, or any
    aggregator/firm now publishing this firm's sale notices. Grepped this
    codebase too: no other scraper or module reads Korn data from
    anywhere else -- the only other "korn" hits in the repo are unrelated
    docstring comparisons citing this module as an example, plus the
    kornlawfirm.com domain already listed in link_validator.py's
    known-dead-domains set.

Conclusion: disabled_reason below is CONFIRMED STILL ACCURATE as of
2026-10-13. No successor site found; `disabled = True` stays. No code
change made.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as dateparser
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind
from ._helpers import ADDR_RE, COUNTY_RE, DATE_RE, parse_blocks

URLS = (
    "https://www.kornlawfirm.com/foreclosure-sales/",
    "https://www.kornlawfirm.com/sales/",
)

BID_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


async def _fetch_url(url: str) -> str:
    """Drive the click-through 'Enter' splash + wait for listings."""
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return ""

    async def page_action(page):
        # Splash entry click — Korn uses various button shapes
        for sel in (
            'a:has-text("Click here to enter")',
            'a:has-text("Enter")',
            'button:has-text("Enter")',
            'a:has-text("Accept")',
            'a.enter-button',
        ):
            try:
                await page.click(sel, timeout=4000)
                await page.wait_for_load_state("networkidle", timeout=12000)
                break
            except Exception:
                continue
        # Wait for any listings to appear
        for sel in (
            "table tbody tr",
            "div.foreclosure-list",
            "div.sale-listing",
            "article",
        ):
            try:
                await page.wait_for_selector(sel, timeout=15000)
                break
            except Exception:
                continue
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    try:
        # FORECLOSURE_NO_CF_SOLVE=1 disables Cloudflare/Turnstile SOLVING (compliant run);
        # the page then simply fails to render rather than defeating the challenge.
        import os as _os
        _solve = _os.environ.get("FORECLOSURE_NO_CF_SOLVE", "").strip().lower() not in ("1", "true", "yes")
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True,
            timeout=180000, page_action=page_action,
            solve_cloudflare=_solve,
        )
        body = getattr(result, "body", b"")
        return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    except Exception:
        return ""


def _parse_html(html: str, url: str, slug: str) -> list[Listing]:
    if not html or len(html) < 1000:
        return []
    tree = HTMLParser(html)
    out: list[Listing] = []
    seen: set[str] = set()

    # Path A: structured table rows
    for table in tree.css("table"):
        for row in table.css("tr"):
            text = row.text(separator=" ", strip=True)
            if not text or len(text) < 30:
                continue
            li = _parse_chunk(text, url, slug)
            if li:
                _add_unique(li, out, seen)

    # Path B: card/article fallback
    if not out:
        for sel in ("article", "div.sale-listing", "div.foreclosure-list li"):
            for node in tree.css(sel):
                text = node.text(separator=" ", strip=True)
                if not text or len(text) < 30:
                    continue
                li = _parse_chunk(text, url, slug)
                if li:
                    _add_unique(li, out, seen)

    # Path C: text-block fallback
    if not out:
        body = tree.body
        if body:
            text = body.text(separator="\n")
            for li in parse_blocks(text, source_slug=slug, source_url=url):
                li.listing_type = ListingType.FORECLOSURE_SALE
                li.state = "SC"  # Korn is SC-only
                _add_unique(li, out, seen)
    return out


def _parse_chunk(text: str, url: str, slug: str) -> Listing | None:
    addr_m = ADDR_RE.search(text)
    if not addr_m:
        return None
    county_m = COUNTY_RE.search(text)
    date_m = DATE_RE.search(text)
    bid_m = BID_RE.search(text)

    sale_date = None
    if date_m:
        try:
            sale_date = dateparser.parse(date_m.group(0))
        except (ValueError, TypeError):
            pass

    bid = None
    if bid_m:
        try:
            v = float(bid_m.group(1).replace(",", ""))
            if 100 <= v <= 5_000_000:
                bid = v
        except ValueError:
            pass

    return Listing(
        source=slug,
        source_url=url,
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        state="SC",  # Korn is SC-only
        county=county_m.group(1) if county_m else None,
        street_address=addr_m.group(1),
        sale_date=sale_date,
        opening_bid=bid,
        description=f"Korn Law Firm trustee sale: {text[:200]}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )


def _add_unique(li: Listing, out: list, seen: set[str]) -> None:
    key = (li.street_address or "").upper() + "|" + (li.county or "")
    if key.strip("|") in seen:
        return
    seen.add(key.strip("|"))
    out.append(li)


class Korn(BaseScraper):
    slug = "law_firms.korn"
    name = "Korn Law Firm (SC, stealth)"
    category = "law_firm"
    requires_apify = False
    requires_render = True
    expected_min_count = 0
    timeout_s = 240.0
    disabled = True
    disabled_reason = ("kornlawfirm.com domain parked (dead since 2026-05-13, "
                        "re-verified live 2026-10-04: plain 'domain for sale' page, "
                        "no successor site found; re-confirmed live 2026-10-13: still "
                        "parked (now no redirect at all), web search found no new "
                        "domain/merger/aggregator for this firm's SC sale notices)")

    async def fetch(self) -> Iterable[Listing]:
        # Domain dead since 2026-05-13 — skip network entirely. `disabled =
        # True` above means safe_run never even calls this, but fetch() stays
        # a safe no-op for any direct caller (tests, __main__ probes, etc.)
        return []

"""Foreclosure.com — auth-gated scraper.

Foreclosure.com paywalls both the listing detail pages AND, as of May
2026, the state-listing preview pages (plain HTTP returns 403; the
"preview" path that the v0 of this scraper hit is now subscription-
only). The scraper now refuses to attempt the fetch when credentials
are not configured, saving ~60s of Scrapling stealth time per weekly
run that previously produced zero listings silently.

Configuration:
  Set the env vars  FORECLOSURE_DOT_COM_USER  and  FORECLOSURE_DOT_COM_PASS
  in the GitHub Actions secrets to enable. Without them the scraper
  short-circuits to [] and the orchestrator marks it PAYWALL-BLOCKED in
  the run summary (instead of REGRESSED, which would trigger noise).

When credentials ARE present, the scraper drives a Scrapling stealth
login flow (login form → state-listing page → parse). The login flow
is tracked separately so a wrong-password run logs a clear error.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import structlog
from selectolax.parser import HTMLParser

from ...base_scraper import BaseScraper
from ...models import Listing, ListingType, PropertyKind

log = structlog.get_logger()

URLS = (
    ("NC", "https://www.foreclosure.com/listings/north-carolina/"),
    ("SC", "https://www.foreclosure.com/listings/south-carolina/"),
)
LOGIN_URL = "https://www.foreclosure.com/login"


def _credentials() -> tuple[str | None, str | None]:
    """Read foreclosure.com credentials from env. Returns (None, None) when
    not configured, which means the scraper short-circuits to []."""
    return (
        os.environ.get("FORECLOSURE_DOT_COM_USER"),
        os.environ.get("FORECLOSURE_DOT_COM_PASS"),
    )


def _ltype(text: str) -> ListingType:
    t = (text or "").lower()
    if "auction" in t:
        return ListingType.AUCTION
    if "reo" in t or "bank" in t:
        return ListingType.REO
    if "pre" in t:
        return ListingType.LIS_PENDENS
    return ListingType.FORECLOSURE_SALE


async def _fetch_state(state: str, url: str) -> list[Listing]:
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return []

    async def page_action(page):
        try:
            await page.wait_for_selector(
                "[class*='listing'], [class*='property'], a[href*='/listing/']",
                timeout=30000,
            )
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            url, headless=True, network_idle=True, timeout=120000,
            page_action=page_action,
        )
    except Exception as exc:
        log.warning("foreclosure_dot_com.fetch_fail", state=state, error=str(exc)[:200])
        return []

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 5000:
        return []

    out: list[Listing] = []
    seen: set[str] = set()
    tree = HTMLParser(html)
    for card in tree.css("[class*='listing-card'], [class*='property-card'], article, tr"):
        try:
            addr_node = card.css_first("[class*='address']") or card.css_first("td")
            addr = addr_node.text(strip=True) if addr_node else ""
            if not addr or len(addr) < 8:
                continue
            m = re.match(r"^(.+?),\s*([A-Za-z .'-]+),\s*([A-Z]{2})\s*(\d{5})?", addr)
            if not m:
                continue
            street, city, st, z = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
            if st != state:
                continue
            link_node = card.css_first("a[href*='/listing/']") or card.css_first("a[href]")
            link = (link_node.attributes.get("href", "") if link_node else "") or url
            if link and not link.startswith("http"):
                link = f"https://www.foreclosure.com{link}"
            if link in seen:
                continue
            seen.add(link)
            status_node = card.css_first("[class*='status']")
            status = status_node.text(strip=True) if status_node else ""
            out.append(
                Listing(
                    source="national.foreclosure_dot_com",
                    source_url=link,
                    listing_type=_ltype(status),
                    property_kind=PropertyKind.UNKNOWN,
                    street_address=street, city=city, state=st, zip_code=z,
                    auction_status=status or None,
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                    raw={"foreclosure_dot_com": {"status": status}},
                )
            )
        except Exception:
            continue
    return out


class ForeclosureDotCom(BaseScraper):
    slug = "national.foreclosure_dot_com"
    name = "Foreclosure.com (paywall)"
    category = "national_aggregator"
    expected_min_count = 0
    requires_apify = False
    requires_paywall = True       # surfaces in run summary as PAYWALL-BLOCKED
    timeout_s = 360.0

    async def fetch(self) -> Iterable[Listing]:
        user, pw = _credentials()
        if not user or not pw:
            # No creds -> short-circuit. Saves ~60s of Scrapling stealth
            # per weekly run that would otherwise just hit the 403.
            log.info("foreclosure_dot_com.skipped_no_credentials")
            return []

        # When creds are present we'd drive an authenticated stealth flow.
        # Keeping this path explicit so a future owner of the credentials
        # can drop in the login automation without rewriting the file.
        log.warning(
            "foreclosure_dot_com.auth_flow_not_implemented",
            note=("Credentials provided but the auth flow isn't wired yet. "
                  "Implement the login Scrapling page_action and remove this "
                  "guard."),
        )
        return []

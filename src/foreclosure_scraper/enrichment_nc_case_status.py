"""NC eCourts case-status enrichment via Tyler Odyssey portal.

For each NC foreclosure listing with a case_number, query the public
case-search portal and tag the listing with current case status:
  - "pending" — sale scheduled but not yet held
  - "sold" — sale held, awaiting upset bid period or confirmation
  - "upset_bid" — currently in 10-day upset bid window
  - "confirmed" — sale confirmed, deed delivery pending
  - "dismissed" — case dismissed (settlement, payment, etc.)

Tyler portal blocks direct HTTP — uses Scrapling's StealthyFetcher
(camoufox/Playwright stealth) to render the page and extract status.

Free, covers ALL 100 NC counties via single endpoint.

Tags listing.raw["nc_case_status"] = {
    "status": <one of above>,
    "last_event_date": ISO date,
    "last_event_text": brief description,
    "in_upset_bid_window": bool,
    "upset_bid_deadline": ISO date or None,
    "checked_at": ISO timestamp,
}
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


PORTAL_BASE = "https://portal-nc.tylertech.cloud/Portal"
SEARCH_URL = f"{PORTAL_BASE}/Home/Dashboard/29"


# Case-status text → normalized state machine
STATUS_MAP = [
    (r"\bdismissed\b|\bdismiss\b", "dismissed"),
    (r"\bconfirmed\b|\border confirming sale\b", "confirmed"),
    (r"\bupset bid\b", "upset_bid"),
    (r"\bsold\b|\breport of sale\b", "sold"),
    (r"\bpending\b|\bscheduled\b", "pending"),
]


# Sold-price patterns observed in NC eCourts docket text. Tyler displays
# Order Confirming Sale / Report of Sale entries with the hammer price
# inline. Patterns ordered most-specific first.
SOLD_PRICE_PATTERNS = [
    # "high bid of $123,456.78" / "high bid: $X"
    re.compile(r"high\s+bid(?:\s+of)?\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "sold to ABC LLC for $X" / "sold for $X"
    re.compile(r"sold\s+(?:to\s+[^$\n]{1,80}?\s+)?for\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "purchase price $X" / "purchased for $X"
    re.compile(r"purchas(?:e\s+price|ed\s+for)\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "amount of $X" near "confirm" / "report of sale"
    re.compile(r"(?:confirm[a-z]*|report\s+of\s+sale)[^\n$]{0,80}\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "successful bid $X" / "winning bid $X"
    re.compile(r"(?:successful|winning)\s+bid\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
    # "Sale Price: $X"
    re.compile(r"sale\s+price\s*[:=]?\s*\$\s*([\d,]+(?:\.\d{2})?)", re.I),
]


def _extract_sold_price(text: str) -> Optional[float]:
    """Pull a credible hammer price from rendered case-detail text.
    Returns None when no pattern matches or the value is implausible
    (<$100 or >$10M)."""
    if not text:
        return None
    for pat in SOLD_PRICE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if 100 <= v <= 10_000_000:
            return v
    return None


def _normalize_status(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for pattern, status in STATUS_MAP:
        if re.search(pattern, t):
            return status
    return None


async def _check_case(case_number: str) -> Optional[dict]:
    """Hit the Tyler portal for one case# and parse current status.

    Returns dict with status info, or None on failure.
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    # Tyler search-by-case URL pattern
    search_url = f"{PORTAL_BASE}/Home/WorkspaceMode?p=29"

    async def page_action(page):
        try:
            # Type into the case-number search box. Selectors may need tuning
            # if the Angular template changes — wrap in try/except.
            await page.wait_for_selector("input[name='caseNumber'], input[id*='Case'], #caseNumber", timeout=15000)
            sel = "input[name='caseNumber'], input[id*='Case'], #caseNumber"
            await page.fill(sel, case_number)
            # Submit form
            for btn_sel in ("button[type='submit']", "input[type='submit']", "button.search"):
                try:
                    await page.click(btn_sel, timeout=3000)
                    break
                except Exception:
                    continue
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            search_url,
            headless=True,
            network_idle=True,
            timeout=60000,
            page_action=page_action,
        )
    except Exception as exc:
        log.debug("nc_case_status.fetch_fail", case=case_number, error=str(exc)[:200])
        return None

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html or len(html) < 1000:
        return None

    # Look for case-status text in the rendered page
    # Tyler portals typically show case events in a table with dates + descriptions
    events = re.findall(
        r"(\d{1,2}/\d{1,2}/\d{2,4})\s*[\-:]?\s*([A-Z][\w \-,/.()&'\"]{8,200})",
        html,
    )
    last_event = events[0] if events else None

    # Determine overall status from the page text blob
    status = _normalize_status(html)
    if not status:
        return None

    info: dict = {
        "status": status,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
    if last_event:
        info["last_event_date"] = last_event[0]
        info["last_event_text"] = last_event[1].strip()[:200]

    info["in_upset_bid_window"] = status == "upset_bid" or (
        status == "sold" and last_event and _within_10_days(last_event[0])
    )

    # Hammer price: extract from the docket text when status indicates a
    # sale already happened (sold / confirmed / upset_bid). Routes the
    # listing into the sold-comp pool if a price was found.
    if status in ("sold", "confirmed", "upset_bid"):
        sold_price = _extract_sold_price(html)
        if sold_price is not None:
            info["sold_price"] = sold_price
    return info


def _within_10_days(date_str: str) -> bool:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            d = datetime.strptime(date_str, fmt)
            return (datetime.utcnow() - d).days < 10
        except ValueError:
            continue
    return False


async def enrich_with_nc_case_status(
    listings: list[Listing], concurrency: int = 2, max_check: int = 100
) -> None:
    """For NC foreclosure listings with case_number, look up case status on
    the Tyler portal. Concurrency capped low to be polite to the portal.

    max_check caps the number of cases looked up per run since each takes
    several seconds (Playwright render + form submit).
    """
    targets = [
        li
        for li in listings
        if li.state == "NC"
        and li.case_number
        and li.source not in ("national.courtlistener_bankruptcy",)
    ]

    # Prioritize: listings with sale_date in the past 30 days are MOST useful
    # for upset-bid detection. Future-scheduled ones don't help yet.
    def _priority(li: Listing) -> tuple:
        if li.sale_date:
            d = li.sale_date if hasattr(li.sale_date, "tzinfo") else None
            if d and d.tzinfo:
                d = d.replace(tzinfo=None)
            now = datetime.utcnow()
            if d:
                days_ago = (now - d).days
                # 0-10 days: highest priority (upset bid window)
                if 0 <= days_ago <= 10:
                    return (0, days_ago)
                # 10-30 days: high (recent sales)
                if 10 < days_ago <= 30:
                    return (1, days_ago)
        return (2, 0)

    targets.sort(key=_priority)
    targets = targets[:max_check]

    if not targets:
        log.info("nc_case_status.no_targets")
        return

    log.info("nc_case_status.start", target_count=len(targets))

    sem = asyncio.Semaphore(concurrency)
    counts = {"checked": 0, "tagged": 0, "in_upset_bid": 0,
              "sold_price_extracted": 0, "promoted_to_sold_comp": 0}

    async def one(li: Listing) -> None:
        async with sem:
            info = await _check_case(li.case_number)
            counts["checked"] += 1
            if not info:
                return
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["nc_case_status"] = info
            counts["tagged"] += 1
            if info.get("in_upset_bid_window"):
                counts["in_upset_bid"] += 1

            # Hammer-price promotion: if the case-detail page surfaced a
            # sold price AND the case is in a sale-completed state, tag
            # raw.actual_sold_price + set sale_date so the orchestrator's
            # post-enrichment "promote to sold pool" pass can route this
            # listing into the foreclosure_sold_comps pool.
            sold_price = info.get("sold_price")
            if sold_price and info.get("status") in ("sold", "confirmed", "upset_bid"):
                li.raw["actual_sold_price"] = sold_price
                counts["sold_price_extracted"] += 1
                # Set sale_date from last_event_date so the comp pool
                # has the right anchor (vs whatever sale_date the
                # original lis pendens scraper assigned).
                last_date = info.get("last_event_date")
                if last_date:
                    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
                        try:
                            li.sale_date = datetime.strptime(last_date, fmt)
                            break
                        except ValueError:
                            continue
                # Mark for promotion logging
                li.raw.setdefault("nc_case_status", {})[
                    "promoted_to_sold_comp"
                ] = True
                counts["promoted_to_sold_comp"] += 1

    await asyncio.gather(*(one(li) for li in targets))
    log.info("nc_case_status.done", **counts)

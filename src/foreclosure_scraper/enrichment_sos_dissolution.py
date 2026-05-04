"""NC + SC Secretary of State LLC dissolution cross-reference enrichment.

For listings whose defendant is an LLC/Inc/Corp, check whether the entity
has been administratively dissolved or had its registration revoked. A
dissolved-LLC defendant is a strong distress signal: the property is
orphaned, owner of record can't legally act, foreclosure is more likely
to proceed unopposed.

NC: sosnc.gov blocks direct HTTP. Uses Scrapling stealth.
SC: businessfilings.sc.gov is more accessible.

Concurrency capped low to avoid SOS rate limits. Caches per-name lookups
in-memory across the run.

Free, no auth, Scrapling stealth.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()


_BUSINESS_MARKERS = (
    "llc", "l.l.c.", "inc", "inc.", "corp", "corp.", "corporation",
    "company", "co.", "ltd", "ltd.", "lp", "l.p.", "llp",
)


def _is_business(name: str) -> bool:
    if not name:
        return False
    n = name.lower()
    return any(m in n for m in _BUSINESS_MARKERS)


def _strip_business_suffix(name: str) -> str:
    """Get the core entity name without LLC/Inc suffix for cleaner search."""
    s = name.strip()
    s = re.sub(
        r"\s*,?\s*(L\.?L\.?C\.?|Inc\.?|Corp\.?(?:oration)?|Co\.?(?:mpany)?|"
        r"Ltd\.?|L\.?P\.?|L\.?L\.?P\.?)\.?\s*$",
        "", s, flags=re.I,
    )
    return s.strip(" ,.-")


async def _lookup_nc_sos(name: str, cache: dict) -> Optional[dict]:
    """Look up NC SOS for the given entity name. Returns status dict or None."""
    if name in cache:
        return cache[name]
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError:
        return None

    core = _strip_business_suffix(name)
    if not core or len(core) < 3:
        cache[name] = None
        return None

    search_url = (
        f"https://www.sosnc.gov/online_services/search/by_title/_Business_Registration"
    )

    async def page_action(page):
        try:
            await page.wait_for_selector("input[name*='search'], input[id*='search'], input[type='search']",
                                         timeout=15000)
            sel = "input[name*='search'], input[id*='search'], input[type='search']"
            await page.fill(sel, core)
            for btn in ("button[type='submit']", "input[type='submit']"):
                try:
                    await page.click(btn, timeout=3000)
                    break
                except Exception:
                    continue
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

    try:
        result = await StealthyFetcher.async_fetch(
            search_url, headless=True, network_idle=True, timeout=60000,
            page_action=page_action,
        )
    except Exception:
        cache[name] = None
        return None

    body = getattr(result, "body", b"")
    html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body or "")
    if not html:
        cache[name] = None
        return None

    # Look for status keywords. NC SOS surfaces statuses like:
    # "Current-Active", "Admin. Dissolved", "Dissolved", "Suspended"
    blob = html.lower()
    out: dict = {"checked": True}
    if "admin. dissolved" in blob or "admin dissolved" in blob:
        out["status"] = "admin_dissolved"
    elif "dissolved" in blob:
        out["status"] = "dissolved"
    elif "suspended" in blob:
        out["status"] = "suspended"
    elif "current-active" in blob or "current active" in blob:
        out["status"] = "active"
    else:
        out["status"] = "unknown"
    cache[name] = out
    return out


async def enrich_with_sos_dissolution(listings: list[Listing], max_check: int = 50) -> None:
    """For listings with LLC/Inc defendants, check NC SOS for dissolution status.

    Capped to top max_check unique names per run to bound runtime — each
    Scrapling render takes ~10-30s. Cached in-memory.
    """
    targets = []
    seen_names: set[str] = set()
    for li in listings:
        if not li.defendant or not _is_business(li.defendant):
            continue
        if li.state != "NC":  # NC SOS only for now
            continue
        nm = li.defendant.strip().lower()
        if nm in seen_names:
            continue
        seen_names.add(nm)
        targets.append(li)
        if len(targets) >= max_check:
            break

    if not targets:
        log.info("sos_dissolution.no_targets")
        return

    log.info("sos_dissolution.start", target_count=len(targets))

    sem = asyncio.Semaphore(2)
    cache: dict = {}
    counts = {"checked": 0, "dissolved": 0, "active": 0, "unknown": 0}

    async def one(li: Listing) -> None:
        async with sem:
            info = await _lookup_nc_sos(li.defendant, cache)
            counts["checked"] += 1
            if not info:
                return
            status = info.get("status")
            counts[status if status in counts else "unknown"] = (
                counts.get(status if status in counts else "unknown", 0) + 1
            )
            if status in ("dissolved", "admin_dissolved", "suspended"):
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["sos_status"] = info

    await asyncio.gather(*(one(li) for li in targets))
    log.info("sos_dissolution.done", **counts)

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
import os
import re
import time
from datetime import datetime
from typing import Optional

import structlog

from .models import Listing

log = structlog.get_logger()

# Reliability guards — sosnc.gov sits behind Cloudflare and will challenge every
# request when it decides to; without these the run hung 4.5h grinding retries.
# Hard per-call timeout (kills a render even if the fetcher's own timeout hangs),
# an overall wall-clock budget, and a consecutive-failure breaker that bails the
# whole step the moment SOS starts blocking. All env-tunable; 0 disables a guard.
_SOS_CALL_TIMEOUT_S = float(os.environ.get("SOS_CALL_TIMEOUT_S", "75"))
_SOS_MAX_SECONDS = float(os.environ.get("SOS_MAX_SECONDS", "240"))
_SOS_BREAKER_FAILS = int(os.environ.get("SOS_BREAKER_FAILS", "5"))


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
        # Hard outer timeout: Cloudflare interstitials can hang a stealth render
        # past its own `timeout`, so asyncio.wait_for is the real kill-switch.
        coro = StealthyFetcher.async_fetch(
            search_url, headless=True, network_idle=True, timeout=60000,
            page_action=page_action,
        )
        result = (await asyncio.wait_for(coro, timeout=_SOS_CALL_TIMEOUT_S)
                  if _SOS_CALL_TIMEOUT_S > 0 else await coro)
    except (Exception, asyncio.TimeoutError):
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
    # Circuit-breaker state: bail the whole step once SOS starts blocking, so a
    # Cloudflare wall can't turn a 50-name check into a multi-hour hang.
    state = {"consec_fail": 0, "tripped": False, "deadline": time.monotonic() + _SOS_MAX_SECONDS}

    async def one(li: Listing) -> None:
        if state["tripped"] or time.monotonic() > state["deadline"]:
            return
        async with sem:
            if state["tripped"] or time.monotonic() > state["deadline"]:
                return
            info = await _lookup_nc_sos(li.defendant, cache)
            counts["checked"] += 1
            if not info:
                state["consec_fail"] += 1
                if _SOS_BREAKER_FAILS and state["consec_fail"] >= _SOS_BREAKER_FAILS:
                    state["tripped"] = True
                    log.warning("sos_dissolution.circuit_open",
                                consec_fail=state["consec_fail"], checked=counts["checked"])
                return
            state["consec_fail"] = 0
            status = info.get("status")
            counts[status if status in counts else "unknown"] = (
                counts.get(status if status in counts else "unknown", 0) + 1
            )
            if status in ("dissolved", "admin_dissolved", "suspended"):
                if not isinstance(li.raw, dict):
                    li.raw = {}
                li.raw["sos_status"] = info

    try:
        # Hard overall backstop in case the per-call timeout + breaker still leave
        # work outstanding (e.g. many slow-but-not-failing renders).
        await asyncio.wait_for(asyncio.gather(*(one(li) for li in targets)),
                               timeout=_SOS_MAX_SECONDS + _SOS_CALL_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("sos_dissolution.overall_timeout", **counts)
    log.info("sos_dissolution.done", tripped=state["tripped"], **counts)

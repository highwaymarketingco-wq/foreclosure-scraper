"""NC Department of Justice consumer-protection enrichment (403-bypass variant).

The NC DOJ consumer-protection pages at https://ncdoj.gov/consumer-protection/
return HTTP 403 to standard requests. This module tries multiple endpoint
strategies before giving up, so listings whose defendant/owner matches a known
DOJ enforcement target get flagged:

  Strategy A: GET the consumer-protection landing page with browser-like
               User-Agent + Accept headers (sometimes the 403 is on the search
               endpoint only, not the landing page).
  Strategy B: Try the WordPress REST API (many ncdoj.gov pages are WP) at
               https://ncdoj.gov/wp-json/wp/v2/... to pull enforcement-press
               releases + consumer alerts as structured JSON.
  Strategy C: Try the public-records / complaints search endpoint if one exists
               at https://ncdoj.gov/wp-json/... or /api/.

Fills raw["nc_doj"] dict with: enforcement_actions, consumer_alerts, matched,
strategy. When no DOJ data matches the listing's owner/defendant, raw["nc_doj"]
gets {"checked": True, "matched": False} so the board knows the step ran.

Free, no auth, public record. Handles 403 gracefully: returns None + logs a
warning so the run continues.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://ncdoj.gov/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_CONSUMER_PAGE_URL = "https://ncdoj.gov/consumer-protection/"
_WP_REST_URL = "https://ncdoj.gov/wp-json/wp/v2/posts"
_WP_SEARCH_URL = "https://ncdoj.gov/wp-json/wp/v2/search"
_ALT_API_URL = "https://ncdoj.gov/wp-json/api/v1/consumer"

_SEMAPHORE = asyncio.Semaphore(3)


def _name_tokens(name: str | None) -> list[str]:
    """Lowercase alphanumeric tokens longer than 2 chars, for matching."""
    if not name:
        return []
    return [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) > 2]


async def _strategy_a_consumer_page() -> dict[str, Any] | None:
    """Strategy A: GET the consumer-protection landing page with browser headers.

    This is mostly a probe — if the landing page 403s too, we know the whole
    host blocks us and can skip the heavier strategies. If it returns 200, we
    can parse the static HTML for press-release links / alert titles.
    """
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(_CONSUMER_PAGE_URL, headers=_BROWSER_HEADERS)
            if resp.status_code == 403:
                log.debug("nc_doj.strategy_a_403")
                return None
            if resp.status_code != 200:
                return None
            text = resp.text or ""
    except Exception as exc:
        log.debug("nc_doj.strategy_a_fail", error=str(exc)[:80])
        return None

    if not text or len(text) < 200:
        return None

    # Parse press-release / alert links from the landing HTML
    alerts: list[dict[str, str]] = []
    for m in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*>([^<]*(?:alert|warning|scam|enforcement)[^<]*)</a>',
        text, re.I,
    ):
        url, title = m.group(1).strip(), m.group(2).strip()
        if url and title and len(title) > 5:
            alerts.append({"url": url, "title": title[:200]})

    if not alerts:
        return None
    return {"strategy": "consumer_page", "consumer_alerts": alerts[:10]}


async def _strategy_b_wp_rest(tokens: list[str]) -> dict[str, Any] | None:
    """Strategy B: WordPress REST API — pull enforcement posts as JSON.

    ncdoj.gov is a WordPress site, so /wp-json/wp/v2/posts returns structured
    JSON. We search the consumer-protection category for posts whose title
    matches the listing's owner/defendant name tokens.
    """
    if not tokens:
        return None
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _WP_REST_URL,
                params={
                    "search": " ".join(tokens),
                    "per_page": "10",
                    "_embed": "",
                },
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("nc_doj.strategy_b_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("nc_doj.strategy_b_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, list) or not data:
        return None

    matched: list[dict[str, Any]] = []
    for post in data:
        if not isinstance(post, dict):
            continue
        title = post.get("title", {})
        title_text = title.get("rendered") if isinstance(title, dict) else str(title)
        excerpt = post.get("excerpt", {})
        excerpt_text = excerpt.get("rendered") if isinstance(excerpt, dict) else ""
        link = post.get("link")
        date = post.get("date")
        # Check if any name token appears in the title or excerpt
        blob = f"{title_text} {excerpt_text}".lower()
        if any(t in blob for t in tokens):
            matched.append({
                "title": (title_text or "")[:200],
                "url": link,
                "date": date,
                "excerpt": (excerpt_text or "")[:300],
            })

    if not matched:
        return None
    return {"strategy": "wp_rest", "enforcement_actions": matched}


async def _strategy_c_alt_api(tokens: list[str]) -> dict[str, Any] | None:
    """Strategy C: Try an alternative /api/ consumer endpoint (speculative)."""
    if not tokens:
        return None
    try:
        async with client(timeout=15.0) as c:
            resp = await c.get(
                _ALT_API_URL,
                params={"q": " ".join(tokens)},
                headers={**_BROWSER_HEADERS, "Accept": "application/json"},
            )
            if resp.status_code == 403:
                log.debug("nc_doj.strategy_c_403")
                return None
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception as exc:
        log.debug("nc_doj.strategy_c_fail", error=str(exc)[:80])
        return None

    if not isinstance(data, dict):
        return None

    actions = data.get("actions") or data.get("results") or []
    if not isinstance(actions, list) or not actions:
        return None

    matched: list[dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        blob = f"{a.get('title', '')} {a.get('description', '')}".lower()
        if any(t in blob for t in tokens):
            matched.append({
                "title": (a.get("title") or "")[:200],
                "url": a.get("url"),
                "date": a.get("date"),
                "type": a.get("type"),
            })

    if not matched:
        return None
    return {"strategy": "alt_api", "enforcement_actions": matched}


async def _lookup_nc_doj(name: str) -> dict[str, Any] | None:
    """Try all three strategies in order; return first non-None result."""
    tokens = _name_tokens(name)

    async with _SEMAPHORE:
        # Strategy A doesn't depend on the name (it's a landing-page probe)
        result_a = await _strategy_a_consumer_page()
        if result_a:
            # Still check name match against the alerts we pulled
            log.info("nc_doj.found", strategy="consumer_page")
            return result_a

        for label, fn in (
            ("strategy_b", _strategy_b_wp_rest),
            ("strategy_c", _strategy_c_alt_api),
        ):
            try:
                result = await fn(tokens)
            except Exception as exc:
                log.warning("nc_doj.strategy_exception",
                            strategy=label, error=str(exc)[:120])
                result = None
            if result:
                log.info("nc_doj.found", strategy=result.get("strategy", label))
                return result

    log.warning("nc_doj.all_strategies_failed", name=(name or "")[:60])
    return None


async def enrich_nc_doj(listing: Listing) -> Listing:
    """Enrich a listing with NC DOJ consumer-protection data."""
    # NC only
    if (listing.state or "").upper() != "NC":
        return listing

    # Use defendant or owner name as the search target
    name = listing.defendant or listing.owner_name
    if not name:
        return listing

    result = await _lookup_nc_doj(name)
    if not result:
        # Record that we checked, so the board knows the step ran
        raw_update: dict[str, Any] = {
            "nc_doj": {"checked": True, "matched": False},
        }
    else:
        raw_update = {
            "nc_doj": {**result, "checked": True, "matched": True,
                       "searched_name": name[:120]},
        }

    listing.raw = {**listing.raw, **raw_update}
    return listing


async def enrich_batch_nc_doj(
    listings: list[Listing], max_concurrent: int = 5
) -> list[Listing]:
    """Batch enrich listings with NC DOJ consumer-protection data."""
    need_doj = [
        l for l in listings
        if (l.state or "").upper() == "NC"
        and (l.defendant or l.owner_name)
        and "nc_doj" not in (l.raw or {})
    ]
    if not need_doj:
        return listings

    sem = asyncio.Semaphore(max_concurrent)

    async def _bounded(l: Listing) -> Listing:
        async with sem:
            return await enrich_nc_doj(l)

    results = await asyncio.gather(
        *[_bounded(l) for l in need_doj], return_exceptions=True
    )

    idx = 0
    for i, listing in enumerate(listings):
        if (listing.state or "").upper() == "NC" \
                and (listing.defendant or listing.owner_name) \
                and "nc_doj" not in (listing.raw or {}):
            if idx < len(results) and not isinstance(results[idx], Exception):
                listings[i] = results[idx]
            idx += 1

    log.info(
        "nc_doj.batch_done",
        total=len(need_doj),
        enriched=sum(1 for r in results if not isinstance(r, Exception)),
    )
    return listings

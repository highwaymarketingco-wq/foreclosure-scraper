"""Validate every listing's source_url is reachable. Drops 404s and dead listings."""
from __future__ import annotations

import asyncio

import httpx
import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()


# Status codes that mean "URL exists but anonymous bot can't fetch it" — these
# are NOT dead links, they just need login. We keep these listings.
AUTH_GATED_CODES = {401, 403, 429}

# Status codes that mean "URL is genuinely dead" — drop the listing.
DEAD_CODES = {404, 410, 451}


async def _check_one(c: httpx.AsyncClient, url: str) -> tuple[bool, int | None]:
    """Return (keep, status). Keep=True means listing should survive validation."""
    try:
        # HEAD first (cheap), fall back to GET if site rejects HEAD
        r = await c.head(url, follow_redirects=True, timeout=15.0)
        if r.status_code == 405:
            r = await c.get(url, follow_redirects=True, timeout=20.0)
        status = r.status_code
        if 200 <= status < 400:
            return True, status
        if status in AUTH_GATED_CODES:
            # URL is real, just behind a login (Propwire requires auth).
            # We keep the listing — the data is good.
            return True, status
        if status in DEAD_CODES:
            return False, status
        # 5xx, 400, etc. — could be transient. One retry as GET.
        r = await c.get(url, follow_redirects=True, timeout=20.0)
        if 200 <= r.status_code < 400 or r.status_code in AUTH_GATED_CODES:
            return True, r.status_code
        return False, r.status_code
    except (httpx.HTTPError, httpx.InvalidURL):
        # Connection error, DNS failure, timeout — drop.
        return False, None


async def validate(listings: list[Listing], *, workers: int = 24) -> list[Listing]:
    """Return listings whose source_url is reachable OR auth-gated (kept either way).

    Only drops listings with genuine 404/410/451 or connection-level failures.
    Auth-gated URLs (401/403 from Propwire etc.) are kept because the data is real,
    just locked behind a paywall — the dashboard surfaces the address + facts even
    when the link isn't directly clickable.
    """
    if not listings:
        return []
    sem = asyncio.Semaphore(workers)
    keep: list[Listing] = []
    auth_gated = 0

    async with client(timeout=20.0) as c:

        async def task(listing: Listing) -> None:
            nonlocal auth_gated
            async with sem:
                ok, status = await _check_one(c, listing.source_url)
                if ok:
                    keep.append(listing)
                    if status in AUTH_GATED_CODES:
                        auth_gated += 1
                        # Tag the listing so the dashboard can show "login required"
                        if not isinstance(listing.raw, dict):
                            listing.raw = {}
                        listing.raw["link_auth_gated"] = True
                else:
                    log.debug("link.dead", url=listing.source_url, status=status,
                              source=listing.source)

        await asyncio.gather(*(task(li) for li in listings))

    log.info("link.validate.done", kept=len(keep),
             dropped=len(listings) - len(keep), auth_gated=auth_gated)
    return keep

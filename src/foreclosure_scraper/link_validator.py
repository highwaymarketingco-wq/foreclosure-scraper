"""Validate every listing's source_url is reachable. Drops 404s and dead listings."""
from __future__ import annotations

import asyncio

import httpx
import structlog

from .http_client import client
from .models import Listing

log = structlog.get_logger()


async def _check_one(c: httpx.AsyncClient, url: str) -> bool:
    """Return True if URL responds with a healthy status."""
    try:
        # HEAD first (cheap), fall back to GET if site rejects HEAD
        r = await c.head(url, follow_redirects=True, timeout=15.0)
        if r.status_code == 405 or r.status_code >= 400:
            r = await c.get(url, follow_redirects=True, timeout=20.0)
        return 200 <= r.status_code < 400
    except (httpx.HTTPError, httpx.InvalidURL):
        return False


async def validate(listings: list[Listing], *, workers: int = 24) -> list[Listing]:
    """Return only listings whose source_url is reachable."""
    if not listings:
        return []
    sem = asyncio.Semaphore(workers)
    keep: list[Listing] = []

    async with client(timeout=20.0) as c:

        async def task(listing: Listing) -> None:
            async with sem:
                ok = await _check_one(c, listing.source_url)
                if ok:
                    keep.append(listing)
                else:
                    log.debug("link.dead", url=listing.source_url, source=listing.source)

        await asyncio.gather(*(task(li) for li in listings))

    log.info("link.validate.done", kept=len(keep), dropped=len(listings) - len(keep))
    return keep

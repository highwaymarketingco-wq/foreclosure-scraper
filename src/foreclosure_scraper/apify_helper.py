"""Thin async wrapper around the Apify API.

Used for:
  * sites that need JS rendering (we run apify/rag-web-browser as a generic fetcher)
  * sites with mature pre-built scrapers (Auction.com, Foreclosure.com, Zillow)
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

from .http_client import client

log = structlog.get_logger()

APIFY_BASE = "https://api.apify.com/v2"

# Generic JS-rendering fetcher (returns Markdown of the rendered page).
RAG_WEB_BROWSER_ACTOR = "apify/rag-web-browser"


def _actor_path(actor_id: str) -> str:
    # Apify accepts both `username/name` and `username~name` in URLs
    return actor_id.replace("/", "~")


async def run_actor_sync(
    actor_id: str,
    run_input: dict[str, Any],
    *,
    token: str | None = None,
    timeout_s: int = 300,
) -> list[dict[str, Any]]:
    """Run an actor synchronously and return dataset items.

    Returns [] on any error (these are best-effort lookups).
    """
    token = token or os.environ.get("APIFY_TOKEN", "")
    if not token:
        log.warning("apify.no_token", actor=actor_id)
        return []
    url = f"{APIFY_BASE}/acts/{_actor_path(actor_id)}/run-sync-get-dataset-items"
    try:
        async with client(timeout=timeout_s + 30) as c:
            r = await c.post(
                url,
                params={"token": token, "timeout": timeout_s, "memory": 1024},
                json=run_input,
            )
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("apify.run.error", actor=actor_id, error=str(exc))
        return []


async def fetch_rendered(url: str, *, token: str | None = None) -> str:
    """Use rag-web-browser to fetch a rendered page. Returns Markdown text."""
    items = await run_actor_sync(
        RAG_WEB_BROWSER_ACTOR,
        {"query": url, "maxResults": 1, "outputFormats": ["markdown"]},
        token=token,
        timeout_s=120,
    )
    if not items:
        return ""
    first = items[0]
    return first.get("markdown") or first.get("text") or ""


async def fetch_rendered_many(urls: list[str], *, token: str | None = None, concurrency: int = 4) -> dict[str, str]:
    """Fetch many URLs with bounded concurrency."""
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, str] = {}

    async def one(u: str) -> None:
        async with sem:
            out[u] = await fetch_rendered(u, token=token)

    await asyncio.gather(*(one(u) for u in urls))
    return out

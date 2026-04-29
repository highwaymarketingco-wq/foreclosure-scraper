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

from .budget import actor_cost, ensure_budget
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
    estimated_cost_usd: float | None = None,
) -> list[dict[str, Any]]:
    """Run an actor and return dataset items.

    Strategy:
      1. Try /run-sync-get-dataset-items (fast, single round-trip)
      2. If that 403s (Apify limits sync calls to free credits — overage spend
         is only allowed via the async /runs endpoint), fall back to async:
         POST /acts/<id>/runs, poll /actor-runs/<runId> until terminal,
         then GET /datasets/<defaultDatasetId>/items.

    Returns [] on any error (best-effort lookups). Budget pre-flight check
    denies the call if remaining Apify credit can't cover estimated_cost_usd.
    """
    token = token or os.environ.get("APIFY_TOKEN", "")
    if not token:
        log.warning("apify.no_token", actor=actor_id)
        return []
    cost = estimated_cost_usd if estimated_cost_usd is not None else actor_cost(actor_id)
    if not await ensure_budget(cost, token=token):
        log.warning("apify.skipped_budget", actor=actor_id, cost=cost)
        return []

    sync_url = f"{APIFY_BASE}/acts/{_actor_path(actor_id)}/run-sync-get-dataset-items"
    try:
        async with client(timeout=timeout_s + 30) as c:
            r = await c.post(
                sync_url,
                params={"token": token, "timeout": timeout_s, "memory": 1024},
                json=run_input,
            )
            if r.status_code == 200:
                data = r.json()
                return data if isinstance(data, list) else []
            if r.status_code != 403:
                # Not the overage-403 we expect — log and bail
                r.raise_for_status()
            # 403: sync endpoint denied (likely "free credits exhausted, use async").
            # Fall through to async.
            log.info("apify.sync_403_falling_back_to_async", actor=actor_id)
    except Exception as exc:  # noqa: BLE001
        # Any non-403 error: log and bail (don't retry async — preserves old semantics)
        if "403" not in str(exc):
            log.warning("apify.run.error", actor=actor_id, error=str(exc))
            return []
        log.info("apify.sync_403_falling_back_to_async", actor=actor_id)

    # ----- Async fallback path -----
    return await _run_actor_async(actor_id, run_input, token=token, timeout_s=timeout_s)


async def _run_actor_async(
    actor_id: str,
    run_input: dict[str, Any],
    *,
    token: str,
    timeout_s: int = 300,
) -> list[dict[str, Any]]:
    """Async actor run: start -> poll -> fetch dataset items.

    Used when /run-sync-get-dataset-items returns 403 (Apify gates sync calls
    to free credits only; overage credits require async runs).
    """
    start_url = f"{APIFY_BASE}/acts/{_actor_path(actor_id)}/runs"
    try:
        async with client(timeout=timeout_s + 60) as c:
            r = await c.post(
                start_url,
                params={"token": token, "memory": 1024},
                json=run_input,
            )
            if r.status_code != 201:
                log.warning("apify.async_start_failed", actor=actor_id,
                            status=r.status_code, body=r.text[:300])
                return []
            run = r.json().get("data", {})
            run_id = run.get("id")
            dataset_id = run.get("defaultDatasetId")
            if not run_id:
                log.warning("apify.async_no_run_id", actor=actor_id)
                return []

            # Poll until terminal status
            poll_interval = 5
            elapsed = 0
            terminal = ("SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED")
            status = run.get("status") or "READY"
            while status not in terminal and elapsed < timeout_s:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                rs = await c.get(
                    f"{APIFY_BASE}/actor-runs/{run_id}",
                    params={"token": token},
                )
                if rs.status_code != 200:
                    continue
                rd = rs.json().get("data", {})
                status = rd.get("status") or status
                dataset_id = rd.get("defaultDatasetId") or dataset_id

            if status != "SUCCEEDED":
                log.warning("apify.async_not_succeeded", actor=actor_id,
                            status=status, elapsed=elapsed)
                if not dataset_id:
                    return []
                # Still try to fetch — partial data may be present

            if not dataset_id:
                return []

            # Fetch dataset items (may have many — limit to 5000)
            items_r = await c.get(
                f"{APIFY_BASE}/datasets/{dataset_id}/items",
                params={"token": token, "format": "json", "limit": 5000, "clean": "true"},
            )
            if items_r.status_code != 200:
                log.warning("apify.async_dataset_fetch_failed", actor=actor_id,
                            status=items_r.status_code)
                return []
            data = items_r.json()
            return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        log.warning("apify.async_error", actor=actor_id, error=str(exc)[:300])
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

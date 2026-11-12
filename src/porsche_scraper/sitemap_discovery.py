"""Sitemap-driven listing discovery.

The pagination-based search approach has two big limits:
1. Sites cap result pages (cars.com tops out around 20 pages).
2. Site-internal search ranking buries cheap+rare listings.

Sitemaps fix both: they list every URL the site wants indexed, and many
sites embed year + make + model right in the slug — so we can filter
without even fetching the detail page.

This module:
- walks a sitemap (and any nested sitemap-index files, gzip or plain)
- yields the leaf URLs
- per-site URL→Listing parsers extract whatever we can from the slug
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import re
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Iterable

import httpx

from .http_client import client, fetch_text_stealth

log = logging.getLogger("porsche_scraper.sitemap")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


async def _fetch_bytes(url: str, *, timeout: float = 30.0, use_stealth: bool = False) -> bytes:
    if use_stealth:
        text = await fetch_text_stealth(url, timeout=timeout)
        return text.encode("utf-8")
    async with client(timeout=timeout) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def _fetch_xml(url: str, *, timeout: float = 30.0, use_stealth: bool = False) -> str:
    body = await _fetch_bytes(url, timeout=timeout, use_stealth=use_stealth)
    if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return body.decode("utf-8", errors="replace")


async def walk_sitemap(
    root_url: str,
    *,
    use_stealth: bool = False,
    max_children: int = 100,
    timeout: float = 30.0,
) -> AsyncIterator[str]:
    """Yield every leaf URL reachable from `root_url`.

    Recursively expands sitemap-index files. `max_children` caps total
    sub-sitemaps fetched (defensive — some sites publish hundreds and we
    only need to seed a few thousand URLs).
    """
    queue = [root_url]
    seen_sitemaps: set[str] = set()
    fetched = 0
    while queue and fetched < max_children:
        url = queue.pop(0)
        if url in seen_sitemaps:
            continue
        seen_sitemaps.add(url)
        fetched += 1
        try:
            xml = await _fetch_xml(url, timeout=timeout, use_stealth=use_stealth)
        except Exception as exc:  # noqa: BLE001
            log.info("sitemap fetch failed %s: %s", url, exc)
            continue
        if "<sitemapindex" in xml[:400].lower():
            # Sub-sitemap index — enqueue its children.
            for child in _LOC_RE.findall(xml):
                queue.append(child)
            continue
        for loc in _LOC_RE.findall(xml):
            yield loc


# Generic year+model extraction. Each scraper provides a per-site regex
# that names "year" and optionally "model" groups.
@dataclass(frozen=True)
class SlugParser:
    pattern: re.Pattern
    model_aliases: dict[str, str]  # raw → canonical model

    def parse(self, url: str) -> tuple[int | None, str | None]:
        m = self.pattern.search(url)
        if not m:
            return None, None
        try:
            year = int(m.group("year"))
        except (IndexError, KeyError, ValueError):
            year = None
        try:
            raw_model = m.group("model").lower()
            model = self.model_aliases.get(raw_model, raw_model.title())
        except (IndexError, KeyError):
            model = None
        return year, model


async def fetch_details_concurrently(
    urls: list[str],
    fetcher: Callable,
    *,
    max_concurrency: int = 8,
) -> list:
    """Fetch detail-page data with bounded concurrency.

    `fetcher(url)` is awaited per URL; return value is appended to the
    output list (None-results are dropped).
    """
    sem = asyncio.Semaphore(max_concurrency)

    async def one(u):
        async with sem:
            try:
                return await fetcher(u)
            except Exception as exc:  # noqa: BLE001
                log.info("detail fetch failed %s: %s", u, exc)
                return None

    results = await asyncio.gather(*(one(u) for u in urls))
    return [r for r in results if r is not None]

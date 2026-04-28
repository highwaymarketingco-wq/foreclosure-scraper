"""BaseScraper interface — every source module subclasses this."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Iterable

import structlog

from .models import Listing

log = structlog.get_logger()


class BaseScraper(ABC):
    """A single source of foreclosure listings."""

    #: Stable slug, e.g. "law_firms.brock_scott" — also acts as the source attribution.
    slug: str = ""

    #: Human label for logs / sheet rows.
    name: str = ""

    #: Categorization for the run report.
    category: str = ""

    #: Soft timeout for the full scrape, seconds.
    timeout_s: float = 180.0

    #: If True, scraper is skipped automatically on errors instead of failing the run.
    optional: bool = True

    @abstractmethod
    async def fetch(self) -> Iterable[Listing]:
        """Yield Listing objects. Implementations may be async generators or return lists."""

    async def safe_run(self) -> list[Listing]:
        """Run with timeout + error handling; never raise to the orchestrator."""
        bound = log.bind(scraper=self.slug)
        try:
            bound.info("scraper.start")
            results = await asyncio.wait_for(self._collect(), timeout=self.timeout_s)
            bound.info("scraper.ok", count=len(results))
            return results
        except asyncio.TimeoutError:
            bound.warning("scraper.timeout")
            return []
        except Exception as exc:  # noqa: BLE001
            bound.warning("scraper.error", error=str(exc), exc_type=type(exc).__name__)
            if not self.optional:
                raise
            return []

    async def _collect(self) -> list[Listing]:
        out: list[Listing] = []
        result = self.fetch()
        if hasattr(result, "__aiter__"):
            async for listing in result:  # type: ignore[union-attr]
                out.append(listing)
        else:
            awaited = await result if asyncio.iscoroutine(result) else result
            for listing in awaited:
                out.append(listing)
        return out

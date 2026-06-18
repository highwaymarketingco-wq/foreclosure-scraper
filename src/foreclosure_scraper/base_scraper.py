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

    #: Minimum expected listings per run. If a run returns fewer than this AND
    #: a previous run returned more, treat as a regression (flag in run report).
    #: Set to 0 for sources that legitimately return 0 sometimes (e.g. annual
    #: tax sales, currently-empty firms).
    expected_min_count: int = 0

    #: True if this scraper is known to require Apify (rag-web-browser or paid actor).
    #: Used for skip-when-budget-exhausted and run-report categorization.
    requires_apify: bool = False

    #: Months (1-12) this source is active; None = always. Sources whose data is
    #: published only seasonally (e.g. SC annual delinquent-tax lists post ~Nov)
    #: set this so off-season runs skip cleanly and auto-resume in-window — no
    #: wasted fetches against absent data. Override the "current month" for
    #: testing with env SEASONAL_MONTH_OVERRIDE.
    active_months: tuple[int, ...] | None = None

    def _in_season(self) -> bool:
        if self.active_months is None:
            return True
        import datetime as _dt
        import os as _os
        mo = int(_os.environ.get("SEASONAL_MONTH_OVERRIDE", "0")) or _dt.datetime.utcnow().month
        return mo in self.active_months

    @abstractmethod
    async def fetch(self) -> Iterable[Listing]:
        """Yield Listing objects. Implementations may be async generators or return lists."""

    async def safe_run(self) -> list[Listing]:
        """Run with timeout + error handling; never raise to the orchestrator."""
        bound = log.bind(scraper=self.slug)
        if not self._in_season():
            bound.info("scraper.dormant_off_season", active_months=self.active_months)
            return []
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

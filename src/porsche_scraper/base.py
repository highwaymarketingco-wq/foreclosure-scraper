"""Base scraper contract for a single Porsche-listing source."""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Iterable

from .models import Listing

log = logging.getLogger("porsche_scraper.base")


class BaseScraper(ABC):
    """One Porsche-listing source (cars.com, BringATrailer, etc.)."""

    slug: str = ""
    name: str = ""
    timeout_s: float = 120.0
    optional: bool = True  # If True, error from this source doesn't abort the run.

    @abstractmethod
    async def fetch(self) -> Iterable[Listing]:
        """Yield Listing objects."""

    async def safe_run(self) -> list[Listing]:
        log_ = log.getChild(self.slug)
        try:
            log_.info("scraper.start")
            out = await asyncio.wait_for(self._collect(), timeout=self.timeout_s)
            log_.info("scraper.ok count=%d", len(out))
            return out
        except asyncio.TimeoutError:
            log_.warning("scraper.timeout")
            return []
        except Exception as exc:  # noqa: BLE001
            log_.warning("scraper.error %s: %s", type(exc).__name__, exc)
            if not self.optional:
                raise
            return []

    async def _collect(self) -> list[Listing]:
        result = self.fetch()
        out: list[Listing] = []
        if hasattr(result, "__aiter__"):
            async for item in result:  # type: ignore[union-attr]
                out.append(item)
        else:
            awaited = await result if asyncio.iscoroutine(result) else result
            for item in awaited:
                out.append(item)
        return out

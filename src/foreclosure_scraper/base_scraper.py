"""BaseScraper interface — every source module subclasses this."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Iterable

import httpx
import structlog

from .models import Listing

log = structlog.get_logger()

# Per-run outcome classes so the orchestrator can tell the owner EXACTLY why a
# source produced nothing — a code bug, a block, a timeout, or a legit empty.
OUTCOME_OK = "OK"
OUTCOME_ZERO = "ZERO_RESULT"      # ran clean, genuinely 0 rows
OUTCOME_TIMEOUT = "TIMEOUT"       # exceeded the soft timeout / network timeout
OUTCOME_BLOCKED = "BLOCKED"       # 401/403/406/429 or WAF/connection refused
OUTCOME_ERROR = "ERROR"           # code/parse exception (a real bug)
OUTCOME_DORMANT = "DORMANT"       # intentionally skipped (off-season)


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

    #: Set by every safe_run() so the orchestrator/report can explain a 0-count.
    last_outcome: str = OUTCOME_OK
    last_reason: str = ""

    async def safe_run(self) -> list[Listing]:
        """Run with timeout + error handling; never raise to the orchestrator.

        Records self.last_outcome / self.last_reason so a 0-count is never
        ambiguous — the owner sees code-error vs blocked vs timeout vs legit-empty.
        """
        bound = log.bind(scraper=self.slug)
        self.last_outcome, self.last_reason = OUTCOME_OK, ""
        if not self._in_season():
            self.last_outcome = OUTCOME_DORMANT
            self.last_reason = f"off-season (active months {self.active_months})"
            bound.info("scraper.dormant_off_season", active_months=self.active_months)
            return []
        try:
            bound.info("scraper.start")
            results = await asyncio.wait_for(self._collect(), timeout=self.timeout_s)
            if not results:
                self.last_outcome = OUTCOME_ZERO
                self.last_reason = "ran clean but returned 0 rows"
            bound.info("scraper.ok", count=len(results), outcome=self.last_outcome)
            return results
        except asyncio.TimeoutError:
            self.last_outcome = OUTCOME_TIMEOUT
            self.last_reason = f"exceeded soft timeout {self.timeout_s:.0f}s"
            bound.warning("scraper.timeout")
            return []
        except httpx.TimeoutException as exc:
            self.last_outcome = OUTCOME_TIMEOUT
            self.last_reason = f"network timeout ({type(exc).__name__})"
            bound.warning("scraper.net_timeout", exc_type=type(exc).__name__)
            if not self.optional:
                raise
            return []
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code in (401, 403, 406, 429):
                self.last_outcome = OUTCOME_BLOCKED
                self.last_reason = f"HTTP {code} ({'rate-limited' if code == 429 else 'blocked/forbidden'})"
            elif code and 500 <= code < 600:
                self.last_outcome = OUTCOME_BLOCKED
                self.last_reason = f"HTTP {code} (server error / possible WAF)"
            else:
                self.last_outcome = OUTCOME_ERROR
                self.last_reason = f"HTTP {code}"
            bound.warning("scraper.http_error", code=code, outcome=self.last_outcome)
            if not self.optional:
                raise
            return []
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ProxyError) as exc:
            self.last_outcome = OUTCOME_BLOCKED
            self.last_reason = f"connection refused/dropped ({type(exc).__name__})"
            bound.warning("scraper.conn_error", exc_type=type(exc).__name__)
            if not self.optional:
                raise
            return []
        except Exception as exc:  # noqa: BLE001
            self.last_outcome = OUTCOME_ERROR
            self.last_reason = f"{type(exc).__name__}: {str(exc)[:160]}"
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

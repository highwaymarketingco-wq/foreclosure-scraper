"""Apify cost governor + hard pre-flight budget check.

User mandate: ZERO overages. We are on Apify Starter ($29/mo plan credit).
We split the month between two runs:
  * 1st of month  - foreclosures (target ~$22 credit)
  * 15th of month - multifamily   (target ~$5-7 credit)
Total monthly target: ~$27-29, fits inside the plan with no overage.

Before any Apify actor call, callers MUST `await ensure_budget(estimated_cost)`.
If remaining plan credit < estimated_cost + RESERVE_USD, the call is denied and
the orchestrator simply skips that scraper (it is logged + reported as
APIFY-BUDGET-LOCKED in the run summary). The point is to NEVER tip into a
metered overage charge.
"""
from __future__ import annotations

import os
from typing import Any

import structlog

from .http_client import client

log = structlog.get_logger()

APIFY_BASE = "https://api.apify.com/v2"

# Hard plan caps (we will never spend above these in a single run).
PLAN_MONTHLY_USD = float(os.environ.get("APIFY_PLAN_USD", "29.00"))     # Starter
RESERVE_USD = float(os.environ.get("APIFY_RESERVE_USD", "1.00"))        # safety margin
TARGET_FORECLOSURE_RUN_USD = float(os.environ.get("FORECLOSURE_BUDGET_USD", "22.00"))
TARGET_MULTIFAMILY_RUN_USD = float(os.environ.get("MULTIFAMILY_BUDGET_USD", "6.00"))

# Per-source caps tuned for the comprehensive monthly foreclosure run.
# Cost math (per-result fees on Starter; values rounded up):
#   propwire             1500 x $0.007   = $10.50
#   zillow_bulk          25co x 80       = 2000 x $0.003   = $6.00
#   trulia                750 x $0.002   = $1.50
#   auction_dot_com       400 x $0.001   = $0.40
#   realtor_foreclosures 1000 x FREE
#   hud_homestore        5000 x ~free
#   zillow_enrichment    1000 x $0.001   = $1.00
#   probate_foreclosure   600 x $0.001   = $0.60
#   ----- Total ~$20/run
ITEM_CAPS: dict[str, int] = {
    "propwire": 1500,
    "zillow_bulk_foreclosures": 80,
    "trulia_foreclosures": 750,
    "auction_dot_com": 400,
    "realtor_foreclosures": 1000,
    "hud_homestore": 5000,
    "probate_foreclosure_leads": 600,
    "zillow_enrichment_per_run": 1000,
    "foreclosure_dot_com": 800,
    "hubzu": 300,
    "xome": 300,
    # multifamily run (15th)
    "loopnet_multifamily": 600,
    "crexi_multifamily": 400,
    "zillow_multifamily": 500,
    "realtor_multifamily": 600,
}


def cap(slug_suffix: str, default: int = 500) -> int:
    """Per-run item cap. Override via env CAP_<SUFFIX>."""
    env_key = f"CAP_{slug_suffix.upper()}"
    if env_key in os.environ:
        try:
            return int(os.environ[env_key])
        except ValueError:
            pass
    return ITEM_CAPS.get(slug_suffix, default)


def is_free_tier() -> bool:
    return os.environ.get("APIFY_FREE_TIER_ONLY", "0") == "1"


# ----- live usage check ----------------------------------------------------

# Cached for the lifetime of one process run (we only need the figure once)
_usage_cache: dict[str, Any] | None = None


async def fetch_apify_usage(token: str | None = None) -> dict[str, Any]:
    """Pull current month's Apify spend.

    Returns {"used_usd": float, "limit_usd": float, "remaining_usd": float}
    Returns sentinel {"used_usd": None, ...} when the API can't be reached;
    callers treat that as "do not spend" (fail closed).
    """
    global _usage_cache
    if _usage_cache is not None:
        return _usage_cache
    token = token or os.environ.get("APIFY_TOKEN", "")
    if not token:
        _usage_cache = {"used_usd": None, "limit_usd": PLAN_MONTHLY_USD, "remaining_usd": 0.0}
        return _usage_cache
    try:
        async with client(timeout=15.0) as c:
            r = await c.get(f"{APIFY_BASE}/users/me/limits", params={"token": token})
            r.raise_for_status()
            j = r.json().get("data", {})
            # Apify returns "current.monthlyUsageUsd" + "limits.maxMonthlyUsageUsd"
            current = j.get("current", {}) or {}
            limits = j.get("limits", {}) or {}
            used = float(current.get("monthlyUsageUsd") or 0.0)
            limit = float(limits.get("maxMonthlyUsageUsd") or PLAN_MONTHLY_USD)
            _usage_cache = {
                "used_usd": used,
                "limit_usd": limit,
                "remaining_usd": max(0.0, limit - used),
            }
            return _usage_cache
    except Exception as exc:
        log.warning("apify.budget.fetch_failed", error=str(exc))
        # Fail closed - if we can't read usage, assume zero remaining.
        _usage_cache = {"used_usd": None, "limit_usd": PLAN_MONTHLY_USD, "remaining_usd": 0.0}
        return _usage_cache


async def ensure_budget(estimated_cost_usd: float, *, token: str | None = None) -> bool:
    """Returns True iff we can afford `estimated_cost_usd` without tipping into overage.

    Caller pattern:
        if not await ensure_budget(2.00):
            log.warning("scraper.skipped_budget")
            return []
        ... call Apify ...
    """
    if estimated_cost_usd <= 0:
        return True
    info = await fetch_apify_usage(token=token)
    remaining = info.get("remaining_usd", 0.0) or 0.0
    if remaining < estimated_cost_usd + RESERVE_USD:
        log.warning(
            "apify.budget.locked",
            need=round(estimated_cost_usd + RESERVE_USD, 2),
            remaining=round(remaining, 2),
            used=round(info.get("used_usd") or 0.0, 2),
            limit=round(info.get("limit_usd") or PLAN_MONTHLY_USD, 2),
        )
        return False
    return True


# Per-actor estimated cost (used by ensure_budget calls inside scrapers).
# These are deliberately conservative (rounded up).
ACTOR_COST_USD: dict[str, float] = {
    "epctex/propwire-scraper": 11.0,
    "maxcopell/zillow-foreclosures-scraper": 0.5,    # per county
    "epctex/trulia-scraper": 1.6,
    "epctex/auction-com-scraper": 0.5,
    "tugkan/realtor-scraper": 0.0,
    "tri_angle/zillow-search-scraper": 0.0,
    "epctex/hud-homestore-scraper": 0.0,
    "compass/probate-leads-scraper": 0.6,
    "maxcopell/zillow-detail-scraper": 1.1,
    "apify/rag-web-browser": 0.10,                    # per call
    "epctex/loopnet-scraper": 4.0,
    "natanielsantos/crexi-scraper": 2.0,
}


def actor_cost(actor_id: str) -> float:
    return ACTOR_COST_USD.get(actor_id, 0.5)

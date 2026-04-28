"""Apify cost governor.

Apify's free tier is $5/month in platform credits. We size every actor call so
the total weekly run stays under ~$1.20, leaving comfortable headroom for the
4 weekly runs per month plus ad-hoc enrichment.
"""
from __future__ import annotations

import os

# Per-run caps that keep the monthly cost roughly flat.
# Source: Apify Store pricing pages, Apr 2026.
APIFY_FREE_TIER_MONTHLY = 5.00          # USD
WEEKLY_BUDGET = APIFY_FREE_TIER_MONTHLY / 5.0  # leave a 20% safety buffer


# Caps per source, in raw item counts. Tuned so weekly cost ≈ $1.10-$1.20.
ITEM_CAPS: dict[str, int] = {
    "auction_dot_com": 400,             # $0.001/result × 400 = $0.40
    "foreclosure_dot_com": 400,         # rag-web-browser fallback, ~free
    "hubzu": 200,                       # rag-web-browser fallback, ~free
    "xome": 200,                        # rag-web-browser fallback, ~free
    "zillow_foreclosures": 300,         # $0.0008-$0.0036/result; tier-dependent. ~$0.30
    "zillow_enrichment_per_run": 60,    # only enrich the most promising 60 listings
    "hud_homestore": 5000,              # $0.00001/result, effectively free
    "probate_foreclosure_leads": 250,   # $0.001/result + $0.10 start = $0.35
}


def cap(slug_suffix: str, default: int = 200) -> int:
    """Look up the per-run item cap for a source."""
    # Allow override via env (one-off boosts without code change)
    env_key = f"CAP_{slug_suffix.upper()}"
    if env_key in os.environ:
        try:
            return int(os.environ[env_key])
        except ValueError:
            pass
    return ITEM_CAPS.get(slug_suffix, default)


def is_free_tier() -> bool:
    """User explicitly opts out of paid Apify usage with this env var."""
    return os.environ.get("APIFY_FREE_TIER_ONLY", "1") == "1"

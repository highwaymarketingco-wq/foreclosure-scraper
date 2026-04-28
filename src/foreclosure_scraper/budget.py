"""Apify cost governor.

Apify free tier is $5/month in platform credits. We run ONCE per month and use
the full budget for a comprehensive scan (was $1/week, now ~$4/month).
"""
from __future__ import annotations

import os

APIFY_FREE_TIER_MONTHLY = 5.00          # USD (user is willing to pay above this)
TARGET_PER_RUN = 18.00                  # comprehensive monthly run

# Per-source caps tuned for one comprehensive MONTHLY run.
# Cost math (all per-result fees on FREE tier):
#   propwire             1500 × $0.007  = $10.50  (the big one — has ALL property data)
#   zillow_bulk          25co × 80      = 2000   × $0.003   = $6.00
#   trulia               750  × $0.002  = $1.50
#   auction_dot_com      400  × $0.001  = $0.40
#   realtor_foreclosures 1000 × FREE
#   hud_homestore        5000 × ~free
#   zillow_enrichment    1000 × $0.001  = $1.00
#   probate_foreclosure  600  × $0.001  = $0.60
#   ----- Total          ~$20/month for ~5000 raw listings
ITEM_CAPS: dict[str, int] = {
    "propwire": 1500,                   # ~$10.50 — preforeclosure + auction + REO + tax-lien
    "zillow_bulk_foreclosures": 80,     # per county; 25 counties × 80 = 2000 — ~$6
    "trulia_foreclosures": 750,         # ~$1.50
    "auction_dot_com": 400,             # ~$0.40
    "realtor_foreclosures": 1000,       # FREE
    "hud_homestore": 5000,              # ~free
    "probate_foreclosure_leads": 600,   # ~$0.60
    "zillow_enrichment_per_run": 1000,  # ~$1.00 (per-address detail enrichment)
    "foreclosure_dot_com": 800,         # rag-web-browser (~free)
    "hubzu": 300,
    "xome": 300,
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
    return os.environ.get("APIFY_FREE_TIER_ONLY", "1") == "1"

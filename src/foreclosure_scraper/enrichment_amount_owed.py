"""Cross-source "amount owed" waterfall — a complete, honestly-labeled debt
figure for every foreclosure listing.

Owner ask: when one source has a gap (no judgment / amount owed), fill it
from another source rather than leaving it blank — but never misrepresent
what the number actually is.

The explicit judgment / indebtedness lives only in the full legal Notice
of Sale text (which states "principal amount of indebtedness $X"). The
list/aggregator pages we scrape carry the foreclosure OPENING BID instead,
which lenders set at or near the debt owed. So we fill a single
`amount_owed` field from the best available signal, and ALWAYS record where
it came from + a confidence, so the dashboard can show the provenance:

    raw["amount_owed"] = {
        "value": 187425.0,
        "source": "judgment" | "opening_bid" | "assessed_value",
        "label": "Judgment / indebtedness"      # human-facing
                 | "Opening bid (≈ debt owed)"
                 | "Tax-assessed value (not debt)",
        "confidence": "high" | "medium" | "low",
        "is_actual_debt": True | False,
    }

Waterfall (highest-fidelity first):
  1. judgment_amount  — explicit indebtedness parsed from notice text. HIGH.
  2. opening_bid      — foreclosure auction opening; lender opens at the
                        debt. MEDIUM. is_actual_debt=False (it's a proxy).
  3. assessed_value / tax_value — NOT debt; only used as a last-resort
                        magnitude hint, clearly labeled. LOW.

This never invents a number and never relabels a proxy as the real debt —
it just makes the field complete and transparent.
"""
from __future__ import annotations

import structlog

from .models import Listing, ListingType

log = structlog.get_logger()


def _set(li: Listing, value: float, source: str, label: str,
         confidence: str, is_actual_debt: bool) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["amount_owed"] = {
        "value": round(float(value), 2),
        "source": source,
        "label": label,
        "confidence": confidence,
        "is_actual_debt": is_actual_debt,
    }


def enrich_amount_owed(listings: list[Listing]) -> dict[str, int]:
    """Populate raw.amount_owed from the best available signal. Returns
    per-source counts for the run summary."""
    counts = {"judgment": 0, "opening_bid": 0, "assessed_value": 0, "none": 0}

    for li in listings:
        # Only meaningful for distressed/foreclosure listings — a plain REO
        # or tax sale "amount owed" isn't a thing in the same sense.
        is_foreclosure = li.listing_type in (
            ListingType.FORECLOSURE_SALE,
            ListingType.LIS_PENDENS,
        )

        if li.judgment_amount and li.judgment_amount > 0:
            _set(li, li.judgment_amount, "judgment",
                 "Judgment / indebtedness", "high", True)
            counts["judgment"] += 1
        elif is_foreclosure and li.opening_bid and li.opening_bid > 0:
            _set(li, li.opening_bid, "opening_bid",
                 "Opening bid (≈ debt owed)", "medium", False)
            counts["opening_bid"] += 1
        elif li.assessed_value and li.assessed_value > 0:
            _set(li, li.assessed_value, "assessed_value",
                 "Tax-assessed value (not debt)", "low", False)
            counts["assessed_value"] += 1
        elif li.tax_value and li.tax_value > 0:
            _set(li, li.tax_value, "assessed_value",
                 "Tax value (not debt)", "low", False)
            counts["assessed_value"] += 1
        else:
            counts["none"] += 1

    log.info("amount_owed.done", **counts)
    return counts

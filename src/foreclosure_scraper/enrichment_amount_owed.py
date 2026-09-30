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

from typing import Optional

import structlog

from .models import Listing, ListingType

log = structlog.get_logger()

#: amount_owed sources that represent a DIFFERENT, often more directly relevant debt for the
#: specific lead (a mortgage judgment, or a foreclosure auction's opening bid) and must never
#: be displaced by a delinquent-TAX balance discovered later. Everything else -- missing, or a
#: non-debt proxy (assessed_value / tax_value / any one-off script's estimate) -- is fair game.
_NEVER_OVERWRITE_SOURCES = frozenset({"judgment", "opening_bid"})


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


def _tax_owed_promotion(raw: dict) -> Optional[dict]:
    """The promoted amount_owed dict for `raw`, or None if no promotion applies.

    Pure dict logic (no Listing needed) so it can run both over real Listing objects
    (promote_tax_owed_amount_owed, below) and directly over raw board-row dicts in a
    streaming backfill that never pays Listing.model_validate() for untouched rows --
    see scripts/backfill_tax_owed_amount_owed.py.
    """
    if not isinstance(raw, dict):
        return None
    to = raw.get("tax_owed")
    if not isinstance(to, dict):
        return None
    try:
        balance = float(to.get("balance") or 0)
    except (TypeError, ValueError):
        return None
    if balance <= 0:
        return None
    ao = raw.get("amount_owed")
    ao_src = ao.get("source") if isinstance(ao, dict) else None
    if ao_src in _NEVER_OVERWRITE_SOURCES:
        return None
    # Idempotent: a row already correctly promoted (source == "tax_owed", same value) would
    # produce the identical dict again, so re-running this pass is always safe.
    confidence = "high" if to.get("basis") == "own_record" else "medium"
    return {
        "value": round(balance, 2),
        "source": "tax_owed",
        "label": "Delinquent property tax owed",
        "confidence": confidence,
        "is_actual_debt": True,
    }


def promote_tax_owed_amount_owed(listings: list[Listing]) -> dict[str, int]:
    """Second waterfall pass: promote raw['amount_owed'] once raw['tax_owed'] exists.

    enrich_amount_owed() (above) runs BEFORE enrich_tax_owed() in main.py's pipeline
    (tax_owed depends on the resolver having run first, per that call site's own
    comment), so its waterfall can only ever see judgment_amount / opening_bid /
    assessed_value / tax_value on the Listing itself -- never the authoritative,
    county-stated delinquent-tax balance enrich_tax_owed normalizes into raw['tax_owed']
    a few enrichment steps later. That balance comes from a REAL county record (the
    qPayBill delinquent roll, nc_ptscloud, Pickens's own delinquent-parcels list, SC
    Catalis, etc.) -- it is not a proxy, and treating it as one (or dropping it
    entirely) is exactly the "proxy value confused with / instead of a real debt
    amount" defect this field exists to prevent.

    Measured live on the 2026-09-29 board (219,530 rows): 88,959 rows carried a real
    raw['tax_owed'].balance, and only 628 of them (0.7%) showed it as amount_owed --
    the other 88,331 showed either nothing (35,694) or a mislabeled, is_actual_debt=
    False assessed-value proxy (33,576+) despite the real number sitting one raw key
    over, unused. counties_sc.qpaybill_delinquent_roll alone (31,231 rows, ALL of them
    carrying a real balance) had only 36 rows correctly surfaced.

    Run this AFTER enrich_tax_owed(). Never overwrites a judgment- or opening_bid-
    sourced amount_owed (_NEVER_OVERWRITE_SOURCES) -- a different, and often more
    directly relevant, debt for that specific lead (e.g. a mortgage judgment
    cross-referenced onto a lead that also happens to carry a delinquent tax balance);
    promotes everything else -- missing, or an assessed-value/tax-value/any other
    non-debt proxy -- to the real tax-owed figure. Confidence is 'high' when
    tax_owed's own basis is 'own_record' (the county's own record for THIS parcel)
    and 'medium' when it arrived by 'parcel_cross_ref' (inherited from a different
    lead the resolver pinned to the same parcel).
    """
    counts = {"promoted": 0, "unchanged": 0}
    for li in listings:
        if not isinstance(li.raw, dict):
            counts["unchanged"] += 1
            continue
        new_ao = _tax_owed_promotion(li.raw)
        if new_ao is None:
            counts["unchanged"] += 1
            continue
        li.raw["amount_owed"] = new_ao
        counts["promoted"] += 1

    log.info("amount_owed.tax_owed_promotion.done", **counts)
    return counts

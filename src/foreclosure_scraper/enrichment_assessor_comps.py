"""Assessor-card QUALIFIED sales -> Tier-0 recorded-comp signal.

The county GIS recorded-comps enricher (enrichment_recorded_comps) only covers
the handful of counties whose ArcGIS layer carries a heated-sqft field. For
every other lead the valuation has no Tier-0 recorded signal and falls back to
scraped listing comps / zestimate / tax value.

Many leads already carry the subject parcel's OWN recorded sale history in
raw['assessor_card']['sales'][], pulled live from the qPublic card. A QUALIFIED
arms-length entry there (reason contains 'QUALIF' but not 'NOT QUALIF', price
above the nominal-transfer floor) is a real recorded transaction on THIS parcel.
Divided by the subject's known living sqft it yields a $/sqft the valuation can
use exactly like a recorded comp.

This is a self-comp (the property's own past arms-length sale scaled to today),
NOT a basket of nearby sales, so it is deliberately:
  - confidence MEDIUM (never HIGH) and source-labelled 'assessor_card_qualified_sales'
  - skipped entirely when a real GIS recorded_comps basket already exists
    (never clobber the higher-signal nearby-sales comp)
  - skipped when sqft is a footprint ESTIMATE (no bankable $/sqft from it)

Output matches the shape enrichment_recorded_comps writes and valuation/calc.py
reads: raw['recorded_comps'] dict + the raw['comp_median_ppsf_recorded'] scalar.
Runs BEFORE valuation (and after the GIS recorded-comps pass so it only fills
the gaps that pass left).
"""
from __future__ import annotations

from statistics import median

import structlog

from .models import Listing

log = structlog.get_logger()

_MIN_ARMS_LENGTH = 10000        # exclude $1 / nominal family transfers
_MAX_SALE = 100_000_000         # exclude parse-garbage / aggregate roll-ups
_MIN_SQFT = 200                 # exclude land / outbuildings
_PPSF_FLOOR, _PPSF_CEIL = 20.0, 800.0   # drop garbage $/sqft


def _qualified_prices(card: dict) -> list[float]:
    """All QUALIFIED arms-length sale prices on the subject's assessor card.

    QUALIFIED == reason contains 'QUALIF' but NOT 'NOT QUALIF' (the card carries
    both 'DEED QUALIFIED'/'QUALIFIED SALE' and 'NOT QUALIFIED'); same predicate
    enrichment_gis_derived._qualified_sale_from_card uses.
    """
    sales = card.get("sales")
    if not isinstance(sales, list):
        return []
    out: list[float] = []
    for s in sales:
        if not isinstance(s, dict):
            continue
        reason = (s.get("reason") or "").upper()
        if "QUALIF" not in reason or "NOT QUALIF" in reason:
            continue
        try:
            price = float(s.get("price"))
        except (TypeError, ValueError):
            continue
        if _MIN_ARMS_LENGTH <= price <= _MAX_SALE:
            out.append(price)
    return out


def enrich_assessor_comps(listings: list[Listing]) -> dict:
    """Seed raw['recorded_comps'] from QUALIFIED assessor-card sales when no GIS
    recorded-comps basket exists. Mutates in place. Returns a counts summary.
    """
    counts = {"seeded_ppsf": 0, "qualified_no_sqft": 0, "skipped_has_gis": 0, "candidates": 0}
    if not listings:
        return counts
    for li in listings:
        try:
            raw = li.raw if isinstance(li.raw, dict) else {}
            card = raw.get("assessor_card")
            if not isinstance(card, dict):
                continue
            prices = _qualified_prices(card)
            if not prices:
                continue
            counts["candidates"] += 1
            # Never clobber the higher-signal nearby-sales basket.
            if raw.get("recorded_comps"):
                counts["skipped_has_gis"] += 1
                continue
            # A footprint ESTIMATE is not bankable GLA -> no $/sqft from it.
            sqft = li.living_sqft
            if not sqft or sqft <= _MIN_SQFT or getattr(li, "living_sqft_estimated", False):
                counts["qualified_no_sqft"] += 1
                continue
            ppsf_list = sorted(
                round(p / float(sqft), 2) for p in prices
                if _PPSF_FLOOR <= (p / float(sqft)) <= _PPSF_CEIL
            )
            if not ppsf_list:
                counts["qualified_no_sqft"] += 1
                continue
            med = round(median(ppsf_list), 2)
            raw["recorded_comps"] = {
                "median_ppsf": med,
                "count": len(ppsf_list),
                "p25_ppsf": ppsf_list[0],
                "p75_ppsf": ppsf_list[-1],
                "radius_mi": 0.0,   # self-comp: the subject parcel's own sale(s)
                "confidence": "MEDIUM",   # self-comp is never HIGH
                "source": "assessor_card_qualified_sales",
            }
            raw["comp_median_ppsf_recorded"] = med
            li.raw = raw
            counts["seeded_ppsf"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("assessor_comps.per_listing_failed",
                        source=getattr(li, "source", None), error=str(exc))
    log.info("assessor_comps.done", **counts)
    return counts

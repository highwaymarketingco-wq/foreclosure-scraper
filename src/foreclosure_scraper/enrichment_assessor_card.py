"""Grade-gated ON-DEMAND per-parcel assessor-card enricher.

For high-value leads only (grade A/B, ~dozens per run) fetch the county's
PER-PARCEL assessor card and fill the two fields the bulk CAMA/GIS feed omits in
SC: heated/finished living sqft and recorded SALE PRICE (+ history). This is the
per-subject, low-volume path that sidesteps the bulk-distribution / WAF walls that
block scraping the same data in bulk — a title company researches one chain at a
time, and so do we, only for the leads worth the call.

Wiring: runs AFTER the first calc/grade pass (so a grade exists to gate on) and is
followed by a re-calc/re-grade of the touched leads — a real card sqft clears the
footprint-ESTIMATE flag, which lets ARV grade at HIGH confidence (calc caps to
MEDIUM while living_sqft_estimated is True). Fills only missing fields.

OFF by default; enable with ASSESSOR_CARD_ON=1. Hard-bounded by ASSESSOR_CARD_MAX
(default 150) as a per-run circuit breaker. Adapters live in assessor_cards/.
"""
from __future__ import annotations

import asyncio
import os

import structlog

from .models import Listing

log = structlog.get_logger()

GRADE_GATE = {"A", "B"}


def _adapters() -> dict:
    """(state, county) -> async fetch. Auto-discovered: any module in
    assessor_cards/ that exposes COUNTY=(state, county) + an async fetch(li) is
    registered. Each module is imported defensively so one broken adapter never
    breaks the pipeline (it's just skipped)."""
    import importlib
    import pkgutil

    from . import assessor_cards as pkg

    table: dict = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name in ("base", "__init__"):
            continue
        try:
            mod = importlib.import_module(f".assessor_cards.{m.name}", __package__)
            county = getattr(mod, "COUNTY", None)
            fetch = getattr(mod, "fetch", None)
            if county and callable(fetch):
                table[tuple(county)] = fetch
        except Exception:  # noqa: BLE001
            log.warning("assessor_card.adapter_import_failed", adapter=m.name)
    return table


def _is_bplus(li: Listing) -> bool:
    return (((li.raw or {}).get("grade") or {}).get("overall")) in GRADE_GATE


def _apply(li: Listing, res, stats: dict) -> None:
    if not isinstance(li.raw, dict):
        li.raw = {}
    if res.living_sqft and (li.living_sqft is None or li.living_sqft_estimated):
        li.living_sqft = res.living_sqft
        li.living_sqft_estimated = False   # real card sqft -> unlock HIGH-confidence ARV
        stats["filled_sqft"] += 1
    if res.year_built and not li.year_built:
        li.year_built = res.year_built
    if res.bedrooms and li.bedrooms is None:
        li.bedrooms = res.bedrooms
    if res.bathrooms and li.bathrooms is None:
        li.bathrooms = res.bathrooms

    prov: dict = {"source_url": res.source_url}
    if res.sales:
        prov["sales"] = [s.as_dict() for s in res.sales[:8]]
    sp = res.best_sale_price()
    if sp:
        prov["sale_price"] = sp
        stats["filled_price"] += 1
    if li.market_value is None and res.market_value:
        li.market_value = res.market_value
    li.raw["assessor_card"] = prov


async def _aenrich(listings: list[Listing]) -> dict:
    adapters = _adapters()
    if not adapters:
        return {}
    cap = int(os.environ.get("ASSESSOR_CARD_MAX", "150"))
    targets = [li for li in listings
               if _is_bplus(li) and (li.state, li.county) in adapters][:cap]
    stats = {"targets": len(targets), "matched": 0, "filled_sqft": 0, "filled_price": 0}
    for li in targets:
        try:
            res = await adapters[(li.state, li.county)](li)
        except Exception:  # noqa: BLE001
            log.debug("assessor_card.adapter_failed", county=li.county,
                      url=(li.source_url or "")[:100])
            continue
        if not res or not res.has_fill():
            continue
        stats["matched"] += 1
        _apply(li, res, stats)
    return stats


def enrich_assessor_card(listings: list[Listing]) -> dict:
    """Sync entrypoint for the orchestrator. No-op unless ASSESSOR_CARD_ON is set."""
    if os.environ.get("ASSESSOR_CARD_ON", "").lower() not in ("1", "true", "yes"):
        return {}
    try:
        return asyncio.run(_aenrich(listings))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_aenrich(listings))
        finally:
            loop.close()

"""Distress-ranked ON-DEMAND per-parcel assessor-card enricher.

For the leads worth the call, fetch the county's PER-PARCEL assessor card and fill
the two fields the bulk CAMA/GIS feed omits in SC: heated/finished living sqft and
recorded SALE PRICE (+ history). This is the per-subject, low-volume path that
sidesteps the bulk-distribution / WAF walls that block scraping the same data in
bulk — a title company researches one chain at a time, and so do we.

UNLOCK 3 — widened sqft gate. The original gate was grade A/B ONLY, which on the
real board (mostly unrated/None or C/D leads, the A/B bucket is ~dozens) left the
qPublic counties almost entirely un-enriched: 2,063 props (69.7%) had no
living_sqft, capping ARV confidence. The gate is now:

  * include any lead MISSING true living_sqft (living_sqft is None or an ESTIMATE),
  * that sits in a county with an adapter,
  * that has a usable parcel key (a parcel_id, or SC lat/lng for the resolver),
  * and is NOT vacant land (a card yields no heated sqft for raw land — wasting a
    render slot), then
  * RANK by distress (grade tier, then distress_stack score) and take the top-N.

The cap is the bound. qPublic is a per-parcel browser render (~30s-3min each), so a
run could balloon without one. ASSESSOR_CARD_MAX (default 300) is the hard cap;
ASSESSOR_CARD_GRADES (default "A,B,C,") tunes which grades are eligible — a trailing
empty token (the default) ALSO admits unrated/None-grade BUILT leads, which is most
of the missing-sqft inventory. Set ASSESSOR_CARD_GRADES="A,B" to restore the old
high-grade-only behavior.

Wiring: runs AFTER the first calc/grade pass (so grade + distress_stack exist to
rank on) and is followed by a re-calc/re-grade of the touched leads — a real card
sqft clears the footprint-ESTIMATE flag, which lets ARV grade at HIGH confidence
(calc caps to MEDIUM while living_sqft_estimated is True). Fills only missing
fields.

OFF by default; enable with ASSESSOR_CARD_ON=1 (the merge/daily scripts document
the full invocation, e.g.
``ASSESSOR_CARD_ON=1 python scripts/regenerate_dashboard.py``). Adapters live in
assessor_cards/.
"""
from __future__ import annotations

import asyncio
import os

import structlog

from .models import Listing, PropertyKind

log = structlog.get_logger()

# Grades that historically counted as "high value" (kept for the A/B fast path and
# for back-compat with _is_bplus, which the test-suite gates on).
GRADE_GATE = {"A", "B"}

# Default eligible grades. The trailing empty string ("") is intentional: it admits
# UNRATED / None-grade leads (vacant-land-ish unrated rows are filtered separately),
# which is where most of the missing-sqft built inventory lives on the real board.
_DEFAULT_GRADES = "A,B,C,"

# Per-run hard cap (circuit breaker). qPublic is a per-parcel render, so this is
# what keeps a run from ballooning. Widened gate => a few hundred, not unbounded.
_DEFAULT_MAX = 300

# Render-class counties (Cloudflare-solving browser per parcel, ~30s-3min each).
# ASSESSOR_CARD_SKIP_RENDER=1 skips them for a fast JSON/HTML-only pass.
_RENDER_COUNTIES = {("SC", "Spartanburg"), ("SC", "Oconee"), ("SC", "Pickens"),
                    ("SC", "Union"), ("NC", "Buncombe")}

# Property kinds that have no heated/finished living area — a card render returns no
# sqft for these, so they're excluded to keep the (capped) budget on built homes.
_NO_STRUCTURE_KINDS = {PropertyKind.LAND}

# Rank weight per grade bucket (higher = fetched first within the cap).
_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}


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
        if m.name == "base" or m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f".assessor_cards.{m.name}", __package__)
            fetch = getattr(mod, "fetch", None)
            if not callable(fetch):
                continue
            # a module registers one COUNTY=(state,county) or many COUNTIES=[...]
            keys = getattr(mod, "COUNTIES", None) or ([getattr(mod, "COUNTY")] if getattr(mod, "COUNTY", None) else [])
            for k in keys:
                table[tuple(k)] = fetch
        except Exception:  # noqa: BLE001
            log.warning("assessor_card.adapter_import_failed", adapter=m.name)
    return table


def _is_bplus(li: Listing) -> bool:
    return (((li.raw or {}).get("grade") or {}).get("overall")) in GRADE_GATE


def _eligible_grades() -> set[str]:
    """Parse ASSESSOR_CARD_GRADES into a set of accepted grade strings. A blank
    token (e.g. trailing comma) is kept as "" and means 'also unrated/None-grade'."""
    raw = os.environ.get("ASSESSOR_CARD_GRADES")
    if raw is None:
        raw = _DEFAULT_GRADES
    return {tok.strip().upper() for tok in raw.split(",")}


def _grade_of(li: Listing) -> str | None:
    return ((li.raw or {}).get("grade") or {}).get("overall")


def _distress_score(li: Listing) -> int:
    """Numeric distress signal for ranking (raw.distress_stack.score), 0 if absent."""
    try:
        return int(((li.raw or {}).get("distress_stack") or {}).get("score") or 0)
    except (TypeError, ValueError):
        return 0


def _needs_sqft(li: Listing) -> bool:
    """True when living_sqft is absent OR only a footprint-based ESTIMATE — i.e. a
    real card sqft would actually move ARV confidence off the MEDIUM cap."""
    return (not li.living_sqft) or bool(getattr(li, "living_sqft_estimated", False))


def _has_structure(li: Listing) -> bool:
    """Exclude raw land — a card has no heated/finished living area for it, so
    fetching one only burns a render slot. Conservative: only the explicit LAND
    kind is dropped (UNKNOWN may well be a house with a missing kind)."""
    return li.property_kind not in _NO_STRUCTURE_KINDS


def _has_key(li: Listing) -> bool:
    """A usable lookup key for the adapter: a parcel_id, or (SC only) lat/lng the
    parcel_resolver can turn into a county key. Avoids queueing leads that would
    just no-op at fetch time."""
    if (li.parcel_id or "").strip():
        return True
    return li.state == "SC" and li.latitude is not None and li.longitude is not None


def _grade_ok(li: Listing, grades: set[str]) -> bool:
    """A lead's grade is eligible if it's in the configured set. The blank token
    "" in `grades` means 'also admit UNRATED / None-grade leads' (which carry no
    overall grade because they lack a bankable ARV — yet most missing-sqft BUILT
    homes land here, and a card sqft is exactly what would let them grade)."""
    g = _grade_of(li)
    if g is None:
        return "" in grades
    return g.upper() in grades


def _is_card_eligible(li: Listing, grades: set[str], adapters: dict,
                      skip_render: bool) -> bool:
    if (li.state, li.county) not in adapters:
        return False
    if skip_render and (li.state, li.county) in _RENDER_COUNTIES:
        return False
    if not _grade_ok(li, grades):
        return False
    if not _needs_sqft(li):
        return False
    if not _has_structure(li):
        return False
    return _has_key(li)


def _rank_key(li: Listing) -> tuple:
    """Sort key (descending) — fetch the most worthwhile leads first within the cap:
    A/B grades, then highest distress score, then any grade rank, then has-parcel_id
    (cheaper than a resolver round-trip)."""
    return (
        _GRADE_RANK.get(_grade_of(li) or "", 0),
        _distress_score(li),
        1 if (li.parcel_id or "").strip() else 0,
    )


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
    cap = int(os.environ.get("ASSESSOR_CARD_MAX", str(_DEFAULT_MAX)))
    skip_render = os.environ.get("ASSESSOR_CARD_SKIP_RENDER", "").lower() in ("1", "true", "yes")
    grades = _eligible_grades()
    eligible = [li for li in listings
                if _is_card_eligible(li, grades, adapters, skip_render)]
    # Rank by distress/grade so a tight cap spends its budget on the best leads.
    eligible.sort(key=_rank_key, reverse=True)
    targets = eligible[:cap]
    stats = {"eligible": len(eligible), "cap": cap, "targets": len(targets),
             "key_resolved": 0, "matched": 0, "filled_sqft": 0, "filled_price": 0}
    for li in targets:
        # Most B+ leads lack parcel_id but have lat/lng — resolve the county key
        # via point-in-polygon against SCDOT so the adapter has something to fetch.
        if not li.parcel_id and li.state == "SC":
            try:
                from .parcel_resolver import resolve_sc_parcel_key
                key = await resolve_sc_parcel_key(li)
            except Exception:  # noqa: BLE001
                key = None
            if key:
                li.parcel_id = key
                stats["key_resolved"] += 1
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

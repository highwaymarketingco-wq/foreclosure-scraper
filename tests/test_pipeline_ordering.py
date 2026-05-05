"""Regression tests for pipeline ordering invariants.

These pin properties of the orchestration in main.py that, if violated
by a future refactor, would silently corrupt investor-facing numbers.
"""
from __future__ import annotations

import inspect
from datetime import datetime

from foreclosure_scraper import main as orchestrator
from foreclosure_scraper.enrichment_property_kind import enrich_property_kind
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc


def test_property_kind_reclassification_is_respected_by_valuation():
    """Simulate the orchestrator order: property_kind enrichment, THEN
    valuation. A listing initially tagged UNKNOWN gets reclassified to
    LAND from its description; when calc runs, it must see LAND and
    zero out rehab."""
    li = Listing(
        source="counties_sc.spartanburg_master_in_equity",
        source_url="http://x",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.UNKNOWN,
        street_address="0 Pasture Road",
        description="Vacant land — 2.4 acre buildable lot, no improvements",
        acreage=2.4,
        opening_bid=15_000.0,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={},
    )
    # Step 1: enrichment classifies UNKNOWN → LAND
    enrich_property_kind([li])
    assert li.property_kind == PropertyKind.LAND

    # Step 2: valuation must respect the new tag
    c = vcalc.compute(li)
    assert c.rehab_tier == "land"
    assert c.rehab_expected == 0.0
    assert c.rehab_low == 0.0
    assert c.rehab_high == 0.0


def test_main_orchestrator_runs_property_kind_before_valuation():
    """Static guarantee: read main.run's source and verify the property_kind
    enrichment line precedes the valuation_calc line. If a refactor moves
    valuation up, this catches it."""
    src = inspect.getsource(orchestrator.run)
    pk_idx = src.find("enrich_property_kind")
    calc_idx = src.find("valuation_calc.compute")
    assert pk_idx > 0, "enrich_property_kind no longer called in orchestrator"
    assert calc_idx > 0, "valuation_calc.compute no longer called in orchestrator"
    assert pk_idx < calc_idx, (
        "Pipeline ordering broken: enrich_property_kind must run BEFORE "
        "valuation_calc.compute. Found property_kind at offset "
        f"{pk_idx}, calc at offset {calc_idx}."
    )


def test_no_enrichment_runs_after_valuation_that_changes_property_kind():
    """Static guarantee: between the valuation_calc line and the end of
    main.run, no other enrichment may change property_kind. We approximate
    this by checking no `enrich_*property_kind*` call appears after calc."""
    src = inspect.getsource(orchestrator.run)
    calc_idx = src.find("valuation_calc.compute")
    after = src[calc_idx:]
    assert "property_kind" not in after.replace("li.property_kind", "").replace(
        "raw.property_kind", ""
    ), "Something downstream of valuation modifies property_kind — re-run calc"

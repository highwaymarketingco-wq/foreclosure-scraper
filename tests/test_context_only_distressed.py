"""The catch-all 'distressed' listing type must only score when the record is real evidence.

Audit 2026-09-21: 31 sources emit ListingType.DISTRESSED and every one got a PROPERTY category.
Demolition permits, environmental registries, county-owned inventory and federal contract
records are context about a parcel or a program, not owner distress, and were completing a
stack of two (645 of the 1,646 HOT leads were New Hanover demolition permits).
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.distress_score import _context_only_distressed, _signals_for
from foreclosure_scraper.models import Listing, ListingType


def _lead(source, raw=None, lt=ListingType.DISTRESSED, county="Gaston"):
    return Listing(source=source, source_url="u", listing_type=lt, state="NC", county=county, raw=raw or {})


def _cats(li):
    return {c for _n, c, _w in _signals_for(li)}


@pytest.mark.parametrize("slug", [
    "new_hanover_demolition_permits", "nc_ust_incidents", "sc_ust_registry", "nc_dam_safety",
    "nc_inactive_hazardous", "sc_des_brownfields", "sems", "acres", "hud_section8_contracts",
    "crexi_multifamily", "fema_disasters", "hendersonville_flood_zone_structures",
    "buncombe_hmgp_buyout", "buncombe_county_owned", "laurens_county_owned", "any_new_county_owned",
])
def test_context_only_sources_add_no_property_signal(slug):
    li = _lead(f"counties_generic.{slug}")
    assert _context_only_distressed(li)
    assert "PROPERTY" not in _cats(li)


@pytest.mark.parametrize("slug", [
    "gaston_vacant", "charlotte_open_data", "spartanburg_property_cleanup", "spartanburg_infill_eligible",
    "burke_storm_damage", "pickens_flood_damage", "buncombe_landslide_damage", "asheville_helene",
    "transylvania_damage_assessment", "hud_reac_inspection", "distressed", "mcdowell_probate",
])
def test_real_condition_and_enforcement_sources_still_score(slug):
    li = _lead(f"counties_nc.{slug}")
    assert not _context_only_distressed(li)
    assert "PROPERTY" in _cats(li)


def test_a_demolition_permit_plus_a_real_tax_balance_is_no_longer_stack_two():
    li = _lead("counties_generic.new_hanover_demolition_permits", county="New Hanover",
               raw={"tax_owed": {"balance": 4200}})
    assert _cats(li) == {"FINANCIAL"}                    # the tax balance only; no PROPERTY category


def test_poor_condition_evidence_still_counts_on_a_context_only_source():
    # raw['distressed'] is set only by CAMA condition, code violations and similar per-parcel evidence
    li = _lead("counties_generic.new_hanover_demolition_permits", county="New Hanover",
               raw={"distressed": True})
    assert "PROPERTY" in _cats(li)


def test_only_the_distressed_listing_type_is_affected():
    # a tax lien from a source that happens to share a slug word keeps its FINANCIAL signal
    li = _lead("counties_generic.buncombe_county_owned", lt=ListingType.TAX_LIEN)
    assert "FINANCIAL" in _cats(li)


def test_source_without_a_dotted_prefix_and_missing_source():
    assert _context_only_distressed(_lead("nc_ust_incidents"))
    assert not _context_only_distressed(_lead("gaston_vacant"))

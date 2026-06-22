"""Assessed-value anchor: a comp ARV wildly off the county appraisal gets
flagged + confidence-downgraded (the comp-accuracy cross-check)."""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.valuation import calc


def _comp_listing(living_sqft, ppsf, tax_value):
    # comps + comp_median_ppsf + living_sqft -> comp-grounded HIGH ARV
    return Listing(
        source="national.distressed", source_url="u", listing_type=ListingType.REO,
        state="NC", county="Gaston", living_sqft=living_sqft, tax_value=tax_value,
        raw={"comps": [{"price_per_sqft": ppsf}] * 3, "comp_median_ppsf": ppsf},
    )


def test_comp_arv_far_above_assessment_downgrades():
    # ARV = 200 * 1500 = 300k vs 80k appraisal -> 3.75x -> flagged, HIGH->MEDIUM
    c = calc.compute(_comp_listing(1500, 200, 80000))
    assert c.arv_expected == 300000
    assert c.arv_vs_assessed == 3.75
    assert c.arv_confidence == "MEDIUM"
    assert any("county appraisal" in n for n in c.notes)


def test_comp_arv_in_band_stays_high():
    # ARV 300k vs 250k appraisal -> 1.2x -> within band, stays HIGH
    c = calc.compute(_comp_listing(1500, 200, 250000))
    assert c.arv_confidence == "HIGH"
    assert c.arv_vs_assessed == 1.2
    assert not any("county appraisal" in n for n in c.notes)


def test_comp_arv_far_below_assessment_downgrades():
    # ARV 150k vs 400k appraisal -> 0.38x -> flagged
    c = calc.compute(_comp_listing(1500, 100, 400000))
    assert c.arv_vs_assessed and c.arv_vs_assessed < 0.6
    assert c.arv_confidence == "MEDIUM"


def test_tax_based_arv_not_downgraded_by_anchor():
    # No comps -> ARV = tax*1.25 (MEDIUM). Anchor must not touch it (circular),
    # but the ratio is still recorded for transparency (~1.25).
    li = Listing(source="x", source_url="u", listing_type=ListingType.REO,
                 state="NC", county="Gaston", living_sqft=1500, tax_value=100000, raw={})
    c = calc.compute(li)
    assert c.arv_confidence == "MEDIUM"
    assert c.arv_vs_assessed == 1.25

"""Comp-accuracy deal math: rehab contingency, wholesale MAO, and comp-quality
confidence gating for scraped comps."""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc


def _recorded_arv_listing(**kw):
    raw = {"comp_median_ppsf_recorded": 200.0,
           "recorded_comps": {"median_ppsf": 200.0, "count": 10, "p25_ppsf": 180,
                              "p75_ppsf": 220, "radius_mi": 1, "confidence": "HIGH"},
           "condition_tier": "cosmetic"}
    raw.update(kw.pop("raw", {}))
    return Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", living_sqft=1500,
                   property_kind=PropertyKind.SINGLE_FAMILY, raw=raw, **kw)


def test_rehab_contingency_applied_to_max_bid():
    c = calc.compute(_recorded_arv_listing(opening_bid=50000))
    assert c.arv_expected == 300000
    assert c.rehab_expected is not None
    assert c.rehab_with_contingency == round(c.rehab_expected * 1.125, -2)
    # 70% rule, post-calibration (backtest n=266): the 30% haircut already embeds selling cost,
    # so max_bid = 0.75*ARV - rehab (no separate fee — the old formula double-charged ~7% of ARV).
    assert c.max_bid_70 == round(0.75 * 300000 - c.rehab_with_contingency, -2)


def test_wholesale_mao_and_spread():
    c = calc.compute(_recorded_arv_listing(opening_bid=40000))
    assert c.wholesale_mao == round(c.max_bid_70 - calc.ASSIGNMENT_FEE, -2)
    assert c.wholesale_spread == round(c.max_bid_70 - 40000, -2)


def _scraped(comps, ppsf):
    return Listing(source="x", source_url="u", listing_type=ListingType.REO, state="NC",
                   county="Gaston", living_sqft=1500,
                   raw={"comps": comps, "comp_median_ppsf": ppsf})


def test_scraped_comps_high_when_enough_anchored_tight():
    comps = [{"price_per_sqft": p, "geo_anchored": True} for p in (190, 200, 210)]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "HIGH"


def test_scraped_comps_medium_when_too_few():
    comps = [{"price_per_sqft": 200, "geo_anchored": True}]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("only 1 comp" in n for n in c.notes)


def test_scraped_comps_medium_when_not_geo_anchored():
    comps = [{"price_per_sqft": p, "geo_anchored": False} for p in (190, 200, 210)]
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("county-wide" in n for n in c.notes)


def test_scraped_comps_medium_when_dispersed():
    comps = [{"price_per_sqft": p, "geo_anchored": True} for p in (120, 200, 260)]  # 2.17x spread
    c = calc.compute(_scraped(comps, 200))
    assert c.arv_confidence == "MEDIUM"
    assert any("disagree" in n for n in c.notes)


def test_ppsf_usable_rejects_only_a_known_size_mismatch():
    """2026-10-17 gap-sweep wave 7, valuation-hot-arv-supported: adjusted_ppsf is always usable
    (already size-corrected); the raw price_per_sqft fallback is rejected only when BOTH sides'
    sqft are known and outside PPSF_FALLBACK_SIZE_RATIO (2x) -- a data-completeness gap (sqft
    missing on either side) must pass through unchanged, not be silently dropped for an
    unrelated reason."""
    assert calc._ppsf_usable({"adjusted_ppsf": 150, "sqft": 1000}, 4000)       # already adjusted
    assert not calc._ppsf_usable({"price_per_sqft": 150, "sqft": 1400}, 4590)  # live shape: 3.3x
    assert calc._ppsf_usable({"price_per_sqft": 150, "sqft": 2400}, 4590)      # 1.9x: inside 2x
    assert calc._ppsf_usable({"price_per_sqft": 150}, 4590)                    # comp sqft unknown
    assert calc._ppsf_usable({"price_per_sqft": 150, "sqft": 1400}, None)      # subject sqft unknown


def test_scraped_comps_arv_ignores_a_known_size_mismatched_comp():
    """Same shape as the live case (SC|Laurens|901-11-02-007: a HOT subject priced off comps
    2.2x-3.3x smaller, no adjusted_ppsf). Calls _arv_signals directly -- compute()'s own
    county-calibration layer is a separate, unrelated adjustment this fix doesn't touch."""
    comps = [{"price_per_sqft": 95, "sqft": 900, "geo_anchored": True},
             {"price_per_sqft": 100, "sqft": 1050, "geo_anchored": True},
             {"price_per_sqft": 90, "sqft": 1200, "geo_anchored": True}]
    li = Listing(source="x", source_url="u", listing_type=ListingType.FORECLOSURE_SALE, state="SC",
                 county="Laurens", living_sqft=2800, raw={"comps": comps, "comp_median_ppsf": 60.0})
    expected, low, high, conf, notes = calc._arv_signals(li)
    # all 3 comps are a known size mismatch (2.3x-3.1x), so none fed the median: the scalar
    # comp_median_ppsf fallback is used instead of the (wrong, much higher) per-comp prices.
    assert expected == round(60.0 * 2800, -2)
    assert any("only 0 comp" in n for n in notes)


def test_recorded_comps_unaffected_by_scraped_gate():
    # Tier-0 recorded comps return before Tier-1 scraped gating.
    c = calc.compute(_recorded_arv_listing())
    assert c.arv_confidence == "HIGH"


# ===========================================================================
# geo_imprecise tiers (2026-09-30 fix): `census_geocode` is a REAL, resolved
# street address (Census batch geocoder matched THIS lead's own address and
# returned ITS OWN coordinate) and must not be treated the same as a bare
# centroid fallback that thousands of OTHER leads share. Before this fix, a
# plain `if raw.get("geo_imprecise")` truthiness check lumped every non-empty
# value together, so a census_geocode lead lost its deal verdict and was
# capped at MEDIUM confidence for the same reason a leftover-centroid lead
# was — even though its comps were drawn around its own address, not a
# shared landmark. See valuation/calc.py's `_GEO_REAL_ADDRESS_TAGS` comment
# for the full tier breakdown and the calibration judgment call.
# ===========================================================================

def _tight_anchored_comps():
    return [{"price_per_sqft": p, "geo_anchored": True} for p in (190, 200, 210)]


def test_census_geocode_does_not_trigger_geo_imprecise_comps():
    """A resolved street address (census_geocode) is not a shared centroid:
    it must not pick up geo_imprecise_comps or lose HIGH confidence."""
    li = _scraped(_tight_anchored_comps(), 200)
    li.raw["geo_imprecise"] = "census_geocode"
    c = calc.compute(li)
    assert "geo_imprecise_comps" not in (c.arv_flags or [])
    assert c.arv_confidence == "HIGH"


def test_true_centroid_tags_still_trigger_geo_imprecise_comps():
    """Regression guard: every tag that means 'no real address, a shared
    fallback point' must keep the old behavior — flagged and capped MEDIUM."""
    for tag in ("centroid_snap", "county_centroid", "county_centroid_no_addr",
                "out_of_bbox"):
        li = _scraped(_tight_anchored_comps(), 200)
        li.raw["geo_imprecise"] = tag
        c = calc.compute(li)
        assert "geo_imprecise_comps" in (c.arv_flags or []), tag
        assert c.arv_confidence == "MEDIUM", tag


def test_legacy_dict_shaped_geo_imprecise_still_treated_as_imprecise():
    """Two older gap-fill scripts (fill_final_gaps.py, fill_all_gaps.py) wrote
    raw['geo_imprecise'] as a DICT ({"state": "centroid_snap", ...}) instead of
    the bare string every other writer uses. It must still be treated as
    imprecise (it is never a real-address tag) and, since a dict is
    unhashable, must not crash a set-membership check — the tier check uses a
    tuple + `not in`, not a set, specifically so this cannot raise TypeError."""
    li = _scraped(_tight_anchored_comps(), 200)
    li.raw["geo_imprecise"] = {"state": "centroid_snap", "source": "state_centroid"}
    c = calc.compute(li)
    assert "geo_imprecise_comps" in (c.arv_flags or [])
    assert c.arv_confidence == "MEDIUM"

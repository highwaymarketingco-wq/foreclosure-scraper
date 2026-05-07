"""Pin the foreclosure-sold-comps matcher's like-for-like policy.

User mandate verbatim: 'be sure to only include comparable specs. so
I dont want a trailer compared to a 5 bed house or a house compared
to land.'

These tests pin every rejection path so a future change can't loosen
the matching to the point of mixing trailers with SFR or land with
houses.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.enrichment_foreclosure_sold_comps import (
    FORECLOSURE_SALE_SOURCES,
    LOOKBACK_DAYS,
    MAX_COMPS_PER_LISTING,
    enrich_foreclosure_sold_comps,
    is_sold_pool_candidate,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(*, source="law_firms.brock_scott", county="Spartanburg",
        state="SC", kind=PropertyKind.SINGLE_FAMILY,
        beds=3, baths=2, sqft=1500.0, sale_days_ago: int | None = None,
        opening_bid=50000.0, addr="123 Main St", **kw) -> Listing:
    sd = (datetime.utcnow() - timedelta(days=sale_days_ago)
          if sale_days_ago is not None else None)
    base = dict(
        source=source,
        source_url=f"https://example.com/{addr}",
        listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=kind,
        county=county, state=state,
        bedrooms=beds, bathrooms=baths, living_sqft=sqft,
        street_address=addr, sale_date=sd, opening_bid=opening_bid,
        first_seen=datetime.utcnow(), last_seen=datetime.utcnow(),
        raw={},
    )
    base.update(kw)
    return Listing(**base)


# ---- is_sold_pool_candidate ----

def test_recent_law_firm_sale_is_pool_candidate():
    li = _li(sale_days_ago=10)
    assert is_sold_pool_candidate(li) is True


def test_too_old_sale_not_pool_candidate():
    li = _li(sale_days_ago=LOOKBACK_DAYS + 5)
    assert is_sold_pool_candidate(li) is False


def test_future_sale_not_pool_candidate():
    """A scheduled-for-future sale isn't a 'sold' result yet."""
    li = _li(sale_days_ago=-30)  # 30 days in future
    assert is_sold_pool_candidate(li) is False


def test_no_sale_date_not_pool_candidate():
    li = _li(sale_days_ago=None)
    assert is_sold_pool_candidate(li) is False


def test_non_foreclosure_source_not_pool_candidate():
    """HomeHarvest distressed listings have past sale_dates sometimes
    but they're MLS sold, not foreclosure-auction sold. Different signal."""
    li = _li(source="national.distressed", sale_days_ago=10)
    assert is_sold_pool_candidate(li) is False


def test_pool_sources_include_law_firms_and_mie():
    """Spot-check FORECLOSURE_SALE_SOURCES has the right shape."""
    for s in ("law_firms.brock_scott", "law_firms.hutchens",
              "counties_sc.spartanburg_master_in_equity",
              "national.auction_dot_com"):
        assert s in FORECLOSURE_SALE_SOURCES, f"{s} missing"


# ---- like-for-like matching ----

def test_trailer_does_not_match_sfr():
    """User's exact example: don't compare a trailer to a 5-bed house."""
    subj = _li(kind=PropertyKind.SINGLE_FAMILY, beds=5, sqft=2800,
               addr="500 SFR Ave")
    comp = _li(kind=PropertyKind.MOBILE, beds=2, sqft=900,
               sale_days_ago=10, addr="999 Trailer Park")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


def test_house_does_not_match_land():
    """User's exact example: don't compare a house to land."""
    subj = _li(kind=PropertyKind.SINGLE_FAMILY, beds=3, sqft=1500)
    comp = _li(kind=PropertyKind.LAND, beds=None, sqft=None,
               sale_days_ago=10, addr="999 Vacant Lot")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


def test_sfr_matches_townhouse_same_group():
    """Single-family and townhouse are both improved-detached residential
    and trade in similar foreclosure-comp pools."""
    subj = _li(kind=PropertyKind.SINGLE_FAMILY, beds=3, sqft=1500)
    comp = _li(kind=PropertyKind.TOWNHOUSE, beds=3, sqft=1400,
               sale_days_ago=20, addr="222 Townhome Ln")
    enrich_foreclosure_sold_comps([subj], [comp])
    comps = subj.raw.get("foreclosure_sold_comps") or []
    assert len(comps) == 1
    assert comps[0]["property_kind"] == "townhouse"


def test_mobile_matches_mobile():
    subj = _li(kind=PropertyKind.MOBILE, beds=2, sqft=900)
    comp = _li(kind=PropertyKind.MOBILE, beds=3, sqft=1100,
               sale_days_ago=15, addr="555 Mobile Way")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert len((subj.raw.get("foreclosure_sold_comps") or [])) == 1


def test_condo_isolated_from_sfr():
    """Condos have different price drivers (HOA, building) — keep separate."""
    subj = _li(kind=PropertyKind.CONDO, beds=2, sqft=900)
    comp = _li(kind=PropertyKind.SINGLE_FAMILY, beds=2, sqft=950,
               sale_days_ago=15, addr="111 House Rd")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


def test_multi_family_isolated_from_sfr():
    subj = _li(kind=PropertyKind.MULTI_FAMILY, beds=4, sqft=2400)
    comp = _li(kind=PropertyKind.SINGLE_FAMILY, beds=4, sqft=2400,
               sale_days_ago=15, addr="999 House St")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


# ---- county strict ----

def test_different_county_does_not_match():
    """Foreclosure-comp value is HEAVILY county-dependent; cross-county
    matches dilute the signal."""
    subj = _li(county="Spartanburg", state="SC")
    comp = _li(county="Anderson", state="SC", sale_days_ago=10,
               addr="333 Neighbor County")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


def test_different_state_does_not_match():
    subj = _li(county="Cherokee", state="SC")
    comp = _li(county="Cherokee", state="NC", sale_days_ago=10,
               addr="444 Same Name Different State")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


# ---- bedrooms ----

def test_beds_within_one_passes():
    subj = _li(beds=3)
    comp = _li(beds=4, sale_days_ago=10, addr="111 4-bed")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert len((subj.raw.get("foreclosure_sold_comps") or [])) == 1


def test_beds_more_than_one_apart_fails():
    """User's mandate: don't comp 2-bed to 5-bed even if same kind."""
    subj = _li(beds=2)
    comp = _li(beds=5, sale_days_ago=10, addr="222 5-bed")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


def test_beds_skipped_for_mobile_group():
    """Mobile homes — bed count varies wildly even for similar trades.
    Skip the bed check for the mobile group."""
    subj = _li(kind=PropertyKind.MOBILE, beds=2, sqft=900)
    comp = _li(kind=PropertyKind.MOBILE, beds=4, sqft=1100,
               sale_days_ago=15, addr="555 Mobile Big")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert len((subj.raw.get("foreclosure_sold_comps") or [])) == 1


# ---- sqft ----

def test_sqft_within_40pct_passes():
    subj = _li(sqft=1000)
    comp = _li(sqft=1300, sale_days_ago=10, addr="111 30pct")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert len((subj.raw.get("foreclosure_sold_comps") or [])) == 1


def test_sqft_too_different_fails():
    """A 1000 sqft house is not comparable to a 3000 sqft house."""
    subj = _li(sqft=1000)
    comp = _li(sqft=3000, sale_days_ago=10, addr="111 Mansion")
    enrich_foreclosure_sold_comps([subj], [comp])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


# ---- output shape ----

def test_comp_dict_includes_required_fields():
    """Dashboard popout reads these — must be present."""
    subj = _li(beds=3, sqft=1500)
    comp = _li(beds=3, sqft=1450, sale_days_ago=15, opening_bid=42000.0,
               addr="111 Comp St")
    enrich_foreclosure_sold_comps([subj], [comp])
    c = subj.raw["foreclosure_sold_comps"][0]
    for key in ("sold_price", "sold_date", "address", "county", "state",
                "beds", "baths", "living_sqft", "property_kind",
                "source", "source_url", "case_number", "similarity_score",
                "condition_tier", "primary_photo_url", "photo_count"):
        assert key in c, f"comp dict missing {key}"
    assert c["sold_price"] == 42000.0
    assert c["beds"] == 3


def test_comp_summary_includes_county_and_median():
    subj = _li(beds=3, sqft=1500)
    comps = [
        _li(beds=3, sqft=1450, sale_days_ago=10, opening_bid=40000.0,
            addr=f"100 Comp"),
        _li(beds=3, sqft=1500, sale_days_ago=15, opening_bid=50000.0,
            addr=f"200 Comp"),
        _li(beds=3, sqft=1550, sale_days_ago=20, opening_bid=60000.0,
            addr=f"300 Comp"),
    ]
    enrich_foreclosure_sold_comps([subj], comps)
    s = subj.raw["foreclosure_sold_comp_summary"]
    assert s["n_comps"] == 3
    assert s["county"] == "Spartanburg"
    assert s["property_kind_group"] == "improved_detached"
    assert s["median_sold_price"] == 50000.0


def test_caps_at_max_comps_per_listing():
    subj = _li(beds=3, sqft=1500)
    comps = [
        _li(beds=3, sqft=1500, sale_days_ago=i + 1, opening_bid=40000.0 + i * 1000,
            addr=f"{i} Many Comp")
        for i in range(20)
    ]
    enrich_foreclosure_sold_comps([subj], comps)
    assert len(subj.raw["foreclosure_sold_comps"]) == MAX_COMPS_PER_LISTING


def test_self_match_excluded():
    """A listing in the sold pool shouldn't comp against itself."""
    subj = _li(beds=3, sqft=1500, sale_days_ago=10)
    enrich_foreclosure_sold_comps([subj], [subj])
    assert "foreclosure_sold_comps" not in (subj.raw or {})


# ---- vision-condition fields when photos available ----

def test_condition_tier_passes_through_when_set():
    """Vision data on the comp listing flows into the comp_dict so the
    investor sees what condition the comp was sold in."""
    subj = _li(beds=3, sqft=1500)
    comp = _li(beds=3, sqft=1500, sale_days_ago=10, opening_bid=40000.0,
               addr="111 Vision Comp",
               raw={
                   "condition_tier": "major",
                   "condition_source": "vision-HIGH",
                   "vision": {"confidence": "HIGH",
                              "summary": "rotted siding, missing roof shingles"},
                   "images": {"primary": "https://example.com/photo.jpg",
                              "real": ["https://example.com/photo.jpg"]},
               })
    enrich_foreclosure_sold_comps([subj], [comp])
    c = subj.raw["foreclosure_sold_comps"][0]
    assert c["condition_tier"] == "major"
    assert c["vision_confidence"] == "HIGH"
    assert "rotted siding" in c["vision_summary"]
    assert c["primary_photo_url"] == "https://example.com/photo.jpg"
    assert c["photo_count"] == 1

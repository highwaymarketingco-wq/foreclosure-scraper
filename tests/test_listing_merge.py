"""Pin Listing.merge() behavior (M1 fix).

Pre-fix bugs:
  - 0/0.0 in monetary fields blocked real values from filling
  - first_seen kept self's value instead of min(both)
  - raw merge was shallow — nested subkeys clobbered
  - No multi-source attribution recorded

These tests pin each fix so regressions can't sneak in.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.models import Listing, ListingType, _deep_merge_dict


def _li(**kw) -> Listing:
    base = dict(
        source="test_a",
        source_url="https://a.example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- monetary-field falsy treatment ----

def test_zero_opening_bid_does_not_block_real_value():
    """Pre-M1, a scraper writing opening_bid=0.0 blocked the real
    bid from filling on merge. Now 0 is treated as falsy."""
    a = _li(opening_bid=0.0, street_address="123 Main St")
    b = _li(opening_bid=85_000.0, street_address="123 Main St")
    merged = a.merge(b)
    assert merged.opening_bid == 85_000.0


def test_zero_tax_value_does_not_block_real_value():
    a = _li(tax_value=0.0)
    b = _li(tax_value=125_000.0)
    merged = a.merge(b)
    assert merged.tax_value == 125_000.0


def test_real_opening_bid_kept_over_zero():
    """The other direction: don't OVERWRITE a real value with 0."""
    a = _li(opening_bid=85_000.0)
    b = _li(opening_bid=0.0)
    merged = a.merge(b)
    assert merged.opening_bid == 85_000.0


def test_non_money_zero_kept():
    """Non-monetary fields where 0 is a valid sentinel (e.g. bedrooms=0
    for studios) should NOT be treated as falsy."""
    a = _li(bedrooms=0)
    b = _li(bedrooms=3)
    merged = a.merge(b)
    # 0 bedrooms is a valid value for studio — keep self (current)
    assert merged.bedrooms == 0


# ---- first_seen / last_seen ----

def test_first_seen_uses_min():
    """Earliest sighting preserved across merges."""
    earlier = datetime(2026, 1, 1)
    later = datetime(2026, 5, 1)
    a = _li(first_seen=later)
    b = _li(first_seen=earlier)
    merged = a.merge(b)
    assert merged.first_seen == earlier


def test_last_seen_uses_max():
    """Most recent sighting preserved."""
    earlier = datetime(2026, 1, 1)
    later = datetime(2026, 5, 1)
    a = _li(last_seen=earlier)
    b = _li(last_seen=later)
    merged = a.merge(b)
    assert merged.last_seen == later


# ---- raw deep-merge ----

def test_deep_merge_preserves_nested_subkeys():
    """Pre-fix shallow merge wiped raw['gis'] entirely when both sides
    had it. Now nested dicts merge."""
    a_raw = {"gis": {"roof_age": 15, "stories": 2}}
    b_raw = {"gis": {"year_built": 1985}}
    a = _li(raw=a_raw)
    b = _li(raw=b_raw)
    merged = a.merge(b)
    assert merged.raw["gis"]["roof_age"] == 15
    assert merged.raw["gis"]["stories"] == 2
    assert merged.raw["gis"]["year_built"] == 1985


def test_deep_merge_b_wins_on_leaf_collision():
    """When both sides set the SAME nested leaf, b wins (it's the
    newer scrape)."""
    a = _li(raw={"gis": {"stories": 2}})
    b = _li(raw={"gis": {"stories": 3}})
    merged = a.merge(b)
    assert merged.raw["gis"]["stories"] == 3


def test_deep_merge_handles_disjoint_top_level():
    a = _li(raw={"gis": {"x": 1}})
    b = _li(raw={"zillow": {"y": 2}})
    merged = a.merge(b)
    assert merged.raw["gis"] == {"x": 1}
    assert merged.raw["zillow"] == {"y": 2}


# ---- multi-source attribution ----

def test_merge_records_secondary_source_slug():
    """When two listings from different sources merge, the secondary
    source goes into raw['also_seen_in']."""
    a = _li(source="law_firms.brock_scott", source_url="https://brockandscott.com/1")
    b = _li(source="counties_nc.nc_ecourts_lis_pendens",
            source_url="https://ecourts.nc.gov/2")
    merged = a.merge(b)
    assert merged.source == "law_firms.brock_scott"
    # also_seen_in keeps BOTH the secondary source slug AND its link (so an
    # investor can open the other portal too) — list of {source, url} dicts.
    also_seen = merged.raw.get("also_seen_in", [])
    assert any(e["source"] == "counties_nc.nc_ecourts_lis_pendens" for e in also_seen)
    assert any(e["url"] == "https://ecourts.nc.gov/2" for e in also_seen)


def test_merge_preserves_already_seen_in():
    """Three-way merge: A merged with B (a+b), then merged with C
    should retain attribution + link for all three sources."""
    a = _li(source="src.a", source_url="https://a.example/1")
    b = _li(source="src.b", source_url="https://b.example/2")
    c = _li(source="src.c", source_url="https://c.example/3")
    ab = a.merge(b)
    abc = ab.merge(c)
    also_seen = abc.raw.get("also_seen_in", [])
    seen_srcs = {e["source"] for e in also_seen}
    seen_urls = {e["url"] for e in also_seen}
    assert "src.b" in seen_srcs and "https://b.example/2" in seen_urls
    assert "src.c" in seen_srcs and "https://c.example/3" in seen_urls


def test_merge_does_not_duplicate_source_in_also_seen():
    """Merging the same scraper twice (e.g. two separate scrape runs
    of the same source) doesn't pile up duplicate also_seen entries."""
    a = _li(source="src.a")
    b = _li(source="src.a")
    merged = a.merge(b)
    also_seen = merged.raw.get("also_seen_in", [])
    # same slug as the primary source -> never added to also_seen_in
    assert sum(1 for e in also_seen if e["source"] == "src.a") == 0


# ---- _deep_merge_dict directly ----

def test_deep_merge_dict_basic():
    a = {"x": 1, "y": {"a": 1}}
    b = {"y": {"b": 2}, "z": 3}
    out = _deep_merge_dict(a, b)
    assert out == {"x": 1, "y": {"a": 1, "b": 2}, "z": 3}


def test_deep_merge_dict_none_doesnt_overwrite():
    a = {"x": 5}
    b = {"x": None}
    out = _deep_merge_dict(a, b)
    assert out == {"x": 5}


def test_deep_merge_dict_handles_non_dict_b():
    out = _deep_merge_dict({"x": 1}, "not a dict")  # noqa
    assert out == {"x": 1}

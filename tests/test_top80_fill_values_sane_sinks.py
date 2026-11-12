"""2026-10-18: top80-fill-values-sane (37 violations) root cause + fix.

gis_fill.py's own fill (and enrichment_gis_attrs.apply_gis_attrs's sibling fill a few lines
above it) already bound market_value/assessed_value via gis_fill.plausible_value() (or an
inline 1000<=mv<=1e9 / 100<=av<=1e9 equivalent) before writing them. Three OTHER call sites
that also copy a county value onto a Listing had no bound at all:

  1. parcel_cache_join.apply_hit() -- market_value/tax_value from the local parcel-cache
     SQLite (data/parcel_cache), which stores whatever a county GIS layer's raw field held
     with no plausibility check of its own.
  2. enrichment_gis_attrs.enrich_gis_attrs()'s OWN parcel-cache-join block (a DIFFERENT call
     site than apply_gis_attrs, ~100 lines below it in the same file) -- same cache, same gap.
  3. enrichment_owner_mailing.py's county-appraisal-value fill -- tax_value/market_value/
     assessed_value(non-SC) from res["_value"], which for the live-GIS-regex lane was already
     bounded by _num_value() (1000..50_000_000) but for the SC bulk-assessor-roll lane
     (_from_bulk_roll's rec.get("market_value")) carried no bound at all.

Each test below confirms: (a) an implausible value (outside gis_fill.plausible_value()'s
100..5e8) is now dropped instead of written, and (b) an ordinary plausible value still fills
normally -- fill-only behavior is unchanged. test_owner_mailing_value_sink_* additionally
confirms a legitimate LOW SC value is still correctly excluded from assessed_value by the
pre-existing, unrelated SC-ratio carve-out (not by the new bound), and that a low but
plausible NC value is NOT rejected by the new bound.
"""
from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from foreclosure_scraper import parcel_cache as pc
from foreclosure_scraper import enrichment_gis_attrs as G
from foreclosure_scraper import enrichment_owner_mailing as M
from foreclosure_scraper.gis_fill import plausible_value
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.parcel_cache_join import apply_hit, join_listings


def L(pid="1234567890", county="Gaston", state="NC", **kw):
    return Listing(source="t", source_url="https://example.invalid/x", county=county, state=state,
                   parcel_id=pid, street_address=kw.pop("street", "10 FAKE ST"), **kw)


# ---------------------------------------------------------------- site 1: parcel_cache_join.apply_hit


def test_apply_hit_drops_implausible_market_and_tax_value():
    li = L()
    c = Counter()
    # 7e9 is far above plausible_value's 5e8 ceiling -- a corrupted/garbage cache cell.
    apply_hit(li, {"market_value": 7e9, "tax_value": 3.0}, c)
    assert li.market_value is None and li.tax_value is None
    assert c["dropped market value: implausible"] == 1
    assert c["dropped tax value: implausible"] == 1


def test_apply_hit_still_fills_a_plausible_value():
    li = L()
    c = Counter()
    apply_hit(li, {"market_value": 185_000.0, "tax_value": 150_000.0}, c)
    assert li.market_value == 185_000.0 and li.tax_value == 150_000.0
    assert c["filled market value"] == 1 and c["filled tax value"] == 1


def test_join_listings_end_to_end_drops_implausible_cache_value(monkeypatch):
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"market_value": 1.0})
    li = L()
    join_listings([li])
    assert li.market_value is None  # 1.0 is below plausible_value's 100 floor


# ---------------------------------------------------------------- site 2: enrichment_gis_attrs's OWN
# parcel-cache block (distinct from apply_gis_attrs, which was already bounded)


def test_enrich_gis_attrs_pcache_site_drops_implausible_market_value(monkeypatch):
    # street_address + cache_is_stale forced False -> the pc-cache block returns right after
    # its own fill, before the live-GIS-query path (base/_resolve_layer/httpx) is ever reached.
    # FORECLOSURE_CACHE_JOIN=0 turns off the OTHER (already-separately-tested) call site this
    # same function also runs first (parcel_cache_join.join_listings, site 1), isolating site 2.
    monkeypatch.setenv("FORECLOSURE_CACHE_JOIN", "0")
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"market_value": 9e9})
    monkeypatch.setattr(pc, "cache_is_stale", lambda *a, **k: False)
    li = L()
    stats = asyncio.run(G.enrich_gis_attrs([li]))
    assert li.market_value is None
    assert stats["filled_market"] == 0


def test_enrich_gis_attrs_pcache_site_fills_a_plausible_market_value(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_CACHE_JOIN", "0")
    monkeypatch.setattr(pc, "lookup", lambda c, p, s=None: {"market_value": 210_000.0})
    monkeypatch.setattr(pc, "cache_is_stale", lambda *a, **k: False)
    li = L()
    stats = asyncio.run(G.enrich_gis_attrs([li]))
    assert li.market_value == 210_000.0
    assert stats["filled_market"] == 1


# ---------------------------------------------------------------- site 3: enrichment_owner_mailing's
# county-appraisal-value sink (tax_value / market_value / assessed_value-for-non-SC)


def _run_resolve(li, resolved, monkeypatch):
    async def _fake_resolve_one(http, l):
        return dict(resolved)

    # is_reachable gates `targets` on SCDOT/COUNTY_GIS config this test has no business
    # depending on -- force every listing in, so only the value-sink logic under test decides
    # the outcome.
    monkeypatch.setattr(M, "is_reachable", lambda l: True)
    monkeypatch.setattr(M, "_resolve_one", _fake_resolve_one)
    return asyncio.run(M.enrich_owner_mailing([li]))


def test_owner_mailing_value_sink_drops_implausible_value(monkeypatch):
    li = L(state="NC", county="Gaston")
    res = {"owner": "DOE JANE", "absentee": False, "out_of_state": False, "_value": 6e9}
    _run_resolve(li, res, monkeypatch)
    assert li.tax_value is None and li.market_value is None and li.assessed_value is None


def test_owner_mailing_value_sink_fills_a_plausible_value_for_nc(monkeypatch):
    li = L(state="NC", county="Gaston")
    res = {"owner": "DOE JANE", "absentee": False, "out_of_state": False, "_value": 150_000.0}
    _run_resolve(li, res, monkeypatch)
    assert li.tax_value == 150_000.0 and li.market_value == 150_000.0
    assert li.assessed_value == 150_000.0  # non-SC: all three share the one total


def test_owner_mailing_value_sink_still_excludes_sc_assessed_for_a_low_but_plausible_value(monkeypatch):
    """The SC-ratio carve-out (pre-existing, unrelated to this fix) must still keep a
    perfectly plausible appraisal total OUT of assessed_value for SC -- only market_value/
    tax_value get it. 4,500 is well inside plausible_value's 100..5e8 bound, confirming the
    exclusion is the state check, not the new bound rejecting a legitimate low SC figure."""
    li = L(state="SC", county="Anderson")
    res = {"owner": "DOE JANE", "absentee": False, "out_of_state": False, "_value": 4_500.0}
    _run_resolve(li, res, monkeypatch)
    assert li.tax_value == 4_500.0 and li.market_value == 4_500.0
    assert li.assessed_value is None


def test_owner_mailing_value_sink_rejects_non_numeric_value(monkeypatch):
    li = L(state="NC", county="Gaston")
    res = {"owner": "DOE JANE", "absentee": False, "out_of_state": False, "_value": "not-a-number"}
    _run_resolve(li, res, monkeypatch)
    assert li.tax_value is None and li.market_value is None and li.assessed_value is None


# ---------------------------------------------------------------- plausible_value itself (unchanged
# contract this fix relies on -- regression guard against a future bound edit silently breaking
# a low SC ratio value elsewhere)


def test_plausible_value_bound_unchanged():
    assert plausible_value(99) is None
    assert plausible_value(100) == 100
    assert plausible_value(5e8) == 5e8
    assert plausible_value(5e8 + 1) is None
    assert plausible_value(None) is None

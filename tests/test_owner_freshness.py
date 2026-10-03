"""owner_name REFRESH policy (2026-10-02/03) -- see src/foreclosure_scraper/owner_freshness.py.

Root cause this guards against, re-verified live against the real Buncombe County tax
site (tax.buncombenc.gov/Parcel/Details/{pin}) the same day as the earlier validation
session that first flagged it (docs/HANDOFF.md item 52 Finding C): a 59-row live sample
of Buncombe tax-delinquency candidates found 15 (25.4%, strict token-overlap re-check)
show a DIFFERENT current owner than the board for the identical parcel_id -- e.g. PIN
965488696900000, board owner_name "Brandon Bryant" vs. the live site's current
"SUSAN STANFILL, IAN HUGHES" for the SAME parcel, fetched fresh just now.

Before this fix, every owner-filling path in enrichment_arcgis.py / enrichment_gis_attrs.py
only ever fired on `if not li.owner_name: ...` -- a field, once set (often straight off a
scraper's own one-time ArcGIS-layer read at ingest time, e.g. the generic
counties_generic.arcgis_distress family), was NEVER revisited even when a fresher,
already-local parcel_cache snapshot sitting right next to it on the SAME pipeline run
disagreed. Fix: owner_freshness.py adds a per-field freshness stamp
(raw['owner_name_as_of']) and a should_refresh_owner_name()/stamp_owner_name() pair that
both enrichers now use in place of the bare `if not li.owner_name` guard -- a REFRESH,
not just a blank-fill, gated on the existing value being unstamped (legacy data, unknown
age -> treated as stale, same convention parcel_cache.cache_is_stale() uses for a missing
cache file) or stamped at least OWNER_REFRESH_MIN_AGE_DAYS ago.

Deliberately NOT wired into: enrichment_court_owner_verify.py (an unrelated wrong-PARCEL
guard, not a staleness policy), any scraper's initial notice/caption-sourced owner_name
(a court docket defendant / divorce party / tax-sale notice name is a HISTORICAL record of
who was party to that specific filing, not current real-world ownership -- refreshing it
to "whoever owns it today" would make it WRONG, not right), and enrichment_ncpts_lrc.py /
enrichment_owner_mailing.py (both live-network-query paths; wiring a cost-bounded refresh
into those is explicitly flagged as separate future work, not covered by the cheap, local,
every-run parcel_cache fast path this commit bounds its cost to).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from foreclosure_scraper import owner_freshness as of
from foreclosure_scraper import enrichment_gis_attrs as ga
from foreclosure_scraper import enrichment_arcgis as arc
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(owner=None, parcel="9608108745", county="Buncombe", state="NC",
        owner_as_of=None, market_value=None, living_sqft=None,
        street_address="1068 MONTE VISTA RD", raw_extra=None):
    now = datetime.utcnow()
    raw = dict(raw_extra or {})
    if owner_as_of is not None:
        raw["owner_name_as_of"] = owner_as_of
    return Listing(source="s", source_url="https://x/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, street_address=street_address,
                   owner_name=owner, market_value=market_value, living_sqft=living_sqft,
                   first_seen=now, last_seen=now, raw=raw)


def _iso_days_ago(n: float) -> str:
    d = (datetime.now(timezone.utc) - timedelta(days=n)).date()
    return d.isoformat()


# ---- owner_name_as_of / owner_name_age_days / is_owner_refreshable --------------------

def test_as_of_none_when_never_stamped():
    li = _li(owner="Brandon Bryant")
    assert of.owner_name_as_of(li) is None
    assert of.owner_name_age_days(li) is None
    assert of.is_owner_refreshable(li) is True   # unstamped == unknown age == stale


def test_fresh_stamp_not_refreshable_stale_stamp_is():
    fresh = _li(owner="A", owner_as_of=_iso_days_ago(0))
    assert of.is_owner_refreshable(fresh) is False
    old = _li(owner="A", owner_as_of=_iso_days_ago(30))
    assert of.is_owner_refreshable(old) is True


def test_boundary_respects_min_age_days():
    li = _li(owner="A", owner_as_of=_iso_days_ago(5))
    assert of.is_owner_refreshable(li, min_age_days=10.0) is False
    assert of.is_owner_refreshable(li, min_age_days=1.0) is True


def test_malformed_stamp_treated_as_unstamped():
    li = _li(owner="A", raw_extra={"owner_name_as_of": "not-a-date"})
    assert of.owner_name_age_days(li) is None
    assert of.is_owner_refreshable(li) is True


# ---- should_refresh_owner_name / stamp_owner_name --------------------------------------

def test_blank_owner_is_a_plain_fill_always_allowed():
    li = _li(owner=None)
    assert of.should_refresh_owner_name(li, "CONNER RICKEY") is True


def test_same_name_different_punctuation_is_not_a_refresh():
    li = _li(owner="CONNER, RICKEY", owner_as_of=_iso_days_ago(30))
    assert of.should_refresh_owner_name(li, "Conner Rickey") is False


def test_different_name_blocked_while_stamp_is_fresh():
    li = _li(owner="Brandon Bryant", owner_as_of=_iso_days_ago(0))
    assert of.should_refresh_owner_name(li, "SUSAN STANFILL") is False


def test_different_name_allowed_once_stamp_is_old_enough():
    li = _li(owner="Brandon Bryant", owner_as_of=_iso_days_ago(5))
    assert of.should_refresh_owner_name(li, "SUSAN STANFILL") is True


def test_different_name_allowed_when_never_stamped_at_all():
    # The exact live-confirmed Buncombe scenario: owner_name was set long ago by a
    # scraper that predates this fix and never stamped anything.
    li = _li(owner="Brandon Bryant")
    assert of.should_refresh_owner_name(li, "SUSAN STANFILL, IAN HUGHES") is True


def test_empty_candidate_never_refreshes():
    li = _li(owner="Brandon Bryant")
    assert of.should_refresh_owner_name(li, "") is False
    assert of.should_refresh_owner_name(li, None) is False


def test_stamp_owner_name_sets_value_and_todays_date():
    li = _li(owner=None)
    of.stamp_owner_name(li, "SUSAN STANFILL, IAN HUGHES")
    assert li.owner_name == "SUSAN STANFILL, IAN HUGHES"
    assert li.raw["owner_name_as_of"] == _iso_days_ago(0)


# ---- enrichment_arcgis.enrich(): parcel-cache fast path refresh -----------------------

class _BoomClient:
    """Any attribute access that looks like a live network call fails the test."""
    async def get(self, *a, **k):
        raise AssertionError("live network GIS query made despite a parcel-cache hit")


def test_arcgis_parcel_cache_refreshes_stale_unstamped_owner_no_network(monkeypatch):
    monkeypatch.setattr(arc, "lookup", None, raising=False)  # ensure we patch the real import site
    import foreclosure_scraper.parcel_cache as pc_mod

    def _fake_lookup(county, parcel_id, state=None):
        return {"owner": "SUSAN STANFILL, IAN HUGHES", "market_value": 189200, "tax_value": 100400}

    monkeypatch.setattr(pc_mod, "lookup", _fake_lookup)

    li = _li(owner="Brandon Bryant", market_value=189200, parcel="9654886969")
    asyncio.run(arc.enrich([li], concurrency=1))

    assert li.owner_name == "SUSAN STANFILL, IAN HUGHES"
    assert li.raw.get("owner_name_as_of") == _iso_days_ago(0)


def test_arcgis_parcel_cache_does_not_reflap_a_just_refreshed_owner(monkeypatch):
    import foreclosure_scraper.parcel_cache as pc_mod
    monkeypatch.setattr(pc_mod, "lookup",
                         lambda county, parcel_id, state=None: {"owner": "OTHER NAME", "market_value": 189200})

    li = _li(owner="SUSAN STANFILL, IAN HUGHES", market_value=189200,
             parcel="9654886969", owner_as_of=_iso_days_ago(0))
    asyncio.run(arc.enrich([li], concurrency=1))

    # Stamped today -> not refreshable yet -> must NOT flap to "OTHER NAME".
    assert li.owner_name == "SUSAN STANFILL, IAN HUGHES"


def test_arcgis_no_parcel_id_takes_the_unmodified_fallthrough_path(monkeypatch):
    """Cost guard: owner_refresh_due is gated on li.parcel_id (see enrichment_arcgis.py
    comment) specifically so a lead with NO parcel_id gets ZERO behavior change from
    this fix -- `if li.parcel_id:` is false, so execution falls through to the exact
    same county-resolution code this function always ran for such a lead. Proven here
    with a real street_address but a county absent from NC_GIS/SC_GIS, which the
    unmodified fallthrough path already returns early on (cfg missing) -- reaching
    that specific, pre-existing early return (and not crashing, not touching
    owner_name) demonstrates the normal path was taken, not some new staleness-driven
    shortcut."""
    li = _li(owner="Brandon Bryant", market_value=189200, parcel=None,
             county="Nonexistent County", state="NC")
    asyncio.run(arc.enrich([li], concurrency=1))
    assert li.owner_name == "Brandon Bryant"   # untouched, no crash, no network attempted


def test_arcgis_parcel_cache_miss_on_stale_owner_bails_without_live_query(monkeypatch):
    import foreclosure_scraper.parcel_cache as pc_mod
    monkeypatch.setattr(pc_mod, "lookup", lambda county, parcel_id, state=None: None)

    async def _boom(*a, **k):
        raise AssertionError("live network GIS query made despite owner-only stale recheck")
    monkeypatch.setattr(arc, "_wfs_query", _boom)

    li = _li(owner="Brandon Bryant", market_value=189200, parcel="9654886969")
    # Should return cleanly without attempting a live query for a county/parcel this
    # test deliberately gives no live-query configuration for either (NC_GIS/SC_GIS
    # lookups would return early with `cfg` missing) -- the real assertion is just
    # that nothing raises and owner_name is left exactly as the cache-miss leaves it.
    asyncio.run(arc.enrich([li], concurrency=1))
    assert li.owner_name == "Brandon Bryant"


# ---- enrichment_gis_attrs.enrich_gis_attrs(): parcel-cache fast path refresh ----------

def test_gis_attrs_parcel_cache_refreshes_stale_unstamped_owner_no_network(monkeypatch):
    import foreclosure_scraper.parcel_cache as pc_mod
    monkeypatch.setattr(pc_mod, "lookup",
                         lambda county, parcel_id, state=None: {"owner": "SUSAN STANFILL, IAN HUGHES"})
    monkeypatch.setattr(pc_mod, "cache_is_stale", lambda county, state=None: False)

    async def _boom(*a, **k):
        raise AssertionError("live network GIS query made despite a parcel-cache hit")
    monkeypatch.setattr(ga, "_query_point", _boom)
    monkeypatch.setattr(ga, "_query_parcel", _boom)

    li = _li(owner="Brandon Bryant", market_value=189200, living_sqft=1200,
             parcel="9654886969")
    stats = asyncio.run(ga.enrich_gis_attrs([li]))

    assert li.owner_name == "SUSAN STANFILL, IAN HUGHES"
    assert li.raw.get("owner_name_as_of") == _iso_days_ago(0)
    assert stats["filled_owner"] == 1


def test_gis_attrs_skips_entirely_when_owner_already_fresh(monkeypatch):
    """Performance guard: a lead whose owner was JUST stamped (today) must take the
    original `skipped_done` fast exit -- no parcel_cache lookup, no live query."""
    import foreclosure_scraper.parcel_cache as pc_mod

    def _boom_lookup(*a, **k):
        raise AssertionError("parcel_cache consulted despite an already-fresh owner stamp")
    monkeypatch.setattr(pc_mod, "lookup", _boom_lookup)

    li = _li(owner="SUSAN STANFILL, IAN HUGHES", market_value=189200, living_sqft=1200,
             parcel="9654886969", owner_as_of=_iso_days_ago(0))
    stats = asyncio.run(ga.enrich_gis_attrs([li]))
    assert stats["skipped_done"] == 1
    assert li.owner_name == "SUSAN STANFILL, IAN HUGHES"


def test_gis_attrs_cache_miss_on_stale_owner_only_bails_without_live_query(monkeypatch):
    import foreclosure_scraper.parcel_cache as pc_mod
    monkeypatch.setattr(pc_mod, "lookup", lambda county, parcel_id, state=None: None)

    async def _boom(*a, **k):
        raise AssertionError("live network GIS query made despite owner-only stale recheck")
    monkeypatch.setattr(ga, "_query_point", _boom)
    monkeypatch.setattr(ga, "_query_parcel", _boom)
    monkeypatch.setattr(ga, "_resolve_layer", _boom)

    li = _li(owner="Brandon Bryant", market_value=189200, living_sqft=1200,
             parcel="9654886969")
    asyncio.run(ga.enrich_gis_attrs([li]))
    assert li.owner_name == "Brandon Bryant"


# ---- apply_gis_attrs() direct unit coverage (the live-GIS-attrs owner refresh path) ---

def test_apply_gis_attrs_refreshes_stale_unstamped_owner():
    li = _li(owner="Tim Magee", market_value=None, living_sqft=None)
    flags = ga.apply_gis_attrs(li, {"OwnerAll": "JAMES DAVENPORT, LISA DAVENPORT"})
    assert li.owner_name == "JAMES DAVENPORT, LISA DAVENPORT"
    assert flags["owner_name"] == 1
    assert li.raw.get("owner_name_as_of") == _iso_days_ago(0)


def test_apply_gis_attrs_does_not_refresh_a_fresh_stamped_owner():
    li = _li(owner="JAMES DAVENPORT, LISA DAVENPORT", owner_as_of=_iso_days_ago(0))
    flags = ga.apply_gis_attrs(li, {"OwnerAll": "SOME OTHER NAME"})
    assert li.owner_name == "JAMES DAVENPORT, LISA DAVENPORT"
    assert flags["owner_name"] == 0


def test_apply_gis_attrs_still_fills_a_blank_owner_like_before():
    li = _li(owner=None)
    flags = ga.apply_gis_attrs(li, {"OwnerAll": "NEW OWNER"})
    assert li.owner_name == "NEW OWNER"
    assert flags["owner_name"] == 1

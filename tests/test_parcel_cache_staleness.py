"""parcel_cache value-field staleness guard (2026-10-02).

Root cause this guards against, confirmed live against the real Buncombe County
GIS service (gis.buncombecounty.org/.../property_bc_dis/MapServer/1): the
2026-09-27 refresh of data/parcel_cache/buncombe.sqlite carries market_value /
tax_value figures that the live service has since moved on from (e.g. parcel
9608108745, owner CONNER RICKEY DEWAYNE: cached market_value=269400 / tax_value=
72600 vs live TotalMarketValue=AppraisedValue=TaxValue=130600 for the SAME
parcel on 2026-10-02 — a 1.80x overstatement). A population sample (60 of 1,176
Buncombe tax-delinquency candidates) found 39/41 owner-matched leads overstated
at a tight median ratio of 1.78x, consistent with this exact mechanism.

`enrichment_arcgis.enrich()` and `enrichment_gis_attrs.enrich_gis_attrs()` both
had a "parcel cache fast path" that filled li.market_value / li.tax_value from
this local SQLite snapshot with NO freshness check at all, unlike every live
per-parcel GIS query elsewhere in this codebase, which always reads the
CURRENT county data. Fix: parcel_cache.lookup_with_tier() now omits
market_value/tax_value from its result once the county's cache file is older
than CACHE_VALUE_MAX_AGE_DAYS, and enrichment_gis_attrs.py's cache-hit early
return now falls through to its own (correctly-aliased) live query when that
happens, instead of leaving the value permanently empty. Owner/address/sqft/
acreage are NOT gated by this -- those fields don't carry the same
staleness risk a dollar figure used for a bid decision does."""
from __future__ import annotations

import os
import sqlite3
import time

import pytest

from foreclosure_scraper import parcel_cache as pc


def _make_cache(tmp_path, monkeypatch, name, rows, state=None, age_days=None):
    """rows: [(id, owner, address, market_value, tax_value)]. age_days backdates
    the file's mtime so cache_is_stale() sees it as that old."""
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    pc._CONN.clear()
    stem = name if state is None else f"{name}_{state.lower()}"
    path = tmp_path / f"{stem}.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE parcels(id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, "
                "market_value REAL, tax_value REAL, acreage REAL, living_sqft REAL, "
                "land_use TEXT, sale_price REAL, sale_date TEXT)")
    for pid, owner, addr, mv, tv in rows:
        con.execute(
            "INSERT INTO parcels(id, owner, address, market_value, tax_value) VALUES(?,?,?,?,?)",
            (pid, owner, addr, mv, tv),
        )
    con.commit()
    con.close()
    if age_days is not None:
        stamp = time.time() - age_days * 86400
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture(autouse=True)
def _clear():
    yield
    pc._CONN.clear()


# ---- cache_age_days / cache_is_stale -------------------------------------------

def test_cache_age_days_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    assert pc.cache_age_days("Nowhere", "NC") is None
    assert pc.cache_is_stale("Nowhere", "NC") is True   # missing == stale


def test_cache_is_stale_fresh_vs_old(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "fresh", [("1", "A", "1 OAK ST", 100000, 100000)], age_days=1)
    assert pc.cache_is_stale("fresh") is False
    _make_cache(tmp_path, monkeypatch, "old", [("1", "A", "1 OAK ST", 100000, 100000)], age_days=20)
    assert pc.cache_is_stale("old") is True


def test_cache_is_stale_boundary_respects_max_age_days(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "boundary", [("1", "A", "1 OAK ST", 1, 1)], age_days=5)
    assert pc.cache_is_stale("boundary", max_age_days=10.0) is False
    assert pc.cache_is_stale("boundary", max_age_days=1.0) is True


# ---- lookup_with_tier withholds value on a stale cache -------------------------

def test_fresh_cache_still_returns_market_and_tax_value(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "buncombe",
                [("9608108745", "CONNER RICKEY", "1068 MONTE VISTA RD", 130600, 130600)],
                age_days=1)
    hit, tier = pc.lookup_with_tier("Buncombe", "9608108745")
    assert tier == "exact"
    assert hit["market_value"] == 130600
    assert hit["tax_value"] == 130600
    assert hit["owner"] == "CONNER RICKEY"          # non-value fields unaffected


def test_stale_cache_omits_market_and_tax_value_but_keeps_everything_else(tmp_path, monkeypatch):
    # Reproduces the live-confirmed Buncombe case: a stale cache's own value figures
    # (269400/72600) must never reach a caller once the file is past the freshness bound.
    _make_cache(tmp_path, monkeypatch, "buncombe",
                [("9608108745", "CONNER RICKEY DEWAYNE", "1068 MONTE VISTA RD", 269400, 72600)],
                age_days=20)
    hit, tier = pc.lookup_with_tier("Buncombe", "9608108745")
    assert tier == "exact"
    assert "market_value" not in hit
    assert "tax_value" not in hit
    assert hit["owner"] == "CONNER RICKEY DEWAYNE"   # owner/address still served
    assert hit["address"] == "1068 MONTE VISTA RD"


def test_stale_cache_omits_value_through_the_zero_pad_tier_too(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "harnett",
                [("0546741638000", "SCHACHTER", "3603 MCLEAN CHAPEL CHURCH RD", 200000, 150000)],
                age_days=30)
    hit, tier = pc.lookup_with_tier("Harnett", "0546-74-1638", "NC")
    assert tier == "zero_pad"
    assert "market_value" not in hit and "tax_value" not in hit
    assert hit["owner"] == "SCHACHTER"


def test_lookup_plain_wrapper_also_withholds_stale_value(tmp_path, monkeypatch):
    _make_cache(tmp_path, monkeypatch, "buncombe",
                [("9608108745", "CONNER", "1068 MONTE VISTA RD", 269400, 72600)], age_days=20)
    hit = pc.lookup("Buncombe", "9608108745")
    assert hit is not None
    assert "market_value" not in hit and "tax_value" not in hit


# ---- enrichment_gis_attrs falls through to a live query when value was withheld ----

def test_gis_attrs_cache_hit_does_not_early_return_when_value_is_stale(tmp_path, monkeypatch):
    """The early-return that used to fire on street_address alone must NOT fire when
    the parcel cache withheld market_value/tax_value for staleness -- otherwise this
    lead's value stays empty forever instead of falling through to the live GIS query
    that (unlike the cache) always reads the county's current figures."""
    import asyncio

    from foreclosure_scraper import enrichment_gis_attrs as ga
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    _make_cache(tmp_path, monkeypatch, "buncombe",
                [("9608108745", "CONNER RICKEY", "1068 MONTE VISTA RD", 269400, 72600)],
                age_days=20)

    li = Listing(
        source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
        source_url="https://www.buncombecounty.org/governing/depts/tax/",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.LAND,
        state="NC", county="Buncombe", parcel_id="9608108745",
        street_address="1068 MONTE VISTA RD", owner_name="CONNER, RICKEY",
        latitude=35.563336666803, longitude=-82.692849690772,
    )

    # No live network in this test — the live-query layer resolution is stubbed to
    # fail closed (None) and spied on, so the only question under test is whether
    # the function SKIPPED the live path entirely (old bug) or at least attempted
    # it (fixed).
    calls = {"n": 0}

    def _spy(_li):
        calls["n"] += 1
        return None   # fail closed — no live network in this test

    monkeypatch.setattr(ga, "_resolve_layer", _spy)

    asyncio.run(ga.enrich_gis_attrs([li]))

    # The live-query path must actually have been attempted (old bug: it never was).
    assert calls["n"] == 1
    # Cache's stale 269400/72600 must never have been written onto the lead.
    assert li.market_value != 269400
    assert li.tax_value != 72600
    # Owner/address (not staleness-sensitive) still came from the cache.
    assert li.owner_name == "CONNER, RICKEY"      # already set; cache wouldn't overwrite anyway
    assert li.street_address == "1068 MONTE VISTA RD"


def test_gis_attrs_does_not_force_live_fallthrough_when_value_already_present(tmp_path, monkeypatch):
    """Performance guard: a lead that already carries a market_value (e.g. set directly
    by its own scraper, independent of the cache) must NOT trigger an extra live query
    just because this county's cache happens to be stale -- there is nothing left for
    the live query to usefully add, and forcing it would turn every lead in a stale-
    cache county into a live call instead of only the ones that actually still need a
    value."""
    import asyncio

    from foreclosure_scraper import enrichment_gis_attrs as ga
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    _make_cache(tmp_path, monkeypatch, "buncombe",
                [("9608108745", "CONNER RICKEY", "1068 MONTE VISTA RD", 269400, 72600)],
                age_days=20)

    li = Listing(
        source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
        source_url="https://www.buncombecounty.org/governing/depts/tax/",
        listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.LAND,
        state="NC", county="Buncombe", parcel_id="9608108745",
        street_address="1068 MONTE VISTA RD", owner_name="CONNER, RICKEY",
        market_value=130600.0,   # already correct, from this lead's own scraper
        latitude=35.563336666803, longitude=-82.692849690772,
    )

    calls = {"n": 0}

    def _spy(_li):
        calls["n"] += 1
        return None

    monkeypatch.setattr(ga, "_resolve_layer", _spy)

    asyncio.run(ga.enrich_gis_attrs([li]))

    assert calls["n"] == 0            # no live query needed — value was already present
    assert li.market_value == 130600.0   # untouched by the stale cache

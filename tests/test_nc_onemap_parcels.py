"""NC OneMap statewide parcels: the contact + value layer for 96 NC counties.

WHY THIS SOURCE MATTERS. The per-county coverage matrix measured the CONTACT layer as the
binding constraint, and three FOOTPRINT counties -- Buncombe, Lincoln and Transylvania --
had dedicated parcel layers that publish no owner mailing field at all. About 223,000
footprint parcels had no owner mailing available from any wired source. NC OneMap carries
it for all of them, in one statewide service:

    5,938,900 NC parcels, 100 counties, verified live 2026-09-10
    owner mailing populated 99.6-100% in every NC footprint county:
        Buncombe 134,741/134,741  ·  Gaston 117,252/117,211  ·  Henderson 75,373/75,373
        Cleveland 59,964/59,790   ·  Burke 59,374/59,350     ·  Rutherford 57,599/57,580
        Lincoln 56,862/56,862     ·  McDowell 33,449/33,449  ·  Transylvania 31,755/31,755
        Polk 18,211/18,063        ·  Mitchell 17,671/17,270
    = 662,251 footprint parcels

THE HAZARD THIS FILE USED TO GUARD, AND HOW IT CLOSED. The parcel cache was
originally keyed by county NAME with no state -- lookup(county, parcel_id) and every
caller passed only li.county. Four county names exist in BOTH Carolinas (Beaufort,
Cherokee, Lee, Union; Anson and Chester also collide, Chester has no NC data), so an
NC fallback on a shared name could silently read NC parcel data for an SC lead. They
were excluded entirely rather than risk it.

FIXED 2026-09-14. _db_path/lookup/nc_onemap_cfg all now require and thread an explicit
state for these six names (DUAL_STATE_COUNTIES) -- a lookup with no state RAISES or
returns None rather than guessing (see test_parcel_cache_state_aware.py), and
nc_onemap_cfg tags state="NC" so refresh_county writes lee_nc.sqlite, not lee.sqlite.
With the collision itself closed at the storage layer, excluding these counties from
NC OneMap was pure loss: Anson was the one of the six already enabled, and because
nc_onemap_cfg omitted the state tag until this same fix, ANSON'S OWN CACHE HAD BEEN
SILENTLY FAILING TO BUILD since the state-aware refactor -- refresh_county's
_db_path(county, cfg.get("state")) raised on every attempt. The four other REAL NC
counties (Lee, Cherokee, Union, Beaufort -- 35K-118K parcels each, verified live;
Chester returns 0 rows, NC has no Chester county) are now enabled too. This file's
job is now to prove the state-threading holds, not that these names are unreachable.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.parcel_cache import (
    NC_ONEMAP_URL, PARCEL_LAYERS, _COLS, _NC_COUNTY_NAMES, nc_onemap_cfg,
    resolve_layer_cfg,
)

SHARED_NAMES = {"Beaufort", "Cherokee", "Lee", "Union", "Anson"}


@pytest.mark.parametrize("name", sorted(SHARED_NAMES))
def test_shared_names_get_a_state_tagged_nc_fallback(name):
    """These names ARE now enabled for NC OneMap -- the guard moved from "excluded
    entirely" to "state-tagged so the cache path can never collide with SC"."""
    assert name in _NC_COUNTY_NAMES
    cfg = resolve_layer_cfg(name)
    assert cfg is not None
    assert cfg.get("state") == "NC", (
        f"{name} exists in both Carolinas; its OneMap config MUST tag state='NC' "
        f"or _db_path cannot safely name its cache file."
    )


@pytest.mark.parametrize("name", sorted(SHARED_NAMES))
def test_lookup_without_a_state_still_refuses_to_guess(name):
    """The real safety property: being ENABLED for NC does not mean an SC lead for
    the same name can ever read this cache by accident. A caller that omits state
    (the old bug class) gets None, never a wrong-state parcel."""
    from foreclosure_scraper.parcel_cache import lookup
    assert lookup(name, "1234567890") is None


def test_the_nc_list_covers_the_rest_of_the_state():
    # 100 NC counties minus Chester (0 rows on the statewide layer -- not a real
    # NC county, so it stays excluded rather than build an always-empty cache).
    assert len(_NC_COUNTY_NAMES) == 100   # all 100 real NC counties; Chester never was one
    assert "Chester" not in _NC_COUNTY_NAMES
    for c in ("Buncombe", "Lincoln", "Transylvania", "Wake", "Mecklenburg", "Gaston",
              "Lee", "Cherokee", "Union", "Beaufort", "Anson"):
        assert c in _NC_COUNTY_NAMES


@pytest.mark.parametrize("county", ["Buncombe", "Lincoln", "Transylvania"])
def test_the_three_footprint_counties_with_no_mailing_route_to_onemap(county):
    """These are the reason this source was wired: their own county layers publish no
    mailing field, so ~223,000 footprint parcels had no owner mailing anywhere."""
    cfg = resolve_layer_cfg(county)
    assert cfg is not None
    assert "nconemap" in cfg["url"], f"{county} should fall back to the statewide layer"
    assert cfg["map"]["owner_mailing"]


@pytest.mark.parametrize("county", ["Rutherford", "Henderson", "Burke", "McDowell",
                                    "Cleveland", "Gaston", "Mitchell", "Polk"])
def test_a_county_whose_own_layer_has_mailing_keeps_it(county):
    """The county's own data wins: it is usually richer (heated sqft, condition codes)
    than the statewide aggregate, and it is the authority for its own parcels."""
    cfg = resolve_layer_cfg(county)
    assert "nconemap" not in cfg["url"], f"{county} has its own mailing field; do not override it"


@pytest.mark.parametrize("county", ["Pickens", "Laurens", "Anderson", "Spartanburg"])
def test_sc_counties_are_never_served_nc_parcels(county):
    cfg = resolve_layer_cfg(county)
    if cfg:
        assert "nconemap" not in cfg["url"], f"{county} is in SOUTH Carolina"


def test_the_statewide_config_filters_to_one_county():
    """Without the where clause the count check would ask for 5,938,900 rows and the
    pager would never terminate on a single county."""
    cfg = nc_onemap_cfg("Buncombe")
    assert cfg["where"] == "cntyname='Buncombe'"
    assert "1=1" not in cfg["where"]


def test_the_field_map_only_uses_columns_the_cache_has():
    cfg = nc_onemap_cfg("Wake")
    for col in cfg["map"]:
        assert col in _COLS, f"{col!r} is not a parcel-cache column"
    assert cfg["map"]["owner_mailing"] == ["mailadd", "munit", "mcity", "mstate", "mzip"]
    assert cfg["map"]["market_value"] == "parval"


def test_id_fields_cover_the_parcel_number_variants():
    """NC parcel ids arrive in several shapes; OneMap publishes three of them."""
    assert nc_onemap_cfg("Wake")["id_fields"] == ["parno", "altparno", "nparno"]


def test_the_url_is_a_query_endpoint_on_the_state_host():
    assert NC_ONEMAP_URL.startswith("https://services.nconemap.gov/")
    assert NC_ONEMAP_URL.endswith("/query")
    assert "NC1Map_Parcels" in NC_ONEMAP_URL


def test_an_unknown_county_does_not_invent_a_config():
    assert resolve_layer_cfg("Nowhere") is None

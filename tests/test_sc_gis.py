"""Guard for the SC_GIS county-native resolver map.

Context: SCDOT SC_Parcels (the shared owner/situs layer for every SC county)
went token-walled 2026-08-12 (HTTP 200 + code 499 "Token Required"). SC_GIS is
the county-native replacement. These tests pin its shape so a future edit can't
silently (a) drop a working county, (b) re-add a county whose native GIS is
walled/owner-masked/situs-less, or (c) unpin Beaufort's GisFile_-prefixed situs.

The static tests are hermetic. The network test (owner+situs actually resolve on
the live layer) runs only with RUN_NETWORK_TESTS=1 so CI stays offline.
"""
from __future__ import annotations

import os

import pytest

from foreclosure_scraper.enrichment_arcgis import SC_GIS

#: Counties validated live 2026-08-12 (owner + situs both resolve).
#: Georgetown uses a split-situs concat (StreetNumber+StreetName) via layer 2.
BUILT = {"Spartanburg", "Laurens", "Pickens", "Colleton", "Beaufort", "Georgetown"}

#: Probed live and confirmed to have NO free county-native owner+situs path.
#: They must NOT be in SC_GIS (adding a broken endpoint silently returns 0 rows).
#: See docs/walls_register.md. Georgetown/Charleston are deferred (buildable).
WALLED = {"Cherokee", "Union", "Oconee", "Anderson"}


def test_sc_gis_has_exactly_the_built_counties():
    assert set(SC_GIS) == BUILT, (
        f"SC_GIS drifted. Expected {sorted(BUILT)}, got {sorted(SC_GIS)}. "
        "If adding a county, validate owner+situs resolve live first."
    )


def test_walled_counties_are_not_in_sc_gis():
    for c in WALLED:
        assert c not in SC_GIS, (
            f"{c} has no free county-native owner+situs path (see "
            "docs/walls_register.md) — it must not be in SC_GIS"
        )


def test_sc_gis_urls_are_query_endpoints():
    for county, cfg in SC_GIS.items():
        url = cfg.get("url", "")
        assert url.startswith("https://"), f"{county}: url not https: {url!r}"
        assert url.endswith("/query"), f"{county}: url must end in /query: {url!r}"


def test_beaufort_situs_is_pinned():
    # Beaufort's layer is GisFile_-prefixed, so situs can't auto-detect from the
    # unprefixed aliases — it must be pinned or address resolution silently fails.
    assert SC_GIS["Beaufort"]["addr_field"] == "GisFile_SitusAddre"


def test_autodetect_counties_have_no_pin():
    # These auto-detect situs via FIELD_ALIASES; a stray pin would mask drift.
    for c in ("Spartanburg", "Laurens", "Pickens", "Colleton"):
        assert SC_GIS[c].get("addr_field") is None, f"{c} should auto-detect situs"


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live county GIS — set RUN_NETWORK_TESTS=1 to enable",
)
@pytest.mark.parametrize("county", sorted(BUILT))
def test_owner_and_situs_resolve_live(county: str):
    import asyncio

    import httpx

    from foreclosure_scraper import enrichment_address_owner_v2 as v2

    async def check() -> tuple:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"}, timeout=25.0, verify=False
        ) as c:
            url = SC_GIS[county]["url"]
            owner = await v2._detect_owner_field_v2(c, url)
            situs = await v2._detect_site_field(c, url)
            return owner, situs

    owner, situs = asyncio.run(check())
    assert owner, f"{county}: owner field not detected on live layer"
    assert situs, f"{county}: situs field not detected on live layer"

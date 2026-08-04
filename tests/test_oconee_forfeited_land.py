"""Oconee SC Forfeited Land Commission (Assignment_Availability FeatureServer).

Covers the silent-degradation guard on this source specifically. It reads a
DIFFERENT service from counties_sc.oconee_flc_assignment (Assignment_Availability
vs Assignment_FLC) on the same county GIS org, and both declare two layers
(FLC + Assignment), so both must fail rather than shrink when one layer dies.

Before the guard this source did two things that hid a dead layer:
  * ``except (httpx.HTTPError, ValueError): continue`` around the per-layer fetch
  * a hand-rolled paginator that logged ``oconee_forfeited_land.arcgis_error``
    and ``break``-ed on an HTTP-200-with-error-body, returning its partial pages

It also requested ``outFields="*"``, which is now enumerated per layer.
"""
from __future__ import annotations

import pytest

# --------------------------------------------------------------------------- #
# silent-degradation guard (see foreclosure_scraper/layer_guard.py)
# --------------------------------------------------------------------------- #

def test_out_fields_are_enumerated_per_layer_never_star():
    """PRIVACY + the two layers do not share a schema.

    This source used to request outFields="*", which both broke the
    enumerate-only rule and pulled the entire tax-arithmetic block nothing
    reads. query_features now hard-rejects "*", so this asserts the field lists
    stayed explicit and layer-specific.
    """
    from foreclosure_scraper.scrapers.counties_sc import oconee_forfeited_land as mod

    by_label = {label: fields for _id, label, fields in mod._LAYERS}
    assert set(by_label) == {"FLC", "Assignment"}
    for fields in by_label.values():
        assert fields and "*" not in fields
        assert "TMS" in fields and "OBJECTID" in fields
    # Layer-specific columns must NOT be requested from the layer that lacks
    # them — ArcGIS 400s the whole query on an unknown field name.
    assert "Sale_Date" in by_label["FLC"] and "Sale_Date" not in by_label["Assignment"]
    assert "Redeem_Assign" in by_label["Assignment"]
    assert "Redeem_Assign" not in by_label["FLC"]


def test_a_dead_layer_fails_the_run_instead_of_halving_the_inventory():
    """Half the FLC roll is a believable number, so it must not be shippable.

    The old code logged oconee_forfeited_land.layer_failed and continued; the
    hand-rolled paginator additionally broke out on an HTTP-200-with-error-body
    and returned its partial page set.
    """
    import asyncio

    from foreclosure_scraper.layer_guard import PartialHarvest
    from foreclosure_scraper.scrapers.counties_sc import oconee_forfeited_land as mod

    from tests._arcgis_fakes import FakeHttp

    class _ctx:
        def __init__(self, http):
            self.http = http

        async def __aenter__(self):
            return self.http

        async def __aexit__(self, *a):
            return False

    # Layer 1 alive, layer 0 retired (200 + error body, no features key).
    http = FakeHttp(routes={
        "FeatureServer/1": {"features": [], "exceededTransferLimit": False},
        "FeatureServer/0": {"error": {"code": 400, "message": "Invalid URL"}},
    })
    original = mod.client
    mod.client = lambda *a, **kw: _ctx(http)      # noqa: E731
    try:
        with pytest.raises(PartialHarvest) as ei:
            asyncio.run(mod.OconeeForfeitedLand().fetch())
    finally:
        mod.client = original
    assert "Assignment" in str(ei.value)
    assert "1/2 declared layers alive" in str(ei.value)

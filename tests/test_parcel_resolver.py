"""parcel_resolver — lat/lng -> county parcel key (short-circuits + field map)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as N

from foreclosure_scraper import parcel_resolver as pr


def _lead(**kw):
    base = dict(parcel_id=None, state="SC", county="Spartanburg",
                latitude=None, longitude=None)
    base.update(kw)
    return N(**base)


def test_returns_existing_parcel_id_without_network():
    li = _lead(parcel_id="7-17-02-041.00")
    assert asyncio.run(pr.resolve_sc_parcel_key(li)) == "7-17-02-041.00"


def test_none_when_no_latlng():
    assert asyncio.run(pr.resolve_sc_parcel_key(_lead())) is None


def test_none_for_unconfigured_county():
    li = _lead(county="Charleston", latitude=32.0, longitude=-80.0)
    assert asyncio.run(pr.resolve_sc_parcel_key(li)) is None


def test_field_map_has_verified_counties():
    # Spartanburg's qPublic KeyValue is the dashed MAPNUMBER — the verified mapping.
    assert pr._SC_KEY_FIELD["Spartanburg"] == ("MAPNUMBER",)
    assert "Anderson" in pr._SC_KEY_FIELD and "Laurens" in pr._SC_KEY_FIELD
    assert all(c in pr.SC_LAYER for c in pr._SC_KEY_FIELD)

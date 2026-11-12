"""Regression test for the SC lis-pendens resolver COUNTY_SCHEMA.

Forensics 2026-06-15: the resolver filled 0 of 277 SC LP addresses
because (a) 5 of 11 user counties had no COUNTY_SCHEMA entry, and
(b) the 6 counties that DID have schemas referenced field names that
had drifted off the live SCDOT layers (Pickens "LOCADD" doesn't exist,
Oconee "FullAdd" doesn't exist, Anderson was missing "PHYS_ADDR" in
the situs slot, etc.).

This test queries each county's live SCDOT layer once and asserts the
configured owner / situs / situs_parts / parcel field names actually
exist on the layer. Catches future schema drift.

Network-gated — only runs with RUN_NETWORK_TESTS=1.
"""
from __future__ import annotations

import os

import httpx
import pytest

from foreclosure_scraper.enrichment_lis_pendens_resolver import (
    COUNTY_SCHEMA,
    SC_LAYER,
    SCDOT_BASE,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live SCDOT — set RUN_NETWORK_TESTS=1 to enable",
)


# Counties whose user-facing role is required (see scope docs).
REQUIRED_USER_COUNTIES = {
    "Greenville", "Spartanburg", "Anderson", "Pickens", "Oconee",
    "Cherokee", "Union", "Laurens", "Abbeville", "Greenwood", "Newberry",
}


def _layer_fields(layer_id: int) -> set[str]:
    r = httpx.get(
        f"{SCDOT_BASE}/{layer_id}",
        params={"f": "json"},
        timeout=30,
        verify=False,
    )
    info = r.json()
    return {f["name"] for f in info.get("fields", [])}


def test_every_user_county_has_a_schema() -> None:
    """The 11 user counties must each have a COUNTY_SCHEMA entry."""
    missing = REQUIRED_USER_COUNTIES - set(COUNTY_SCHEMA)
    assert not missing, f"COUNTY_SCHEMA missing user counties: {missing}"


@pytest.mark.parametrize("county", sorted(REQUIRED_USER_COUNTIES))
def test_county_schema_field_names_exist_on_live_layer(county: str) -> None:
    """For each user county, every NON-EMPTY field tuple in COUNTY_SCHEMA
    must reference at least one field that exists on the live layer.
    Empty tuples are allowed (means 'this slot isn't available here')."""
    layer_id = SC_LAYER[county]
    schema = COUNTY_SCHEMA[county]
    fields = _layer_fields(layer_id)
    # Field name comparison is case-insensitive on the server side, mirror that.
    fields_ci = {f.lower() for f in fields}

    failures = []
    for slot, candidates in schema.items():
        if not candidates:
            continue
        if not any(c.lower() in fields_ci for c in candidates):
            failures.append(f"{slot}: none of {candidates} present on layer {layer_id}")

    assert not failures, (
        f"{county} layer {layer_id} schema drift — "
        + "; ".join(failures)
        + f"  (available fields sample: {sorted(fields)[:15]})"
    )

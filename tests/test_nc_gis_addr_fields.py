"""Regression test for NC_GIS addr_field correctness.

Forensics 2026-06-15: 9 of 13 NC counties had wrong addr_field configured,
causing 89% of NC lis-pendens to land with placeholder addresses despite
the parcel being resolved. Example: Buncombe was set to "streetname"
which returns "OTEEN CHURCH" (street name only, no house #) instead of
"Address" which returns "72 OTEEN CHURCH RD".

This test queries each NC county FeatureServer with a known-good parcel
and asserts the configured addr_field returns a value that LOOKS like
a real street address (starts with a number, has letters after).

Counties whose addr_field is None (no situs layer available) are skipped
intentionally — they're documented in NC_GIS comments as TODOs.

Marked network — only runs when RUN_NETWORK_TESTS=1, so CI stays hermetic.
"""
from __future__ import annotations

import os
import re

import httpx
import pytest

from foreclosure_scraper.enrichment_arcgis import NC_GIS

# Verified-real parcel IDs per county. Updated when a county's parcel layer
# rotates IDs (rare). To refresh: pull a real parcel from
# docs/listings.json for that county.
KNOWN_GOOD_PARCELS = {
    "Mecklenburg":  "22141259",
    "Buncombe":     "9639754730",
    "Henderson":    "9633229181",
    "Polk":         "P123-27",
    "Gaston":       "3524910792",
    "Transylvania": "8573-39-3687-000",
    "McDowell":     "173000150271",
    "Lincoln":      "3671830805",
    "Burke":        "1743179710",
    # Mitchell: layer exposes street name only — house # unknown
    "Mitchell":     "0883-00-65-0990",
    # Madison: TODO confirm a real PID
}

# Where-clause field names tried in order (FeatureServer schemas vary).
WHERE_CANDIDATES = (
    "PIN", "PINNUM", "pin", "pinnum", "REID", "TMS",
    "PARCELNUMBER", "PARNO", "PARID", "MAPNUMBER", "PID",
)

# Acceptable answer: starts with digits + whitespace + letters
# (e.g. "72 OTEEN CHURCH RD", "11436 KINGFISHER DR CHARLOTTE NC")
LOOKS_LIKE_ADDRESS = re.compile(r"^\s*\d+\s+\w")

# Looser check — at least a non-empty string that's NOT a parcel/owner name
LOOKS_LIKE_STREET = re.compile(r"^\s*(\w+\s+)+(RD|DR|LN|ST|AVE|CT|HWY|BLVD|WAY|TRL|CIR|PKWY)\b", re.I)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="hits live county GIS — set RUN_NETWORK_TESTS=1 to enable",
)


@pytest.mark.parametrize("county", sorted(KNOWN_GOOD_PARCELS))
def test_nc_gis_addr_field_returns_real_address(county: str) -> None:
    cfg = NC_GIS.get(county)
    assert cfg is not None, f"{county} not in NC_GIS"

    addr_field = cfg["addr_field"]
    if addr_field is None:
        pytest.skip(f"{county} has no addr layer (documented)")

    pid = KNOWN_GOOD_PARCELS[county]
    feats = None
    last_err = None
    for wf in WHERE_CANDIDATES:
        try:
            r = httpx.get(
                cfg["url"],
                params={
                    "where": f"{wf}='{pid}'",
                    "outFields": addr_field,
                    "returnGeometry": "false",
                    "f": "json",
                },
                timeout=20,
                verify=False,
            )
            d = r.json()
            if d.get("features"):
                feats = d["features"]
                break
        except Exception as e:
            last_err = e

    assert feats, f"{county}: no parcel matched PID={pid!r} (last err: {last_err})"
    val = feats[0]["attributes"].get(addr_field)
    assert val, f"{county}: configured addr_field {addr_field!r} returned empty"
    assert isinstance(val, str), f"{county}: addr_field returned non-string: {val!r}"

    # The Mitchell layer has only street name (no house #). Allow it.
    if county == "Mitchell":
        assert LOOKS_LIKE_STREET.match(val) or LOOKS_LIKE_ADDRESS.match(val), (
            f"{county}: {addr_field}={val!r} doesn't look like a street"
        )
        return

    assert LOOKS_LIKE_ADDRESS.match(val), (
        f"{county}: {addr_field}={val!r} doesn't look like a real address "
        "(should start with house number). Schema may have drifted."
    )

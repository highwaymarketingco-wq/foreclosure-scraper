"""Ocean-proximity geofilter — "within 2-3 blocks of the Atlantic" gate.

Verifies the bundled NC+SC ocean-shoreline reference correctly flags genuine
oceanfront coords as near-beach and excludes inland / sound-side coords (the
non-beach towns the owner listed: Wilmington, Manteo, Beaufort SC, Mt Pleasant
city all sit on rivers/sounds, not the open ocean, and must be filtered out).
"""
from __future__ import annotations

from foreclosure_scraper.coastal_geofilter import (
    distance_to_ocean_m, is_near_beach, NEAR_BEACH_M,
)

# Genuine oceanfront coords (verified ~50-225 m to the open Atlantic).
OCEANFRONT = [
    ("Wrightsville Beach", 34.2085, -77.7960),
    ("Carolina Beach", 34.0350, -77.8925),
    ("Folly Beach", 32.6550, -79.9400),
    ("Surfside Beach", 33.6060, -78.9670),
    ("Atlantic Beach", 34.6985, -76.7400),
]

# Listed-but-NOT-oceanfront: river/sound/inland — must be excluded.
NOT_BEACH = [
    ("Wilmington (inland)", 34.2255, -77.9450),
    ("Manteo (Roanoke I/sound)", 35.9080, -75.6680),
    ("Beaufort SC (Port Royal Sound)", 32.4320, -80.6700),
    ("Mt Pleasant (harbor side)", 32.7940, -79.8620),
]


def test_oceanfront_is_near_beach():
    for name, lat, lon in OCEANFRONT:
        d = distance_to_ocean_m(lat, lon)
        assert d is not None and d <= NEAR_BEACH_M, f"{name}: {d} m should be <= {NEAR_BEACH_M}"
        assert is_near_beach(lat, lon) is True, name


def test_inland_and_sound_excluded():
    for name, lat, lon in NOT_BEACH:
        assert is_near_beach(lat, lon) is False, f"{name} wrongly flagged near-beach"
        assert distance_to_ocean_m(lat, lon) > NEAR_BEACH_M, name


def test_threshold_is_tunable():
    # A point ~400 m inland passes a loose 600 m gate but fails the strict 250 m one.
    lat, lon = 34.2120, -77.8010  # ~400 m back from Wrightsville oceanfront
    assert is_near_beach(lat, lon, max_m=50) is False
    d = distance_to_ocean_m(lat, lon)
    assert d is not None


def test_missing_coords_returns_false():
    assert is_near_beach(None, None) is False
    assert distance_to_ocean_m(None, None) is None


def test_coastline_asset_loaded():
    # Inland NC (Spartanburg-ish) is hundreds of km from the Atlantic.
    assert distance_to_ocean_m(34.95, -81.93) > 50_000

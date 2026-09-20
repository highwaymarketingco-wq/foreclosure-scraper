"""The Pickens acreage-as-value repair must clear exactly the corrupted rows.

parcel_cache once mapped Pickens market_value to CalcAcres. 2,030 leads carried an
acreage (0.59, 1.24, 6.59 ...) as their market value, and the rounded acreage as
assessed_value. The rule is scoped to Pickens SC and must not touch real values or
other counties' cheap-but-genuine land values.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from repair_pickens_acreage_as_value import acreage_as_value, plan_changes  # noqa: E402


def test_acreage_stored_as_value_is_caught():
    assert acreage_as_value("SC", "Pickens", 0.591124577422, 0.591124577422, 1.0)
    assert acreage_as_value("SC", "Pickens", 1.24492774496, 1.18, 1.0)      # CalcAcres vs deeded acres
    assert acreage_as_value("SC", "Pickens", 6.59038371361, 6.44, 7.0)


def test_fractions_of_an_acre_with_a_real_assessed_value_are_caught():
    # 0.24 "dollars" on a parcel whose real assessed value is $46,000
    assert acreage_as_value("SC", "Pickens", 0.24, None, 46000.0)


def test_a_plausible_low_price_not_near_the_acreage_is_kept():
    assert not acreage_as_value("SC", "Pickens", 500.0, 12.0, None)


def test_real_values_are_never_touched():
    assert not acreage_as_value("SC", "Pickens", 85000.0, 0.5, 46000.0)
    assert not acreage_as_value("SC", "Pickens", 1000.0, 1000.0, None)     # not tiny


def test_other_counties_and_missing_values_are_left_alone():
    assert not acreage_as_value("SC", "Spartanburg", 700.0, 0.89, None)    # genuinely cheap land
    assert not acreage_as_value("NC", "Pickens", 0.5, 0.5, None)           # wrong state
    assert not acreage_as_value("SC", "Pickens", None, 0.5, None)
    assert not acreage_as_value("SC", "Pickens", 0, 0.5, None)


def test_county_suffix_is_tolerated():
    assert acreage_as_value("SC", "Pickens County", 0.5, 0.5, 1.0)


def test_only_tiny_companion_values_are_cleared():
    assert plan_changes(0.59, 1.0, None) == {"market_value": True, "assessed_value": True, "tax_value": False}
    assert plan_changes(0.24, 46000.0, None) == {"market_value": True, "assessed_value": False, "tax_value": False}
    assert plan_changes(0.5, 1.0, 2.0)["tax_value"] is True

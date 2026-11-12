"""A regex fragment is not a parcel identifier.

MEASURED on the live 115,942-row board, 2026-09-13:
    1,053 rows carried a parcel_id that _normalize_parcel already REJECTS (no digit)
      205 more were shorter than 4 characters
    worst: 'e' 336 · 'es' 171 · 'g' 105 · 'I' 94 · 'ey' 69 · '-' 51 · 'of' 19 · 'in' 14
    1,184 of the 1,258 came from counties_generic.liensnc

Same class as the PIN_RE bug that produced 'ehurst' from "Pinehurst" and 'number' from
"PIN number:". The dedupe guards already refuse to MERGE on a digitless parcel, so these
were not fusing rows -- which is exactly why they survived. What they did do:

  * waste a parcel-cache lookup per row that can never hit
  * break any per-county tool that probes with "the first parcel in this county"

That second one is how they were found. BT appraisal-card tax-year discovery probed Moore
with its first eligible parcel -- the value 'es' -- got a stub for every candidate year,
and concluded Moore had no appraisal cards at all. Moore parcel 00049504 returns a
20,396-byte PDF. One junk value wrote off a whole county's worth of sqft and sale data.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "clear_junk", Path(__file__).resolve().parent.parent / "scripts" / "clear_junk_parcel_ids.py")
cj = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cj)


@pytest.mark.parametrize("v", ["e", "es", "g", "I", "ey", "-", "E", "ES", "k", "s",
                               "of", "in", "the", "ehurst", "number", "eville"])
def test_the_real_junk_values_are_rejected(v):
    """Every one of these was on the live board as a parcel_id."""
    assert cj.is_junk(v) is True


@pytest.mark.parametrize("v", [
    "855215723667", "00049504", "0668-00-82-0841", "4192-00-96-2106",
    "226-00-04-016", "7-17-02-041.00", "09-3414", "A105-32", "1234",
])
def test_real_parcel_identifiers_survive(v):
    """Including the awkward ones: short dashed ids and letter-prefixed ids are real."""
    assert cj.is_junk(v) is False


def test_absent_is_not_junk():
    """A row with no parcel is honest. Clearing must only target VALUES that lie."""
    assert cj.is_junk(None) is False
    assert cj.is_junk("") is False
    assert cj.is_junk("   ") is False


def test_a_digitless_value_is_junk_however_long():
    """'Pinehurst' is not a parcel no matter how many characters it has."""
    assert cj.is_junk("PINEHURST") is True
    assert cj.is_junk("NORTHCAROLINA") is True


def test_a_short_but_numeric_value_is_kept():
    """Some counties really do use short numeric ids; the floor is 4 characters."""
    assert cj.is_junk("1234") is False
    assert cj.is_junk("123") is True

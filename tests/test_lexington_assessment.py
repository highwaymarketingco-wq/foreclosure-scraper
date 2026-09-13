"""Lexington's assessment ratio as a free owner-occupancy signal.

SC assesses an owner-occupied legal residence at 4% of fair market value and
everything else at 6%. So assessment/fmv separates a homeowner from a landlord,
second-home owner or LLC WITHOUT needing a mailing address — which matters because
Lexington has no free parcel layer (its maps host is a bare Apache default page and
SCDOT's statewide parcel service is token-walled).

Verified live 2026-09-13: fmv 250,000 / assessed 15,000 = 6.0% for A & K
ENTERPRISES LLC.
"""
from foreclosure_scraper.enrichment_lexington_assessment import (
    _tms,
    classify_ratio,
)


def test_six_percent_is_not_owner_occupied():
    assert classify_ratio(250000, 15000) == (6.0, False)


def test_four_percent_is_owner_occupied():
    assert classify_ratio(200000, 8000) == (4.0, True)


def test_other_ratios_are_left_undecided():
    # Agricultural and manufacturing classes sit at other ratios. Forcing them into
    # one of the two buckets would invent an occupancy claim.
    ratio, occupied = classify_ratio(100000, 3000)
    assert ratio == 3.0
    assert occupied is None


def test_missing_or_zero_values_decide_nothing():
    for fmv, assessed in ((0, 0), (None, None), (250000, 0), (0, 15000), ("x", "y")):
        assert classify_ratio(fmv, assessed) == (None, None)


def test_tms_must_be_undashed_and_long_enough():
    # The API returns [] for the dashed form — a silent empty that looks like a
    # miss rather than a format error.
    assert _tms("004121-01-024") == "00412101024"


def test_short_account_ids_are_not_tms():
    # Some Lexington rows carry an account number, not a TMS. Those are filtered
    # out rather than counted as misses.
    assert _tms("26811") is None
    assert _tms("") is None

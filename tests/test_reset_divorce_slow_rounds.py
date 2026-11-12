"""reset_divorce_slow_rounds must clear only person-owned NEGATIVE stamps from small,
pre-fix rounds. Positives, companies, healthy rounds and post-fix rounds stay."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from reset_divorce_slow_rounds import is_suspect, suspect_rounds  # noqa: E402

SMALL = "2026-09-18T03:25:41.109530+00:00"     # a 51-lead overnight round
HEALTHY = "2026-09-18T08:17:00.000000+00:00"   # a 1,378-lead round
POSTFIX = "2026-09-18T17:35:00.000000+00:00"   # after ed15f11 (16:16 UTC)
OLD = "2026-08-24T10:00:00.000000+00:00"       # before the window


def _rounds():
    return suspect_rounds({SMALL: 51, HEALTHY: 1378, POSTFIX: 60, OLD: 40})


def _stamp(fetched_at, case_count=0):
    return {"fetched_at": fetched_at, "case_count": case_count}


def test_only_small_pre_fix_rounds_in_window_are_suspect():
    assert _rounds() == {SMALL}


def test_person_owned_negative_in_a_small_round_is_reset():
    assert is_suspect("SC", "Cherokee", "BISHOP CHERRYL", _stamp(SMALL), _rounds()) is True


def test_positives_are_never_reset():
    assert is_suspect("SC", "Cherokee", "BISHOP CHERRYL", _stamp(SMALL, case_count=2), _rounds()) is False


def test_companies_are_left_alone():
    assert is_suspect("SC", "Cherokee", "ACME HOLDINGS LLC", _stamp(SMALL), _rounds()) is False


def test_healthy_postfix_and_old_rounds_are_left_alone():
    for ts in (HEALTHY, POSTFIX, OLD):
        assert is_suspect("SC", "Cherokee", "BISHOP CHERRYL", _stamp(ts), _rounds()) is False


def test_out_of_scope_and_unstamped_leads_are_left_alone():
    assert is_suspect("NC", "Wake", "BISHOP CHERRYL", _stamp(SMALL), _rounds()) is False
    assert is_suspect("SC", "Cherokee", "BISHOP CHERRYL", None, _rounds()) is False
    assert is_suspect("SC", "Cherokee", "", _stamp(SMALL), _rounds()) is False

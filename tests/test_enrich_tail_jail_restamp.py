"""run_enrich_tail re-reads the county-jail stamps before verification and scoring.

enrich_jail_bookings runs before the dot_ocr checkpoint, so a resume from that checkpoint
(resume_from_checkpoint --enrich-only / --run) skipped it and kept stamps an old rule had ended
(a respelled name still on the roster; a 60+ day stay that may be a prison transfer). HANDOFF item 79.
"""
from __future__ import annotations

import inspect

from foreclosure_scraper import main as M


def _tail_src() -> str:
    return inspect.getsource(M.run_enrich_tail)


def test_tail_calls_the_jail_stamp():
    assert "enrich_jail_bookings" in _tail_src()


_IMPORT = "from .enrichment_jail_bookings import enrich_jail_bookings"


def test_jail_stamp_runs_before_verification_apply_and_scoring():
    src = _tail_src()
    i_jail = src.index(_IMPORT)
    assert i_jail < src.index("apply_verification")
    assert i_jail < src.index("score_board")


def test_a_failing_jail_stamp_is_logged_not_raised():
    src = _tail_src()
    i = src.index(_IMPORT)
    window = src[i - 200: i + 700]
    assert "except Exception" in window and "jail_bookings_tail.failed" in window


def test_stats_key_is_distinct_from_the_pre_checkpoint_one():
    assert 'enrichment_stats["jail_bookings_tail"]' in _tail_src()

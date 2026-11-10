"""Tests for scripts/triage_zero_row_sources.py's board-aware classification.

2026-11-10 fix under test: PIPELINE used to print "but board has none" for every
in-footprint hit WITHOUT reading the board at all -- pure unverified prose. Caught
live on national.bid4assets (board already had 25 rows) and counties_sc.
cherokee_delinquent_tax (board already had 530). board_counts() now streams the
real board parts and classify() uses that real count to pick PIPELINE (board
confirmed 0 -- a real gap) vs. the new STALE bucket (board already has rows --
not a bug, just due for a re-scrape), falling back to the old wording only when
the board genuinely could not be read, rather than ever asserting a count it
never checked.

Uses synthetic gzip part files under tmp_path, never the real board.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import triage_zero_row_sources as T  # noqa: E402


def _write_part(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt") as f:
        json.dump(rows, f)


# ---- board_counts() ---------------------------------------------------------

def test_board_counts_counts_rows_per_slug_across_parts(tmp_path, monkeypatch):
    part0 = tmp_path / "listings_part_000.json.gz"
    part1 = tmp_path / "listings_part_001.json.gz"
    _write_part(part0, [
        {"source": "national.bid4assets", "sale_date": "2026-10-07T00:00:00"},
        {"source": "national.bid4assets", "sale_date": "2026-11-03T00:00:00"},
        {"source": "other.source", "sale_date": "2026-11-09T00:00:00"},
    ])
    _write_part(part1, [
        {"source": "national.bid4assets", "sale_date": "2026-10-19T00:00:00"},
        {"source": "counties_sc.cherokee_delinquent_tax", "sale_date": None},
    ])
    monkeypatch.setattr(T, "_board_parts", lambda: [str(part0), str(part1)])

    out = T.board_counts(["national.bid4assets", "counties_sc.cherokee_delinquent_tax",
                           "national.never_seen"])

    assert out["national.bid4assets"]["count"] == 3
    assert out["national.bid4assets"]["max_sale_date"] == "2026-11-03T00:00:00"
    assert out["counties_sc.cherokee_delinquent_tax"]["count"] == 1
    assert out["counties_sc.cherokee_delinquent_tax"]["max_sale_date"] is None
    # A slug truly absent from every part is a real, checked zero.
    assert out["national.never_seen"]["count"] == 0


def test_board_counts_skips_an_unreadable_part_without_raising(tmp_path, monkeypatch):
    good = tmp_path / "listings_part_000.json.gz"
    _write_part(good, [{"source": "x", "sale_date": None}])
    corrupt = tmp_path / "listings_part_001.json.gz"
    corrupt.write_bytes(b"not actually gzip")
    monkeypatch.setattr(T, "_board_parts", lambda: [str(good), str(corrupt)])

    out = T.board_counts(["x"])

    assert out["x"]["count"] == 1


# ---- classify() --------------------------------------------------------------

def _always_in_scope(_county, _state):
    return True


def test_classify_marks_stale_when_board_already_has_rows():
    rows = [{"county": "Haywood County", "state": "NC"}]
    bucket, detail, _top = T.classify(
        rows, None, _always_in_scope, set(),
        board={"count": 25, "max_sale_date": "2026-11-03T00:00:00"},
    )
    assert bucket == "STALE"
    assert "ALREADY HAS 25" in detail
    assert "not a bug" in detail


def test_classify_marks_pipeline_when_board_confirmed_zero():
    rows = [{"county": "Haywood County", "state": "NC"}]
    bucket, detail, _top = T.classify(
        rows, None, _always_in_scope, set(),
        board={"count": 0, "max_sale_date": None},
    )
    assert bucket == "PIPELINE"
    assert "confirmed 0" in detail


def test_classify_pipeline_says_board_not_checked_when_board_arg_omitted():
    """The board read itself failed upstream (board=None) -- must never silently
    claim a verified zero it never checked."""
    rows = [{"county": "Haywood County", "state": "NC"}]
    bucket, detail, _top = T.classify(rows, None, _always_in_scope, set(), board=None)
    assert bucket == "PIPELINE"
    assert "not checked" in detail
    assert "board has none" not in detail  # the exact unverified phrase this fix removed


def test_classify_broken_still_broken_but_annotates_existing_board_rows():
    bucket, detail, _top = T.classify(
        None, "TypeError: boom", _always_in_scope, set(),
        board={"count": 530, "max_sale_date": None},
    )
    assert bucket == "BROKEN"
    assert "530" in detail


def test_classify_policy_unaffected_by_board_info():
    rows = [{"county": "Nowhere", "state": "ZZ"}]
    bucket, detail, _top = T.classify(
        rows, None, lambda c, s: False, set(),
        board={"count": 999, "max_sale_date": None},
    )
    assert bucket == "POLICY"
    assert "999" not in detail

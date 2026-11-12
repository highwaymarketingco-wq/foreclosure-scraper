"""iter_board_rows must equal json.load, including across chunk boundaries."""
from __future__ import annotations

import gzip
import json

from foreclosure_scraper import board_stream
from foreclosure_scraper.board_stream import iter_board_rows


def _write(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(rows, f)


def _rows(n):
    return [{"i": i, "owner_name": f"Owner {i} é", "raw": {"k": "x" * (i % 50), "n": {"a": [i, i + 1]}}}
            for i in range(n)]


def test_matches_json_load(tmp_path):
    p = tmp_path / "b.json.gz"; rows = _rows(500); _write(p, rows)
    assert list(iter_board_rows(p)) == rows


def test_objects_spanning_tiny_chunks_are_reassembled(tmp_path, monkeypatch):
    monkeypatch.setattr(board_stream, "_CHUNK", 37)     # forces splits mid-object and mid-string
    p = tmp_path / "b.json.gz"; rows = _rows(120); _write(p, rows)
    assert list(iter_board_rows(p)) == rows


def test_empty_and_single_row(tmp_path):
    p = tmp_path / "e.json.gz"; _write(p, []); assert list(iter_board_rows(p)) == []
    _write(p, [{"a": 1}]); assert list(iter_board_rows(p)) == [{"a": 1}]


def test_preserves_order_for_positional_comparison(tmp_path):
    p = tmp_path / "b.json.gz"; rows = _rows(50); _write(p, rows)
    assert [r["i"] for r in iter_board_rows(p)] == list(range(50))

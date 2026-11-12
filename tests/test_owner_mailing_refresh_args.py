"""owner_mailing_refresh: county filter parsing and the snapshot memory guard."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import owner_mailing_refresh as m  # noqa: E402


def test_parse_counties():
    assert m.parse_counties("SC:Union, NC:Burke ,,SC:Laurens") == {"SC:Union", "NC:Burke", "SC:Laurens"}
    assert m.parse_counties("") == set() and m.parse_counties(None) == set()


def test_small_snapshot_is_used_as_is(tmp_path):
    p = tmp_path / "listings.json"
    p.write_text("[]")
    assert m.snapshot_for_scoring(p) == p


def test_huge_snapshot_is_never_parsed(tmp_path, monkeypatch):
    p = tmp_path / "listings.json"
    p.write_text("[]")
    monkeypatch.setattr(m, "_MAX_SNAPSHOT_BYTES", 1)          # pretend the file is "too big"
    out = m.snapshot_for_scoring(p)
    assert out != p and not out.exists()                       # score_board treats a missing file as no index


def test_missing_snapshot_passes_through(tmp_path):
    p = tmp_path / "listings.json"
    assert m.snapshot_for_scoring(p) == p

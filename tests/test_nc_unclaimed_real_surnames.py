"""national.nc_unclaimed searches real board surnames, not a hardcoded stub list.

FOUND 2026-10-13 (source-completeness audit): this scraper searched the same 10
hardcoded surnames ("Smith", "Johnson", ...) on every run regardless of which
owners/defendants are actually on the board -- the same stub-data bug already
fixed in the sibling national.people_search on 2026-10-12, never applied here.
The nccash.gov API searches by `lastName` only, so the fix pulls real surnames
off the board's own owner_name/defendant fields via the same bounded
board_stream.iter_board_rows() people_search.py uses.
"""
from __future__ import annotations

import json

from foreclosure_scraper.scrapers.national import nc_unclaimed as mod


def test_surname_of_handles_last_comma_first_convention():
    assert mod._surname_of("SMITH, A H") == "SMITH"
    assert mod._surname_of("Smith, John Robert") == "Smith"


def test_surname_of_handles_first_last_convention():
    assert mod._surname_of("John Smith") == "Smith"
    assert mod._surname_of("Mary Jane Watson") == "Watson"


def test_surname_of_rejects_entities():
    assert mod._surname_of("SMITH & LOWE DEVELOPMENT INC") is None
    assert mod._surname_of("ABC HOMEOWNERS ASSOCIATION") is None
    assert mod._surname_of("ESTATE OF JOHN DOE") is None


def test_surname_of_rejects_blank_and_too_short():
    assert mod._surname_of("") is None
    assert mod._surname_of(None) is None
    assert mod._surname_of("A,") is None


def test_surname_of_strips_punctuation_but_keeps_hyphen_and_apostrophe():
    assert mod._surname_of("O'Brien, Patrick") == "O'Brien"
    assert mod._surname_of("Smith-Jones, Carol") == "Smith-Jones"


def _row(owner=None, defendant=None):
    return {"owner_name": owner, "defendant": defendant, "raw": {}}


def test_candidate_surnames_pulls_real_board_names(monkeypatch, tmp_path):
    rows = [
        _row(owner="SMITH, ALBERT DAVID"),
        _row(owner="JONES, MARY"),
        _row(defendant="WILLIAMS, ROBERT"),
        _row(owner="ABC CORP INC"),  # entity -- excluded
    ]
    monkeypatch.setattr("foreclosure_scraper.board_stream.iter_board_rows", lambda: iter(rows))
    ledger_path = tmp_path / "nc_unclaimed_searched.json"
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", ledger_path)

    out = mod._candidate_surnames(limit=10)
    assert out == ["SMITH", "JONES", "WILLIAMS"]


def test_candidate_surnames_dedupes_and_respects_limit(monkeypatch, tmp_path):
    rows = [_row(owner="SMITH, A"), _row(owner="SMITH, B"), _row(owner="JONES, C")]
    monkeypatch.setattr("foreclosure_scraper.board_stream.iter_board_rows", lambda: iter(rows))
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", tmp_path / "ledger.json")

    out = mod._candidate_surnames(limit=10)
    assert out == ["SMITH", "JONES"]  # second SMITH deduped

    out2 = mod._candidate_surnames(limit=1)
    assert out2 == ["SMITH"]


def test_candidate_surnames_skips_already_searched(monkeypatch, tmp_path):
    rows = [_row(owner="SMITH, A"), _row(owner="JONES, C")]
    monkeypatch.setattr("foreclosure_scraper.board_stream.iter_board_rows", lambda: iter(rows))
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({"surnames": {"smith": {"checked_at": "2026-01-01"}}}))
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", ledger_path)

    out = mod._candidate_surnames(limit=10)
    assert out == ["JONES"]  # smith already in the ledger, skipped


def test_candidate_surnames_falls_back_when_board_empty(monkeypatch, tmp_path):
    monkeypatch.setattr("foreclosure_scraper.board_stream.iter_board_rows", lambda: iter([]))
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", tmp_path / "ledger.json")

    out = mod._candidate_surnames(limit=5)
    assert out  # never a hard empty -- falls back so the real search path still runs
    assert len(out) <= 5


def test_candidate_surnames_scan_error_does_not_raise(monkeypatch, tmp_path):
    def _boom():
        raise RuntimeError("board read failed")
        yield  # pragma: no cover

    monkeypatch.setattr("foreclosure_scraper.board_stream.iter_board_rows", _boom)
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", tmp_path / "ledger.json")

    out = mod._candidate_surnames(limit=5)
    assert out  # falls back cleanly, doesn't propagate the exception


def test_searched_ledger_round_trips(monkeypatch, tmp_path):
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(mod, "_SEARCHED_LEDGER_PATH", ledger_path)

    ledger = mod._load_searched_ledger()
    assert ledger == {"schema": 1, "kind": "nc_unclaimed_searched", "surnames": {}}

    ledger["surnames"]["smith"] = {"checked_at": "2026-10-13", "found": 2}
    mod._save_searched_ledger(ledger)

    reloaded = mod._load_searched_ledger()
    assert reloaded["surnames"]["smith"]["found"] == 2
    assert "generated_at" in reloaded

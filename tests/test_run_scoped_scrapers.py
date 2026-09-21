"""Offline tests for scripts/run_scoped_scrapers.py.

No network, and the live board is never read or written: every board in here is a tmp dir
(write_artifact only enforces the board lock for the live docs dir) or a plain list of dicts.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper.models import Listing, ListingType

_SPEC = importlib.util.spec_from_file_location(
    "run_scoped_scrapers", Path(__file__).resolve().parent.parent / "scripts" / "run_scoped_scrapers.py")
rss = importlib.util.module_from_spec(_SPEC)
sys.modules["run_scoped_scrapers"] = rss
_SPEC.loader.exec_module(rss)  # type: ignore[union-attr]


def _li(**kw) -> Listing:
    base = dict(source="counties_nc.test_src", source_url="https://x/" + str(kw.get("parcel_id") or kw.get("street_address") or "u"),
                listing_type=ListingType.TAX_LIEN, state="NC", county="Rutherford")
    base.update(kw)
    return Listing(**base)


NOW = datetime.utcnow()


# --------------------------------------------------------------------------- #
# filters: the orchestrator's own functions, with reasons
# --------------------------------------------------------------------------- #

def test_dateless_row_is_dropped_unless_whitelisted_and_reason_names_it():
    dateless = _li(source="counties_nc.not_whitelisted_yet", parcel_id="100")
    kept, drops = rss.filter_like_orchestrator([dateless], 120)
    assert kept == []
    assert list(drops["active"]) == ["dateless and slug not in DATELESS_OK_SOURCES"]

    ok = _li(source="counties_nc.rutherford_wildfire_tax", parcel_id="101")   # whitelisted in main
    kept, _ = rss.filter_like_orchestrator([ok], 120)
    assert kept == [ok]


def test_extra_dateless_ok_is_scoped_to_the_call_and_restored():
    from foreclosure_scraper import main as M
    slug = "public_notices.some_future_source"       # deliberately not in main's list, now or later
    li = _li(source=slug, listing_type=ListingType.PROBATE_NOTICE, county="Cleveland", defendant="Test Person")
    assert slug not in M.DATELESS_OK_SOURCES
    kept, drops = rss.filter_like_orchestrator([li], 120)
    assert kept == [] and drops["active"]
    kept, _ = rss.filter_like_orchestrator([li], 120, extra_dateless=[slug])
    assert kept == [li]
    assert slug not in M.DATELESS_OK_SOURCES         # restored


def test_flip_outside_footprint_is_dropped_with_a_reason_but_a_tax_lien_there_is_kept():
    flip = _li(source="counties_nc.x", listing_type=ListingType.FORECLOSURE_SALE, county="Wake",
               street_address="1 A St", sale_date=NOW + timedelta(days=10))
    lien = _li(source="counties_nc.rutherford_wildfire_tax", county="Wake", parcel_id="9")
    kept, drops = rss.filter_like_orchestrator([flip, lien], 120)
    assert kept == [lien]                       # distressed types are in scope in every NC/SC county
    assert "flip outside the 18-county footprint" in next(iter(drops["scope"]))


def test_terminal_status_and_past_sale_are_dropped_with_reasons():
    sold = _li(source="counties_nc.x", listing_type=ListingType.TAX_SALE, parcel_id="1",
               sale_date=NOW - timedelta(days=3), auction_status="sold")
    old = _li(source="counties_nc.x", listing_type=ListingType.TAX_SALE, parcel_id="2",
              sale_date=NOW - timedelta(days=90))
    live = _li(source="counties_nc.x", listing_type=ListingType.TAX_SALE, parcel_id="3",
               sale_date=NOW + timedelta(days=9))
    kept, drops = rss.filter_like_orchestrator([sold, old, live], 120)
    assert kept == [live]
    reasons = list(drops["active"])
    assert any(r.startswith("terminal status 'sold'") for r in reasons)
    assert any(r.startswith("sale 90d ago") for r in reasons)


def test_the_decision_is_mains_own_function_not_a_copy(monkeypatch):
    """If the runner copied the scope logic this monkeypatch would change nothing."""
    from foreclosure_scraper import main as M
    li = _li(source="counties_nc.rutherford_wildfire_tax", parcel_id="5")
    assert rss.filter_like_orchestrator([li], 120)[0] == [li]
    monkeypatch.setattr(M, "_in_scope", lambda x: False)
    kept, drops = rss.filter_like_orchestrator([li], 120)
    assert kept == [] and sum(drops["scope"].values()) == 1
    monkeypatch.undo()
    monkeypatch.setattr(M, "_active_only", lambda x, h: False)
    assert rss.filter_like_orchestrator([li], 120)[0] == []


def test_in_batch_duplicates_are_merged_by_the_shared_dedupe():
    a = _li(source="counties_nc.rutherford_wildfire_tax", parcel_id="777", judgment_amount=10.0)
    b = _li(source="counties_nc.rutherford_tax", parcel_id="777", judgment_amount=10.0)
    kept, drops = rss.filter_like_orchestrator([a, b], 120)
    assert len(kept) == 1
    assert sum(drops["dedupe"].values()) == 1


# --------------------------------------------------------------------------- #
# new vs already on the board: one streaming pass
# --------------------------------------------------------------------------- #

def _row(**kw) -> dict:
    return _li(**kw).model_dump(mode="json")


def test_board_overlap_matches_on_parcel_address_and_case_and_reads_the_stream_once():
    cands = [
        _li(parcel_id="1215-531", source="counties_nc.new"),                                  # same parcel as row 0
        _li(street_address="12 Oak Street", zip_code="28043", source="counties_nc.new"),      # same address as row 1
        _li(parcel_id="999999", source="counties_nc.new"),                                    # nowhere
        _li(case_number="26SP000130", street_address="2831 Cove Road", source="counties_nc.new"),
    ]
    board = [
        _row(parcel_id="1215531", source="counties_nc.rutherford_tax"),
        _row(street_address="12 Oak St", zip_code="28043", source="reo.old"),
        _row(case_number="26SP000130", street_address="2831 Cove Rd", source="law_firms.kania",
             listing_type=ListingType.FORECLOSURE_SALE),
    ]
    consumed = {"n": 0}

    def stream():
        for r in board:
            consumed["n"] += 1
            yield r
    hit = rss.board_overlap(cands, stream())
    assert consumed["n"] == 3
    assert sorted(hit) == [0, 1, 3]
    assert hit[0] == "counties_nc.rutherford_tax" and hit[1] == "reo.old"


# --------------------------------------------------------------------------- #
# apply_rows: additive, asserted, written to a scratch board only
# --------------------------------------------------------------------------- #

def _seed_board(docs: Path, rows: list[Listing]) -> list[Listing]:
    from foreclosure_scraper.web_artifact import load_board, write_artifact
    write_artifact(rows, {"by_source": {}}, docs_dir=docs)
    return load_board(docs)


def test_apply_rows_adds_only_new_rows_and_never_touches_existing_ones(tmp_path):
    docs = tmp_path / "docs"
    seeded = _seed_board(docs, [
        _li(parcel_id="111", source="counties_nc.rutherford_tax", judgment_amount=5.0),
        _li(parcel_id="222", source="counties_nc.rutherford_tax", judgment_amount=6.0),
    ])
    before = [li.model_dump_json() for li in seeded]
    new = [
        _li(parcel_id="222", source="counties_nc.rutherford_wildfire_tax", judgment_amount=99.0),  # on board
        _li(parcel_id="333", source="counties_nc.rutherford_wildfire_tax", judgment_amount=7.0),
        _li(parcel_id="444", source="counties_nc.rutherford_wildfire_tax", judgment_amount=8.0),
    ]
    stats = rss.apply_rows(seeded, new, docs_dir=docs)
    assert (stats["existing"], stats["candidates"], stats["added"], stats["already_on_board"]) == (2, 3, 2, 1)
    assert stats["written"] is True and stats["total_after"] == 4
    assert stats["added_by_source"] == {"counties_nc.rutherford_wildfire_tax": 2}
    assert stats["skipped_by_source"] == {"counties_nc.rutherford_wildfire_tax": 1}
    assert [li.model_dump_json() for li in seeded] == before        # existing rows byte-identical
    from foreclosure_scraper.web_artifact import load_board
    again = load_board(docs)
    assert sorted(li.parcel_id for li in again) == ["111", "222", "333", "444"]
    assert next(li for li in again if li.parcel_id == "222").judgment_amount == 6.0   # not overwritten


def test_apply_rows_dry_computation_writes_nothing(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seeded = _seed_board(docs, [_li(parcel_id="1", source="counties_nc.a")])
    import foreclosure_scraper.web_artifact as wa
    monkeypatch.setattr(wa, "write_artifact",
                        lambda *a, **k: pytest.fail("write_artifact must not be called with write=False"))
    stats = rss.apply_rows(seeded, [_li(parcel_id="2", source="counties_nc.b")], docs_dir=docs, write=False)
    assert stats["added"] == 1 and stats["written"] is False


def test_apply_rows_refuses_if_anything_modifies_an_existing_row(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seeded = _seed_board(docs, [_li(parcel_id="1", source="counties_nc.a", judgment_amount=1.0)])
    import foreclosure_scraper.enrichment_tax_owed as eto

    def evil(listings):          # a buggy enricher that reaches an existing row
        seeded[0].judgment_amount = 123456.0
        return {}
    monkeypatch.setattr(eto, "enrich_tax_owed", evil)
    with pytest.raises(AssertionError, match="modified 1 existing row"):
        rss.apply_rows(seeded, [_li(parcel_id="2", source="counties_nc.b")], docs_dir=docs, write=False)


def test_apply_rows_with_nothing_new_writes_nothing(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    seeded = _seed_board(docs, [_li(parcel_id="1", source="counties_nc.a")])
    import foreclosure_scraper.web_artifact as wa
    monkeypatch.setattr(wa, "write_artifact", lambda *a, **k: pytest.fail("nothing to write"))
    stats = rss.apply_rows(seeded, [_li(parcel_id="1", source="counties_nc.b")], docs_dir=docs)
    assert stats["added"] == 0 and stats["already_on_board"] == 1 and stats["written"] is False


def test_new_rows_get_offline_valuation_and_landed_by_stamp(tmp_path):
    docs = tmp_path / "docs"
    seeded = _seed_board(docs, [_li(parcel_id="1", source="counties_nc.a")])
    new = [_li(parcel_id="2", source="counties_nc.rutherford_wildfire_tax", judgment_amount=50.0,
               raw={"rutherford_wildfire": {"amount_owed": 50.0}})]
    rss.apply_rows(seeded, new, docs_dir=docs, write=False, score=False)
    assert new[0].raw["landed_by"] == "scripts/run_scoped_scrapers.py"
    assert "calc" in new[0].raw and "grade" in new[0].raw


# --------------------------------------------------------------------------- #
# running scrapers / CLI
# --------------------------------------------------------------------------- #

class _FakeScraper:
    def __init__(self, slug, rows, limit_aware=False, outcome="OK"):
        self.slug, self._rows, self.timeout_s, self.last_outcome, self.last_reason = slug, rows, 100.0, outcome, ""
        self.limit_seen = None
        if limit_aware:
            self.apply_row_limit = self._alim

    def _alim(self, n):
        self.limit_seen = n

    async def safe_run(self):
        return list(self._rows)


def _patch_registry(monkeypatch, scrapers):
    import foreclosure_scraper.scrapers._registry as reg
    monkeypatch.setattr(reg, "all_scrapers", lambda: scrapers)


def test_unknown_slug_is_loud(monkeypatch):
    _patch_registry(monkeypatch, [_FakeScraper("a.b", [])])
    import asyncio
    with pytest.raises(SystemExit, match="match no registered scraper"):
        asyncio.run(rss.run_scrapers(["a.b", "nope.nope"], 10, None))


def test_limit_truncates_and_limit_aware_scrapers_are_told(monkeypatch):
    rows = [_li(parcel_id=str(i), source="a.b") for i in range(9)]
    s1, s2 = _FakeScraper("a.b", rows), _FakeScraper("c.d", rows, limit_aware=True)
    _patch_registry(monkeypatch, [s1, s2])
    import asyncio
    res = asyncio.run(rss.run_scrapers(["a.b", "c.d"], 4, 30.0))
    assert [len(r[3]) for r in res] == [4, 4]
    assert [r[4] for r in res] == [9, 9]                      # the pre-cap count is kept
    assert s2.limit_seen == 4 and s1.timeout_s == 30.0        # timeout only ever lowered


def test_env_flag_is_set_before_scrapers_are_built(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_INCLUDE_GREENVILLE", raising=False)
    out = rss._apply_env(["FORECLOSURE_INCLUDE_GREENVILLE=1"])
    import os
    assert os.environ["FORECLOSURE_INCLUDE_GREENVILLE"] == "1" and out == {"FORECLOSURE_INCLUDE_GREENVILLE": "1"}
    with pytest.raises(SystemExit):
        rss._apply_env(["BADPAIR"])
    monkeypatch.delenv("FORECLOSURE_INCLUDE_GREENVILLE")


def test_slugs_file_ignores_comments_and_duplicates(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("a.b  # first\n\n# nothing\nc.d\na.b\n")
    ns = rss._parse_args(["--slugs-file", str(f)])
    assert rss._read_slugs(ns) == ["a.b", "c.d"]
    assert rss._parse_args(["--slugs", "x.y"]).limit == rss.DEFAULT_LIMIT == 200


def test_default_run_is_a_dry_run_and_never_writes_or_locks(monkeypatch, capsys, tmp_path):
    rows = [_li(source="counties_nc.rutherford_wildfire_tax", parcel_id=str(i), county="Rutherford") for i in range(3)]
    rows.append(_li(source="counties_nc.rutherford_wildfire_tax", parcel_id="w", county="Rutherford",
                    listing_type=ListingType.FORECLOSURE_SALE, sale_date=NOW - timedelta(days=200)))
    _patch_registry(monkeypatch, [_FakeScraper("counties_nc.rutherford_wildfire_tax", rows)])
    import foreclosure_scraper.web_artifact as wa
    monkeypatch.setattr(wa, "write_artifact", lambda *a, **k: pytest.fail("dry run wrote the board"))
    monkeypatch.setattr(wa, "board_lock", lambda *a, **k: pytest.fail("dry run took the board lock"))
    monkeypatch.setattr(wa, "load_board", lambda *a, **k: pytest.fail("dry run called load_board"))
    out = tmp_path / "kept.json"
    rc = rss.main(["--slugs", "counties_nc.rutherford_wildfire_tax", "--no-board", "--save-json", str(out)])
    text = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN: nothing was written" in text
    assert "kept after filters 3" in text
    assert "sale 200d ago" in text                            # the reason a row was dropped is printed
    assert len(json.loads(out.read_text())) == 3


def test_apply_from_saved_json_uses_lock_load_board_and_apply_rows(monkeypatch, tmp_path):
    kept = [_li(source="counties_nc.rutherford_wildfire_tax", parcel_id="55")]
    f = tmp_path / "kept.json"
    f.write_text(json.dumps([li.model_dump(mode="json") for li in kept], default=str))
    calls = []
    import foreclosure_scraper.web_artifact as wa
    from contextlib import contextmanager

    @contextmanager
    def fake_lock(*a, **k):
        calls.append("lock")
        yield
    monkeypatch.setattr(wa, "board_lock", fake_lock)
    monkeypatch.setattr(wa, "load_board", lambda docs: calls.append("load") or [])
    monkeypatch.setattr(rss, "apply_rows", lambda rows, new, **k: calls.append(f"apply:{len(new)}") or {"added": len(new)})
    rc = rss.main(["--load-json", str(f), "--no-board", "--apply", "--docs", str(tmp_path)])
    assert rc == 0 and calls == ["lock", "load", "apply:1"]

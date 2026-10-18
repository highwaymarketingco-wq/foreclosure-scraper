"""scripts/backfill_deed_ref_bound.py: classification and repair logic for both row shapes
(top80-fill-deed-ref-bound), on synthetic fixtures. No real board, no real network -- gis_fill's
live lookup is monkeypatched, and board_lock/load_board/write_artifact are replaced with
recorders/fakes that fail the test if a dry run reaches them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_deed_ref_bound as bb  # noqa: E402

from foreclosure_scraper import gis_fill as G  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402


def _listing(**kw) -> Listing:
    base = dict(source="counties_nc.nc_ecourts_lis_pendens", source_url="https://example/1",
                state="NC", county="Brunswick")
    base.update(kw)
    return Listing(**base)


# ---------------------------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------------------------

def test_classify_wrong_parno_when_parcel_id_present_and_block_names_other_parcel():
    li = _listing(parcel_id="102506498464",
                  raw={"county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal",
                                        "text": "L-121 OCEAN FOREST PLAT M/108", "parno": "2402C122",
                                        "fetched_at": "2026-10-15T13:56:02+00:00"}})
    assert bb.classify(li) == "wrong_parno"


def test_classify_stale_strip_when_parcel_id_null():
    li = _listing(parcel_id=None,
                  raw={"county_deed_ref": {"source": "nc_onemap", "parno": "1645782", "book": "AD",
                                           "page": "3365", "fetched_at": "2026-10-15T13:56:02+00:00"},
                       "gis_fill": {"checked_at": "2026-10-15T13:56:02+00:00", "source": "nc_onemap",
                                   "found": True, "deed": "found", "legal": "none", "value": "found",
                                   "acres": "found"}})
    assert bb.classify(li) == "stale_strip"


def test_classify_none_when_parno_matches_own_pin():
    li = _listing(parcel_id="102506498464",
                  raw={"county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal",
                                        "text": "whatever", "parno": "102506498464",
                                        "fetched_at": "2026-10-15T13:56:02+00:00"}})
    assert bb.classify(li) is None


def test_classify_none_for_other_source():
    """Only nc_onemap / *_parcel_layer-sourced blocks are this check's business, same as the
    audit's own Bound check."""
    li = _listing(parcel_id="123", raw={"county_legal": {"source": "some_register",
                                                          "text": "x", "parno": "999"}})
    assert bb.classify(li) is None


# ---------------------------------------------------------------------------------------------
# corrected_parno()
# ---------------------------------------------------------------------------------------------

def test_corrected_parno_deed_ref_when_book_page_agree():
    block = {"source": "nc_onemap", "parno": "1645782", "book": "AD", "page": "3365",
             "date": "2008-06-02", "fetched_at": "2026-10-15T13:56:02+00:00"}
    matched = {"parno": "0632599209", "deed": {"book": "AD", "page": "3365", "date": "2008-06-02"}}
    assert bb.corrected_parno(block, matched, "0632599209") == "0632599209"


def test_corrected_parno_legal_when_text_agrees():
    block = {"source": "nc_onemap", "kind": "assessor_short_legal", "text": "L-121 OCEAN FOREST PLAT M/108",
             "parno": "2402C122", "fetched_at": "2026-10-15T13:56:02+00:00"}
    matched = {"parno": "102506498464", "legal": "L-121 OCEAN FOREST PLAT M/108"}
    assert bb.corrected_parno(block, matched, "102506498464") == "102506498464"


def test_corrected_parno_none_when_not_found_live():
    block = {"source": "nc_onemap", "parno": "1645782", "book": "AD", "page": "3365"}
    assert bb.corrected_parno(block, None, "0632599209") is None


def test_corrected_parno_none_when_live_content_disagrees():
    """The re-fetch found a parcel matching the row's own pin, but its deed content differs from
    what is published -- this is NOT a confirmed pure parno-echo case, so it must be skipped
    rather than guessed at."""
    block = {"source": "nc_onemap", "parno": "1645782", "book": "AD", "page": "3365"}
    matched = {"parno": "0632599209", "deed": {"book": "ZZ", "page": "9999"}}
    assert bb.corrected_parno(block, matched, "0632599209") is None


def test_corrected_parno_none_when_new_parno_still_foreign():
    block = {"source": "nc_onemap", "parno": "1645782", "book": "AD", "page": "3365"}
    matched = {"parno": "9999999999", "deed": {"book": "AD", "page": "3365"}}
    assert bb.corrected_parno(block, matched, "0632599209") is None


# ---------------------------------------------------------------------------------------------
# main(): dry run never touches the board; a real run repairs both shapes and leaves what it
# cannot confirm untouched.
# ---------------------------------------------------------------------------------------------

class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fixtures():
    wrong = _listing(
        parcel_id="0632599209", county="Rutherford",
        raw={"county_deed_ref": {"source": "nc_onemap", "parno": "1645782", "book": "AD", "page": "3365",
                                 "date": "2008-06-02", "fetched_at": "2026-10-15T13:56:02+00:00"},
             "county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal", "text": "ROCKY BROAD RIVER",
                             "parno": "1645782", "fetched_at": "2026-10-15T13:56:02+00:00"}})
    unresolvable = _listing(
        parcel_id="4444444444", county="Rutherford",
        raw={"county_deed_ref": {"source": "nc_onemap", "parno": "1111111", "book": "XY", "page": "22",
                                 "fetched_at": "2026-10-15T13:56:02+00:00"}})
    stale = _listing(
        parcel_id=None, county="Henderson", source="national.courtlistener_bankruptcy",
        raw={"qa_flags": ["court_owner_mismatch"],
             "county_deed_ref": {"source": "nc_onemap", "parno": "9536617322", "book": "1364", "page": "688",
                                 "fetched_at": "2026-10-15T13:56:02+00:00"},
             "county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal", "text": "SNYDER S/D",
                             "parno": "9536617322", "fetched_at": "2026-10-15T13:56:02+00:00"},
             "gis_fill": {"checked_at": "2026-10-15T13:56:02+00:00", "source": "nc_onemap", "found": True,
                         "deed": "found", "legal": "found", "value": "found", "acres": "found"}})
    clean = _listing(parcel_id="102506498464", county="Brunswick",
                      raw={"county_legal": {"source": "nc_onemap", "kind": "assessor_short_legal",
                                            "text": "fine", "parno": "102506498464"}})
    return {"wrong": wrong, "unresolvable": unresolvable, "stale": stale, "clean": clean}


def _fake_fetch_nc(county, pins):
    """Only resolves Rutherford's 0632599209 (the confirmed-live sample); everything else is a
    miss, same as a layer that genuinely does not hold that parcel any more."""
    out = G.Got()
    if county == "Rutherford" and "0632599209" in pins:
        out["0632599209"] = {"parno": "0632599209", "deed": {"book": "AD", "page": "3365", "date": "2008-06-02"},
                             "legal": "ROCKY BROAD RIVER"}
    return out


def _fake_fetch_nc_like(county, pins):
    return G.Got()  # second pass never finds anything new in this fixture set


def test_dry_run_reports_without_writing(monkeypatch, fixtures):
    def boom(name):
        def f(*a, **k):
            raise AssertionError(f"{name} must not be called on a dry run")
        return f

    monkeypatch.setattr(bb, "board_lock", boom("board_lock"))
    monkeypatch.setattr(bb, "write_artifact", boom("write_artifact"))
    monkeypatch.setattr(bb, "load_board",
                        lambda *a, **k: [fixtures["wrong"], fixtures["unresolvable"], fixtures["stale"],
                                         fixtures["clean"]])
    monkeypatch.setattr(G, "fetch_nc", _fake_fetch_nc)
    monkeypatch.setattr(G, "fetch_nc_like", _fake_fetch_nc_like)

    rc = _run_with_argv(bb, ["--dry-run"])
    assert rc == 0
    # dry run must not have mutated the fixtures at all
    assert fixtures["wrong"].raw["county_deed_ref"]["parno"] == "1645782"
    assert fixtures["stale"].raw.get("county_deed_ref") is not None
    assert "unbound_property_blocks" not in fixtures["stale"].raw


def _run_with_argv(mod, argv):
    old = sys.argv
    sys.argv = ["backfill_deed_ref_bound.py", *argv]
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_real_run_fixes_confirmed_rows_and_skips_unresolved(monkeypatch, fixtures):
    written = {}

    def fake_write_artifact(rows, summary, docs_dir=None, **kw):
        written["rows"] = rows
        written["summary"] = summary
        return (Path("x"), Path("y"))

    monkeypatch.setattr(bb, "board_lock", lambda *a, **k: _FakeLock())
    monkeypatch.setattr(bb, "write_artifact", fake_write_artifact)
    all_rows = [fixtures["wrong"], fixtures["unresolvable"], fixtures["stale"], fixtures["clean"]]
    monkeypatch.setattr(bb, "load_board", lambda *a, **k: all_rows)
    monkeypatch.setattr(G, "fetch_nc", _fake_fetch_nc)
    monkeypatch.setattr(G, "fetch_nc_like", _fake_fetch_nc_like)

    rc = _run_with_argv(bb, [])
    assert rc == 0
    assert "rows" in written, "write_artifact was never called"

    # mechanism 1: the confirmed live match corrected both blocks' parno
    assert fixtures["wrong"].raw["county_deed_ref"]["parno"] == "0632599209"
    assert fixtures["wrong"].raw["county_legal"]["parno"] == "0632599209"
    # book/page/text/date untouched -- only the provenance id changed
    assert fixtures["wrong"].raw["county_deed_ref"]["book"] == "AD"
    assert fixtures["wrong"].raw["county_legal"]["text"] == "ROCKY BROAD RIVER"

    # the layer never answered for this pin: left exactly as published, not guessed at
    assert fixtures["unresolvable"].raw["county_deed_ref"]["parno"] == "1111111"

    # mechanism 2: the three gis_fill-owned keys moved aside, byte for byte
    assert "county_deed_ref" not in fixtures["stale"].raw
    assert "county_legal" not in fixtures["stale"].raw
    assert "gis_fill" not in fixtures["stale"].raw
    moved = fixtures["stale"].raw["unbound_property_blocks"]
    assert moved["county_deed_ref"]["parno"] == "9536617322"
    assert moved["gis_fill"]["found"] is True
    # qa_flags (not a gis_fill key) must be untouched
    assert fixtures["stale"].raw["qa_flags"] == ["court_owner_mismatch"]

    # a row with no violation at all is never touched
    assert fixtures["clean"].raw["county_legal"]["parno"] == "102506498464"


def test_classify_is_now_clean_for_fixed_rows(fixtures):
    """After the repairs above would run, re-classifying must find nothing left (the actual
    audit-delta check the task asks the real run to report)."""
    fixtures["wrong"].raw["county_deed_ref"]["parno"] = "0632599209"
    fixtures["wrong"].raw["county_legal"]["parno"] = "0632599209"
    assert bb.classify(fixtures["wrong"]) is None

    moved = {k: fixtures["stale"].raw.pop(k) for k in ("county_deed_ref", "county_legal", "gis_fill")}
    fixtures["stale"].raw["unbound_property_blocks"] = moved
    assert bb.classify(fixtures["stale"]) is None

"""scripts/backfill_deed_ref_bound.py: classification and repair logic for both row shapes
(top80-fill-deed-ref-bound), on synthetic fixtures. No real board, no real network -- gis_fill's
live lookup is monkeypatched, and board_lock/iter_board_rows/patch_existing_rows are replaced
with recorders/fakes that fail the test if a dry run reaches them.

BOARD I/O REWRITE (2026-10-18): the module under test moved from load_board()/write_artifact()
to board_stream.iter_board_rows() + web_artifact.patch_existing_rows() (never materializing the
whole board). iter_board_rows() yields plain dicts (what's actually on disk), not Listing
objects, so fixtures are turned into board-shaped dicts via Listing.model_dump(mode="json")
before being handed to the fake iter_board_rows(). The real-run assertions now inspect the
`patches` dict handed to patch_existing_rows() -- the new seam -- rather than mutated Listing
objects in place, since nothing mutates the original fixtures anymore (candidates are lightweight
copies built fresh from the streamed dicts).
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


def _board_dict(li: Listing) -> dict:
    """What iter_board_rows() would actually yield for this row -- a plain dict, same shape
    json.loads(listings.json) produces, not a Listing object."""
    return li.model_dump(mode="json")


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
# _watchdog_should_kill() / _parse_proc_status_text() -- the supervised-write kill-switch's pure,
# OS-independent decision logic.
# ---------------------------------------------------------------------------------------------

def test_parse_proc_status_text_reads_rss_and_hwm():
    text = (
        "Name:\tpython3\n"
        "VmPeak:\t  123456 kB\n"
        "VmRSS:\t   654321 kB\n"
        "VmHWM:\t   789012 kB\n"
    )
    rss, hwm = bb._parse_proc_status_text(text)
    assert rss == pytest.approx(654321 / 1024.0)
    assert hwm == pytest.approx(789012 / 1024.0)


def test_parse_proc_status_text_missing_fields():
    assert bb._parse_proc_status_text("Name:\tpython3\n") == (None, None)


def test_watchdog_should_kill_none_when_under_both_ceilings():
    assert bb._watchdog_should_kill(10.0, 500.0, 600.0, timeout_s=1200.0, mem_ceiling_mb=16000.0) is None


def test_watchdog_should_kill_on_timeout():
    reason = bb._watchdog_should_kill(1300.0, 100.0, 100.0, timeout_s=1200.0, mem_ceiling_mb=16000.0)
    assert reason is not None and "timeout" in reason


def test_watchdog_should_kill_on_rss_ceiling():
    reason = bb._watchdog_should_kill(10.0, 20000.0, 100.0, timeout_s=1200.0, mem_ceiling_mb=16000.0)
    assert reason is not None and "VmRSS" in reason


def test_watchdog_should_kill_on_hwm_ceiling():
    reason = bb._watchdog_should_kill(10.0, 100.0, 20000.0, timeout_s=1200.0, mem_ceiling_mb=16000.0)
    assert reason is not None and "VmHWM" in reason


def test_watchdog_should_kill_ignores_unknown_signals():
    """Neither VmRSS nor VmHWM was readable (e.g. a host with no /proc) -- must not false-kill on
    memory, only the wall-clock timeout can still fire."""
    assert bb._watchdog_should_kill(10.0, None, None, timeout_s=1200.0, mem_ceiling_mb=16000.0) is None


# ---------------------------------------------------------------------------------------------
# main(): dry run never touches the board; a real run builds patches for both shapes and leaves
# what it cannot confirm untouched.
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


def _run_with_argv(mod, argv):
    old = sys.argv
    sys.argv = ["backfill_deed_ref_bound.py", *argv]
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_dry_run_reports_without_writing(monkeypatch, fixtures):
    def boom(name):
        def f(*a, **k):
            raise AssertionError(f"{name} must not be called on a dry run")
        return f

    rows = [fixtures["wrong"], fixtures["unresolvable"], fixtures["stale"], fixtures["clean"]]
    monkeypatch.setattr(bb, "board_lock", boom("board_lock"))
    monkeypatch.setattr(bb, "patch_existing_rows", boom("patch_existing_rows"))
    monkeypatch.setattr(bb, "_run_patch_supervised", boom("_run_patch_supervised"))
    monkeypatch.setattr(bb, "iter_board_rows",
                        lambda *a, **k: iter([_board_dict(li) for li in rows]))
    monkeypatch.setattr(G, "fetch_nc", _fake_fetch_nc)
    monkeypatch.setattr(G, "fetch_nc_like", _fake_fetch_nc_like)

    rc = _run_with_argv(bb, ["--dry-run"])
    assert rc == 0
    # dry run must not have mutated the original fixtures at all -- nothing in the new
    # streaming/patch design even holds a reference back to them.
    assert fixtures["wrong"].raw["county_deed_ref"]["parno"] == "1645782"
    assert fixtures["stale"].raw.get("county_deed_ref") is not None
    assert "unbound_property_blocks" not in fixtures["stale"].raw


def test_real_run_builds_patches_for_confirmed_rows_and_skips_unresolved(monkeypatch, fixtures):
    captured = {}

    def fake_run_patch_supervised(patches, summary, docs_dir, **kw):
        captured["patches"] = patches
        captured["summary"] = summary
        return (
            {"existing": 4, "patches": len(patches), "matched": len(patches),
             "applied": len(patches), "not_found": 0, "duplicate_key_matches": 0,
             "written": True, "total_after": 4},
            {"peak_rss_mb": 0.0, "peak_vmhwm_mb": 0.0, "elapsed_s": 0.0, "killed_reason": None},
        )

    rows = [fixtures["wrong"], fixtures["unresolvable"], fixtures["stale"], fixtures["clean"]]
    monkeypatch.setattr(bb, "board_lock", lambda *a, **k: _FakeLock())
    monkeypatch.setattr(bb, "board_patch_size_state",
                        lambda *a, **k: {"source_mb": 1.0, "max_mb": 2300.0, "ok": True, "reason": ""})
    monkeypatch.setattr(bb, "_run_patch_supervised", fake_run_patch_supervised)
    monkeypatch.setattr(bb, "iter_board_rows",
                        lambda *a, **k: iter([_board_dict(li) for li in rows]))
    monkeypatch.setattr(G, "fetch_nc", _fake_fetch_nc)
    monkeypatch.setattr(G, "fetch_nc_like", _fake_fetch_nc_like)

    rc = _run_with_argv(bb, [])
    assert rc == 0
    assert "patches" in captured, "_run_patch_supervised was never called"
    patches = captured["patches"]

    # mechanism 1: the confirmed live match corrected both blocks' parno
    wrong_key = fixtures["wrong"].dedupe_key()
    assert patches[wrong_key]["raw"]["county_deed_ref"]["parno"] == "0632599209"
    assert patches[wrong_key]["raw"]["county_legal"]["parno"] == "0632599209"
    # book/page/text untouched -- only the provenance id changed
    assert patches[wrong_key]["raw"]["county_deed_ref"]["book"] == "AD"
    assert patches[wrong_key]["raw"]["county_legal"]["text"] == "ROCKY BROAD RIVER"

    # the layer never answered for this pin: left exactly as published, not guessed at
    unresolvable_key = fixtures["unresolvable"].dedupe_key()
    assert unresolvable_key not in patches

    # mechanism 2: the three gis_fill-owned keys tombstoned to None and moved aside, byte for byte
    stale_key = fixtures["stale"].dedupe_key()
    stale_raw_patch = patches[stale_key]["raw"]
    assert stale_raw_patch["county_deed_ref"] is None
    assert stale_raw_patch["county_legal"] is None
    assert stale_raw_patch["gis_fill"] is None
    moved = stale_raw_patch["unbound_property_blocks"]
    assert moved["county_deed_ref"]["parno"] == "9536617322"
    assert moved["gis_fill"]["found"] is True
    # qa_flags (not a gis_fill key) is never part of this patch at all
    assert "qa_flags" not in stale_raw_patch

    # a row with no violation at all is never patched
    clean_key = fixtures["clean"].dedupe_key()
    assert clean_key not in patches


def test_real_run_refuses_oversized_board_without_allow_large(monkeypatch, fixtures):
    def boom(name):
        def f(*a, **k):
            raise AssertionError(f"{name} must not be called when the board is too large "
                                  f"and --allow-large was not passed")
        return f

    rows = [fixtures["wrong"]]
    monkeypatch.setattr(bb, "board_lock", lambda *a, **k: _FakeLock())
    monkeypatch.setattr(bb, "board_patch_size_state",
                        lambda *a, **k: {"source_mb": 4985.0, "max_mb": 2300.0, "ok": False,
                                         "reason": "board source is 4985 MB, over the 2300 MB ceiling"})
    monkeypatch.setattr(bb, "_run_patch_supervised", boom("_run_patch_supervised"))
    monkeypatch.setattr(bb, "iter_board_rows",
                        lambda *a, **k: iter([_board_dict(li) for li in rows]))
    monkeypatch.setattr(G, "fetch_nc", _fake_fetch_nc)
    monkeypatch.setattr(G, "fetch_nc_like", _fake_fetch_nc_like)

    rc = _run_with_argv(bb, [])
    assert rc == 1


def test_collect_candidates_excludes_ambiguous_shared_identity(monkeypatch, tmp_path):
    """Two DIFFERENT violating rows that happen to share one dedupe_key (the board already has
    a duplicate identity) must NOT land a patch at all: patch_existing_rows() would apply
    whichever one patch is built under that key to every board row matching it, and this
    script's patch values are derived from each row's own (potentially different) raw content
    -- so landing one row's correction on its sibling would risk corrupting the sibling."""
    same_parcel_kw = dict(parcel_id="7777777777", county="Ashe", state="NC")
    a = _listing(
        **same_parcel_kw,
        raw={"county_legal": {"source": "nc_onemap", "text": "TRACT A", "parno": "1111111"}})
    b = _listing(
        **same_parcel_kw,
        raw={"county_legal": {"source": "nc_onemap", "text": "TRACT B", "parno": "2222222"}})
    assert a.dedupe_key() == b.dedupe_key()

    monkeypatch.setattr(bb, "iter_board_rows",
                        lambda *a_, **k_: iter([_board_dict(a), _board_dict(b)]))

    wrong_parno, stale_strip, total, ambiguous = bb._collect_candidates(tmp_path)
    assert total == 2
    assert ambiguous == 1
    assert a.dedupe_key() not in wrong_parno
    assert a.dedupe_key() not in stale_strip


def test_classify_is_now_clean_for_fixed_rows(fixtures):
    """After the repairs above would apply, re-classifying must find nothing left (the actual
    audit-delta check the task asks the real run to report). Mirrors how the patch would land on
    disk: county_deed_ref/county_legal/gis_fill set to None (tombstoned, not popped -- see this
    module's RAW-UPDATE GOTCHA), and their values folded into unbound_property_blocks."""
    fixtures["wrong"].raw["county_deed_ref"]["parno"] = "0632599209"
    fixtures["wrong"].raw["county_legal"]["parno"] = "0632599209"
    assert bb.classify(fixtures["wrong"]) is None

    moved = {k: fixtures["stale"].raw[k] for k in ("county_deed_ref", "county_legal", "gis_fill")}
    fixtures["stale"].raw["unbound_property_blocks"] = moved
    for k in ("county_deed_ref", "county_legal", "gis_fill"):
        fixtures["stale"].raw[k] = None
    assert bb.classify(fixtures["stale"]) is None

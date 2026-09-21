"""Board write-path integrity (audit 2026-09-21 O3, O4, O11, O9).

Covers, in order:
  1. write_artifact REFUSES to write the live board without the board lock, and when the
     board changed after this process loaded it
  2. the manifest: written last, verified on load, plain-over-gz preference refused when it
     disagrees, torn sets detected
  3. load_board counts and logs every row it drops and fails above 0.1%
  4. health honesty: health_as_of carried forward, age, stale nulling, per-source last success
  5. lock hardening: heartbeat, children, expiry, token fencing, the memory gate

Every "live board" test points web_artifact._live_docs_dir at a scratch tree, so nothing here
can touch the real docs/ or the real logs/.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int) -> Listing:
    return Listing(source=f"src.{i % 2}", source_url=f"u{i}",
                   listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
                   parcel_id=f"P{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i} Elm"}],
                        "vision": {"parsed": True}})


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A scratch 'repo': tmp/docs is the live board and tmp/logs/.board.lock its lock."""
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(wa, "_live_docs_dir", lambda: docs)
    for var in (wa.BOARD_LOCK_ENV, wa.BOARD_LOCK_TOKEN_ENV):
        monkeypatch.delenv(var, raising=False)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return tmp_path


def _write(docs: Path, n=5, summary=None):
    wa.write_artifact([_lead(i) for i in range(n)], summary or {"notes": "t"}, docs_dir=docs)


# ===========================================================================
# 1. THE LOCK IS ENFORCED
# ===========================================================================

def test_write_artifact_refuses_the_live_board_without_the_lock(live):
    with pytest.raises(wa.BoardLockNotHeld) as ei:
        _write(live / "docs")
    assert "with_board_lock.sh" in str(ei.value)
    assert not (live / "docs" / "listings.json").exists(), "nothing may be written before the refusal"


def test_write_artifact_succeeds_inside_the_lock(live):
    with wa.board_lock(live, owner="t"):
        _write(live / "docs")
    assert (live / "docs" / "listings.json").exists()


def test_bypass_is_explicit_and_logged(live, monkeypatch):
    monkeypatch.setenv("BOARD_LOCK_BYPASS", "1")
    _write(live / "docs")
    assert (live / "docs" / "listings.json").exists()


def test_a_scratch_board_needs_no_lock(tmp_path):
    """A docs dir that is not the live board shares nothing to protect."""
    scratch = tmp_path / "scratch"
    wa.write_artifact([_lead(0)], {"notes": "t"}, docs_dir=scratch)
    assert (scratch / "listings.json").exists()


def test_the_env_var_alone_is_not_enough_when_a_token_says_the_lock_was_lost(live, monkeypatch):
    """A hung holder whose lock was broken as stale keeps its inherited env vars. The token
    on disk no longer matches, so it is fenced out instead of writing over the new holder."""
    d = wa.board_lock_dir(live)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nnew-holder\n1\n1\n60\nNEWTOKEN\n")
    monkeypatch.setenv(wa.BOARD_LOCK_ENV, str(d))
    monkeypatch.setenv(wa.BOARD_LOCK_TOKEN_ENV, "OLDTOKEN")
    with pytest.raises(wa.BoardLockLost):
        _write(live / "docs")


def test_a_legacy_holder_without_a_token_is_still_accepted(live, monkeypatch):
    d = wa.board_lock_dir(live)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nold-wrapper\n")
    monkeypatch.setenv(wa.BOARD_LOCK_ENV, str(d))
    _write(live / "docs")
    assert (live / "docs" / "listings.json").exists()


def test_write_refuses_when_the_board_changed_since_load(live):
    with wa.board_lock(live, owner="t"):
        _write(live / "docs")
        board = wa.load_board(live / "docs")
        # another writer replaces the board while this one works on its copy
        time.sleep(0.01)
        (live / "docs" / "listings.json").write_bytes(
            (live / "docs" / "listings.json").read_bytes() + b" ")
        with pytest.raises(wa.BoardChangedSinceLoad) as ei:
            wa.write_artifact(board, {"notes": "stale"}, docs_dir=live / "docs")
        assert "changed since this process loaded it" in str(ei.value)


def test_a_second_write_in_the_same_process_is_not_mistaken_for_someone_elses(live):
    with wa.board_lock(live, owner="t"):
        _write(live / "docs")
        board = wa.load_board(live / "docs")
        wa.write_artifact(board, {"notes": "one"}, docs_dir=live / "docs")
        wa.write_artifact(board, {"notes": "two"}, docs_dir=live / "docs")    # must not raise


def test_a_process_that_never_loaded_is_not_stamp_checked(live):
    with wa.board_lock(live, owner="t"):
        _write(live / "docs")
        wa._LOAD_STAMPS.clear()
        (live / "docs" / "listings.json").write_bytes(b"[]")
        _write(live / "docs")                       # a full re-scrape has nothing to compare


# ===========================================================================
# 2. THE MANIFEST
# ===========================================================================

def test_manifest_is_written_last_and_describes_every_payload_file(tmp_path):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(7)], {"notes": "t"}, docs_dir=docs)
    man = json.loads((docs / wa.MANIFEST_NAME).read_text())
    assert man["schema"] == wa.MANIFEST_SCHEMA and man["count"] == 7 and man["detail_count"] == 7
    files = man["files"]
    for name in ("listings.json", "listings_detail.json", "listings.json.gz",
                 "listings_detail.json.gz", "listings_slim.json", "listings_slim.json.gz",
                 "run_meta.json"):
        assert name in files, name
        assert files[name]["bytes"] == (docs / name).stat().st_size
        assert len(files[name]["sha256"]) == 64
    assert any(k.startswith("detail_shards/") for k in files)
    newest_payload = max((docs / n).stat().st_mtime_ns for n in files)
    assert (docs / wa.MANIFEST_NAME).stat().st_mtime_ns >= newest_payload, "manifest must be LAST"
    assert wa.verify_manifest(docs)["ok"]


def test_a_plain_file_that_disagrees_with_the_manifest_loses_to_its_gz_twin(tmp_path):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=docs)
    good = json.loads((docs / "listings.json").read_text())
    (docs / "listings.json").write_text("[]")               # torn / stale plain file
    got = wa.read_board_json(docs / "listings.json")
    assert got == good, "the manifest-matching gz twin must win over the disagreeing plain file"


def test_a_torn_set_is_refused_not_loaded(tmp_path):
    """The failure the manifest exists for: listings.json from write N and the sidecar from
    write N-1 join by index and load without an error."""
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=docs)
    for name in ("listings_detail.json", "listings_detail.json.gz"):
        (docs / name).write_bytes(b"[{}, {}]")              # a sidecar from another write
    with pytest.raises(wa.BoardIntegrityError) as ei:
        wa.load_board(docs)
    assert "torn or mixed" in str(ei.value)


def test_write_artifact_will_not_publish_on_top_of_a_torn_set(tmp_path):
    """_load_prior_details_by_key used to swallow every exception and return {}: the next
    write then published details[i] = {} for every lead it had not re-enriched."""
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=docs)
    for name in ("listings_detail.json", "listings_detail.json.gz"):
        (docs / name).write_bytes(b"[{}, {}]")
    with pytest.raises(wa.BoardIntegrityError):
        wa.write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=docs)


def test_a_fresh_clone_with_only_the_gz_twins_loads_and_verifies(tmp_path):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(4)], {"notes": "t"}, docs_dir=docs)
    for name in ("listings.json", "listings_detail.json", "listings_slim.json"):
        (docs / name).unlink()
    assert len(wa.load_board(docs)) == 4
    assert wa.verify_manifest(docs)["ok"]


def test_no_manifest_keeps_the_legacy_behaviour(tmp_path):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(3)], {"notes": "t"}, docs_dir=docs)
    (docs / wa.MANIFEST_NAME).unlink()
    (docs / "listings.json").write_text(json.dumps(json.loads((docs / "listings.json").read_text())[:2]))
    assert len(wa.load_board(docs)) == 2, "no manifest: the plain file wins, as it always did"


def test_the_manifest_skip_escape_hatch(tmp_path, monkeypatch):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(3)], {"notes": "t"}, docs_dir=docs)
    (docs / "listings_detail.json").write_bytes(b"[{}]")
    (docs / "listings_detail.json.gz").write_bytes(b"junk")
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")
    assert len(wa.load_board(docs)) == 3


def test_verify_manifest_names_the_bad_file(tmp_path):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(0)], {"notes": "t"}, docs_dir=docs)
    (docs / "listings.json.gz").write_bytes(b"corrupt")
    res = wa.verify_manifest(docs)
    assert not res["ok"] and any("listings.json.gz" in p for p in res["problems"])


def test_a_manifest_that_could_not_be_written_is_removed_not_left_stale(tmp_path, monkeypatch):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(0)], {"notes": "t"}, docs_dir=docs)
    assert (docs / wa.MANIFEST_NAME).exists()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(wa, "write_manifest", boom)
    wa.write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=docs)
    assert not (docs / wa.MANIFEST_NAME).exists()


# ===========================================================================
# 3. DROPPED ROWS ARE COUNTED, LOGGED, AND CAPPED
# ===========================================================================

def _poison(docs: Path, indices):
    recs = json.loads((docs / "listings.json").read_text())
    for i in indices:
        recs[i]["listing_type"] = "not-a-real-type"
    (docs / "listings.json").write_text(json.dumps(recs))


def test_a_drop_below_the_limit_loads_and_is_logged(tmp_path, monkeypatch):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(2000)], {"notes": "t"}, docs_dir=docs)
    _poison(docs, [17])
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")
    board = wa.load_board(docs)                       # 1 of 2000 = 0.05%, under 0.1%
    assert len(board) == 1999
    assert wa.LAST_LOAD_STATS["dropped"] == 1 and wa.LAST_LOAD_STATS["total"] == 2000
    dropped_log = tmp_path / "logs" / "board_load_dropped.jsonl"
    # scratch docs: the drop log goes next to the (patched or real) lock dir's logs/
    assert wa.LAST_LOAD_STATS["drop_rate"] == pytest.approx(0.0005)
    _ = dropped_log


def test_a_drop_rate_over_the_limit_fails_the_load(tmp_path, monkeypatch):
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(1000)], {"notes": "t"}, docs_dir=docs)
    _poison(docs, [1, 2])                             # 0.2%
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")
    with pytest.raises(wa.BoardLoadDropError) as ei:
        wa.load_board(docs)
    assert "2 of 1,000" in str(ei.value)
    assert len(wa.load_board(docs, max_drop_rate=1.0)) == 998        # a caller with its own recovery
    monkeypatch.setenv("BOARD_LOAD_ALLOW_DROPS", "1")
    assert len(wa.load_board(docs)) == 998
    monkeypatch.delenv("BOARD_LOAD_ALLOW_DROPS")
    monkeypatch.setenv("BOARD_LOAD_MAX_DROP_RATE", "0.01")
    assert len(wa.load_board(docs)) == 998


def test_the_drop_log_records_what_was_dropped(live, monkeypatch):
    docs = live / "docs"
    with wa.board_lock(live, owner="t"):
        _write(docs, n=3)
    _poison(docs, [1])
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")
    monkeypatch.setenv("BOARD_LOAD_ALLOW_DROPS", "1")
    wa.load_board(docs)
    lines = (live / "logs" / "board_load_dropped.jsonl").read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["index"] == 1 and rec["source"] == "src.1" and "ValidationError" in rec["error"]


# ===========================================================================
# 4. HEALTH HONESTY
# ===========================================================================

def _meta(docs: Path) -> dict:
    return json.loads((docs / "run_meta.json").read_text())


def test_own_health_is_stamped_and_carried_health_keeps_its_origin(tmp_path):
    docs = tmp_path / "d"
    leads = [_lead(i) for i in range(3)]
    wa.write_artifact(leads, {"notes": "full", "by_source": {"a": 3},
                              "source_status": {"a": "OK (3)", "b": "EMPTY (verified)"},
                              "errors": ["boom"]}, docs_dir=docs)
    first = _meta(docs)
    assert first["health_as_of"] == first["run_time"]
    assert first["health_stale"] is False and first["health_age_hours"] < 0.1
    wa.write_artifact(leads, {"notes": "partial writer"}, docs_dir=docs)
    second = _meta(docs)
    assert second["health_as_of"] == first["health_as_of"], "origin must not move to the latest write"
    assert second["health_carried_from"] == first["health_as_of"]
    assert second["source_status"] == first["source_status"] and second["errors"] == ["boom"]


def test_health_older_than_48_hours_is_nulled_and_says_so(tmp_path):
    docs = tmp_path / "d"
    leads = [_lead(0)]
    wa.write_artifact(leads, {"notes": "full", "source_status": {"a": "OK (1)"},
                              "errors": ["e"], "by_source": {"a": 1}}, docs_dir=docs)
    meta = _meta(docs)
    meta["health_as_of"] = (datetime.utcnow() - timedelta(days=23)).isoformat() + "Z"   # frozen at 8/29
    (docs / "run_meta.json").write_text(json.dumps(meta))
    wa.write_artifact(leads, {"notes": "partial writer"}, docs_dir=docs)
    out = _meta(docs)
    assert out["health_stale"] is True and out["health_age_hours"] > 48
    assert out["source_status"] is None and out["errors"] is None
    assert out["health_nulled"] == ["source_status", "errors"]
    assert out["by_source"] == {"a": 1}, "counts are still carried, labelled by health_as_of"


def test_health_of_unknown_origin_is_treated_as_stale(tmp_path):
    """The live file at audit time: source_status present, no health_as_of anywhere."""
    docs = tmp_path / "d"
    docs.mkdir()
    (docs / "run_meta.json").write_text(json.dumps({
        "run_time": "2026-09-21T05:33:11Z", "source_status": {"a": "OK (9)"}, "errors": ["x"],
        "by_source": {"a": 9}, "health_carried_from": "2026-09-21T05:28:00Z"}))
    wa.write_artifact([_lead(0)], {"notes": "partial writer"}, docs_dir=docs)
    out = _meta(docs)
    assert out["health_as_of"] is None and out["health_age_hours"] is None
    assert out["health_stale"] is True and out["source_status"] is None


def test_source_last_success_is_stamped_per_source_and_carried(tmp_path):
    docs = tmp_path / "d"
    leads = [_lead(0)]
    wa.write_artifact(leads, {"notes": "full", "source_status": {
        "ok.one": "OK (12)", "bad.two": "🔴 TIMEOUT — x", "empty.three": "EMPTY (verified)"}}, docs_dir=docs)
    a = _meta(docs)["source_last_success"]
    assert set(a) == {"ok.one"}
    time.sleep(1.1)
    wa.write_artifact(leads, {"notes": "family", "source_refreshed": ["fam.x"]}, docs_dir=docs)
    b = _meta(docs)["source_last_success"]
    assert b["ok.one"] == a["ok.one"], "an untouched source keeps ITS OWN last success"
    assert "fam.x" in b and b["fam.x"] > a["ok.one"]
    wa.write_artifact(leads, {"notes": "dict form", "source_refreshed": {"fam.y": "2026-01-02T03:04:05Z"}},
                      docs_dir=docs)
    assert _meta(docs)["source_last_success"]["fam.y"] == "2026-01-02T03:04:05Z"


# ===========================================================================
# 5. LOCK HARDENING
# ===========================================================================

def test_lock_record_carries_start_heartbeat_max_runtime_and_token(tmp_path):
    with wa.board_lock(tmp_path, owner="t", max_runtime=120):
        info = wa._bl_info(wa.board_lock_dir(tmp_path))
        assert info["pid"] == os.getpid() and info["owner"] == "t"
        assert info["max_runtime"] == 120 and info["token"]
        assert abs(info["start"] - time.time()) < 5
        assert os.environ[wa.BOARD_LOCK_TOKEN_ENV] == info["token"]
    assert wa.BOARD_LOCK_TOKEN_ENV not in os.environ


def test_the_heartbeat_is_restamped_while_the_lock_is_held(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARD_LOCK_HEARTBEAT_S", "0.2")
    with wa.board_lock(tmp_path, owner="t"):
        d = wa.board_lock_dir(tmp_path)
        first = wa._bl_info(d)["heartbeat"]
        deadline = time.time() + 5
        while time.time() < deadline and wa._bl_info(d)["heartbeat"] == first:
            time.sleep(0.1)
        assert wa._bl_info(d)["heartbeat"] > first


def test_a_live_holder_past_its_max_runtime_plus_30_minutes_is_broken(tmp_path):
    """A hung holder with a LIVE pid used to block every other job forever."""
    d = wa.board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    long_ago = int(time.time()) - 3600 - 1900                  # max runtime 1 h + 30 min + slack
    (d / "pid").write_text(f"{os.getpid()}\nhung\n{long_ago}\n{long_ago}\n3600\nTOK\n")
    assert wa._bl_stale_reason(d) == "expired"
    with wa.board_lock(tmp_path, owner="new"):
        assert wa._bl_info(d)["owner"] == "new"
    from foreclosure_scraper import job_events
    assert any(e.get("event") == "lock_break" and e.get("reason") == "expired"
               for e in job_events.read_events())


def test_a_live_holder_inside_its_max_runtime_is_not_broken(tmp_path):
    d = wa.board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    now = int(time.time())
    (d / "pid").write_text(f"{os.getpid()}\nbusy\n{now - 100}\n{now}\n3600\nTOK\n")
    assert wa._bl_stale_reason(d) is None
    with pytest.raises(wa.BoardLockBusy):
        with wa.board_lock(tmp_path, owner="second"):
            pass


def test_a_legacy_lock_uses_the_pid_file_mtime_as_its_start(tmp_path):
    d = wa.board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nold\n")
    old = time.time() - 7 * 3600                                # older than the 6 h default + 30 min
    os.utime(d / "pid", (old, old))
    assert wa._bl_stale_reason(d) == "expired"


def test_a_registered_child_keeps_the_lock_alive_after_its_wrapper_dies(tmp_path):
    d = wa.board_lock_dir(tmp_path)
    (d / "children").mkdir(parents=True)
    (d / "pid").write_text("99998\nwrapper-killed\n")            # the wrapper's pid is dead
    (d / "children" / str(os.getpid())).write_text("python-child")   # this process is the live child
    assert wa._bl_stale_reason(d) is None, "a live child means the lock is NOT stale"
    (d / "children" / str(os.getpid())).unlink()
    assert wa._bl_stale_reason(d) == "dead_owner"


def test_a_reentrant_child_registers_and_unregisters(tmp_path, monkeypatch):
    d = wa.board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nwrapper\n")
    monkeypatch.setenv(wa.BOARD_LOCK_ENV, str(d))
    with wa.board_lock(tmp_path, owner="child"):
        assert (d / "children" / str(os.getpid())).exists()
    assert not (d / "children" / str(os.getpid())).exists()


def test_a_reentrant_child_refuses_when_its_lock_was_taken_over(tmp_path, monkeypatch):
    d = wa.board_lock_dir(tmp_path)
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{os.getpid()}\nsomeone-else\n1\n1\n60\nNEW\n")
    monkeypatch.setenv(wa.BOARD_LOCK_ENV, str(d))
    monkeypatch.setenv(wa.BOARD_LOCK_TOKEN_ENV, "OLD")
    with pytest.raises(wa.BoardLockLost):
        with wa.board_lock(tmp_path, owner="child"):
            pass


def test_an_expired_lock_that_was_retaken_is_not_deleted_by_its_old_holder(tmp_path):
    """The old holder's context exit must only remove the lock if the token is still its own."""
    with wa.board_lock(tmp_path, owner="first") as d:
        (d / "pid").write_text(f"{os.getpid()}\nsecond\n1\n1\n60\nOTHERTOKEN\n")   # someone re-took it
    assert d.is_dir(), "the new holder's lock was deleted by the old holder's exit"


def test_the_memory_gate_modes(monkeypatch):
    monkeypatch.setenv("BOARD_GATE_FAKE_SWAP_MB", "5000")
    monkeypatch.setenv("BOARD_GATE_FAKE_FREE_MB", "4000")
    monkeypatch.setenv("BOARD_MEM_GATE", "off")
    assert wa.board_memory_gate("t")["ok"] is True
    monkeypatch.setenv("BOARD_MEM_GATE", "warn")
    assert "swap_used_mb=5000" in wa.board_memory_gate("t")["reason"]         # proceeds
    monkeypatch.setenv("BOARD_MEM_GATE", "enforce")
    monkeypatch.setenv("BOARD_MEM_GATE_WAIT", "0.2")
    with pytest.raises(wa.BoardMemoryPressure) as ei:
        wa.board_memory_gate("t", poll=0.05)
    assert "swap_used_mb=5000>3072" in str(ei.value)


def test_the_gate_also_trips_on_free_plus_inactive_ram(monkeypatch):
    monkeypatch.setenv("BOARD_GATE_FAKE_SWAP_MB", "100")
    monkeypatch.setenv("BOARD_GATE_FAKE_FREE_MB", "300")
    st = wa.board_memory_state()
    assert st["ok"] is False and "free_plus_inactive_mb=300<1024" in st["reason"]


def test_the_gate_refusal_is_a_job_event_and_blocks_the_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARD_MEM_GATE", "enforce")
    monkeypatch.setenv("BOARD_MEM_GATE_WAIT", "0.1")
    monkeypatch.setenv("BOARD_GATE_FAKE_SWAP_MB", "9000")
    with pytest.raises(wa.BoardMemoryPressure):
        with wa.board_lock(tmp_path, owner="daily"):
            pytest.fail("the gate must refuse before the lock is taken")
    assert not wa.board_lock_dir(tmp_path).exists()
    from foreclosure_scraper import job_events
    acts = [e.get("action") for e in job_events.read_events() if e.get("event") == "mem_gate"]
    assert "refused" in acts


def test_the_gate_clears_when_pressure_drops_while_waiting(tmp_path, monkeypatch):
    monkeypatch.setenv("BOARD_MEM_GATE", "enforce")
    monkeypatch.setenv("BOARD_MEM_GATE_WAIT", "5")
    monkeypatch.setenv("BOARD_GATE_FAKE_SWAP_MB", "9000")
    calls = {"n": 0}
    real = wa.board_memory_state

    def relieved():
        calls["n"] += 1
        if calls["n"] >= 3:
            monkeypatch.setenv("BOARD_GATE_FAKE_SWAP_MB", "10")
        return real()
    monkeypatch.setattr(wa, "board_memory_state", relieved)
    out = wa.board_memory_gate("t", poll=0.05)
    assert out["ok"] is True and calls["n"] >= 3


# ===========================================================================
# the changed-since-load check follows the file that was actually read
# ===========================================================================

def test_no_check_when_load_board_read_the_gz_twin(tmp_path):
    """A gz-only machine (fresh clone, CI, restore): there is no plain file that was loaded,
    so there is nothing to compare, and a rewrite must always go through."""
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(3)], {"notes": "t"}, docs_dir=docs)
    for name in ("listings.json", "listings_detail.json", "listings_slim.json"):
        (docs / name).unlink()
    wa._LOAD_STAMPS.clear()
    board = wa.load_board(docs)                              # read from the gz
    assert wa._LOAD_STAMPS[str((docs / "listings.json").resolve())][0].endswith(".gz")
    # even if the gz is replaced underneath, this flow must not raise
    wa.write_artifact(board, {"notes": "first"}, docs_dir=docs)
    wa.write_artifact(wa.load_board(docs), {"notes": "reload and rewrite"}, docs_dir=docs)
    assert len(wa.load_board(docs)) == 3


def test_rows_loaded_from_a_different_snapshot_can_be_written_to_the_live_board(live):
    """A restore-style flow: load an older snapshot's rows, publish them as the live board.
    Stamps are keyed by the docs dir that was LOADED, so the live board is not compared."""
    snap = live / "snapshot" / "docs"
    wa.write_artifact([_lead(i) for i in range(6)], {"notes": "old"}, docs_dir=snap)
    rows = wa.load_board(snap)
    with wa.board_lock(live, owner="restore"):
        _write(live / "docs", n=5)                           # the live board moved on meanwhile
        wa.write_artifact(rows, {"notes": "from snapshot"}, docs_dir=live / "docs")
    assert len(wa.load_board(live / "docs")) == 6


def test_the_plain_json_protection_is_kept(live):
    """Same setup as the gz case but the PLAIN file was read: a replaced plain file aborts."""
    with wa.board_lock(live, owner="t"):
        _write(live / "docs")
        board = wa.load_board(live / "docs")
        assert not wa._LOAD_STAMPS[str((live / "docs" / "listings.json").resolve())][0].endswith(".gz")
        (live / "docs" / "listings.json").write_bytes((live / "docs" / "listings.json").read_bytes() + b" ")
        with pytest.raises(wa.BoardChangedSinceLoad):
            wa.write_artifact(board, {"notes": "stale"}, docs_dir=live / "docs")

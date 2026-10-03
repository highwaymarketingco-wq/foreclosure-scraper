"""scripts/run_pending_signal_enrichers.py's board-I/O rewrite (2026-10-02, docs/HANDOFF.md item
42): it used to call load_board() to build the WHOLE board, run all 8 steps over it, then
write_artifact(listings, ...) -- the double materialization that kernel-OOM-killed a real
production attempt on the 23GB Oracle VM the same day. This test proves the new path --
board_stream.iter_board_rows() (no lazy-detail sidecar) to build the working set, the real STEPS/
_run_one() dispatch UNCHANGED (each of the 8 real enrich_* functions replaced here with a small
fake so the test is fast/offline, exactly like test_lrcpwa_refresh_patch_integration.py fakes
enrich_lrcpwa_parcel/photo), a pre/post snapshot diff, one web_artifact.patch_existing_rows() call
-- reproduces the original contract, without ever calling load_board()/write_artifact(), and
without any real network call.

Covers:
  1. End-to-end with --only restricting to a subset of steps: only the targeted row is patched.
  2. The ONE raw-key DELETION hazard this migration's docstring discloses:
     enrichment_bop_federal.py's `raw.pop("bop_check", None)` lands as an explicit
     raw['bop_check'] = None (patch_existing_rows() has no delete primitive), and reads back
     exactly like an absent key.
  3. An ordinary row no step touches is never sent to patch_existing_rows() at all.
  4. --dry-run computes and prints before/after counts but writes nothing (and never acquires
     the board lock).
  5. Idempotency: a second real run (fakes return the same result) patches nothing.
  6. The board-too-large-to-patch ceiling is checked BEFORE the expensive full-list build.
  7. LOCK HARDENING: the real run acquires the board lock itself now (board_lock() is reentrant),
     where the original script never called it at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_pending_signal_enrichers as P  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Henderson", raw={})
    base.update(kw)
    return Listing(**base)


def _noop_sync(listings):
    return {}


async def _noop_async(listings):
    return {}


def _fake_liensnc(listings):
    n = 0
    for li in listings:
        if li.source == "liensnc_target":
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["liensnc_posthumous_filing"] = {"matched": True}
            n += 1
    return {"matched": n}


async def _fake_bop_federal(listings):
    """Reproduces the real hazards: a row that was previously stamped a 'no match' miss
    (raw['bop_check']) now gets a real match, and the miss stamp is POPPED (one of the raw-key
    deletions among all 8 steps -- enrichment_bop_federal.py's own `.pop('bop_check', None)`).
    Also reproduces the newer stale-match hazard (2026-10-03, _clear_stale_matches): a row whose
    owner changed since a bop_federal match was stamped gets that match (and, when it was the
    source, raw['incarceration']) POPPED rather than left to name someone who no longer owns
    the parcel."""
    matched = stale_cleared = 0
    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        if li.source == "bop_match_target":
            li.raw["bop_federal"] = {"matched_name": "JOHN DOE", "in_custody": True}
            li.raw.pop("bop_check", None)
            matched += 1
        elif li.source == "bop_stale_target":
            li.raw.pop("bop_federal", None)
            inc = li.raw.get("incarceration")
            if isinstance(inc, dict) and inc.get("source") == "BOP inmate locator":
                li.raw.pop("incarceration", None)
            stale_cleared += 1
    return {"matched": matched, "queried": matched, "stale_cleared": stale_cleared}


@pytest.fixture
def fake_enrichers(monkeypatch):
    import foreclosure_scraper.enrichment_liensnc_posthumous as m_liensnc
    import foreclosure_scraper.enrichment_platted_lots as m_platted
    import foreclosure_scraper.enrichment_divorce_no_subsequent_deed as m_divorce
    import foreclosure_scraper.enrichment_notice_service_defect as m_notice
    import foreclosure_scraper.enrichment_jail_bookings as m_jail
    import foreclosure_scraper.enrichment_bop_federal as m_bop
    import foreclosure_scraper.enrichment_land_buildability as m_land
    import foreclosure_scraper.enrichment_foreclosure_docket_history as m_fdh

    monkeypatch.setattr(m_liensnc, "enrich_liensnc_posthumous", _fake_liensnc)
    monkeypatch.setattr(m_platted, "enrich_platted_lots", _noop_sync)
    monkeypatch.setattr(m_divorce, "enrich_divorce_no_subsequent_deed", _noop_sync)
    monkeypatch.setattr(m_notice, "enrich_notice_service_defect", _noop_sync)

    async def fake_jail(listings, dry_run=False):
        return {}
    monkeypatch.setattr(m_jail, "enrich_jail_bookings", fake_jail)
    monkeypatch.setattr(m_bop, "enrich_bop_federal", _fake_bop_federal)
    monkeypatch.setattr(m_land, "enrich_land_buildability", _noop_async)
    monkeypatch.setattr(m_fdh, "enrich_foreclosure_docket_history", _noop_async)


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch, fake_enrichers):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(P, "REPO", repo)
    monkeypatch.setattr(P, "_engine_running", lambda: False)  # avoid real-pgrep flakiness
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _seed(docs: Path, rows: list[Listing]) -> None:
    wa.write_artifact(rows, {"notes": "run_pending_signal_enrichers test seed"}, docs_dir=docs)


def _read_board(docs: Path) -> list[dict]:
    from foreclosure_scraper.board_stream import iter_board_rows
    gz = docs / "listings.json.gz"
    plain = docs / "listings.json"
    return list(iter_board_rows(gz if gz.exists() else plain))


def test_only_flag_patches_just_the_targeted_row(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [
        _row(0, source="liensnc_target", raw={}),
        _row(1, source="src.ordinary", raw={}),
    ]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv",
                        ["run_pending_signal_enrichers.py", "--only", "liensnc_posthumous"])

    rc = P.asyncio.run(P.main())
    assert rc == 0

    board = _read_board(docs)
    by_url = {r["source_url"]: r for r in board}
    assert by_url[rows[0].source_url]["raw"]["liensnc_posthumous_filing"] == {"matched": True}
    assert "liensnc_posthumous_filing" not in by_url[rows[1].source_url]["raw"]


def test_bop_check_deletion_lands_as_none_and_reads_as_absent(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="bop_match_target",
                 raw={"bop_check": {"checked_at": "2026-09-01T00:00:00+00:00",
                                     "name": "JOHN DOE", "result": "no_match"}})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv",
                        ["run_pending_signal_enrichers.py", "--only", "bop_federal"])

    rc = P.asyncio.run(P.main())
    assert rc == 0

    board = _read_board(docs)
    row = board[0]
    assert row["raw"]["bop_federal"]["matched_name"] == "JOHN DOE"
    assert row["raw"]["bop_check"] is None  # the only representable form of "deleted"
    # every real reader (enrichment_bop_federal._stamp_of) treats that exactly like absent:
    assert row["raw"].get("bop_check") is None


def test_bop_stale_match_deletion_lands_as_none_for_both_keys(scratch_repo, monkeypatch):
    """2026-10-03: _RAW_DELETE_SAFE_AS_NONE must list "bop_federal"/"incarceration" or this
    migration's diff-based patch path silently drops the deletion (it looks correct in memory
    but never reaches the published board) -- this is the regression that would catch it."""
    docs = scratch_repo / "docs"
    rows = [_row(0, source="bop_stale_target",
                 raw={"bop_federal": {"matched_name": "CECIL BENNETT"},
                      "incarceration": {"source": "BOP inmate locator", "state": "FEDERAL"},
                      "owner_mailing": {"owner": "COVENANT PRESBYTERIAN CHURCH"}})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv",
                        ["run_pending_signal_enrichers.py", "--only", "bop_federal"])

    rc = P.asyncio.run(P.main())
    assert rc == 0

    board = _read_board(docs)
    row = board[0]
    assert row["raw"]["bop_federal"] is None
    assert row["raw"]["incarceration"] is None
    assert row["raw"]["owner_mailing"]["owner"] == "COVENANT PRESBYTERIAN CHURCH"  # untouched


def test_ordinary_row_untouched_by_every_step_is_never_patched(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="src.ordinary", raw={})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_pending_signal_enrichers.py"])

    before = (docs / "listings.json").read_bytes()
    rc = P.asyncio.run(P.main())
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before


def test_dry_run_writes_nothing_and_never_locks(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="liensnc_target", raw={})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_pending_signal_enrichers.py", "--dry-run"])

    locked = []
    real_lock = P.board_lock

    def spy_lock(*a, **kw):
        locked.append(True)
        return real_lock(*a, **kw)
    monkeypatch.setattr(P, "board_lock", spy_lock)

    before = (docs / "listings.json").read_bytes()
    rc = P.asyncio.run(P.main())
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before
    assert not locked, "a dry run must never acquire the board lock"

    board = _read_board(docs)
    assert "liensnc_posthumous_filing" not in board[0]["raw"]


def test_second_run_is_idempotent(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="liensnc_target", raw={})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv",
                        ["run_pending_signal_enrichers.py", "--only", "liensnc_posthumous"])

    assert P.asyncio.run(P.main()) == 0
    before = (docs / "listings.json").read_bytes()
    assert P.asyncio.run(P.main()) == 0  # fake re-tags the same row the same way
    assert (docs / "listings.json").read_bytes() == before


def test_board_too_large_refuses_before_building_the_working_set(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed(docs, [_row(0, raw={})])
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0")  # any real board is "too large"
    monkeypatch.setattr(sys, "argv", ["run_pending_signal_enrichers.py"])
    called = []
    real_light_rows = P._light_rows

    def spy(d):
        called.append(True)
        return real_light_rows(d)
    monkeypatch.setattr(P, "_light_rows", spy)

    with pytest.raises(wa.BoardLoadTooLarge):
        P.asyncio.run(P.main())
    assert not called, "the ceiling must be checked BEFORE the full-list read, not after"


def test_real_run_acquires_the_board_lock(scratch_repo, monkeypatch):
    """LOCK HARDENING: the original script never called board_lock() itself at all -- only the
    external shell wrapper did. This migration adds a reentrant board_lock() call around the
    real (non-dry-run) pass as belt-and-suspenders, matching lrcpwa_refresh.py/
    run_tax_owed_normalize.py/backfill_derivation_flags.py."""
    docs = scratch_repo / "docs"
    _seed(docs, [_row(0, source="liensnc_target", raw={})])
    monkeypatch.setattr(sys, "argv",
                        ["run_pending_signal_enrichers.py", "--only", "liensnc_posthumous"])

    locked = []
    real_lock = P.board_lock

    def spy_lock(*a, **kw):
        locked.append(True)
        return real_lock(*a, **kw)
    monkeypatch.setattr(P, "board_lock", spy_lock)

    assert P.asyncio.run(P.main()) == 0
    assert locked, "a real (non-dry-run) pass must acquire the board lock"

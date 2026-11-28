"""resolve()'s retry-on-torn-read (board_parts.py, audit 2026-11-28).

write_parts()'s commit loop replaces ~56 part files one rename at a time -- atomic per file,
not atomic as a set -- before its caller seals the new state by writing a fresh manifest. A
reader resolving the board in that gap sees a manifest that no longer matches a few of the
files it names: BoardIntegrityError. Live on the VM (2026-11-28, 6 concurrent lanes, disk at
89%) that gap was not sub-second the way a bare rename loop suggests -- it tracked how long the
writer's own commit-loop-then-manifest-write actually took under real contention, up to ~100s
observed. resolve() now retries specifically on that signature (_TornPartsError) with capped
exponential backoff, re-reading the manifest fresh each attempt, before it is allowed to escape
as BoardIntegrityError exactly as before. These tests patch the retry constants down to
milliseconds so they stay fast while exercising the real retry loop, not a shortcut around it.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from foreclosure_scraper import board_parts as bp


def _make_board(docs: Path, n_rows: int = 5) -> dict:
    docs.mkdir(parents=True, exist_ok=True)
    blobs = [json.dumps({"i": i}).encode() for i in range(n_rows)]
    result = bp.write_parts(docs, blobs)
    manifest = {
        "schema": bp.MANIFEST_SCHEMA,
        "files": {},
        "parts": bp.make_block(result["entries"], rows_per_part=result["rows_per_part"],
                                cap=result["cap"]),
    }
    (docs / bp.MANIFEST_NAME).write_text(json.dumps(manifest))
    return manifest


def _corrupt_one_part_size(manifest: dict) -> dict:
    torn = json.loads(json.dumps(manifest))
    torn["parts"]["files"][0]["bytes"] += 999999
    return torn


@pytest.fixture
def fast_retry(monkeypatch):
    """The real retry loop, at a speed a test suite can afford."""
    monkeypatch.setattr(bp, "_TORN_READ_RETRIES", 5)
    monkeypatch.setattr(bp, "_TORN_READ_BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(bp, "_TORN_READ_BACKOFF_CAP_S", 0.01)


def test_happy_path_has_no_retry_overhead(tmp_path, fast_retry):
    docs = tmp_path / "docs"
    _make_board(docs)
    t0 = time.time()
    res = bp.resolve(docs)
    dt = time.time() - t0
    assert res is not None and res.source == "manifest"
    assert dt < 0.05, f"a clean read must not pay any retry cost, took {dt:.3f}s"


def test_torn_read_that_heals_mid_retry_succeeds(tmp_path, fast_retry):
    docs = tmp_path / "docs"
    manifest = _make_board(docs)
    good_text = json.dumps(manifest)
    (docs / bp.MANIFEST_NAME).write_text(json.dumps(_corrupt_one_part_size(manifest)))

    def heal():
        time.sleep(0.03)  # a couple of fast-retry sleeps in, well before the budget exhausts
        (docs / bp.MANIFEST_NAME).write_text(good_text)

    healer = threading.Thread(target=heal)
    healer.start()
    res = bp.resolve(docs)  # must NOT raise -- a retry should pick up the healed manifest
    healer.join()
    assert res is not None and res.source == "manifest"


def test_permanently_torn_read_still_raises_after_the_budget(tmp_path, fast_retry):
    docs = tmp_path / "docs"
    manifest = _make_board(docs)
    (docs / bp.MANIFEST_NAME).write_text(json.dumps(_corrupt_one_part_size(manifest)))

    with pytest.raises(bp.BoardIntegrityError, match="torn or mixed"):
        bp.resolve(docs)


def test_non_contiguous_disk_parts_raises_immediately_no_retry(tmp_path, fast_retry, monkeypatch):
    """A different BoardIntegrityError (no manifest, no run_meta, non-contiguous parts on disk)
    must not be retried -- re-checking it cannot help, and retrying could mask a real bug."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True)
    import gzip
    for name in ("listings_part_000.json.gz", "listings_part_002.json.gz"):
        with gzip.open(docs / name, "wb") as fh:
            fh.write(b"[]")
    monkeypatch.setenv("BOARD_PARTS_ALLOW_UNLISTED", "1")

    t0 = time.time()
    with pytest.raises(bp.BoardIntegrityError) as exc_info:
        bp.resolve(docs)
    dt = time.time() - t0
    assert not isinstance(exc_info.value, bp._TornPartsError)
    assert dt < 0.05, f"a non-contiguous-parts failure must raise immediately, took {dt:.3f}s"


def test_explicit_man_on_first_attempt_matches_pre_retry_behavior(tmp_path, fast_retry):
    """A caller that already has a parsed manifest in hand (man=...) must get identical
    behavior to before this retry existed when nothing is actually torn: attempt 0 uses
    exactly the object passed in, no extra disk read."""
    docs = tmp_path / "docs"
    manifest = _make_board(docs)
    res = bp.resolve(docs, man=manifest)
    assert res is not None and res.source == "manifest"

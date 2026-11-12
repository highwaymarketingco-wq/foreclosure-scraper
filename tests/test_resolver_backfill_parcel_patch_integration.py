"""scripts/resolver_backfill_parcel.py's board-I/O rewrite (2026-09-29): it used to call
load_board() to build its full-board `rows` list and write_artifact(rows, ...) at every
checkpoint -- exactly the double materialization BOARD_LOAD_MAX_SOURCE_MB now refuses on the
real ~217K-row board, which is what left this script BLOCKED. This test proves the new
board-read (board_stream.iter_board_rows() + a cheap pre-filter, only validating the small
survivor set into real Listings) and board-write (web_artifact.patch_existing_rows(), only the
resolved handful) mechanism works correctly end-to-end, without touching the real board, the
network, or the ArcGIS resolver -- enrich_parcel_from_geo() is replaced with a small fake that
mimics its exact contract (mutate li.parcel_id + li.raw['parcel_from_geo'] in place on some of
its targets, return {queried, resolved}), since a real resolver run is explicitly out of scope
here (see the task this file was written for).

Covers:
  1. _collect_targets() finds exactly the rows that need resolving (no parcel_id, NC/SC, county
     set, lat/lon in the footprint box) and skips everything else, without ever calling
     load_board().
  2. main() end-to-end: resolved leads land on the board via patch_existing_rows() (not
     write_artifact()), unresolved ones are left alone, and rows outside the target filter are
     completely untouched.
  3. The mid-run checkpoint path (patch_existing_rows() called between chunks, not just at the
     end) fires and lands partial progress.
  4. dry-run never touches the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import resolver_backfill_parcel as rb  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

# Inside enrichment_parcel_from_geo's own footprint box (_LAT_MIN/_MAX, _LON_MIN/_MAX).
IN_BOX = dict(latitude=35.2, longitude=-81.1)
OUT_OF_BOX = dict(latitude=10.0, longitude=-40.0)


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               parcel_id=None, street_address=f"{i + 1} Main St", zip_code="28052",
               raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0, **IN_BOX),                                        # target: resolvable
        _row(1, **IN_BOX),                                        # target: resolvable
        _row(2, **IN_BOX),                                        # target: stays unresolved
        _row(3, parcel_id="P-ALREADY", **IN_BOX),                 # already has a parcel: skip
        _row(4, state="VA", **IN_BOX),                            # wrong state: skip
        _row(5, county=None, **IN_BOX),                           # no county: skip
        _row(6, **OUT_OF_BOX),                                    # outside the footprint: skip
    ]
    wa.write_artifact(rows, {"notes": "resolver integration seed"}, docs_dir=docs)
    return rows


async def _fake_resolve_even_indices(chunk: list[Listing], concurrency: int = 8) -> dict:
    """Mimics enrich_parcel_from_geo()'s exact contract without any network call: resolves
    every OTHER target in the chunk (even position), leaves the rest untouched -- so both the
    'patched' and 'still missing' paths get exercised in one pass."""
    counts = {"queried": len(chunk), "resolved": 0}
    for i, li in enumerate(chunk):
        if i % 2 == 0:
            li.parcel_id = f"PARCEL-{li.street_address.split()[0]}"
            li.raw["parcel_from_geo"] = {"source": "fake_test", "lat": li.latitude,
                                         "lng": li.longitude}
            counts["resolved"] += 1
    return counts


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    """Redirect the script's own REPO (and therefore its board-lock dir and its docs dir) to
    an isolated tmp tree -- resolver_backfill_parcel.py computes `docs = REPO / "docs"` and
    `board_lock(REPO, ...)` at call time inside main(), both reading the (now monkeypatched)
    module-level REPO, so nothing else needs to change to make this safe to run repeatedly and
    never touch the real repo's lock or board."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(rb, "REPO", repo)
    monkeypatch.setattr(rb, "enrich_parcel_from_geo", _fake_resolve_even_indices)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_collect_targets_finds_exactly_the_rows_needing_resolution(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    targets = rb._collect_targets(docs)
    assert {li.street_address for li in targets} == {
        seed[0].street_address, seed[1].street_address, seed[2].street_address,
    }


def test_main_patches_resolved_rows_and_leaves_everything_else_alone(scratch_repo, monkeypatch, capsys):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.setattr(sys, "argv", ["resolver_backfill_parcel.py"])

    rc = rb.main()
    assert rc == 0

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li for li in rows}

    # _fake_resolve_even_indices resolves chunk positions 0 and 2 (i % 2 == 0) of the 3-item
    # chunk [seed[0], seed[1], seed[2]] (board order == target order here) -- i.e. seed[0] and
    # seed[2] resolve, seed[1] is left unresolved, exercising both outcomes in one run.
    for s in (seed[0], seed[2]):
        resolved = by_addr[s.street_address]
        assert resolved.parcel_id == f"PARCEL-{s.street_address.split()[0]}"
        assert resolved.raw.get("parcel_from_geo", {}).get("source") == "fake_test"

    unresolved = by_addr[seed[1].street_address]
    assert unresolved.parcel_id is None

    # rows outside the target filter must be completely untouched
    assert by_addr[seed[3].street_address].parcel_id == "P-ALREADY"
    assert by_addr[seed[4].street_address].parcel_id is None
    assert by_addr[seed[4].street_address].state == "VA"
    assert by_addr[seed[6].street_address].parcel_id is None

    out = capsys.readouterr().out
    assert "still missing parcel_id (in-box NC/SC): 1" in out   # seed[2], the odd-indexed target


def test_checkpoint_fires_mid_run_via_patch_existing_rows_not_write_artifact(
        scratch_repo, monkeypatch):
    """Force multiple small chunks with a checkpoint after every chunk (CHUNK_SIZE=1,
    CHECKPOINT_EVERY=1) and assert patch_existing_rows() actually lands a partial result before
    the run ends -- proving the mid-run write path is real, not just the final flush."""
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.setattr(rb, "CHUNK_SIZE", 1)
    monkeypatch.setattr(rb, "CHECKPOINT_EVERY", 1)

    calls: list[dict] = []
    real_patch = wa.patch_existing_rows

    def counting_patch(patches, summary, docs_dir):
        calls.append(dict(patches))
        return real_patch(patches, summary, docs_dir=docs_dir)

    monkeypatch.setattr(rb, "patch_existing_rows", counting_patch)
    monkeypatch.setattr(sys, "argv", ["resolver_backfill_parcel.py"])

    rc = rb.main()
    assert rc == 0
    # 3 targets, CHUNK_SIZE=1 -> 3 chunks; the fake resolver resolves chunk-position 0 (i%2==0)
    # of each 1-item chunk, i.e. every chunk resolves its one lead -- 3 checkpoint calls, one per
    # chunk, each carrying exactly one patch.
    assert len(calls) == 3
    assert all(len(c) == 1 for c in calls)

    rows = wa.load_board(docs)
    # Identify rows resolved BY THIS RUN specifically (not seed[3]'s pre-existing "P-ALREADY")
    # via the fake resolver's own provenance marker.
    newly_resolved = {li.street_address for li in rows
                      if li.raw.get("parcel_from_geo", {}).get("source") == "fake_test"}
    assert newly_resolved == {seed[0].street_address, seed[1].street_address,
                              seed[2].street_address}


def test_dry_run_never_writes_the_board(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    before = (docs / "listings.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["resolver_backfill_parcel.py", "--dry-run"])

    rc = rb.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before

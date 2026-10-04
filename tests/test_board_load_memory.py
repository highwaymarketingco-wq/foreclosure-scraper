"""audit O13's real fix (2026-09-29): load_board()/read_board_records() used to do a plain
json.loads() of the whole board file, THEN (for load_board()) build a completely separate
Listing-validation graph from it, both alive in memory at the same time. Against the real
board (217,773 rows, 2.52 GB listings.json + 249 MB listings_detail.json) that combination
measured at 26.3 GB peak RSS and never finished; see BoardLoadTooLarge's and
web_artifact._iter_board_records's docstrings for the full incident.

The fix streams both files (board_parts.iter_plain_rows / iter_gz_rows / iter_rows: an
incremental JSON-array decoder that never holds the whole file's text or the whole parsed
list in memory at once) and merges the lazy-detail sidecar in as rows arrive, so load_board()
validates each row into a Listing and lets the raw dict become garbage immediately, rather
than keeping a full list[dict] alive for the whole pass.

These tests demonstrate the improvement is real, not just structurally different:

  1. test_load_board_traces_meaningfully_less_memory_than_the_old_double_materialization runs
     a faithful reconstruction of the OLD (pre-audit-O13) implementation and the CURRENT
     load_board() against the SAME synthetic board, in the SAME process, and compares
     tracemalloc's traced peak for each. tracemalloc is used instead of resource.getrusage/RSS
     because this machine (an 8 GB Mac that runs other things during a normal session --
     CLAUDE.md's memory-safety notes) is often under enough background memory pressure that
     OS-level RSS for a subprocess varies run to run (observed: +/-15% between trials at this
     test's scale from macOS's own memory compression alone) -- tracemalloc's counts are exact
     Python-allocator byte counts and were observed bit-for-bit IDENTICAL across repeated
     trials in a quick probe, which is what a non-flaky assertion needs.

  2. test_open_board_source_rows_is_lazy_not_an_eager_full_read proves the new reader really
     is a streaming generator (cheap to open, proportional-to-size to drain), which is WHY the
     memory result in (1) holds -- an eager reader could not show that gap no matter what was
     done with its result afterward.

WHY THE MEASURED RATIO HERE (~25-30% less peak) IS SMALLER THAN THE REAL INCIDENT'S 26.3 GB:
at this test's safe, moderate scale, a pydantic Listing's own per-row overhead is a big enough
share of the total that removing the SECOND (raw dict) copy is a real but partial win, not a
2x-or-more one. At the real board's scale (217,773 rows) the old code did not just use ~2x the
memory -- it measured GC-thrashing (RSS oscillating in a sawtooth, never completing in 240s),
which is a super-linear pathology from the garbage collector repeatedly re-scanning a huge,
long-lived object graph as hundreds of thousands of ephemeral parse allocations churn around
it. Streaming avoids that pathology by design (each row's raw dict is short-lived, gen0
garbage, never added to the huge long-lived graph the collector has to re-walk), which a
linear small-scale test cannot reproduce -- it can only show that the STRUCTURAL double-copy
this fix removes is real and measurable, which is what it does.

A moderate row count and payload (not the real board's 217K rows / 2.5GB) is used deliberately
so this test is safe to run unattended, including inside a full-suite run. The real-board-scale
measurement (subset loads at 20K/60K/120K rows, extrapolated to 217K) is recorded where
BOARD_LOAD_MAX_SOURCE_MB is set, in web_artifact.py -- run by hand, once, under close memory
monitoring, not as an automated test.
"""
from __future__ import annotations

import gc
import json
import shutil
import time
import tracemalloc
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.board_persist import merge_prior_board as new_merge_prior_board
from foreclosure_scraper.models import Listing, ListingType

# Large enough for the fixed per-row overhead of a pydantic Listing (independent of payload
# size) to stop dominating the comparison, so the double-materialization this fix removes shows
# up clearly; small enough (~350-400 MB on disk) to be safe to allocate on an 8 GB Mac that may
# be running other things at the same time (CLAUDE.md's memory-safety notes). The padding size
# is chosen, not incidental: pad=6000 chars x ~4 padded fields approximates the real board's
# ~11.5 KB average raw-JSON-per-row (2.52 GB + 249 MB over 217,773 rows), because a smaller,
# unrealistically thin payload understates the win a real board actually gets.
N_ROWS = 10_000
PAD_LEN = 6_000


def _fat_lead(i: int) -> Listing:
    """A synthetic row shaped like a real one: some RAW_KEEP-whitelisted top-level detail
    (grade/calc/skip_trace -- stays in listings.json) plus a LAZY_DETAIL_KEYS block (comps --
    moves to listings_detail.json, index-aligned), padded to a realistic per-row size."""
    pad = "x" * PAD_LEN
    return Listing(
        source=f"src.{i % 3}", source_url=f"https://example.test/u{i}",
        listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
        parcel_id=f"P{i}", street_address=f"{i} Main St",
        raw={
            "grade": {"overall": "B", "notes": pad},
            "calc": {"arv": 200000 + i, "rehab": 30000, "max_bid": 140000, "notes": pad},
            "skip_trace": {"owner": f"Owner {i}", "phone": "555-0100", "notes": pad},
            "comps": [{"addr": f"{i} Elm St", "sold_price": 190000 + i, "notes": pad}
                      for _ in range(3)],
        },
    )


@pytest.fixture(scope="module")
def big_board(tmp_path_factory):
    docs = tmp_path_factory.mktemp("big_board") / "docs"
    wa.write_artifact([_fat_lead(i) for i in range(N_ROWS)], {"notes": "memory test fixture"},
                      docs_dir=docs)
    size_mb = (docs / "listings.json").stat().st_size / (1024 * 1024)
    detail_mb = (docs / "listings_detail.json").stat().st_size / (1024 * 1024)
    assert size_mb > 50, f"fixture board is only {size_mb:.1f} MB -- too small to be meaningful"
    return docs, size_mb, detail_mb


def _old_style_load(docs: Path) -> list[Listing]:
    """A faithful reconstruction of the OLD (pre-audit-O13) read_board_records()/load_board():
    json.loads() the whole file, merge the sidecar by index, THEN build a completely separate
    list of validated Listings from the merged dicts -- both fully alive at once. This is not
    the code under test; it exists only so the CURRENT streaming implementation has something
    real to be measured against."""
    records = json.loads((docs / "listings.json").read_text())
    details = json.loads((docs / "listings_detail.json").read_text())
    for i, rec in enumerate(records):
        if i < len(details) and isinstance(details[i], dict) and details[i]:
            raw = rec.get("raw")
            if isinstance(raw, dict):
                raw.update(details[i])
    return [Listing.model_validate(r) for r in records]


def _traced_peak(fn) -> tuple[int, object]:
    """Run fn() with tracemalloc active, return (peak traced bytes, fn's result). gc.collect()
    before and after so neither call's result nor GC timing pollutes the other's measurement."""
    gc.collect()
    tracemalloc.start()
    try:
        result = fn()
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, result


def test_load_board_traces_meaningfully_less_memory_than_the_old_double_materialization(big_board):
    docs, size_mb, detail_mb = big_board

    old_peak, old_result = _traced_peak(lambda: _old_style_load(docs))
    n_old = len(old_result)
    del old_result
    gc.collect()

    new_peak, new_result = _traced_peak(lambda: wa.load_board(docs))
    n_new = len(new_result)
    del new_result
    gc.collect()

    assert n_old == n_new == N_ROWS, "both loaders must see the same board"

    old_mb = old_peak / (1024 * 1024)
    new_mb = new_peak / (1024 * 1024)

    # Real, not structural: tracemalloc reports ACTUAL bytes the Python allocator handed out
    # during each call, not an inference from the code's shape. 0.85 is a deliberately loose
    # threshold relative to what was actually measured while tuning this test (~0.72-0.75) --
    # this asserts the improvement is real and comfortably reproducible, without pinning an
    # exact ratio that would make the test brittle to unrelated future changes.
    assert new_mb < old_mb * 0.85, (
        f"streaming load_board() ({new_mb:.0f} MB traced peak) should use meaningfully less "
        f"memory than the old double-materialization ({old_mb:.0f} MB traced peak) on a "
        f"{size_mb:.0f} MB + {detail_mb:.0f} MB board of {N_ROWS:,} rows -- "
        f"the improvement did not show up as expected"
    )


def test_open_board_source_rows_is_lazy_not_an_eager_full_read(big_board):
    """Proves _open_board_source_rows() -- what load_board()/read_board_records() now use in
    place of the old eager _read_board_json_ex() -- really is a streaming generator: opening it
    is cheap regardless of file size, and the bulk of the size-proportional cost only appears
    once the iterator is actually drained. This is WHY the peak-memory result above holds: an
    eager reader could not show this gap no matter what was done with its result afterward."""
    docs, size_mb, _ = big_board
    t0 = time.perf_counter()
    used, rows_iter = wa._open_board_source_rows(docs / "listings.json")
    open_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    rows = list(rows_iter)
    drain_s = time.perf_counter() - t0

    assert len(rows) == N_ROWS
    assert used.exists()
    # "open" is not free -- the manifest-verification path hashes the whole plain file
    # (board_load_size_state / _file_matches_manifest's sha256 check) before handing back the
    # generator, so it IS proportional to file size too. But hashing raw bytes is far cheaper
    # per byte than incrementally decoding JSON and building N_ROWS Listing-shaped dicts, so
    # opening should still be a small fraction of draining (measured on this machine at this
    # scale: 6-8x; 3x is a conservative floor that leaves headroom for a busier run).
    assert open_s * 3 < drain_s, (
        f"opening the row iterator ({open_s:.4f}s) should be meaningfully cheaper than "
        f"draining {size_mb:.0f} MB through it ({drain_s:.4f}s) -- if it isn't, "
        f"_open_board_source_rows stopped being lazy and is reading the file eagerly again"
    )


# ===========================================================================
# append_new_rows() (task_0658b33b, follow-up to the fix above): landing a SMALL number of new
# rows should not need load_board()'s full list[Listing] of the EXISTING rows at all. These
# tests are the append_new_rows() counterpart of the two above: same tracemalloc method, same
# safe synthetic scale (this file's big_board fixture), for the same reason (a deterministic,
# CI-safe number instead of RSS/subprocess measurement that varies under this machine's real
# background load).
#
# THE REAL-BOARD-SCALE NUMBERS (real board slices at 20K/40K rows, via board_parts.iter_plain_rows
# and macOS's `/usr/bin/time -l` peak-footprint, the same way the load_board() ceiling above was
# calibrated) are recorded where BOARD_APPEND_MAX_SOURCE_MB is set, in web_artifact.py -- run by
# hand, once, under close memory monitoring on an 8 GB Mac already under real background load,
# not as an automated test. The headline finding there: skipping Listing.model_validate() ALONE
# was a much smaller win than expected (~5.0x peak-footprint:source-size, barely under
# load_board()'s ~4.4-5.0x); discarding each row's PARSED FORM immediately after re-encoding it
# to bytes, rather than keeping any full-length list of parsed rows alive at all (dict or
# Listing), is what actually cuts the ratio to about half. This test's smaller, synthetic scale
# reproduces that same structural comparison deterministically.
# ===========================================================================

def _fresh_copy(docs: Path, tmp_path_factory) -> Path:
    """An independent copy of `docs` so two destructive measurements (each appends to /
    rewrites its own copy of the board) never share state or interfere with each other or with
    the other tests sharing the module-scoped big_board fixture."""
    dst = tmp_path_factory.mktemp("copy") / "docs"
    shutil.copytree(docs, dst)
    return dst


def _new_lead(pad_len: int = PAD_LEN) -> Listing:
    pad = "x" * pad_len
    return Listing(
        source="src.new", source_url="https://example.test/u_new",
        listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
        parcel_id="P_NEW", street_address="1 New St",
        raw={"grade": {"overall": "A", "notes": pad}},
    )


def test_append_new_rows_traces_meaningfully_less_memory_than_load_board_then_write(
        big_board, tmp_path_factory):
    docs, size_mb, detail_mb = big_board

    def _old_style_apply() -> int:
        """The pattern append_new_rows() replaces: load the WHOLE existing board as Listings,
        append the new one in Python, rewrite the whole board -- run_scoped_scrapers.py's old
        apply_rows() -> write_artifact(existing + fresh, ...)."""
        d = _fresh_copy(docs, tmp_path_factory)
        rows = wa.load_board(d)
        wa.write_artifact(rows + [_new_lead()], {"notes": "old-style append"}, docs_dir=d)
        return len(rows) + 1

    def _new_style_apply() -> int:
        d = _fresh_copy(docs, tmp_path_factory)
        stats = wa.append_new_rows([_new_lead()], {"notes": "new-style append"}, docs_dir=d)
        return stats["total_after"]

    old_peak, old_total = _traced_peak(_old_style_apply)
    gc.collect()
    new_peak, new_total = _traced_peak(_new_style_apply)
    gc.collect()

    assert old_total == new_total == N_ROWS + 1, "both paths must land the same final board"

    old_mb = old_peak / (1024 * 1024)
    new_mb = new_peak / (1024 * 1024)

    # Loose threshold for the same reason as the load_board() comparison above: this asserts a
    # real, reproducible improvement without pinning an exact ratio a future unrelated change
    # could trip. At this synthetic scale the measured margin was much wider than 0.85 (append
    # never builds a single Listing for the EXISTING rows, where load_board() built N_ROWS of
    # them) -- 0.85 leaves headroom without making the assertion toothless.
    assert new_mb < old_mb * 0.85, (
        f"append_new_rows() ({new_mb:.0f} MB traced peak) should use meaningfully less memory "
        f"than load_board()+write_artifact() ({old_mb:.0f} MB traced peak) to land ONE new row "
        f"onto a {size_mb:.0f} MB + {detail_mb:.0f} MB board of {N_ROWS:,} existing rows -- "
        f"the improvement did not show up as expected"
    )


def test_append_new_rows_never_validates_existing_rows_into_listings(big_board, tmp_path_factory,
                                                                      monkeypatch):
    """Structural proof, not just a memory-size inference: patch Listing.model_validate to
    count its calls, then append one new row to a board of N_ROWS existing ones. ZERO calls
    must happen -- the new row arrives already validated (a Listing the caller built), so
    append_new_rows() has no reason to validate it again, and it must never validate any of the
    N_ROWS existing rows either (that is the actual guarantee this function exists to provide;
    the memory result above is a consequence of it, not a separate claim). A regression that
    started re-validating existing rows (e.g. a future edit that routes them through
    load_board()-style logic by mistake) would turn this into N_ROWS calls, not a subtle
    memory-only change that only shows up on the real 217K-row board."""
    docs, _, _ = big_board
    d = _fresh_copy(docs, tmp_path_factory)

    calls = {"n": 0}
    orig_validate = Listing.model_validate.__func__

    def counting_validate(cls, *a, **k):
        calls["n"] += 1
        return orig_validate(cls, *a, **k)

    monkeypatch.setattr(Listing, "model_validate", classmethod(counting_validate))
    stats = wa.append_new_rows([_new_lead()], {"notes": "t"}, docs_dir=d)
    assert stats["written"] is True
    assert calls["n"] == 0, (
        f"append_new_rows() called Listing.model_validate() {calls['n']} times while landing "
        f"1 new row onto {N_ROWS:,} existing ones -- it must never validate ANY row (new rows "
        f"arrive pre-validated; existing rows must never be validated at all)"
    )


# ===========================================================================
# patch_existing_rows() (follow-up to append_new_rows(), 2026-09-29): mutating a SMALL, known
# subset of EXISTING rows in place -- resolver_backfill_parcel.py's real shape -- should not
# need load_board()'s full list[Listing] of the OTHER, untouched rows either. These tests are
# the patch_existing_rows() counterpart of the append_new_rows() section above: same tracemalloc
# method, same safe synthetic scale (this file's big_board fixture), for the same reason.
#
# THE REAL-BOARD-SCALE NUMBERS (synthetic boards sized to the real board's own ~12.7 KB/row
# average -- NOT this file's fatter _fat_lead() padding, which measured too heavy for a clean
# comparison at 20K/40K rows -- patched with ~1,200 pending patches, resolver_backfill_parcel.py's
# real per-checkpoint scale, run as a monitored child process and measured with BOTH RSS (`ps -o
# rss=` polling) AND macOS's real physical footprint (`sample <pid> 1 -f <file>`, the corrected
# methodology after load_board()'s RSS-looked-safe-but-footprint-was-11.1-GB incident) are
# recorded where BOARD_PATCH_MAX_SOURCE_MB is set, in web_artifact.py -- run by hand, once, not
# as an automated test. Headline finding: patch_existing_rows() measured statistically identical
# to append_new_rows() at 20,000 rows (2.39x footprint:source, both) and about 17% LESS
# footprint-efficient at 40,000 rows (2.29x vs append's 1.96x) -- close enough that assuming
# equality would have been a reasonable guess, but not proven, which is exactly why it earned its
# own measured ceiling instead.
# ===========================================================================

def _patch_for(li: Listing) -> dict:
    """A small, well-typed field update -- resolver_backfill_parcel.py's real shape: a resolved
    parcel_id plus a small provenance dict merged into raw, keyed by the row's OWN
    dedupe_key() (computed before any patch, exactly as patch_existing_rows() requires)."""
    return {li.dedupe_key(): {"parcel_id": "P_PATCHED",
                              "raw": {"parcel_from_geo": {"source": "test", "lat": 35.0,
                                                          "lng": -81.0}}}}


def test_patch_existing_rows_traces_meaningfully_less_memory_than_load_board_then_write(
        big_board, tmp_path_factory):
    docs, size_mb, detail_mb = big_board

    def _old_style_patch() -> int:
        """The pattern patch_existing_rows() replaces: load the WHOLE existing board as
        Listings, mutate the one matching row in Python, rewrite the whole board -- the
        load_board() -> mutate -> write_artifact() shape resolver_backfill_parcel.py used
        before this fix."""
        d = _fresh_copy(docs, tmp_path_factory)
        rows = wa.load_board(d)
        rows[0].parcel_id = "P_PATCHED"
        rows[0].raw["parcel_from_geo"] = {"source": "test", "lat": 35.0, "lng": -81.0}
        wa.write_artifact(rows, {"notes": "old-style patch"}, docs_dir=d)
        return len(rows)

    def _new_style_patch() -> int:
        d = _fresh_copy(docs, tmp_path_factory)
        first = wa.load_board(d)[0]      # read once, off the loop, just to get its identity
        stats = wa.patch_existing_rows(_patch_for(first), {"notes": "new-style patch"},
                                       docs_dir=d)
        return stats["total_after"]

    old_peak, old_total = _traced_peak(_old_style_patch)
    gc.collect()
    new_peak, new_total = _traced_peak(_new_style_patch)
    gc.collect()

    assert old_total == new_total == N_ROWS, "both paths must land the same final board"

    old_mb = old_peak / (1024 * 1024)
    new_mb = new_peak / (1024 * 1024)

    # _new_style_patch()'s traced peak includes one load_board() call just to fetch the target
    # row's identity (not part of what patch_existing_rows() itself does -- a real caller like
    # resolver_backfill_parcel.py already has the identity from its own board_stream-based scan,
    # never a full load_board()), so this comparison is already handicapped against
    # patch_existing_rows() and the gap would be wider without that. 0.85 is the same
    # deliberately loose threshold the append_new_rows() comparison above uses.
    assert new_mb < old_mb * 0.85, (
        f"patch_existing_rows() ({new_mb:.0f} MB traced peak) should use meaningfully less "
        f"memory than load_board()+write_artifact() ({old_mb:.0f} MB traced peak) to mutate ONE "
        f"existing row on a {size_mb:.0f} MB + {detail_mb:.0f} MB board of {N_ROWS:,} rows -- "
        f"the improvement did not show up as expected"
    )


MERGE_N_ROWS = 8_000
MERGE_PAD_LEN = 150


def _varied_lead(i: int, pad_len: int = MERGE_PAD_LEN) -> Listing:
    """Shaped like _fat_lead() (same realistic per-row padding), but with county/zip VARIED
    across rows instead of fixed to one ("Gaston"/no zip). dedupe()'s own pass-2 fuzzy match
    blocks candidates by zip and by (county, state) -- see dedupe.py's own "BLOCKING
    OPTIMIZATION" comment: 'Without this, merge_prior_board on 94K+22K hangs for hours'. A
    fixture where EVERY row shares one (county, state) defeats that blocking entirely (the
    whole board becomes one block) and reproduces exactly that hang at this test's scale -- this
    is what _fat_lead()'s OTHER users in this file never hit, because none of them call dedupe()
    at all. Varying county across 40 buckets and zip across 500 keeps each block's candidate set
    small, the way a real board's own geographic spread does."""
    pad = "x" * pad_len
    return Listing(
        source=f"src.{i % 3}", source_url=f"https://example.test/mv{i}",
        listing_type=ListingType.FORECLOSURE_SALE, state="NC", county=f"County{i % 40}",
        zip_code=f"{28801 + (i % 500)}", parcel_id=f"MP{i}", street_address=f"{i} Main St",
        raw={
            "grade": {"overall": "B", "notes": pad},
            "calc": {"arv": 200000 + i, "rehab": 30000, "max_bid": 140000, "notes": pad},
            "skip_trace": {"owner": f"Owner {i}", "phone": "555-0100", "notes": pad},
            "comps": [{"addr": f"{i} Elm St", "sold_price": 190000 + i, "notes": pad}
                      for _ in range(3)],
        },
    )


@pytest.fixture(scope="module")
def merge_board(tmp_path_factory):
    docs = tmp_path_factory.mktemp("merge_board") / "docs"
    wa.write_artifact([_varied_lead(i) for i in range(MERGE_N_ROWS)],
                      {"notes": "merge_prior_board memory test fixture"}, docs_dir=docs)
    size_mb = (docs / "listings.json").stat().st_size / (1024 * 1024)
    detail_mb = (docs / "listings_detail.json").stat().st_size / (1024 * 1024)
    return docs, size_mb, detail_mb


def test_merge_prior_board_traces_meaningfully_less_memory_than_load_board_then_dedupe(
        merge_board):
    """board_persist.merge_prior_board() (2026-10-04 streaming rewrite): folding a fresh scrape
    into the published board used to call load_board() (the WHOLE existing board as Listings)
    and then run dedupe() over a DOUBLED fresh+prior combined list on top of that -- see
    web_artifact.BOARD_PRIOR_MERGE_MAX_SOURCE_MB's comment for the real incident (the Oracle VM
    run that could never get past this step) this rewrite fixes. Same tracemalloc method as the
    append_new_rows()/patch_existing_rows() comparisons above; its own smaller, geographically
    varied fixture (merge_board, not big_board) so the OLD path's real dedupe() call -- the thing
    actually being measured here, unlike every other comparison in this file -- hits dedupe()'s
    zip/locale blocking the way a real board does, instead of degenerating into the O(n^2) fuzzy
    scan _varied_lead()'s own docstring describes.

    fresh here is a realistic MIX, not a single row: HALF share a parcel_id with an existing
    board row (so they actually exercise the matched/merge path, not just pass-through) and HALF
    are brand new -- proportioned like the real pipeline's fresh scrape against a board several
    times its size, scaled down to this fixture's MERGE_N_ROWS."""
    docs, size_mb, detail_mb = merge_board

    def _old_style_merge(fresh) -> list:
        """A faithful reconstruction of the ORIGINAL merge_prior_board(): load the WHOLE prior
        board as Listings, double it into a `fresh + prior` combined list, run dedupe() over
        that combined list. Omits the aging-loop post-processing (cheap, not what this
        comparison is measuring) -- the expensive part being compared is this load+combine+
        dedupe chain, unchanged from what board_persist.py actually did before 2026-10-04."""
        from foreclosure_scraper.dedupe import dedupe
        prior = wa.load_board(docs)
        combined = list(fresh) + list(prior)
        return dedupe(combined)

    def _fresh_batch() -> list[Listing]:
        half = MERGE_N_ROWS // 2
        matched = [
            Listing(source="src.fresh", source_url=f"https://example.test/fresh{i}",
                   listing_type=ListingType.FORECLOSURE_SALE, state="NC",
                   county=f"County{i % 40}", zip_code=f"{28801 + (i % 500)}",
                   parcel_id=f"MP{i}", street_address=f"{i} Main St",
                   raw={"grade": {"overall": "A"}})
            for i in range(0, MERGE_N_ROWS, 2)  # same parcel_id as half the board's rows
        ]
        new = [
            Listing(source="src.fresh", source_url=f"https://example.test/new{i}",
                   listing_type=ListingType.FORECLOSURE_SALE, state="NC",
                   county=f"County{i % 40}", zip_code=f"{28801 + (i % 500)}",
                   parcel_id=f"NEWP{i}", street_address=f"{i} New St",
                   raw={"grade": {"overall": "A"}})
            for i in range(len(matched))
        ]
        return matched + new

    old_peak, old_result = _traced_peak(lambda: _old_style_merge(_fresh_batch()))
    n_old = len(old_result)
    del old_result
    gc.collect()

    new_peak, new_result = _traced_peak(
        lambda: new_merge_prior_board(_fresh_batch(), docs_dir=docs)[0])
    n_new = len(new_result)
    del new_result
    gc.collect()

    # Both paths must land the same final count: MERGE_N_ROWS/2 matched (collapsed to one row
    # each) + MERGE_N_ROWS/2 fresh-only new siblings + MERGE_N_ROWS/2 untouched prior-only rows.
    expected_total = (MERGE_N_ROWS // 2) * 3
    assert n_old == n_new == expected_total, "both paths must land the same final board"

    old_mb = old_peak / (1024 * 1024)
    new_mb = new_peak / (1024 * 1024)

    # Loose threshold for the same reason as the other comparisons in this file: asserts a real,
    # reproducible improvement without pinning an exact ratio a future unrelated change could
    # trip. The streaming rewrite never builds a `combined` list (fresh+prior doubled) or any of
    # dedupe()'s full-board bucket/blocking/union-find structures, so the gap here is expected to
    # be wide; 0.85 leaves headroom without making the assertion toothless.
    assert new_mb < old_mb * 0.85, (
        f"merge_prior_board() ({new_mb:.0f} MB traced peak) should use meaningfully less memory "
        f"than load_board()+dedupe(combined) ({old_mb:.0f} MB traced peak) to fold "
        f"{MERGE_N_ROWS:,} fresh rows (half matched, half new) into a {size_mb:.0f} MB + "
        f"{detail_mb:.0f} MB board of {MERGE_N_ROWS:,} existing rows -- the improvement did not "
        f"show up as expected"
    )


def test_merge_prior_board_never_validates_terminal_rows_into_listings(big_board, tmp_path_factory,
                                                                        monkeypatch):
    """Structural proof, not just a memory-size inference: a prior row that is TERMINAL (dropped
    outright via the aging check: sold_confirmed here) must never be run through
    Listing.model_validate() at all -- the whole point of the streaming rewrite is to not pay
    that cost for a row that never survives into the output. Forces ALL N_ROWS board rows
    terminal (sold_confirmed=True) and fresh to a disjoint, non-matching single new lead, then
    counts Listing.model_validate() calls: zero is required, exactly mirroring append_new_rows's/
    patch_existing_rows's own "never validates untouched rows" tests above."""
    docs = tmp_path_factory.mktemp("terminal_board") / "docs"
    terminal_leads = []
    for i in range(N_ROWS):
        li = _fat_lead(i)
        li.raw["sold_confirmed"] = True
        terminal_leads.append(li)
    wa.write_artifact(terminal_leads, {"notes": "all-terminal fixture"}, docs_dir=docs)

    calls = {"n": 0}
    orig_validate = Listing.model_validate.__func__

    def counting_validate(cls, *a, **k):
        calls["n"] += 1
        return orig_validate(cls, *a, **k)

    monkeypatch.setattr(Listing, "model_validate", classmethod(counting_validate))
    fresh = [_new_lead()]
    out, stats = new_merge_prior_board(fresh, docs_dir=docs)
    assert stats["aged_out_terminal"] == N_ROWS
    assert len(out) == 1
    assert calls["n"] == 0, (
        f"merge_prior_board() called Listing.model_validate() {calls['n']} times while all "
        f"{N_ROWS:,} prior rows were terminal (dropped outright) -- a row that never survives "
        f"into the output must never be validated into a Listing at all"
    )


def test_patch_existing_rows_never_validates_untouched_rows_into_listings(
        big_board, tmp_path_factory, monkeypatch):
    """Structural proof, not just a memory-size inference: patch ONE row on a board of N_ROWS,
    counting Listing.model_validate() calls. ZERO calls must happen -- patch_existing_rows()
    applies the patch's field updates directly to the raw dict for the one row that matches
    (never Listing.model_validate(), per its own docstring) and streams every other row through
    completely unvalidated. A regression that started validating rows while scanning for a
    match (e.g. routing the identity check through model_validate() instead of
    model_construct()) would turn this into N_ROWS calls, not a subtle memory-only change that
    only shows up on the real 217K-row board."""
    docs, _, _ = big_board
    d = _fresh_copy(docs, tmp_path_factory)
    first = wa.load_board(d)[0]
    patches = _patch_for(first)

    calls = {"n": 0}
    orig_validate = Listing.model_validate.__func__

    def counting_validate(cls, *a, **k):
        calls["n"] += 1
        return orig_validate(cls, *a, **k)

    monkeypatch.setattr(Listing, "model_validate", classmethod(counting_validate))
    stats = wa.patch_existing_rows(patches, {"notes": "t"}, docs_dir=d)
    assert stats["written"] is True
    assert stats["applied"] == 1
    assert calls["n"] == 0, (
        f"patch_existing_rows() called Listing.model_validate() {calls['n']} times while "
        f"patching 1 row on a board of {N_ROWS:,} -- it must never validate ANY row (the "
        f"identity check uses model_construct(); the matched patch is applied to the raw dict "
        f"directly; every other row is streamed through untouched)"
    )

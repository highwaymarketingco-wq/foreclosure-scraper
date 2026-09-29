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
import time
import tracemalloc
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
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

"""scripts/board_selfcheck.py — the current-board read, not the stale mobile payload.

THE BUG THIS COVERS (2026-09-30). append_new_rows()/patch_existing_rows() (2026-09-29,
commits 3272b3c0/758d0bb5) are now the write path for essentially all board landings on a
board too big for load_board()/write_artifact() to re-materialize, and both deliberately skip
regenerating docs/listings_slim.json.gz (see their own docstrings: doing so needs the
parsed-dict form of the WHOLE board, exactly the cost these functions exist to avoid).
board_selfcheck.py's `_current()` used to read that same listings_slim.json.gz for its
INVARIANT checks -- the file `board_selfcheck.py` was written to grade -- so every invariant
check run since the first append/patch landing was silently grading a board smaller and older
than the one actually published (confirmed live: 217,773 slim rows vs. 219,530 real rows,
commit ba3e57b3 is the slim file's last regeneration). A run that would have caught a fresh
defect in the un-slimmed rows could not have: it never saw them.

The fix: `_current()` now reads the real board through
foreclosure_scraper.board_stream.iter_board_rows(), the same memory-safe streaming reader
CLAUDE.md requires for board reads. `_previous()` (MOVEMENT only, never invariants) still
reads the committed listings_slim.json.gz via `git show` -- that is unaffected by this bug and
is the only single stable path the full parts-based board has ever had in git history (see
_previous()'s own docstring in the script).

A SECOND BUG THIS COVERS (2026-09-30, same day, later). The fix above still had `_current()`
do `rows = list(iter_board_rows(...))` -- streaming the READ off disk, but then holding every
row (raw payload and all, ~15-20 KB/row measured) in one Python list for the rest of the
script's run. Measured against the real 219,143-row board: 2.3 GB physical footprint after 9
seconds (still climbing), 6.1 GB before a supervised watchdog had to SIGKILL it -- the same
class of multi-GB spike behind a kernel panic on this 8 GB Mac earlier the same night, and
exactly the "materialize the whole board" pattern CLAUDE.md and board_stream.py's own
docstring warn against. `_current()` is now a GENERATOR (never a list), `invariants()` streams
its input in a single pass with only small bounded per-row state (a handful of counters, plus
one dict of identifier -> [addresses] for the duplicate check), and `movement()` consumes
small per-row summaries (`_light_row()`) built as a side effect of that same pass (`_tee()`)
rather than full rows -- so main() makes ONE streaming pass over the live board, never holding
more than a bounded amount of small state, let alone a second full copy of it.

Because `_current()` is now a generator, tests that need a count or a container wrap it in
`list(...)` themselves -- that's fine at test scale (a handful to a few dozen rows); it is
exactly what the rewrite avoids at real-board scale (219k rows).

This module loads scripts/board_selfcheck.py by file path (it is a script, not a package
module) via importlib, the same pattern tests/test_publish_plumbing.py uses for
check_pages_publish.py.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
import types
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.board_stream import iter_board_rows
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


def _load_selfcheck():
    spec = importlib.util.spec_from_file_location(
        "board_selfcheck", SCRIPTS / "board_selfcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i % 2}", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
                parcel_id=f"P{i}", street_address=f"{i} Main St",
                raw={"grade": {"overall": "B"}})
    base.update(kw)
    return Listing(**base)


# ===========================================================================
# 1. _current() reads the LIVE board, not the stale slim payload
# ===========================================================================

def test_current_reads_the_real_board_not_the_stale_slim_payload(tmp_path):
    """The exact scenario that shipped stale: write a 5-row board (slim regenerated
    to match), then append 3 more rows the way append_new_rows() does in production
    -- which by design leaves listings_slim.json.gz at 5. _current() must report 8,
    the real count, not 5."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)

    slim_before = json.loads(gzip.decompress((docs / "listings_slim.json.gz").read_bytes()))
    assert len(slim_before) == 5, "sanity: the seed write regenerated slim to match"

    stats = wa.append_new_rows([_lead(100), _lead(101), _lead(102)], {"notes": "t"},
                                docs_dir=docs)
    assert stats["written"] is True
    assert stats["total_after"] == 8

    # The documented, disclosed gap: append_new_rows() does NOT touch slim.
    slim_after = json.loads(gzip.decompress((docs / "listings_slim.json.gz").read_bytes()))
    assert len(slim_after) == 5, (
        "if this fails, append_new_rows() started regenerating slim and the "
        "board_selfcheck comments/tests describing it as stale need updating too"
    )

    mod = _load_selfcheck()
    mod.DOCS = docs
    current = list(mod._current())
    assert len(current) == 8, (
        "_current() read the stale slim payload (5) instead of the real board (8) -- "
        "this is the exact bug: every invariant check would silently run against an "
        "undercounted, out-of-date board"
    )
    # And it must be the SAME rows iter_board_rows() gives a caller directly -- not some
    # independent re-derivation that happens to agree on count.
    assert len(current) == len(list(iter_board_rows(docs / "listings.json.gz")))


def test_current_is_a_generator_not_a_materialized_list(tmp_path):
    """The 2026-09-30 memory fix: _current() must never hold the whole board in a list. A
    plain function call returns a generator (no row has been read yet); nothing executes,
    and no memory beyond the generator frame itself is used, until a caller actually iterates
    it. This is the property that makes ONE streaming pass over a 219k-row board bounded."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)
    mod = _load_selfcheck()
    mod.DOCS = docs
    result = mod._current()
    assert isinstance(result, types.GeneratorType), (
        "_current() must return a generator (streamed lazily), not a list built eagerly -- "
        "a list is exactly the pattern that measured 2.3-6.1 GB on the real board"
    )
    assert len(list(result)) == 5


def test_current_matches_slim_when_no_append_or_patch_has_happened(tmp_path):
    """Immediately after a full write_artifact() the two ARE the same size -- the bug only
    shows up once append_new_rows()/patch_existing_rows() runs. This pins the non-buggy case
    so a future change cannot "fix" the count by coincidence."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(5)], {"notes": "seed"}, docs_dir=docs)
    mod = _load_selfcheck()
    mod.DOCS = docs
    assert len(list(mod._current())) == 5


def test_current_raises_a_clear_error_on_an_empty_board(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    mod = _load_selfcheck()
    mod.DOCS = docs
    # _current() is a generator: calling it raises nothing (no row has been read yet). The
    # error only surfaces once a caller actually pulls the first item -- exercised here via
    # list(), the same way invariants()'s own streaming loop would trigger it in production.
    with pytest.raises(SystemExit):
        list(mod._current())


def test_current_raises_on_a_torn_parts_set_rather_than_silently_undercounting(tmp_path):
    """A parts board whose manifest disagrees with what is on disk must fail loudly (the
    codebase's own standing rule: never silently accept a smaller/wrong board), not be
    swallowed into an empty or partial read."""
    docs = tmp_path / "docs"
    wa.write_artifact([_lead(i) for i in range(30)], {"notes": "seed"}, docs_dir=docs)
    manifest_path = docs / "board.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # Corrupt one part's recorded size so verify_dir/resolve() must raise.
    manifest["parts"]["files"][0]["bytes"] += 1
    manifest_path.write_text(json.dumps(manifest))

    mod = _load_selfcheck()
    mod.DOCS = docs
    with pytest.raises(SystemExit):
        list(mod._current())


# ===========================================================================
# 2. invariants() over the shape iter_board_rows() actually yields
#
# (board_selfcheck.py had no test file at all before this one.) These rows are the
# _to_dict()/RAW_KEEP shape -- top-level parcel_id/street_address/county plus a whole
# raw.calc / raw.equity block -- not the further-projected SLIM-V1 shape. Both keep
# calc and equity whole ("*" in both RAW_KEEP and _SLIM_RAW), which is exactly why the
# ORIGINAL _current() fix needed no change to invariants()/movement()'s ROW SHAPE handling.
#
# invariants() itself WAS rewritten the same day (see the module docstring's "SECOND BUG")
# to stream `board` in a single bounded pass instead of taking a fully-materialized list --
# it still accepts any iterable (a plain list here, a generator in production), so every test
# below is unchanged in what it asserts; it is exercising the new streaming implementation
# through the exact same public call shape the old one had.
# ===========================================================================

def _row(parcel_id: str, calc: dict, equity_value=None) -> dict:
    raw = {"calc": calc}
    if equity_value is not None:
        raw["equity"] = {"value": equity_value}
    return {"parcel_id": parcel_id, "street_address": "1 Main St", "county": "Gaston",
            "state": "NC", "source": "test", "case_number": None, "raw": raw}


def test_contradicted_arv_carrying_a_max_bid_is_flagged(tmp_path):
    mod = _load_selfcheck()
    flag = next(iter(mod.CONTRADICTED))
    board = [_row("P1", {"arv_flags": [flag], "max_bid_70": 150_000})]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no max_bid_70 on a contradicted ARV"]
    assert entry["count"] == 1
    assert entry["ok"] is False


def test_clean_board_breaches_nothing(tmp_path):
    mod = _load_selfcheck()
    board = [_row("P1", {"arv_expected": 200_000, "max_bid_70": 140_000}, equity_value=50_000)]
    inv = mod.invariants(board)
    assert all(i["ok"] for i in inv), [i for i in inv if not i["ok"]]


def test_duplicate_parcel_rows_are_counted_once_each_over_the_limit(tmp_path):
    mod = _load_selfcheck()
    board = [_row("DUP1", {}), _row("DUP1", {})]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no duplicate identifiable properties"]
    assert entry["count"] == 1
    assert entry["ok"] is False


def test_invariants_accepts_a_generator_not_just_a_list(tmp_path):
    """The whole point of the rewrite: invariants() must work identically whether handed a
    plain list (as every test above does) or a one-shot generator (as main() now hands it via
    _tee(_current(), ...)). Same board, same two contradicted-ARV rows, fed once as a list and
    once as a generator -- results must be byte-identical."""
    mod = _load_selfcheck()
    flag = next(iter(mod.CONTRADICTED))
    rows = [_row("P1", {"arv_flags": [flag], "max_bid_70": 150_000}),
            _row("P2", {"arv_expected": 200_000, "max_bid_70": 140_000}, equity_value=50_000)]

    from_list = mod.invariants(list(rows))
    from_generator = mod.invariants(r for r in rows)
    assert from_list == from_generator


def test_fusion_threshold_excludes_placeholder_parcel_from_duplicate_count(tmp_path):
    """A parcel_id shared by FUSION_THRESHOLD (4)+ DISTINCT street addresses is a
    fused/placeholder identifier in the source data, not four duplicate rows -- must be
    reported separately (fused_keys/fused_rows) and NOT added to the breaching dupe count.
    Pins the exact behaviour scripts/run_duplicate_merge_20260930.py's docstring documents."""
    mod = _load_selfcheck()
    assert mod.FUSION_THRESHOLD == 4
    # a VALID parcel id (identity.ident_key: 7+ characters); 'MASTER' would name no parcel at all
    board = [
        {**_row("3208-90-5620-0000", {}), "street_address": f"{n} Distinct Rd"} for n in range(1, 5)
    ]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no duplicate identifiable properties"]
    assert entry["count"] == 0, "4 distinct addresses under one parcel must NOT count as dupes"
    assert entry["ok"] is True
    assert entry["fused_keys"] == 1
    assert entry["fused_rows"] == 4


def test_rows_with_no_parcel_and_no_numbered_address_are_excluded_not_flagged(tmp_path):
    """A lead with neither a parcel_id nor a street number (e.g. 'SR 1135') cannot be judged
    either way -- it must be silently excluded from the duplicate check, never counted as a
    breach just because several such rows happen to share nothing in particular."""
    mod = _load_selfcheck()
    unidentifiable = {"parcel_id": None, "street_address": "SR 1135", "county": "McDowell",
                       "state": "NC", "source": "test", "case_number": None,
                       "raw": {"calc": {}}}
    board = [unidentifiable, unidentifiable, unidentifiable]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no duplicate identifiable properties"]
    assert entry["count"] == 0
    assert entry["ok"] is True
    assert "3 leads carry no" in entry["why"] or "3" in entry["why"]


def test_arv_over_2m_without_flags_is_flagged(tmp_path):
    mod = _load_selfcheck()
    board = [_row("BIG1", {"arv_expected": 2_500_000})]  # no arv_flags at all
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["every ARV over $2M carries a flag"]
    assert entry["count"] == 1
    assert entry["ok"] is False


def test_arv_over_2m_with_max_bid_is_flagged(tmp_path):
    mod = _load_selfcheck()
    board = [_row("BIG2", {"arv_expected": 2_500_000, "max_bid_70": 1_000_000,
                            "arv_flags": ["some_flag"]})]
    inv = {i["name"]: i for i in mod.invariants(board)}
    entry = inv["no max bid on an ARV over $2M"]
    assert entry["count"] == 1
    assert entry["ok"] is False


def test_contradicted_arv_deal_verdict_and_equity_are_flagged(tmp_path):
    mod = _load_selfcheck()
    flag = next(iter(mod.CONTRADICTED))
    board = [_row("P1", {"arv_flags": [flag], "deal_status": "GREAT"}, equity_value=75_000)]
    inv = {i["name"]: i for i in mod.invariants(board)}
    assert inv["no deal verdict on a contradicted ARV"]["count"] == 1
    assert inv["no equity on a contradicted ARV"]["count"] == 1


# ===========================================================================
# 3. _light_row() / _tee() / movement() -- the bounded-memory MOVEMENT path
#
# main() no longer hands movement() full board rows; it hands it _light_row() summaries built
# as a side effect of the SAME streaming pass invariants() makes (via _tee()). These tests
# pin that the light-row projection carries everything movement() needs, and that movement()
# on light rows gives the same shape of answer the old full-row version did.
# ===========================================================================

def test_light_row_extracts_key_address_and_money_fields(tmp_path):
    mod = _load_selfcheck()
    row = _row("P1", {"arv_expected": 300_000, "max_bid_70": 200_000, "roi_pct": 0.22,
                       "estimated_profit": 40_000, "wholesale_mao": 180_000})
    light = mod._light_row(row)
    assert light["key"] == mod._key(row)
    assert light["street_address"] == "1 Main St"
    assert light["arv_expected"] == 300_000
    assert light["max_bid_70"] == 200_000
    assert light["roi_pct"] == 0.22
    assert light["estimated_profit"] == 40_000
    assert light["wholesale_mao"] == 180_000
    # Nothing else from the row survives -- in particular no `raw` blob.
    assert set(light.keys()) == {"key", "street_address", "arv_expected",
                                  "max_bid_70", "roi_pct", "estimated_profit", "wholesale_mao"}


def test_tee_counts_rows_and_builds_light_rows_while_passing_them_through(tmp_path):
    mod = _load_selfcheck()
    board = [_row("P1", {"arv_expected": 100_000}), _row("P2", {"arv_expected": 200_000})]
    count_sink: list = []
    light_sink: list = []
    passed_through = list(mod._tee(iter(board), count_sink, light_sink))
    assert passed_through == board, "_tee() must yield every row unchanged"
    assert count_sink == [2]
    assert len(light_sink) == 2
    assert light_sink[0]["arv_expected"] == 100_000
    assert light_sink[1]["arv_expected"] == 200_000


def test_movement_on_light_rows_reports_new_matched_and_dropped(tmp_path):
    mod = _load_selfcheck()
    prev = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 70_000}),
            _row("P2", {"arv_expected": 200_000, "max_bid_70": 140_000})]
    # P1 unchanged, P2 gone (dropped), P3 new.
    cur_full = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 70_000}),
                _row("P3", {"arv_expected": 300_000, "max_bid_70": 210_000})]
    cur_light = [mod._light_row(r) for r in cur_full]

    mv = mod.movement(cur_light, prev)
    assert mv["prev_count"] == 2
    assert mv["curr_count"] == 2
    assert mv["matched"] == 1
    assert mv["new"] == 1
    assert mv["dropped"] == 1
    assert mv["changed"]["arv_expected"] == 0  # P1's arv_expected did not move


def test_movement_detects_a_changed_money_field_on_a_matched_lead(tmp_path):
    mod = _load_selfcheck()
    prev = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 70_000})]
    cur_full = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 90_000})]  # max_bid moved
    cur_light = [mod._light_row(r) for r in cur_full]

    mv = mod.movement(cur_light, prev)
    assert mv["matched"] == 1
    assert mv["changed"]["max_bid_70"] == 1
    assert mv["changed"]["arv_expected"] == 0


def test_movement_big_arv_move_is_reported(tmp_path):
    mod = _load_selfcheck()
    prev = [_row("P1", {"arv_expected": 100_000})]
    cur_full = [_row("P1", {"arv_expected": 250_000})]  # 2.5x -- over the >=2x threshold
    cur_light = [mod._light_row(r) for r in cur_full]

    mv = mod.movement(cur_light, prev)
    assert len(mv["largest_arv_moves"]) == 1
    assert mv["largest_arv_moves"][0]["from"] == 100_000
    assert mv["largest_arv_moves"][0]["to"] == 250_000


# ===========================================================================
# 4. Old (list-based) vs new (streaming) implementation must agree exactly.
#
# This pins the correctness-preservation requirement directly: an independent, deliberately
# naive re-implementation of the OLD full-row-list invariants() logic (kept verbatim in spirit
# -- group full rows by identifier, don't stream) run against the same random-ish synthetic
# board as the new streaming invariants(), on every invariant, including the duplicate/fusion
# counts. If a future edit to the streaming version drifts from the original semantics, this
# is what catches it without needing the real 219k-row board.
# ===========================================================================

def _old_invariants(board: list) -> list[dict]:
    """A faithful re-implementation of the PRE-rewrite (list-based) invariants() -- see
    scripts/board_selfcheck.py's git history for the original. Kept here only so this test
    file can assert the new streaming version agrees with it, without reviving the
    whole-board-list pattern in the script itself."""
    mod = _load_selfcheck()
    CONTRADICTED, MONEY_FIELDS = mod.CONTRADICTED, mod.MONEY_FIELDS
    FUSION_THRESHOLD = mod.FUSION_THRESHOLD
    _calc, _identifier = mod._calc, mod._identifier

    out = []
    contra = [r for r in board if any(f in (_calc(r).get("arv_flags") or [])
                                      for f in CONTRADICTED)]
    for field in MONEY_FIELDS:
        bad = [r for r in contra if _calc(r).get(field)]
        out.append({"name": f"no {field} on a contradicted ARV", "count": len(bad),
                    "must_be": 0, "ok": not bad})
    bad = [r for r in contra if _calc(r).get("deal_status")]
    out.append({"name": "no deal verdict on a contradicted ARV", "count": len(bad),
                "must_be": 0, "ok": not bad})
    bad = [r for r in contra if (((r.get("raw") or {}).get("equity") or {}).get("value"))]
    out.append({"name": "no equity on a contradicted ARV", "count": len(bad),
                "must_be": 0, "ok": not bad})
    big = [r for r in board if (_calc(r).get("arv_expected") or 0) > 2_000_000]
    bad = [r for r in big if _calc(r).get("max_bid_70")]
    out.append({"name": "no max bid on an ARV over $2M", "count": len(bad),
                "must_be": 0, "ok": not bad})
    bad = [r for r in big if not _calc(r).get("arv_flags")]
    out.append({"name": "every ARV over $2M carries a flag", "count": len(bad),
                "must_be": 0, "ok": not bad})

    groups: dict = {}
    for r in board:
        ident = _identifier(r)
        if ident:
            groups.setdefault(ident, []).append(r)
    dupes = 0
    fused_keys = fused_rows = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        addrs = {str(r.get("street_address") or "").strip().lower() for r in rows}
        addrs.discard("")
        if len(addrs) >= FUSION_THRESHOLD:
            fused_keys += 1
            fused_rows += len(rows)
            continue
        dupes += len(rows) - 1
    entry = {"name": "no duplicate identifiable properties", "count": dupes,
             "must_be": 0, "ok": dupes == 0}
    if fused_keys:
        entry["fused_keys"] = fused_keys
        entry["fused_rows"] = fused_rows
    out.append(entry)
    return out


def test_streaming_invariants_agrees_with_the_old_list_based_implementation(tmp_path):
    mod = _load_selfcheck()
    flag = next(iter(mod.CONTRADICTED))
    # valid parcel ids (identity.ident_key, 2026-10-09): 'P1' / 'MASTER' name no parcel, and
    # three rows at '1 Main St' would then be one property by their address
    board = [
        _row("1000000001", {"arv_flags": [flag], "max_bid_70": 150_000, "roi_pct": 0.3,
                     "estimated_profit": 20_000, "wholesale_mao": 90_000,
                     "deal_status": "GREAT"}, equity_value=10_000),
        _row("1000000002", {"arv_expected": 250_000, "max_bid_70": 175_000}, equity_value=60_000),
        _row("1000000003", {"arv_expected": 3_000_000}),  # unflagged $3M ARV -- must breach
        _row("1000000003", {"arv_expected": 3_000_000}),  # exact duplicate parcel_id + address
        {**_row("3208-90-5620-0000", {}), "street_address": "1 Rd"},
        {**_row("3208-90-5620-0000", {}), "street_address": "2 Rd"},
        {**_row("3208-90-5620-0000", {}), "street_address": "3 Rd"},
        {**_row("3208-90-5620-0000", {}), "street_address": "4 Rd"},  # 4 distinct -- fused, not dupes
        {"parcel_id": None, "street_address": "SR 1135", "county": "McDowell", "state": "NC",
         "source": "test", "case_number": None, "raw": {"calc": {}}},  # unidentifiable
    ]

    old = mod.invariants(list(board))  # the CURRENT (streaming) invariants(), list input
    new = mod.invariants(r for r in board)  # same board, generator input
    reference = _old_invariants(board)

    assert old == new
    for o, r in zip(old, reference):
        assert o["name"] == r["name"]
        assert o["count"] == r["count"], f"{o['name']}: streaming={o['count']} old={r['count']}"
        assert o["ok"] == r["ok"]
        if r.get("fused_keys"):
            assert o["fused_keys"] == r["fused_keys"]
            assert o["fused_rows"] == r["fused_rows"]


# ===========================================================================
# 5. _previous() -- the THIRD memory bug (2026-09-30, found re-measuring the fix above).
#
# _previous() used to `json.loads()` the ENTIRE committed listings_slim.json.gz in one call:
# harmless-looking (it is MOVEMENT-only, "never for invariants"), but measured in isolation
# against this repo's real HEAD at 5.97 GB peak memory footprint / 2.53 GB peak RSS -- nearly
# the same crisis _current() had, and one the DEFAULT `main()` invocation hits every time
# (movement runs against HEAD unless told not to). Fixing _current() alone would not have
# fixed the script. _previous() now streams the committed gzip blob through a temp file via
# board_parts.iter_gz_rows(), and movement() reduces each prev row to _light_calc()'s 5
# numbers immediately, never retaining full prev rows.
# ===========================================================================

def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _tiny_repo_with_slim(tmp_path: Path, slim_rows: list) -> Path:
    """A throwaway git repo with one commit holding docs/listings_slim.json.gz -- enough for
    _previous() to `git show HEAD:docs/listings_slim.json.gz` against, without needing the
    real repo's history."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    data = gzip.compress(json.dumps(slim_rows).encode("utf-8"))
    (root / "docs" / "listings_slim.json.gz").write_bytes(data)
    _git(root, "add", "docs/listings_slim.json.gz")
    r = _git(root, "commit", "-q", "-m", "seed")
    assert r.returncode == 0, r.stderr
    return root


def test_previous_streams_the_committed_slim_board(tmp_path):
    mod = _load_selfcheck()
    slim = [_row("P1", {"arv_expected": 100_000}), _row("P2", {"arv_expected": 200_000})]
    mod.REPO = _tiny_repo_with_slim(tmp_path, slim)

    result = mod._previous("HEAD")
    assert result is not None
    assert isinstance(result, types.GeneratorType) or hasattr(result, "__next__"), (
        "_previous() must stream, not return the fully materialized list that measured "
        "5.97 GB on the real board"
    )
    rows = list(result)
    assert len(rows) == 2
    assert {r["parcel_id"] for r in rows} == {"P1", "P2"}


def test_previous_returns_none_when_the_ref_has_no_slim_file(tmp_path):
    mod = _load_selfcheck()
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "docs" / ".keep").write_text("")
    _git(root, "add", "docs/.keep")
    _git(root, "commit", "-q", "-m", "no slim file here")
    mod.REPO = root

    assert mod._previous("HEAD") is None


def test_previous_returns_none_for_a_nonexistent_ref(tmp_path):
    mod = _load_selfcheck()
    mod.REPO = _tiny_repo_with_slim(tmp_path, [_row("P1", {})])
    assert mod._previous("not-a-real-ref-xyz") is None


def test_light_calc_extracts_only_the_five_money_fields(tmp_path):
    mod = _load_selfcheck()
    row = _row("P1", {"arv_expected": 300_000, "max_bid_70": 200_000, "roi_pct": 0.22,
                       "estimated_profit": 40_000, "wholesale_mao": 180_000,
                       "notes": ["should not appear"], "arv_flags": ["should_not_appear"]})
    light = mod._light_calc(row)
    assert light == {"arv_expected": 300_000, "max_bid_70": 200_000, "roi_pct": 0.22,
                      "estimated_profit": 40_000, "wholesale_mao": 180_000}


def test_movement_end_to_end_against_a_real_tiny_git_repo(tmp_path):
    """The whole MOVEMENT path together: a real (tiny) git commit as `--against`, streamed by
    _previous(), reduced by _light_calc(), matched against light `cur` rows -- the same wiring
    main() uses, minus board size."""
    mod = _load_selfcheck()
    prev_rows = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 70_000}),
                 _row("P2", {"arv_expected": 200_000, "max_bid_70": 140_000})]
    mod.REPO = _tiny_repo_with_slim(tmp_path, prev_rows)

    cur_full = [_row("P1", {"arv_expected": 100_000, "max_bid_70": 90_000}),  # max_bid moved
                _row("P3", {"arv_expected": 300_000, "max_bid_70": 210_000})]  # new
    cur_light = [mod._light_row(r) for r in cur_full]

    prev = mod._previous("HEAD")
    mv = mod.movement(cur_light, prev)
    assert mv["prev_count"] == 2
    assert mv["curr_count"] == 2
    assert mv["matched"] == 1
    assert mv["new"] == 1
    assert mv["dropped"] == 1  # P2 was in prev, not in cur
    assert mv["changed"]["max_bid_70"] == 1


def test_movement_dropped_counts_each_previous_row_not_each_unique_key(tmp_path):
    """Two PREVIOUS rows that happen to collide on the same imprecise _key() (both lack a
    parcel_id and a numbered address, so both fall back to the same composite key) must both
    count as dropped if neither survives -- not collapse to 1 just because pi/prev_keys is
    keyed by that shared string internally. Pins the exact per-row (not per-unique-key)
    semantics the streaming rewrite of movement()/`_previous()` was written to preserve."""
    mod = _load_selfcheck()
    same_key_row = {"parcel_id": None, "street_address": "SR 1135", "county": "McDowell",
                     "state": "NC", "source": "test", "case_number": None,
                     "raw": {"calc": {"arv_expected": 50_000}}}
    prev = [same_key_row, dict(same_key_row)]  # two distinct dicts, identical composite key
    cur_light: list = []  # nothing survives

    mv = mod.movement(cur_light, prev)
    assert mv["prev_count"] == 2
    assert mv["dropped"] == 2, "both prev rows must count, even though they share one key"

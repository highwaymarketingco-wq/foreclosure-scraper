"""scripts/run_tax_owed_normalize.py's board-I/O rewrite (2026-10-02, docs/HANDOFF.md item 40):
it used to call load_board() to build the WHOLE board, run enrich_tax_owed() over it, then
write_artifact(rows, ...) -- exactly the double materialization (payload = [_to_dict(li) for li
in listings], a SECOND full copy on top of load_board()'s own Listing list) that kernel-OOM-killed
a real production attempt on the 23GB Oracle VM the same day. This test proves the new path --
board_stream.iter_board_rows() (no lazy-detail sidecar) to build the working set, the real
enrich_tax_owed() UNCHANGED, a pre/post snapshot diff, one web_artifact.patch_existing_rows() call
-- reproduces the original contract exactly, without ever calling load_board()/write_artifact().

Covers:
  1. End-to-end: a tax lead's own amount gets normalized into raw['tax_owed'], and a same-parcel
     court lead with no tax data of its own inherits the SAME balance via cross-reference --
     proving the two-pass, cross-row algorithm still works unchanged against the new
     board_stream-sourced working set.
  2. The dedupe_key()-collision interaction the migration's own docstring discloses ("KNOWN
     INTERACTION WITH dedupe_key() IDENTITY"): an own-record row and its cross-ref target
     necessarily share dedupe_key()'s parcel branch, so patch_existing_rows() applies ONE combined
     patch to both -- this test proves that is visible (duplicate_key_matches == 1) and that
     nothing lands an unrelated/corrupted value (both rows end up with the correct balance), not
     that each row keeps its own distinct `basis` label (it cannot, by design of
     patch_existing_rows()'s one-patch-per-identity contract).
  3. An ordinary row with no tax-ish data anywhere is never sent to patch_existing_rows() at all.
  4. --dry-run computes and prints stats but writes nothing.
  5. Idempotency: a second real run re-derives the identical raw['tax_owed'] values (enrich_tax_owed
     re-stamps every tax row unconditionally) and therefore patches NOTHING -- proving the new
     diff-based gate (not the old stats-based "nothing to do" check) is what actually decides
     whether the board is touched.
  6. The board-too-large-to-patch ceiling is checked BEFORE the expensive full-list build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_tax_owed_normalize as T  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.TAX_LIEN, state="NC", county="Henderson", raw={})
    base.update(kw)
    return Listing(**base)


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(T, "REPO", repo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def _seed(docs: Path, rows: list[Listing]) -> None:
    wa.write_artifact(rows, {"notes": "run_tax_owed_normalize test seed"}, docs_dir=docs)


def _read_board(docs: Path) -> list[dict]:
    from foreclosure_scraper.board_stream import iter_board_rows
    gz = docs / "listings.json.gz"
    plain = docs / "listings.json"
    return list(iter_board_rows(gz if gz.exists() else plain))


def test_normalizes_own_amount_and_cross_references_same_parcel(scratch_repo, monkeypatch, capsys):
    """Own-record row and its cross-ref target necessarily share dedupe_key()'s parcel branch
    (see the script's own "KNOWN INTERACTION WITH dedupe_key() IDENTITY" docstring section) --
    patch_existing_rows() applies ONE combined patch to both, so this asserts what IS guaranteed
    (both end up with the correct, cross-referenced balance; the collision is surfaced via
    duplicate_key_matches, never silent) rather than each row's own distinct `basis` label."""
    docs = scratch_repo / "docs"
    rows = [
        _row(0, source="counties_nc.nc_ptscloud_delinquent_tax", parcel_id="1234567890",
             raw={"nc_ptscloud_delinquent_tax": {"principal_tax_due": 4200.0, "year": "2024"}}),
        _row(1, source="counties_nc.nc_ecourts_lis_pendens", listing_type=ListingType.FORECLOSURE_SALE,
             parcel_id="1234567890", raw={}),  # no tax data of its own, same parcel
        _row(2, source="counties_nc.nc_ecourts_lis_pendens", listing_type=ListingType.FORECLOSURE_SALE,
             parcel_id="9999999999", raw={}),  # unrelated parcel, no tax data anywhere
    ]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py"])

    rc = T.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "duplicate_key_matches" not in out or "1 patch(es) matched" in out

    board = _read_board(docs)
    by_url = {r["source_url"]: r for r in board}

    r0 = by_url[rows[0].source_url]
    r1 = by_url[rows[1].source_url]
    assert r0["raw"]["tax_owed"]["balance"] == 4200.0
    assert r1["raw"]["tax_owed"]["balance"] == 4200.0
    # both rows share one dedupe_key() (same state/county/parcel), so patch_existing_rows()
    # necessarily gives them the SAME final raw['tax_owed'] dict -- document that explicitly.
    assert r0["raw"]["tax_owed"] == r1["raw"]["tax_owed"]

    # unrelated-parcel row: no tax data anywhere -- never touched, never sent to patch at all
    r2 = by_url[rows[2].source_url]
    assert "tax_owed" not in r2["raw"]


def test_cross_reference_collision_is_counted_not_silent(scratch_repo, monkeypatch):
    """Directly exercises the documented dedupe_key() collision: patch_existing_rows() itself
    must report duplicate_key_matches == 1 for the own-record/cross-ref pair, and this script
    must print its own NOTE line surfacing it -- the collision is never silently absorbed."""
    docs = scratch_repo / "docs"
    rows = [
        _row(0, source="counties_sc.sc_state_tax_lien", parcel_id="AB-100",
             raw={"sc_state_tax_lien": {"balance": 500.0}}),
        _row(1, source="counties_sc.sc_public_index", listing_type=ListingType.FORECLOSURE_SALE,
             parcel_id="AB-100", raw={}),
    ]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py"])

    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = T.main()
    assert rc == 0
    assert "1 patch(es) matched more than one board row" in buf.getvalue()


def test_row_with_no_tax_data_is_never_patched(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="counties_nc.nc_ecourts_lis_pendens", raw={})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py"])

    before = (docs / "listings.json").read_bytes()
    rc = T.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before, "nothing to patch -- board must be untouched"


def test_dry_run_writes_nothing(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    rows = [_row(0, source="counties_sc.sc_state_tax_lien",
                 raw={"sc_state_tax_lien": {"balance": 900.0}})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py", "--dry-run"])

    before = (docs / "listings.json").read_bytes()
    rc = T.main()
    assert rc == 0
    assert (docs / "listings.json").read_bytes() == before

    board = _read_board(docs)
    assert "tax_owed" not in board[0]["raw"]


def test_second_run_is_idempotent_and_patches_nothing(scratch_repo, monkeypatch):
    """enrich_tax_owed() re-stamps every tax row unconditionally on every run -- stats['stamped']
    is nonzero again on the second run even though the VALUES are identical. The new diff-based
    gate must still find nothing to patch (unlike the old stats-based gate, which would have
    called write_artifact() -- a whole-board rewrite -- on every single re-run)."""
    docs = scratch_repo / "docs"
    rows = [_row(0, source="counties_sc.sc_state_tax_lien",
                 raw={"sc_state_tax_lien": {"balance": 900.0}})]
    _seed(docs, rows)
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py"])

    assert T.main() == 0
    before = (docs / "listings.json").read_bytes()

    assert T.main() == 0  # stats['stamped'] is nonzero again (re-stamped), but nothing CHANGED
    assert (docs / "listings.json").read_bytes() == before, "idempotent re-run must patch nothing"


def test_board_too_large_refuses_before_building_the_working_set(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    _seed(docs, [_row(0, raw={})])
    monkeypatch.setenv("BOARD_PATCH_MAX_SOURCE_MB", "0")  # any real board is "too large"
    monkeypatch.setattr(sys, "argv", ["run_tax_owed_normalize.py"])
    called = []
    real_light_rows = T._light_rows

    def spy(d):
        called.append(True)
        return real_light_rows(d)
    monkeypatch.setattr(T, "_light_rows", spy)

    with pytest.raises(wa.BoardLoadTooLarge):
        T.main()
    assert not called, "the ceiling must be checked BEFORE the full-list read, not after"

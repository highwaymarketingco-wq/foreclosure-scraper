"""The payload split (audit O1): the board is published as N gzipped parts, each under a size cap.

docs/listings.json.gz was 84 MiB against GitHub's 100 MiB limit and growing 2 to 4 MiB a day. The board
is now docs/listings_part_NNN.json.gz (src/foreclosure_scraper/board_parts.py), listed with size and
sha256 in docs/board.manifest.json and docs/run_meta.json. Everything here uses synthetic boards in
temp directories: no real board is read, nothing under the real docs/ is touched.

  1. the writer: adaptive part size, order, atomicity, stale parts, determinism, growth
  2. write_artifact: parts and manifest, plain listings.json bytes unchanged, no single gz
  3. readers: read_board_json / load_board / read_board_records / iter_board_rows over parts
  4. an interrupted write is detected and never read as valid
  5. the direct-writer helper, board_manifest.py, and the one-shot migration
  6. publishers: board_payload.sh, publish.py, the staged-parts gate, the pre-commit hook
  7. check_payload_size.py, check_pages_publish.py, job_watch, publish_private.sh, restore_board.sh
"""
from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from foreclosure_scraper import board_parts as bp
from foreclosure_scraper import publish as pub
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.board_stream import iter_board_rows
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
PAYLOAD_SH = SCRIPTS / "board_payload.sh"
KiB = 1024


# ===========================================================================
# helpers
# ===========================================================================

def _enc(row: dict) -> bytes:
    return json.JSONEncoder(ensure_ascii=False, default=str).encode(row).encode("utf-8")


def _row(i: int, pad: int = 60) -> dict:
    """A board-shaped row: repetitive keys, a varying id and a padded free-text field."""
    return {"source": f"src.{i % 7}", "source_url": f"https://example.test/{i}", "parcel_id": f"P{i:07d}",
            "street_address": f"{i} Main St ü", "county": "Gaston", "state": "NC",
            "description": ("lorem ipsum dolor sit amet " * 3)[:pad] + str(i * 7919 % 100003),
            "raw": {"grade": {"overall": "BCDA"[i % 4]}, "n": i}}


def _rows(n: int, pad: int = 60) -> list[dict]:
    return [_row(i, pad) for i in range(n)]


def _lead(i: int) -> Listing:
    # owner_name carries 128 hex characters that do not compress away, so a row costs about 100
    # compressed bytes and a small cap really does force several parts
    noise = hashlib.sha256(str(i).encode()).hexdigest() + hashlib.sha256(str(i + 7).encode()).hexdigest()
    return Listing(source=f"src.{i % 2}", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", parcel_id=f"P{i}", street_address=f"{i} Main St",
                   owner_name=noise,
                   raw={"grade": {"overall": "B"}, "comps": [{"addr": f"{i} Elm", "n": i}],
                        "vision": {"parsed": True}})


def _write(docs: Path, n: int = 5, notes: str = "t") -> None:
    wa.write_artifact([_lead(i) for i in range(n)], {"notes": notes}, docs_dir=docs)


def _cap(monkeypatch, n: int) -> None:
    monkeypatch.setattr(bp, "PART_MAX_BYTES", n)


def _part_paths(docs: Path) -> list[Path]:
    return bp.list_part_files(docs)


def _manifest(docs: Path) -> dict:
    return json.loads((docs / "board.manifest.json").read_text())


def _run_meta(docs: Path) -> dict:
    return json.loads((docs / "run_meta.json").read_text())


def _all_rows(docs: Path) -> list:
    return list(bp.iter_rows(docs))


# ===========================================================================
# 1. THE WRITER
# ===========================================================================

def test_a_60k_row_board_with_a_tiny_cap_splits_into_many_parts_and_round_trips_in_order(tmp_path, monkeypatch):
    _cap(monkeypatch, 256 * KiB)
    rows = _rows(60_000)
    blobs = [_enc(r) for r in rows]
    res = bp.write_parts(tmp_path, blobs)
    entries = res["entries"]

    assert len(entries) >= 4, "a 60k-row board must not fit one 256 KiB part"
    assert [e["name"] for e in entries] == [bp.part_name(i) for i in range(len(entries))]
    assert all(e["bytes"] <= 256 * KiB for e in entries), [e["bytes"] for e in entries]
    assert all(p.stat().st_size == e["bytes"] for p, e in zip(_part_paths(tmp_path), entries))
    # contiguous, no gap, no overlap, every row accounted for
    assert entries[0]["start"] == 0
    for a, b in zip(entries, entries[1:]):
        assert b["start"] == a["end"]
    assert entries[-1]["end"] == 60_000 == sum(e["records"] for e in entries)
    # parts are well filled (not one row per part): the cap, not caution, decides the count
    assert max(e["bytes"] for e in entries) > 0.5 * 256 * KiB

    # ROW-FOR-ROW, IN ORDER: index i is the join key across the whole payload
    res_ = bp.Resolution(tmp_path, [tmp_path / e["name"] for e in entries], entries, "manifest")
    assert list(bp.iter_rows(tmp_path, res=res_)) == rows
    assert bp.read_rows(tmp_path, res=res_) == rows
    # and the exact bytes of every row, not merely equal values
    texts = []
    for e in entries:
        texts.extend(bp.iter_row_texts(tmp_path / e["name"]))
    assert texts == blobs


def test_every_part_is_a_complete_gzip_json_array_on_its_own(tmp_path, monkeypatch):
    _cap(monkeypatch, 128 * KiB)
    res = bp.write_parts(tmp_path, [_enc(r) for r in _rows(6000)])
    seen = 0
    for e in res["entries"]:
        rows = json.loads(gzip.decompress((tmp_path / e["name"]).read_bytes()))
        assert isinstance(rows, list) and len(rows) == e["records"]
        assert rows[0]["parcel_id"] == f"P{e['start']:07d}", "a part starts exactly at its recorded row"
        seen += len(rows)
    assert seen == 6000
    assert hashlib.sha256((tmp_path / res["entries"][0]["name"]).read_bytes()).hexdigest() == res["entries"][0]["sha256"]


def test_the_cap_is_a_hard_limit_even_when_the_estimate_is_wrong(tmp_path, monkeypatch):
    """The sample the writer estimates from is compressible; a later region is random hex. The
    estimate overshoots, parts come out oversized, and the re-cut path must bring each one under."""
    _cap(monkeypatch, 96 * KiB)
    easy = [_enc({"i": i, "t": "x" * 200}) for i in range(4000)]
    hard = [_enc({"i": 4000 + i, "t": os.urandom(120).hex()}) for i in range(4000)]
    for source in (easy + hard, iter(easy + hard)):                    # a list, then a stream
        for old in tmp_path.glob("listings_part_*"):
            old.unlink()
        res = bp.write_parts(tmp_path, source)
        assert res["records"] == 8000
        assert all(e["bytes"] <= 96 * KiB for e in res["entries"])
        texts = []
        for e in res["entries"]:
            texts.extend(bp.iter_row_texts(tmp_path / e["name"]))
        assert texts == easy + hard, "re-cutting must not drop, duplicate or reorder a row"


def test_one_row_that_alone_exceeds_the_cap_is_an_error_not_a_silent_oversize(tmp_path, monkeypatch):
    _cap(monkeypatch, 4 * KiB)
    blobs = [_enc({"i": 1}), _enc({"i": 2, "blob": os.urandom(40 * KiB).hex()})]
    with pytest.raises(bp.PartTooLargeError):
        bp.write_parts(tmp_path, blobs)


def test_an_empty_board_is_one_part_holding_an_empty_array(tmp_path):
    res = bp.write_parts(tmp_path, [])
    assert [e["records"] for e in res["entries"]] == [0]
    assert json.loads(gzip.decompress((tmp_path / bp.part_name(0)).read_bytes())) == []


def test_parts_are_deterministic_and_boundaries_stay_put_between_writes(tmp_path, monkeypatch):
    """Identical rows give identical bytes (no git churn), and a change confined to some rows
    rewrites only the parts holding them: the rows-per-part of the last write is kept."""
    _cap(monkeypatch, 200 * KiB)
    rows = _rows(20_000)
    a = bp.write_parts(tmp_path / "a", [_enc(r) for r in rows])
    b = bp.write_parts(tmp_path / "b", [_enc(r) for r in rows])
    assert [e["sha256"] for e in a["entries"]] == [e["sha256"] for e in b["entries"]]

    rows2 = [dict(r) for r in rows]
    rows2[19_500]["description"] = "changed"                    # only the LAST part holds this row
    c = bp.write_parts(tmp_path / "c", [_enc(r) for r in rows2], hint_rows=a["rows_per_part"])
    assert [e["end"] for e in c["entries"]] == [e["end"] for e in a["entries"]], "boundaries moved"
    changed = [i for i, (x, y) in enumerate(zip(a["entries"], c["entries"])) if x["sha256"] != y["sha256"]]
    assert changed == [len(a["entries"]) - 1]


def test_a_growing_board_makes_more_parts_never_a_bigger_one(tmp_path, monkeypatch):
    _cap(monkeypatch, 160 * KiB)
    hint = None
    counts = []
    for n in (4000, 9000, 15_000, 24_000):
        res = bp.write_parts(tmp_path, [_enc(r) for r in _rows(n)], hint_rows=hint)
        hint = res["rows_per_part"]
        assert all(e["bytes"] <= 160 * KiB for e in res["entries"]), n
        assert res["records"] == n
        assert bp.list_part_files(tmp_path)[-1].name == res["entries"][-1]["name"]
        counts.append(len(res["entries"]))
    assert counts == sorted(counts) and counts[-1] > counts[0]


def test_a_shrinking_board_removes_the_stale_higher_numbered_parts(tmp_path, monkeypatch):
    _cap(monkeypatch, 64 * KiB)
    big = bp.write_parts(tmp_path, [_enc(r) for r in _rows(8000)])
    assert len(big["entries"]) >= 4
    small = bp.write_parts(tmp_path, [_enc(r) for r in _rows(300)])
    assert [p.name for p in _part_paths(tmp_path)] == [e["name"] for e in small["entries"]]
    assert not list(tmp_path.glob("*.tmp"))


def test_a_write_that_dies_mid_part_leaves_no_temp_file_and_the_prior_part_intact(tmp_path, monkeypatch):
    _cap(monkeypatch, 12 * KiB)
    bp.write_parts(tmp_path, [_enc(r) for r in _rows(3000)])
    before = {p.name: p.read_bytes() for p in _part_paths(tmp_path)}
    assert len(before) >= 4
    real = bp.atomic_write_bytes
    calls = []

    def dies(path, data):
        calls.append(path.name)
        if len(calls) == 2:
            raise KeyboardInterrupt
        real(path, data)
    monkeypatch.setattr(bp, "atomic_write_bytes", dies)
    with pytest.raises(KeyboardInterrupt):
        bp.write_parts(tmp_path, [_enc(r) for r in _rows(3000, pad=20)])
    assert not list(tmp_path.glob("*.tmp"))
    assert _part_paths(tmp_path)[2].read_bytes() == before[bp.part_name(2)], "parts after the failure are untouched"


# ===========================================================================
# 2. write_artifact
# ===========================================================================

def test_write_artifact_writes_parts_a_sealed_manifest_and_no_single_gz(tmp_path):
    docs = tmp_path / "d"
    (docs).mkdir()
    (docs / "listings.json.gz").write_bytes(b"STALE-SINGLE-FILE")       # an older version's file
    _write(docs, 6)
    assert (docs / "listings.json.gz").read_bytes() == b"STALE-SINGLE-FILE", "never rewritten, never deleted"
    assert [p.name for p in _part_paths(docs)] == ["listings_part_000.json.gz"]
    man = _manifest(docs)
    assert "listings.json.gz" not in man["files"]
    blk = man["parts"]
    assert blk["schema"] == "board-parts-v1" and blk["count"] == 1 and blk["records"] == 6 == man["count"]
    ent = blk["files"][0]
    assert ent["sha256"] == hashlib.sha256((docs / ent["name"]).read_bytes()).hexdigest()
    assert man["files"][ent["name"]]["sha256"] == ent["sha256"]
    # run_meta carries the same list (the dashboard reads it)
    assert _run_meta(docs)["board_parts"] == blk
    assert wa.verify_manifest(docs)["ok"]
    assert (docs / "board.manifest.json").stat().st_mtime_ns >= (docs / ent["name"]).stat().st_mtime_ns, "sealed LAST"


def test_the_plain_listings_json_bytes_are_exactly_what_one_json_dumps_produced(tmp_path):
    """The per-row writer must not change a byte of the gitignored working copy."""
    docs = tmp_path / "d"
    leads = [_lead(i) for i in range(12)]
    wa.write_artifact(leads, {"notes": "t"}, docs_dir=docs)
    text = (docs / "listings.json").read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), ensure_ascii=False, default=str)
    assert (docs / "listings.json").stat().st_size == _manifest(docs)["files"]["listings.json"]["bytes"]
    assert hashlib.sha256((docs / "listings.json").read_bytes()).hexdigest() == \
        _manifest(docs)["files"]["listings.json"]["sha256"]
    # and the parts concatenate to the same array
    assert _all_rows(docs) == json.loads(text)


def test_a_multi_part_write_artifact_round_trips_every_row_in_order(tmp_path, monkeypatch):
    _cap(monkeypatch, 24 * KiB)
    docs = tmp_path / "d"
    _write(docs, 900)
    parts = _part_paths(docs)
    assert len(parts) >= 3
    assert all(p.stat().st_size <= 24 * KiB for p in parts)
    plain = json.loads((docs / "listings.json").read_text())
    assert len(plain) == 900
    assert _all_rows(docs) == plain
    (docs / "listings.json").unlink()                                  # a fresh clone: parts only
    loaded = wa.load_board(docs)
    assert [li.source_url for li in loaded] == [f"u{i}" for i in range(900)]
    assert wa.read_board_json(docs / "listings.json") == plain
    detail = json.loads((docs / "listings_detail.json").read_text())
    assert len(detail) == 900 and detail[123]["comps"][0]["n"] == 123, "index i still joins detail to listings"
    v = wa.verify_manifest(docs)
    assert v["ok"], v


def test_a_60k_lead_write_artifact_splits_and_reloads_in_order(tmp_path, monkeypatch):
    _cap(monkeypatch, 700 * KiB)
    docs = tmp_path / "d"
    wa.write_artifact([_lead(i) for i in range(60_000)], {"notes": "t"}, docs_dir=docs)
    parts = _part_paths(docs)
    assert len(parts) >= 4
    assert all(p.stat().st_size <= 700 * KiB for p in parts)
    (docs / "listings.json").unlink()
    urls = [r["source_url"] for r in iter_board_rows(docs / "listings.json.gz")]
    assert urls == [f"u{i}" for i in range(60_000)]
    assert wa.verify_manifest(docs)["ok"]


def test_a_legacy_single_gz_layout_upgrades_in_place_on_the_next_write(tmp_path):
    """The rollout path: a repo with a single listings.json.gz and a pre-split manifest. The next
    write_artifact publishes parts, leaves the old file alone, and every reader follows the parts."""
    docs = tmp_path / "d"
    _write(docs, 4)
    plain = (docs / "listings.json").read_bytes()
    single = gzip.compress(plain, mtime=0)
    for p in _part_paths(docs):
        p.unlink()
    (docs / "listings.json.gz").write_bytes(single)
    man = _manifest(docs)
    man.pop("parts")
    man["files"] = {k: v for k, v in man["files"].items() if not k.startswith("listings_part_")}
    man["files"]["listings.json.gz"] = {"bytes": len(single), "sha256": hashlib.sha256(single).hexdigest(), "records": 4}
    (docs / "board.manifest.json").write_text(json.dumps(man))
    meta = _run_meta(docs)
    meta.pop("board_parts")
    (docs / "run_meta.json").write_text(json.dumps(meta))
    assert len(wa.read_board_json(docs / "listings.json")) == 4               # legacy layout reads

    (docs / "listings.json").unlink()
    (docs / "listings_detail.json").unlink()
    _write(docs, 7)
    assert (docs / "listings.json.gz").read_bytes() == single, "the old single file is left for git rm"
    assert [p.name for p in _part_paths(docs)] == ["listings_part_000.json.gz"]
    assert len(wa.read_board_json(docs / "listings.json")) == 7
    (docs / "listings.json").unlink()
    assert len(wa.load_board(docs)) == 7, "with the plain file gone the parts, not the stale single gz, are the board"


# ===========================================================================
# 3. READERS
# ===========================================================================

def test_iter_board_rows_streams_the_parts_beside_the_old_single_file_path(tmp_path, monkeypatch):
    _cap(monkeypatch, 24 * KiB)
    docs = tmp_path / "d"
    _write(docs, 700)
    gen = iter_board_rows(docs / "listings.json.gz")                # the path ~25 scripts still name
    assert inspect.isgenerator(gen), "a streaming reader stays a generator (no full-board list)"
    first = next(gen)
    assert first["source_url"] == "u0"
    rest = list(gen)
    assert len(rest) == 699 and rest[-1]["source_url"] == "u699"
    # ... and a scratch board that is one plain single gz still reads as it always did
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "listings.json.gz").write_bytes(gzip.compress(json.dumps(_rows(50)).encode()))
    assert [r["parcel_id"] for r in iter_board_rows(scratch / "listings.json.gz")] == [f"P{i:07d}" for i in range(50)]


def test_the_manifest_listed_parts_beat_a_stale_single_gz_beside_them(tmp_path):
    docs = tmp_path / "d"
    _write(docs, 5)
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps([{"source_url": "STALE"}]).encode()))
    (docs / "listings.json").unlink()
    assert [r["source_url"] for r in iter_board_rows(docs / "listings.json.gz")] == [f"u{i}" for i in range(5)]
    assert [r["source_url"] for r in wa.read_board_json(docs / "listings.json")] == [f"u{i}" for i in range(5)]


def test_read_board_records_merges_the_sidecar_from_a_parts_only_checkout(tmp_path, monkeypatch):
    _cap(monkeypatch, 24 * KiB)
    docs = tmp_path / "d"
    _write(docs, 400)
    for n in ("listings.json", "listings_detail.json", "listings_slim.json"):
        (docs / n).unlink()
    recs = wa.read_board_records(docs)
    assert len(recs) == 400
    assert recs[399]["raw"]["comps"][0]["n"] == 399 and recs[0]["raw"]["vision"]["parsed"] is True


def test_the_plain_file_still_wins_when_it_matches_the_manifest(tmp_path):
    docs = tmp_path / "d"
    _write(docs, 3)
    used, role = wa._choose_board_file(docs / "listings.json")
    assert role == "plain" and used == docs / "listings.json"
    (docs / "listings.json").write_text("[]")                                       # disagrees now
    used, role = wa._choose_board_file(docs / "listings.json")
    assert role == "parts" and used.name == "listings_part_000.json.gz"
    (docs / "listings.json").unlink()
    assert wa._choose_board_file(docs / "listings.json")[1] == "parts"


# ===========================================================================
# 4. AN INTERRUPTED WRITE IS DETECTED AND NEVER READ AS VALID
# ===========================================================================

@pytest.fixture
def two_boards(tmp_path, monkeypatch):
    """docs/ holding board A (sealed), and a second, different board B ready to be written."""
    _cap(monkeypatch, 24 * KiB)
    docs = tmp_path / "d"
    _write(docs, 600, notes="A")
    assert len(_part_paths(docs)) >= 3
    return docs


def _interrupt_after(monkeypatch, n_parts_written: int):
    real = bp.atomic_write_bytes
    n = {"i": 0}

    def flaky(path, data):
        if n["i"] == n_parts_written:
            raise KeyboardInterrupt("killed mid-write")
        n["i"] += 1
        real(path, data)
    monkeypatch.setattr(bp, "atomic_write_bytes", flaky)


def test_part_i_written_manifest_not_updated_is_a_BoardIntegrityError_everywhere(two_boards, monkeypatch):
    docs = two_boards
    board_a = [_lead(i) for i in range(600)]
    _interrupt_after(monkeypatch, 1)                                   # part 000 lands, part 001 does not
    changed = [_lead(i) if i % 2 else _lead(i + 1000) for i in range(600)]      # every part's bytes change
    with pytest.raises(KeyboardInterrupt):
        wa.write_artifact(changed, {"notes": "B"}, docs_dir=docs)
    monkeypatch.undo()
    _ = board_a

    # the manifest on disk is still board A's: it says what the parts SHOULD be, and they are not
    with pytest.raises(wa.BoardIntegrityError):
        wa.read_board_json(docs / "listings.json")
    with pytest.raises(wa.BoardIntegrityError):
        wa.load_board(docs)
    with pytest.raises(wa.BoardIntegrityError):
        list(iter_board_rows(docs / "listings.json.gz"))
    with pytest.raises(wa.BoardIntegrityError):
        wa.read_board_records(docs)
    assert not wa.verify_manifest(docs)["ok"]
    assert not bp.verify_dir(docs)["ok"]
    # a fresh clone (no plain files) is refused too: nothing may read the mixed parts as a board
    for n in ("listings.json", "listings_detail.json", "listings_slim.json"):
        (docs / n).unlink(missing_ok=True)
    with pytest.raises(wa.BoardIntegrityError):
        wa.load_board(docs)
    with pytest.raises(wa.BoardIntegrityError):
        list(iter_board_rows(docs / "listings.json.gz"))


def test_the_next_write_refuses_to_publish_on_top_of_a_torn_part_set(two_boards, monkeypatch):
    docs = two_boards
    _interrupt_after(monkeypatch, 1)
    with pytest.raises(KeyboardInterrupt):
        wa.write_artifact([_lead(i + 5000) for i in range(600)], {"notes": "B"}, docs_dir=docs)
    monkeypatch.undo()
    with pytest.raises(wa.BoardIntegrityError):
        wa.write_artifact([_lead(i) for i in range(600)], {"notes": "C"}, docs_dir=docs)


def test_a_missing_or_truncated_or_extra_part_is_refused(two_boards):
    docs = two_boards
    parts = _part_paths(docs)
    good = parts[1].read_bytes()

    parts[1].write_bytes(good[:-20])                                    # truncated
    with pytest.raises(wa.BoardIntegrityError):
        list(iter_board_rows(docs / "listings.json.gz"))
    parts[1].write_bytes(good[:-1] + bytes([good[-1] ^ 0xFF]))          # same size, one flipped byte
    with pytest.raises(wa.BoardIntegrityError):
        bp.read_rows(docs)
    parts[1].unlink()                                                   # missing
    with pytest.raises(wa.BoardIntegrityError):
        list(iter_board_rows(docs / "listings.json.gz"))
    parts[1].write_bytes(good)
    assert len(list(iter_board_rows(docs / "listings.json.gz"))) == 600  # restored: valid again

    stray = docs / bp.part_name(len(parts) + 3)                          # a stale part nobody listed
    stray.write_bytes(gzip.compress(b"[]"))
    assert len(list(iter_board_rows(docs / "listings.json.gz"))) == 600, "readers follow the manifest"
    res = wa.verify_manifest(docs)
    assert not res["ok"] and any("not list" in p for p in res["problems"])


def test_parts_are_only_ever_read_through_a_listing(two_boards):
    """No manifest and no run_meta listing: a directory holding some parts could be an interrupted
    first write. It is refused unless a complete single file is there to fall back to."""
    docs = two_boards
    (docs / "board.manifest.json").unlink()
    meta = _run_meta(docs)
    meta.pop("board_parts")
    (docs / "run_meta.json").write_text(json.dumps(meta))
    (docs / "listings.json").unlink()

    with pytest.raises(bp.UnlistedPartsError):
        wa.read_board_json(docs / "listings.json")
    with pytest.raises(bp.UnlistedPartsError):
        list(iter_board_rows(docs / "listings.json.gz"))
    # an operator who has checked them by hand can say so
    os.environ["BOARD_PARTS_ALLOW_UNLISTED"] = "1"
    try:
        assert len(list(iter_board_rows(docs / "listings.json.gz"))) == 600
    finally:
        del os.environ["BOARD_PARTS_ALLOW_UNLISTED"]
    # ... and with a complete single file present the last consistent board is used instead
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps([{"source_url": "OLD"}]).encode()))
    assert [r["source_url"] for r in iter_board_rows(docs / "listings.json.gz")] == ["OLD"]
    assert wa.read_board_json(docs / "listings.json") == [{"source_url": "OLD"}]


def test_without_a_manifest_run_meta_is_a_verified_listing(two_boards):
    docs = two_boards
    (docs / "board.manifest.json").unlink()
    (docs / "listings.json").unlink()
    assert len(wa.read_board_json(docs / "listings.json")) == 600
    p = _part_paths(docs)[0]
    p.write_bytes(p.read_bytes()[:-3])
    with pytest.raises(wa.BoardIntegrityError):
        wa.read_board_json(docs / "listings.json")


def test_the_manifest_skip_escape_hatch_still_reads_parts_through_run_meta(two_boards, monkeypatch):
    docs = two_boards
    (docs / "listings.json").unlink()
    p = _part_paths(docs)[0]
    p.write_bytes(p.read_bytes()[:-3])
    monkeypatch.setenv("BOARD_MANIFEST_SKIP", "1")
    with pytest.raises(wa.BoardIntegrityError):
        wa.read_board_json(docs / "listings.json")           # run_meta names the same bytes: still torn
    monkeypatch.setenv("BOARD_PARTS_ALLOW_UNLISTED", "1")
    # the operator's last resort reads what is on disk (the truncated part is not valid gzip)
    with pytest.raises(Exception):
        wa.read_board_json(docs / "listings.json")


# ===========================================================================
# 5. direct writers, board_manifest.py --rebuild, the migration
# ===========================================================================

def test_reseal_from_the_plain_file_recuts_the_parts_after_a_direct_edit(tmp_path, monkeypatch):
    _cap(monkeypatch, 24 * KiB)
    docs = tmp_path / "d"
    _write(docs, 500)
    edited = json.loads((docs / "listings.json").read_text())
    for r in edited:
        r["zip_code"] = "28016"
    (docs / "listings.json").write_text(json.dumps(edited, default=str))       # a legacy stream_save
    # the plain file no longer matches the manifest and the parts are the OLD board: the loaders
    # take the manifest-consistent parts, so the edit is invisible until it is resealed
    assert wa.read_board_json(docs / "listings.json")[0].get("zip_code") != "28016"
    block = wa.reseal_board(docs, resplit=True)
    assert block["records"] == 500
    assert wa.verify_manifest(docs)["ok"]
    assert {r["zip_code"] for r in bp.read_rows(docs)} == {"28016"}
    assert _run_meta(docs)["board_parts"] == _manifest(docs)["parts"]
    assert all(p.stat().st_size <= 24 * KiB for p in _part_paths(docs))


def test_board_manifest_rebuild_resplit_cli(tmp_path):
    docs = tmp_path / "d"
    _write(docs, 30)
    rows = json.loads((docs / "listings.json").read_text())
    rows[0]["zip_code"] = "29601"
    (docs / "listings.json").write_text(json.dumps(rows))
    scratch_root = tmp_path
    r = subprocess.run([sys.executable, str(SCRIPTS / "board_manifest.py"), "--docs", str(docs), "--rebuild", "--resplit"],
                       capture_output=True, text=True, cwd=str(scratch_root),
                       env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "parts: 1 part(s), 30 rows" in r.stdout
    assert bp.read_rows(docs)[0]["zip_code"] == "29601"
    ok = subprocess.run([sys.executable, str(SCRIPTS / "board_manifest.py"), "--docs", str(docs), "--verify"],
                        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")})
    assert ok.returncode == 0, ok.stdout


def _legacy_board(tmp_path: Path, n: int = 40) -> Path:
    """The board as it exists in the real repo today: a single listings.json.gz, a run_meta with no
    board_parts, no manifest."""
    docs = tmp_path / "docs"
    _write(docs, n)
    plain = (docs / "listings.json").read_bytes()
    for p in _part_paths(docs):
        p.unlink()
    (docs / "board.manifest.json").unlink()
    (docs / "listings.json.gz").write_bytes(gzip.compress(plain, compresslevel=9, mtime=0))
    (docs / "listings.json").unlink()
    meta = _run_meta(docs)
    meta.pop("board_parts")
    (docs / "run_meta.json").write_text(json.dumps(meta))
    return docs


def _migrate(docs: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "migrate_board_to_parts.py"), "--docs", str(docs), *args],
                          capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO / "src")})


def _tree(docs: Path) -> dict:
    return {str(p.relative_to(docs)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(docs.rglob("*")) if p.is_file()}


def test_migration_dry_run_touches_nothing_and_shows_the_layout(tmp_path):
    docs = _legacy_board(tmp_path, 300)
    before = _tree(docs)
    r = _migrate(docs, "--cap-bytes", str(8 * KiB))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DRY RUN" in r.stdout and "round trip: OK" in r.stdout and "git rm docs/listings.json.gz" in r.stdout
    assert "listings_part_000.json.gz" in r.stdout and "300" in r.stdout
    assert _tree(docs) == before, "a dry run must not change anything under docs/"
    assert not list(docs.glob(".migrate_parts*"))


def test_migration_apply_converts_streams_proves_and_keeps_the_old_file(tmp_path):
    docs = _legacy_board(tmp_path, 300)
    source_rows = list(iter_board_rows(docs / "listings.json.gz"))
    single = (docs / "listings.json.gz").read_bytes()
    r = _migrate(docs, "--apply", "--cap-bytes", str(8 * KiB))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "final round trip: OK" in r.stdout
    parts = _part_paths(docs)
    assert len(parts) >= 3 and all(p.stat().st_size <= 8 * KiB for p in parts)
    assert (docs / "listings.json.gz").read_bytes() == single, "the migration never deletes the single file"
    assert wa.verify_manifest(docs)["ok"]
    assert _run_meta(docs)["board_parts"] == _manifest(docs)["parts"]
    assert list(iter_board_rows(docs / "listings.json.gz")) == source_rows, "row for row, in order"
    assert bp.read_rows(docs) == source_rows
    assert not list(docs.glob(".migrate_parts*"))
    # idempotence guard: it refuses to run twice
    again = _migrate(docs, "--apply")
    assert again.returncode == 1 and "already migrated" in again.stderr


def test_migration_refuses_a_board_the_dashboard_would_refuse(tmp_path):
    docs = _legacy_board(tmp_path, 40)
    meta = _run_meta(docs)
    meta["board"]["count"] = 41                                   # slim count disagrees with the source
    (docs / "run_meta.json").write_text(json.dumps(meta))
    r = _migrate(docs, "--apply")
    assert r.returncode == 1 and "board.count says 41" in r.stderr
    assert not _part_paths(docs), "nothing was written"
    forced = _migrate(docs, "--apply", "--force")
    assert forced.returncode == 0 and len(list(iter_board_rows(docs / "listings.json.gz"))) == 40


def test_migration_apply_refuses_while_the_board_lock_is_held(tmp_path):
    docs = _legacy_board(tmp_path, 20)
    lock = tmp_path / "logs" / ".board.lock"
    lock.mkdir(parents=True)
    import time
    now = int(time.time())
    (lock / "pid").write_text(f"{os.getpid()}\nrun_daily_vision.sh\n{now}\n{now}\n21600\nTOKEN\n")
    r = _migrate(docs, "--apply")
    assert r.returncode == 75, r.stdout + r.stderr
    assert not _part_paths(docs)


def test_migration_never_calls_load_board():
    src = (SCRIPTS / "migrate_board_to_parts.py").read_text()
    assert "load_board(" not in src and "read_board_records(" not in src and "Listing.model_validate" not in src


# ===========================================================================
# 6. PUBLISHERS
# ===========================================================================

def _git(root: Path, *args, check=True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {r.stdout}{r.stderr}")
    return r


def _repo(tmp_path: Path, install_hook: bool = False) -> Path:
    """A throwaway repo shaped like the real one: scripts/, src/foreclosure_scraper/board_parts.py, docs/."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "scripts").mkdir()
    for name in ("board_payload.sh", "check_staged_parts.py", "git_size_gate.sh"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    (root / "src" / "foreclosure_scraper").mkdir(parents=True)
    shutil.copy(REPO / "src" / "foreclosure_scraper" / "board_parts.py", root / "src" / "foreclosure_scraper" / "board_parts.py")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("docs/listings.json\ndocs/listings_detail.json\ndocs/listings_slim.json\nlogs/\n")
    if install_hook:
        (root / ".git" / "hooks" / "pre-commit").write_text(
            '#!/bin/sh\nROOT="$(git rev-parse --show-toplevel)"\nexec sh "$ROOT/scripts/git_size_gate.sh"\n')
        (root / ".git" / "hooks" / "pre-commit").chmod(0o755)
    return root


def _board_into(root: Path, n: int, cap: int = 24 * KiB, notes: str = "t") -> None:
    import unittest.mock as mock
    with mock.patch.object(bp, "PART_MAX_BYTES", cap), mock.patch.dict(os.environ, {"BOARD_ALLOW_SHRINK": "1"}):
        wa.write_artifact([_lead(i + (0 if notes == "t" else 10_000)) for i in range(n)], {"notes": notes},
                          docs_dir=root / "docs")


def _sh(root: Path, snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/sh", "-c", f'. "{root}/scripts/board_payload.sh"; {snippet}', "sh", str(root)],
                          capture_output=True, text=True)


def test_payload_paths_list_every_part_and_never_the_single_gz(tmp_path):
    root = _repo(tmp_path)
    _board_into(root, 600)
    n = len(_part_paths(root / "docs"))
    assert n >= 3
    (root / "docs" / "listings.json.gz").write_bytes(gzip.compress(b"[]"))
    paths = _sh(root, 'board_payload_paths "$1"').stdout.split()
    assert [p for p in paths if "listings_part_" in p] == [f"docs/{bp.part_name(i)}" for i in range(n)]
    assert "docs/listings.json.gz" not in paths
    assert "docs/board.manifest.json" in paths and "docs/run_meta.json" in paths
    assert "docs/listings.json" not in paths


def test_a_deleted_tracked_part_stays_in_the_list_so_its_deletion_is_staged(tmp_path):
    root = _repo(tmp_path)
    _board_into(root, 600)
    assert _sh(root, 'board_payload_add "$1"').returncode == 0
    _git(root, "commit", "-qm", "seed")
    last = _part_paths(root / "docs")[-1]
    last.unlink()
    assert f"docs/{last.name}" in _sh(root, 'board_payload_paths "$1"').stdout.split()
    _sh(root, 'board_payload_add "$1"')
    assert f"D\tdocs/{last.name}" in _git(root, "diff", "--cached", "--name-status").stdout


def test_board_payload_add_stages_all_parts_in_one_go_and_the_manifest_lists_exactly_them(tmp_path):
    root = _repo(tmp_path)
    _board_into(root, 600)
    r = _sh(root, 'board_payload_add "$1"; echo rc=$?')
    assert "rc=0" in r.stdout
    staged = set(_git(root, "diff", "--cached", "--name-only").stdout.split())
    names = {f"docs/{p.name}" for p in _part_paths(root / "docs")}
    assert names <= staged and "docs/board.manifest.json" in staged
    assert _sh(root, 'board_payload_verify_staged "$1"').returncode == 0


def test_a_part_that_cannot_be_staged_unstages_the_whole_board_payload(tmp_path):
    """All parts or none: half a part set beside a fresh slim/detail/shard set is a mis-joined board."""
    root = _repo(tmp_path)
    _board_into(root, 600)
    victim = _part_paths(root / "docs")[1]
    victim.chmod(0)                                                    # git add cannot read it
    try:
        r = _sh(root, 'board_payload_add "$1"; echo rc=$?')
        assert "rc=1" in r.stdout and "PARTS_STAGE_FAILED" in r.stderr
        assert _git(root, "diff", "--cached", "--name-only").stdout.strip() == "", \
            "nothing at all may stay staged when a part could not be"
    finally:
        victim.chmod(0o644)


def test_the_staged_parts_check_refuses_a_mixed_set(tmp_path):
    """Parts from two different writes staged together: the manifest lists ONE of them."""
    root = _repo(tmp_path)
    _board_into(root, 600, notes="t")
    old_part = _part_paths(root / "docs")[1].read_bytes()
    _board_into(root, 600, notes="other")                              # a different board, new manifest
    _part_paths(root / "docs")[1].write_bytes(old_part)                # ... with one part from the old write
    _sh(root, 'board_payload_add "$1"')
    r = _sh(root, 'board_payload_verify_staged "$1"')
    assert r.returncode == 1
    assert "sha256 does not match the manifest" in r.stderr or "size" in r.stderr, r.stderr


def test_the_staged_parts_check_refuses_a_stray_part_and_a_missing_manifest(tmp_path):
    root = _repo(tmp_path)
    _board_into(root, 600)
    _sh(root, 'board_payload_add "$1"')
    assert _sh(root, 'board_payload_verify_staged "$1"').returncode == 0
    # a part the manifest does not list (an origin part that survived a hard reset)
    extra = root / "docs" / bp.part_name(len(_part_paths(root / "docs")) + 2)
    extra.write_bytes(gzip.compress(b"[]"))
    _git(root, "add", str(extra.relative_to(root)))
    r = _sh(root, 'board_payload_verify_staged "$1"')
    assert r.returncode == 1 and "does not list it" in r.stderr
    _git(root, "rm", "-q", "--cached", str(extra.relative_to(root)))
    # parts staged without the manifest
    _git(root, "reset", "-q", "docs/board.manifest.json")
    (root / "docs" / "board.manifest.json").unlink()
    r = _sh(root, 'board_payload_verify_staged "$1"')
    assert r.returncode == 1 and "manifest" in r.stderr


def test_a_commit_that_touches_no_part_and_not_the_manifest_is_not_checked(tmp_path):
    root = _repo(tmp_path)
    (root / "docs" / "notes.txt").write_text("hello")
    _git(root, "add", "docs/notes.txt")
    assert _sh(root, 'board_payload_verify_staged "$1"').returncode == 0


def test_the_precommit_hook_blocks_a_mixed_commit_and_lets_a_consistent_one_through(tmp_path):
    root = _repo(tmp_path, install_hook=True)
    _board_into(root, 600)
    _sh(root, 'board_payload_add "$1"')
    good = _git(root, "commit", "-qm", "board", check=False)
    assert good.returncode == 0, good.stderr

    _board_into(root, 700, notes="other")
    _sh(root, 'board_payload_add "$1"')
    # tamper: stage the OLD manifest's view of one part by restoring it in the index
    victim = f"docs/{_part_paths(root / 'docs')[0].name}"
    _git(root, "reset", "-q", "HEAD", "--", victim)                    # the index keeps the OLD part
    bad = _git(root, "commit", "-qm", "mixed", check=False)
    assert bad.returncode != 0, "a mixed part set must not commit"
    assert "parts gate: REFUSED" in bad.stderr
    assert (root / "logs" / "publish_blocked.log").is_file()
    # ... and the size gate is still there for any file over the limit
    _git(root, "reset", "-q")
    _git(root, "checkout", "-q", "--", "docs")
    (root / "docs" / "big.bin").write_bytes(b"x" * 2048)
    _git(root, "add", "docs/big.bin")
    over = subprocess.run(["git", "-C", str(root), "commit", "-qm", "big"], capture_output=True, text=True,
                          env={**os.environ, "BOARD_SIZE_GATE_BYTES": "1024"})
    assert over.returncode != 0 and "size gate: BLOCKED" in over.stderr


def test_publish_commit_reports_parts_inconsistent_and_commits_nothing(tmp_path):
    root = _repo(tmp_path)
    for name in ("job_event.sh", "board_lock.sh", "publish_helper.sh", "run_timeout.pl"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    _board_into(root, 600, notes="t")
    old_part = _part_paths(root / "docs")[1].read_bytes()
    _board_into(root, 600, notes="other")
    _part_paths(root / "docs")[1].write_bytes(old_part)
    snippet = ('. "$1/scripts/job_event.sh"; . "$1/scripts/board_lock.sh"; . "$1/scripts/publish_helper.sh"; '
               'publish_commit "$1" "msg" any; echo "rc=$? result=$PUBLISH_COMMIT_RESULT"')
    r = subprocess.run(["/bin/sh", "-c", f'. "{root}/scripts/board_payload.sh"; {snippet}', "sh", str(root)],
                       capture_output=True, text=True)
    assert "rc=2 result=parts_inconsistent" in r.stdout, r.stdout + r.stderr
    assert _git(root, "diff", "--cached", "--name-only").stdout.strip() == "", "nothing may stay staged"
    assert _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0, "nothing was committed"


def test_unstash_drops_origin_parts_that_our_board_does_not_have(tmp_path):
    """The workflows `git reset --hard origin/main` and re-apply the payload. If origin has more
    parts than our board, the extras must not survive into our commit."""
    root = _repo(tmp_path)
    _board_into(root, 900)                                              # origin's board: many parts
    n_origin = len(_part_paths(root / "docs"))
    assert n_origin >= 4
    _sh(root, 'board_payload_add "$1"')
    _git(root, "commit", "-qm", "origin")
    _board_into(root, 300, notes="other")                               # OUR board: fewer parts
    ours = len(_part_paths(root / "docs"))
    assert ours < n_origin
    tar = tmp_path / "payload.tar"
    assert _sh(root, f'board_payload_stash "$1" "{tar}"').returncode == 0
    _git(root, "reset", "-q", "--hard", "HEAD")                         # origin's tree comes back
    assert len(_part_paths(root / "docs")) == n_origin
    assert _sh(root, f'board_payload_unstash "$1" "{tar}"').returncode == 0
    assert len(_part_paths(root / "docs")) == ours, "origin's extra parts must be removed"
    r = _sh(root, 'board_payload_add "$1"; echo rc=$?')
    assert "rc=0" in r.stdout
    assert _sh(root, 'board_payload_verify_staged "$1"').returncode == 0
    deleted = [ln for ln in _git(root, "diff", "--cached", "--name-status").stdout.splitlines() if ln.startswith("D")]
    assert len(deleted) == n_origin - ours


def test_python_publishers_stage_every_part_and_the_manifest(tmp_path):
    root = _repo(tmp_path)
    _board_into(root, 600)
    n = len(_part_paths(root / "docs"))
    spec = pub.board_seal_pathspec(root)
    assert spec[:n] == [f"docs/{bp.part_name(i)}" for i in range(n)] and spec[-1] == "docs/board.manifest.json"
    assert pub.parts_pathspec(root) == spec[:-1]
    assert "docs/listings.json.gz" not in spec
    _git(root, "add", *spec)
    _git(root, "commit", "-qm", "seed")
    _part_paths(root / "docs")[-1].unlink()                            # tracked-but-deleted still listed
    assert pub.parts_pathspec(root)[-1] == f"docs/{bp.part_name(n - 1)}"
    # and the two inline `pub` lists that used to name docs/listings.json.gz now use it
    for rel in ("scripts/daily_api_refresh.py", "scripts/patch_vision_gemini.py"):
        text = (REPO / rel).read_text()
        assert '"docs/listings.json.gz"' not in text.split("pub = ")[1].split("]")[0], rel
        assert "parts_pathspec" in text or "board_seal_pathspec" in text, rel


def test_the_workflows_that_stage_the_payload_check_the_set_before_committing():
    for rel in (".github/workflows/weekly.yml", ".github/workflows/patch-run-scrapers.yml",
                ".github/workflows/patch-listings.yml"):
        text = (REPO / rel).read_text()
        assert "board_payload_verify_staged" in text, rel
        assert text.count("board_payload_verify_staged") >= text.count('board_payload_add "$PWD"'), rel
    assert "listings.json.gz" not in (REPO / ".github/workflows/patch-listings.yml").read_text().replace(
        "no longer one listings.json.gz", "")


# ===========================================================================
# 7. size and Pages checks, the watcher, the private publisher, restore
# ===========================================================================

def _sparse(path: Path, mib: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.truncate(int(mib * 1024 * 1024))


def _size(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / "check_payload_size.py"), "--root", str(root), "--no-site", *args],
                          capture_output=True, text=True)


def test_payload_size_checks_every_part_against_the_part_cap(tmp_path):
    for i in range(4):
        _sparse(tmp_path / "docs" / bp.part_name(i), 21.5)             # 86 MiB in all: fine, per file
    r = _size(tmp_path, "--json")
    data = json.loads(r.stdout)
    assert r.returncode == 0 and all(f["status"] == "ok" for f in data["files"])
    assert data["board_parts"]["count"] == 4 and data["board_parts"]["total_mib"] == 86.0
    _sparse(tmp_path / "docs" / bp.part_name(2), 26)                   # over the part cap, far under GitHub's
    r = _size(tmp_path, "--json")
    data = json.loads(r.stdout)
    by = {f["path"]: f for f in data["files"]}
    assert by["docs/listings_part_002.json.gz"]["status"] == "OVER_PART" and r.returncode == 1
    _sparse(tmp_path / "docs" / bp.part_name(2), 97)                   # GitHub's own wall still BLOCKs
    assert _size(tmp_path).returncode == 2


def test_payload_size_reports_a_part_set_that_disagrees_with_the_manifest(tmp_path):
    docs = tmp_path / "docs"
    _write(docs, 300)
    assert _size(tmp_path).returncode == 0
    p = _part_paths(docs)[0]
    p.write_bytes(p.read_bytes() + b"x")
    r = _size(tmp_path, "--json")
    data = json.loads(r.stdout)
    assert r.returncode == 2 and any("torn" in m or "bytes" in m for m in data["parts_problems"])
    p.write_bytes(p.read_bytes()[:-1])
    (docs / "listings.json.gz").write_bytes(b"old")                    # a lingering single file: warn only
    r = _size(tmp_path, "--json")
    assert r.returncode == 1 and json.loads(r.stdout)["parts_warnings"]


def test_job_watch_alarms_on_an_oversized_part_and_a_torn_set(tmp_path):
    docs = tmp_path / "docs"
    _write(docs, 300)
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPTS / "check_payload_size.py", tmp_path / "scripts" / "check_payload_size.py")
    (tmp_path / "logs").mkdir()
    p = _part_paths(docs)[0]
    p.write_bytes(p.read_bytes() + b"x")
    subprocess.run([sys.executable, str(SCRIPTS / "job_watch.py"), "--root", str(tmp_path), "--no-notify", "--expect", "x:1"],
                   capture_output=True, text=True)
    assert "board parts:" in (tmp_path / "logs" / "job_alerts.log").read_text()
    _sparse(docs / bp.part_name(1), 30)
    (tmp_path / "logs" / ".job_watch_state.json").unlink(missing_ok=True)
    subprocess.run([sys.executable, str(SCRIPTS / "job_watch.py"), "--root", str(tmp_path), "--no-notify", "--expect", "x:1"],
                   capture_output=True, text=True)
    assert "over the 24 MiB board-part cap" in (tmp_path / "logs" / "job_alerts.log").read_text()


def _load_pages_checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cpp_split", SCRIPTS / "check_pages_publish.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pages_check_requires_the_parts_and_the_live_config_publishes_them():
    mod = _load_pages_checker()
    assert "listings_part_000.json.gz" in mod.REQUIRED and "listings_part_000.json.gz" in mod.SIMULATED
    exclude, include = mod.parse_config((REPO / "docs" / "_config.yml").read_text())
    for name in ("listings_part_000.json.gz", "listings_part_007.json.gz", "listings_part_123.json.gz"):
        assert mod.decide(name, exclude, include)[0], name
    # the design claim: the parts need no include, because no exclude is a prefix of their name
    assert mod.decide("listings_part_000.json.gz", exclude, [])[0]
    assert not mod.decide("listings.json.gz", exclude, [])[0], "the trap the name avoids"


def test_pages_check_evaluates_every_part_on_disk(tmp_path):
    mod = _load_pages_checker()
    docs = tmp_path / "docs"
    docs.mkdir()
    for i in range(5):
        (docs / bp.part_name(i)).write_bytes(b"x")
    mod.DOCS = docs
    assert [n for n in mod._parts_on_disk()] == [bp.part_name(i) for i in range(5)]


# ---- publish_private.sh ------------------------------------------------------------------

def _private(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/sh", str(SCRIPTS / "publish_private.sh"), "--root", str(root), *args],
                          capture_output=True, text=True, env={**os.environ, "PATH": os.environ["PATH"]})


def _private_root(tmp_path: Path, n: int = 600, cap: int = 24 * KiB) -> Path:
    root = tmp_path / "priv"
    (root / "docs").mkdir(parents=True)
    import unittest.mock as mock
    with mock.patch.object(bp, "PART_MAX_BYTES", cap):
        wa.write_artifact([_lead(i) for i in range(n)], {"notes": "t"}, docs_dir=root / "docs")
    return root


def test_publish_private_dry_run_releases_every_part_named_in_run_meta(tmp_path):
    root = _private_root(tmp_path)
    n = len(_part_paths(root / "docs"))
    assert n >= 3
    r = _private(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"{n} parts, 600 rows" in r.stdout
    for i in range(n):
        assert bp.part_name(i) in r.stdout
    assert "listings.json.gz" not in r.stdout.replace("single listings.json.gz", "")


def test_publish_private_refuses_a_torn_or_mixed_part_set(tmp_path):
    root = _private_root(tmp_path)
    docs = root / "docs"
    parts = _part_paths(docs)

    good = parts[1].read_bytes()
    parts[1].write_bytes(good[:-1] + bytes([good[-1] ^ 1]))               # same size, wrong sha
    r = _private(root)
    assert r.returncode == 1 and "sha256" in r.stderr
    parts[1].write_bytes(good[:-4])
    assert "bytes" in _private(root).stderr
    parts[1].unlink()
    assert "missing" in _private(root).stderr
    parts[1].write_bytes(good)
    (docs / bp.part_name(len(parts) + 1)).write_bytes(gzip.compress(b"[]"))
    r = _private(root)
    assert r.returncode == 1 and "does not list" in r.stderr
    (docs / bp.part_name(len(parts) + 1)).unlink()
    assert _private(root).returncode == 0


def test_publish_private_refuses_an_oversized_part_and_falls_back_to_a_pre_split_release(tmp_path):
    root = _private_root(tmp_path)
    docs = root / "docs"
    meta = _run_meta(docs)
    meta["board_parts"]["files"][0]["bytes"] = 26 * 1024 * 1024
    (docs / "run_meta.json").write_text(json.dumps(meta))
    _sparse(docs / bp.part_name(0), 26)
    assert "25 MiB per-asset cap" in _private(root).stderr

    legacy = _private_root(tmp_path / "second")
    ld = legacy / "docs"
    meta = _run_meta(ld)
    meta.pop("board_parts")
    (ld / "run_meta.json").write_text(json.dumps(meta))
    for p in _part_paths(ld):
        p.unlink()
    assert _private(legacy).returncode == 1                                # no board at all: refused
    (ld / "listings.json.gz").write_bytes(gzip.compress(b"[]"))
    r = _private(legacy)
    assert r.returncode == 0 and "pre-split layout" in r.stdout + r.stderr


# ---- restore_board.sh ----------------------------------------------------------------------

def _restore_repo(tmp_path: Path) -> tuple:
    from tests._ops_helpers import make_repo, _run
    root = make_repo(tmp_path)
    docs = root / "docs"
    for f in ("listings.json.gz",):
        (docs / f).unlink()
    (root / ".gitignore").write_text("logs/\ndocs/listings.json\ndocs/listings_detail.json\ndocs/listings_slim.json\n")
    return root, docs, _run


def _commit_board(root: Path, docs: Path, n: int, cap: int, tag: str, _run) -> str:
    import unittest.mock as mock
    for p in docs.glob("listings_part_*.json.gz"):
        p.unlink()
    with mock.patch.object(bp, "PART_MAX_BYTES", cap):
        wa.write_artifact([_lead(i) for i in range(n)], {"notes": tag}, docs_dir=docs)
    _run(["git", "add", "-A", "docs"], cwd=root)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "commit", "-q", "-m", tag], cwd=root)
    return _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()


def test_restore_rebuilds_the_board_from_the_parts_of_one_commit(tmp_path):
    from tests._ops_helpers import make_env
    root, docs, _run = _restore_repo(tmp_path)
    old = _commit_board(root, docs, 500, 30 * KiB, "board-old", _run)
    n_old = len(_part_paths(docs))
    _commit_board(root, docs, 1200, 30 * KiB, "board-newer", _run)
    n_new = len(_part_paths(docs))
    assert n_new > n_old
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), old, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 0, out.stdout + out.stderr
    assert len(_part_paths(docs)) == n_old, "the newer board's extra parts must not survive the restore"
    assert "manifest check: MATCHES" in out.stdout
    assert bp.verify_dir(docs)["ok"]
    assert len(bp.read_rows(docs)) == 500
    kept = list((root / "backups").glob("pre-restore-*"))
    assert len(kept) == 1 and len(list(kept[0].glob("listings_part_*.json.gz"))) == n_new
    assert _run(["git", "diff", "--cached", "--name-only"], cwd=root).stdout == ""


def test_restore_of_a_pre_split_commit_removes_the_parts_and_brings_back_the_single_file(tmp_path):
    from tests._ops_helpers import make_env
    root, docs, _run = _restore_repo(tmp_path)
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(_rows(5)).encode()))
    _run(["git", "add", "-A", "docs"], cwd=root)
    _run(["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "commit", "-q", "-m", "pre-split"], cwd=root)
    pre = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    _run(["git", "rm", "-q", "docs/listings.json.gz"], cwd=root)
    _commit_board(root, docs, 400, 30 * KiB, "post-split", _run)
    assert _part_paths(docs)
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), pre, "--yes"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 0, out.stdout + out.stderr
    assert not _part_paths(docs), "a pre-split commit must not be left beside newer parts"
    assert len(list(iter_board_rows(docs / "listings.json.gz"))) == 5


def test_restore_list_names_the_parts_boards(tmp_path):
    from tests._ops_helpers import make_env
    root, docs, _run = _restore_repo(tmp_path)
    _commit_board(root, docs, 500, 30 * KiB, "the-board", _run)
    out = subprocess.run([str(root / "scripts" / "restore_board.sh"), "--list", "3"], capture_output=True, text=True,
                         env=make_env(root), cwd=str(root))
    assert out.returncode == 0 and "the-board" in out.stdout and "parts]" in out.stdout and "MiB" in out.stdout


# ---- git_size_gate / hooks stay ----------------------------------------------------------------

def test_the_95_mib_gate_is_still_in_the_hook():
    gate = (SCRIPTS / "git_size_gate.sh").read_text()
    assert "99614720" in gate and "BLOCKED" in gate
    assert "check_staged_parts.py" in gate


def test_no_script_or_module_still_writes_the_single_gz_twin_of_the_board():
    """The single file is retired: nothing may regenerate it (a stale one beside the parts is exactly
    the confusion the split removes)."""
    offenders = []
    for path in list((REPO / "src").rglob("*.py")) + list(SCRIPTS.glob("*.py")):
        text = path.read_text(errors="ignore")
        if path.name in ("migrate_board_to_parts.py", "check_pages_publish.py", "check_payload_size.py",
                         "merge_title_search.py"):
            continue                                        # migration input, legacy checks, a one-off
        for line in text.splitlines():
            code = line.split("#")[0]
            if 'listings.json.gz' in code and ("write_bytes" in code or '"wb"' in code or "gzip.open" in code and '"wt"' in code):
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, offenders


def test_every_reader_of_the_single_gz_goes_through_the_parts_aware_readers():
    """Every script that names docs/listings.json.gz either hands it to iter_board_rows / a parts-aware
    helper or is on the short list of files that only mention it."""
    naked = []
    for path in SCRIPTS.glob("*.py"):
        text = path.read_text(errors="ignore")
        if path.name in ("migrate_board_to_parts.py", "check_pages_publish.py", "check_payload_size.py",
                         "merge_title_search.py", "board_manifest.py", "check_staged_parts.py"):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            code = line.split("#")[0]
            if "gzip.open(" in code and "listings.json.gz" in code:
                naked.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not naked, naked

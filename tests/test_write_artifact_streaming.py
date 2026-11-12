"""write_artifact() streams the board (2026-10-05) and must still write the SAME BYTES.

The VM's 18h full run on 2026-10-05 (270,232 rows) was OOM-killed one step before
write_artifact, and write_artifact itself would have held a dict copy of every row, every row's
serialized bytes (~3 GB), the prior board parsed in full, the sidecar and the slim payload twice.
It now holds none of that (see its MEMORY docstring). Everything the dashboard and every reader
consume -- listings.json, the parts, the sidecar and its .gz, slim + .gz, the detail shards,
run_meta.json, the manifest -- must be byte-identical to what the list version wrote for the same
input. The list version is kept VERBATIM in tests/fixtures/write_artifact_list_version.py and
exec'd against the module's own helpers; each scenario below runs both writers over the same
inputs (same frozen clock) and compares every file they leave behind.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from foreclosure_scraper import board_parts as bp
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType

FIXTURE = Path(__file__).parent / "fixtures" / "write_artifact_list_version.py"
FIXED_NOW = datetime(2026, 10, 5, 12, 0, 0)
T0 = datetime(2026, 1, 2, 3, 4, 5)


class _FixedDT(datetime):
    @classmethod
    def utcnow(cls):
        return FIXED_NOW


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(wa, "datetime", _FixedDT)


def _reference_writer():
    """The pre-streaming write_artifact, verbatim, bound to web_artifact's current globals
    (built after any monkeypatching a test does, so both writers see the same module)."""
    ns = dict(vars(wa))
    exec(compile(FIXTURE.read_text(), str(FIXTURE), "exec"), ns)  # noqa: S102 - test-only, our own file
    return ns["write_artifact"]


def _lead(i: int, gen: int = 0, *, lazy: bool = True, shared: dict | None = None) -> Listing:
    """A deliberately messy lead. `gen` lets a later board change some rows."""
    aggregator = i % 7 == 0
    raw: dict = {
        "grade": {"overall": "BCDA"[i % 4], "overall_score": 50 + i % 50},
        "calc": {"arv_expected": 100000.5 + i * 3.25 + gen, "confidence": "high"},
        "owner_mailing": {"mailing": f"PO Box {i}", "absentee": bool(i % 2), "owner": "x"},
        "also_seen_in": [{"url": f"https://a/{i}", "source": "s1", "note": "n"}],
        "life_events": ["estate_probate"] * (i % 3),
        "eviction_market": {"rate": i / 7.0, "label": "Ünïcødé — “quoted” ✓"},
        "tax_owed": {"balance": i * 11.11, "year": 2020 + i % 5},
        "acres": "2.5 acres" if i % 5 == 0 else None,
        "observed_at": T0,                      # non-JSON type: default=str path
        "not_in_raw_keep": {"dropped": True},
    }
    if lazy and i % 3 != 0:
        raw["comps"] = [{"sold_price": 200000 + i, "addr": f"{i} Comp Rd"}]
        raw["vision"] = {"parsed": True, "condition": "fair", "score": i % 10}
    if i % 4 == 0:
        raw["cama"] = {"condition": "average", "year": 1990 + i % 30}
    if shared is not None:
        raw["fallback_links"] = shared            # the SAME dict object on several leads
    if gen and i % 5 == 0:
        raw["distress_stack"] = {"tier": "WARM", "gen": gen}
    url = (f"https://www.zillow.com/homedetails/{i}_zpid/" if aggregator
           else f"https://county.example/case/{i // 2 if i % 11 == 0 else i}")   # some shared urls
    return Listing(
        source=f"src.{i % 9}", source_url=url,
        listing_type=[ListingType.FORECLOSURE_SALE, ListingType.TAX_LIEN, ListingType.LIS_PENDENS][i % 3],
        state="NC" if i % 2 else "SC",
        county=["Gaston", "Anderson", "Spartanburg", None][i % 4],
        parcel_id=(f"P{i}" if i % 13 else "P-dup"),
        street_address=(f"{i} Main St" if i % 17 else "Lis Pendens tract"),
        city="Gastonia", zip_code=f"28{i % 1000:03d}" if i % 6 else None,
        owner_name=f"Owner {i} José", description=("Vacant lot. " * (i % 4)) or None,
        legal_description=("LOT " * 120) if i % 10 == 0 else None,
        latitude=35.0 + i / 1e4, longitude=-81.0 - i / 1e4, opening_bid=1000.0 * (i % 9),
        first_seen=T0, last_seen=T0, raw=raw,
    )


def _board(n: int, gen: int = 0) -> list[Listing]:
    shared_a: dict = {}
    shared_b: dict = {"google": "https://preexisting"}
    out = []
    for i in range(n):
        shared = shared_a if i in (7, 14, 21) else shared_b if i in (28, 35) else None
        # gen 1: rows lose their own lazy detail every 4th row (prior must backfill), the
        # order shifts and a few rows are new
        lazy = not (gen and i % 4 == 1)
        out.append(_lead(i + (5 if gen and i % 50 == 0 else 0), gen, lazy=lazy, shared=shared))
    if gen:
        out = out[3:] + out[:3]
    return out


def _snapshot(docs: Path) -> dict:
    return {str(p.relative_to(docs)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(docs.rglob("*")) if p.is_file()}


def _run_both(tmp_path: Path, boards, summaries=None, before_each=None) -> tuple[dict, dict]:
    """Run the reference and the streaming writer over the same sequence of boards, each into
    its own docs dir; returns ({file: sha} after the last write) for each."""
    out = []
    for which in ("reference", "streaming"):
        docs = tmp_path / which / "docs"
        writer = _reference_writer() if which == "reference" else wa.write_artifact
        for k, make in enumerate(boards):
            if before_each:
                before_each(docs, k)
            writer(make(), (summaries or [{"notes": f"w{k}"}] * len(boards))[k], docs_dir=docs)
        out.append(_snapshot(docs))
    return out[0], out[1]


def _assert_same(ref: dict, new: dict) -> None:
    assert sorted(ref) == sorted(new), "different file sets"
    diff = [f for f in ref if ref[f] != new[f]]
    assert not diff, f"files differ: {diff}"


@pytest.fixture
def small_parts(monkeypatch):
    # force many parts and the over-cap re-cut path
    monkeypatch.setattr(bp, "PART_MAX_BYTES", 40_000)


def test_large_board_first_write_then_rewrite_is_byte_identical(tmp_path, small_parts):
    """3,500 rows: > the 2,400-row sampling threshold, 4 detail shards, many parts; then a
    reordered, partly re-enriched rewrite that exercises the prior-sidecar backfill."""
    ref, new = _run_both(tmp_path, [lambda: _board(3500), lambda: _board(3500, gen=1)])
    _assert_same(ref, new)
    names = set(ref)
    assert {"listings.json", "listings_detail.json", "listings_detail.json.gz", "listings_slim.json",
            "listings_slim.json.gz", "run_meta.json", "board.manifest.json"} <= names
    assert sum(1 for f in names if f.startswith("listings_part_")) > 5
    assert sum(1 for f in names if f.startswith("detail_shards/")) == 4


def test_backfill_and_shared_mutation_cases_are_actually_exercised(tmp_path, small_parts):
    """Guard the guard: the second write really did pull comps/vision from the prior sidecar,
    and a lead whose raw['fallback_links'] is shared with a LATER lead was published with the
    keys that later lead added (the reason write_artifact converts every row before encoding)."""
    docs = tmp_path / "d"
    wa.write_artifact(_board(3500), {"notes": "a"}, docs_dir=docs)
    wa.write_artifact(_board(3500, gen=1), {"notes": "b"}, docs_dir=docs)
    det = wa.read_board_json(docs / "listings_detail.json")
    rows = wa.read_board_json(docs / "listings.json")
    # gen-1 rows i % 4 == 1 carry no comps of their own; every one that had comps last time
    # (i % 3 != 0) and a key unique on both boards must have them back from the prior sidecar
    own_less = {f"https://county.example/case/{i}" for i in range(3500)
                if i % 4 == 1 and i % 3 != 0 and i % 7 and i % 11 and i % 50}
    hits = [d for r, d in zip(rows, det) if r["source_url"] in own_less]
    filled = [d for d in hits if d.get("comps") and d.get("vision")]
    assert len(hits) > 100 and len(filled) > 0.9 * len(hits)   # the rest: every key ambiguous
    by_url = {r["source_url"]: r for r in rows}
    a7 = by_url["https://www.zillow.com/homedetails/7_zpid/"]["raw"]["fallback_links"]
    a21 = by_url["https://www.zillow.com/homedetails/21_zpid/"]["raw"]["fallback_links"]
    # row 7 (no county) is published WITH the parcel_gis key that row 14 (Spartanburg) adds later
    assert a7 == a21 and "parcel_gis" in a7


def test_small_board_and_empty_board_are_byte_identical(tmp_path):
    ref, new = _run_both(tmp_path, [lambda: _board(50), lambda: _board(60, gen=1)])
    _assert_same(ref, new)
    ref, new = _run_both(tmp_path / "empty", [lambda: []])
    _assert_same(ref, new)


def test_gz_only_prior_board_is_byte_identical(tmp_path, small_parts):
    """A fresh clone: only the parts and the sidecar .gz exist when the second write runs."""
    def drop_plain(docs: Path, k: int) -> None:
        if k == 1:
            for name in ("listings.json", "listings_detail.json", "listings_slim.json"):
                (docs / name).unlink()
    ref, new = _run_both(tmp_path, [lambda: _board(2600), lambda: _board(2600, gen=1)],
                         before_each=drop_plain)
    _assert_same(ref, new)


@pytest.mark.parametrize("env", ["FORECLOSURE_SLIM", "FORECLOSURE_DETAIL_SHARDS"])
def test_emergency_stops_are_byte_identical(tmp_path, monkeypatch, env):
    def stop_on_second(docs: Path, k: int) -> None:
        if k == 1:
            monkeypatch.setenv(env, "0")
        else:
            monkeypatch.delenv(env, raising=False)
    ref, new = _run_both(tmp_path, [lambda: _board(1200), lambda: _board(1200, gen=1)],
                         before_each=stop_on_second)
    _assert_same(ref, new)
    assert not any(f.startswith("detail_shards/") for f in new)


def test_a_slim_projection_failure_is_byte_identical(tmp_path, monkeypatch):
    real = wa._project_slim_record

    def flaky(rec):
        if rec.get("parcel_id") == "P40":
            raise ValueError("boom")
        return real(rec)
    monkeypatch.setattr(wa, "_project_slim_record", flaky)
    ref, new = _run_both(tmp_path, [lambda: _board(1500)])
    _assert_same(ref, new)
    assert "listings_slim.json" not in new and not any(f.startswith("detail_shards/") for f in new)


def test_a_failure_mid_stream_leaves_the_published_set_untouched(tmp_path, small_parts, monkeypatch):
    docs = tmp_path / "d"
    wa.write_artifact(_board(3000), {"notes": "a"}, docs_dir=docs)
    before = _snapshot(docs)
    real = wa._to_dict
    calls = {"n": 0}

    def dies_late(li):
        # pass 1 (3,000 rows) + the part-size samples (2,400 rows) convert first; this dies
        # half way through pass 2, after several parts and most of listings.json are staged
        calls["n"] += 1
        if calls["n"] > 3000 + 2400 + 1500:
            raise OSError("disk full")
        return real(li)
    monkeypatch.setattr(wa, "_to_dict", dies_late)
    with pytest.raises(OSError):
        wa.write_artifact(_board(3000, gen=1), {"notes": "b"}, docs_dir=docs)
    assert _snapshot(docs) == before, "a published file changed before every row had converted"
    assert not [p for p in docs.iterdir() if p.name.endswith(".tmp")], "temp files left behind"


def test_streamed_row_count_and_sample_groups_match_the_list_rules():
    for n in (0, 1, 2399, 2400, 2401, 3500, 270232):
        blobs = [str(i).encode() for i in range(n)] if n < 5000 else None
        idx = bp.sample_index_groups(n)
        if blobs is not None:
            assert bp.sample_groups_for(n, lambda i: blobs[i]) == [list(g) for g in bp._sample_groups(blobs)]
        assert sum(len(r) for r in idx) == min(n, bp.SAMPLE_CHUNKS * bp.SAMPLE_CHUNK_ROWS) or n <= 2400

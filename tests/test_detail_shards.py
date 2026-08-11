"""Detail shards — the per-lead mobile detail payload.

docs/detail_shards/NNNNN.json.gz lets a phone fetch the detail for the ONE lead
it opened instead of inflating all 70.8 MB of listings_detail.json. Shard k
covers board indices [k*SIZE, (k+1)*SIZE); index alignment is the same join
listings.json / listings_detail.json / listings_slim.json already use.

The three things that would make this dangerous rather than merely broken, and
which are therefore tested here as facts rather than asserted in a comment:

  1. It must be ADDITIVE. listings.json + listings_detail.json are TOGETHER the
     only full-fidelity board on disk. If emitting shards perturbs one byte of
     them (or of the slim payload), an unattended launchd job bakes that loss in
     permanently on the next load_board().
  2. A shard must carry the COMPLEMENT of the slim projection, not just
     LAZY_DETAIL_KEYS. "Everything We Found" is a reflective sweep over
     Object.keys(raw); a name allowlist cannot preserve a reflective reader.
  3. On failure the directory must be REMOVED and the metadata omitted, in
     lockstep, so the client falls back to the honest "open on desktop" note
     instead of rendering one lead's comps under another lead's address.
"""
from __future__ import annotations

import gzip
import json

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import (
    DETAIL_SHARD_DIR,
    DETAIL_SHARD_SCHEMA,
    DETAIL_SHARD_SIZE,
    LAZY_DETAIL_KEYS,
    _SHARD_SKIP_RAW,
    write_artifact,
)

# Payload files whose bytes may never move because a shard emit happened.
_AUTHORITATIVE = (
    "listings.json", "listings.json.gz",
    "listings_detail.json", "listings_detail.json.gz",
    "listings_slim.json", "listings_slim.json.gz",
)


def _lead(i: int) -> Listing:
    """A lead carrying one key from every class the shard rule discriminates."""
    raw = {
        # slim keeps these WHOLE ("*" / scalar) -> must NOT be duplicated
        "grade": {"overall": "B"},
        "calc": {"arv_expected": 100000 + i},
        "intent_score": 55 + i,
        "stale_case": False,
        # slim keeps only a SUB-TUPLE -> shard must carry the FULL block
        "zillow": {"photo": f"p{i}.jpg", "description": f"desc {i}",
                   "zestimate": 200000 + i, "taxAssessedValue": 90000 + i},
        "gis": {"owner": f"OWNER {i}", "mailing": f"{i} Elsewhere Rd",
                "last_sale": {"amount": 1000 * i}},
        "signal_stack": {"count": 3, "signals": ["a", "b", "c"]},
        "equity": {"value": 50000, "pct": 0.5, "is_underwater": False,
                   "payoff_source": "dot_ocr"},
        # slim drops these outright -> shard must carry them
        "amount_owed": {"value": 42000 + i},
        "tenure": {"years_held": 12},
        "eviction_market": {"pressure": "high"},
        "recorded_sales": [{"price": 123000, "date": "2019-04-01"}],
        # lossily projected by slim (list -> int, sub-key map) -> full in shard
        "life_events": ["estate_probate", "multiple_heirs"],
        # LAZY_DETAIL_KEYS: popped into the sidecar, must come back via the shard
        "comps": [{"addr": f"{i} Main St", "price": 200000}],
        "vision": {"parsed": True, "condition": "major", "blob": "x" * 40},
        "cama": {"heated_sqft": 1500 + i, "building_type": "MOBILE HOME"},
        "rent_comps": [{"rent": 1200}],
        "foreclosure_sold_comps": [{"sold_price": 88000}],
    }
    return Listing(source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", street_address=f"{100 + i} Main St",
                   owner_name=f"Lead {i} LLC", raw=raw)


def _read_shard(docs, k):
    return json.loads(gzip.decompress((docs / DETAIL_SHARD_DIR / f"{k:05d}.json.gz").read_bytes()))


def _snapshot(docs) -> dict:
    return {n: (docs / n).read_bytes() for n in _AUTHORITATIVE if (docs / n).exists()}


# --------------------------------------------------------------------------
# 1. Additive: the authoritative payloads must not move.
# --------------------------------------------------------------------------

def test_authoritative_payloads_are_byte_identical_with_and_without_shards(tmp_path, monkeypatch):
    """PROVE, not assert, that shards cost the board nothing.

    Same input written twice: once with the shard emitter switched off, once
    with it on. Every authoritative byte must match. This is the guard against
    the one failure mode that is unrecoverable — a derivative reaching back into
    `payload` (it passes sub-objects by reference) and mutating the board before
    it is serialized.
    """
    # ONE set of Listing objects, written twice. Rebuilding them would introduce
    # the per-object timestamps the model stamps at construction and the
    # comparison would be of two different boards. Reusing them is also the
    # stronger test: _shard_record walks raw's sub-objects BY REFERENCE, so if it
    # wrote into any of them the second write_artifact would serialize the damage.
    leads = [_lead(i) for i in range(7)]

    on = tmp_path / "on"
    write_artifact(leads, {"notes": "t"}, docs_dir=on)
    with_shards = _snapshot(on)
    assert (on / DETAIL_SHARD_DIR / "00000.json.gz").exists()

    off = tmp_path / "off"
    monkeypatch.setenv("FORECLOSURE_DETAIL_SHARDS", "0")
    write_artifact(leads, {"notes": "t"}, docs_dir=off)
    without_shards = _snapshot(off)
    assert not (off / DETAIL_SHARD_DIR).exists(), "emergency stop must emit nothing"

    assert set(with_shards) == set(without_shards) == set(_AUTHORITATIVE)
    for name in _AUTHORITATIVE:
        assert with_shards[name] == without_shards[name], (
            f"{name} is not byte-identical with and without the shard emit"
        )


def test_shard_emit_does_not_mutate_the_board_it_reads(tmp_path):
    """The shard of a lead must not be reachable from the published record.

    _shard_record passes sub-objects by reference for memory reasons, so the
    proof that matters is that listings.json still lacks the lazy keys and still
    carries the card-scope ones after the shard pass ran over the same objects.
    """
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    rec = json.loads((tmp_path / "listings.json").read_text())[0]
    raw = rec["raw"]
    assert not any(k in raw for k in LAZY_DETAIL_KEYS)
    assert raw["grade"]["overall"] == "B" and raw["calc"]["arv_expected"] == 100000
    assert raw["amount_owed"]["value"] == 42000        # still in the fat board


# --------------------------------------------------------------------------
# 2. Content: the complement of slim, not just LAZY_DETAIL_KEYS.
# --------------------------------------------------------------------------

def test_shard_carries_the_lazy_sidecar(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    shard = _read_shard(tmp_path, 0)
    detail = json.loads((tmp_path / "listings_detail.json").read_text())
    assert len(shard) == 2
    for i in range(2):
        for k in LAZY_DETAIL_KEYS:
            assert shard[i][k] == detail[i][k], k


def test_shard_carries_raw_keys_slim_drops(tmp_path):
    """The whole point of the complement. A shard of only LAZY_DETAIL_KEYS would
    leave ~46 "Everything We Found" blocks blank on the phone."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    shard = _read_shard(tmp_path, 0)[0]
    slim_raw = json.loads((tmp_path / "listings_slim.json").read_text())[0]["raw"]

    for k in ("amount_owed", "tenure", "eviction_market", "recorded_sales"):
        assert k not in slim_raw, f"{k} unexpectedly survives the slim projection"
        assert k in shard, f"{k} is dropped by slim and missing from the shard"


def test_shard_restores_blocks_slim_only_partially_keeps(tmp_path):
    """A block slim keeps a SUB-TUPLE of must arrive WHOLE.

    The client merge is a top-level assign, so a partial block in the shard
    would replace — not deepen — the partial block already on the record, and
    the detail panel reads exactly the sub-keys slim drops.
    """
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    shard = _read_shard(tmp_path, 0)[0]
    slim_raw = json.loads((tmp_path / "listings_slim.json").read_text())[0]["raw"]

    assert set(slim_raw["zillow"]) == {"photo"}
    assert shard["zillow"]["description"] == "desc 0"
    assert shard["zillow"]["zestimate"] == 200000

    assert set(slim_raw["gis"]) == {"owner"}
    assert shard["gis"]["mailing"] == "0 Elsewhere Rd"

    assert set(slim_raw["signal_stack"]) == {"count"}
    assert shard["signal_stack"]["signals"] == ["a", "b", "c"]

    assert "payoff_source" not in slim_raw["equity"]
    assert shard["equity"]["payoff_source"] == "dot_ocr"

    # life_events is an int in slim (the client only reads .length) and the list
    # itself is what the panel renders.
    assert slim_raw["life_events"] == 2
    assert shard["life_events"] == ["estate_probate", "multiple_heirs"]


def test_shard_omits_what_slim_already_carries_whole(tmp_path):
    """No duplication of grade/calc/scalars — slim ships those in full and they
    are the largest blocks on the record."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    shard = _read_shard(tmp_path, 0)[0]
    for k in ("grade", "calc", "intent_score", "stale_case"):
        assert k in _SHARD_SKIP_RAW
        assert k not in shard, f"{k} duplicated into the shard"


def test_skip_set_is_derived_from_the_slim_projector(tmp_path):
    """_SHARD_SKIP_RAW must stay a derivation, never a hand-kept second list —
    that is how it cannot drift from _SLIM_RAW the way the client/build
    allowlists did."""
    from foreclosure_scraper.web_artifact import _SLIM_RAW, _SLIM_RAW_SCALARS
    expected = {k for k, v in _SLIM_RAW.items() if v == "*"} | set(_SLIM_RAW_SCALARS)
    assert set(_SHARD_SKIP_RAW) == expected
    # A block slim keeps only part of must NOT be in the skip set.
    for k, v in _SLIM_RAW.items():
        if v != "*":
            assert k not in _SHARD_SKIP_RAW, k


# --------------------------------------------------------------------------
# 3. Index alignment and the run_meta contract.
# --------------------------------------------------------------------------

def test_index_alignment_across_shards(tmp_path, monkeypatch):
    """Shard k holds indices [k*size, (k+1)*size) and shard-local offset
    i % size — the arithmetic the client does to find one lead."""
    monkeypatch.setattr("foreclosure_scraper.web_artifact.DETAIL_SHARD_SIZE", 4)
    leads = [_lead(i) for i in range(10)]
    write_artifact(leads, {"notes": "t"}, docs_dir=tmp_path)

    meta = json.loads((tmp_path / "run_meta.json").read_text())
    ds = meta["board"]["detail_shards"]
    assert ds == {"schema": DETAIL_SHARD_SCHEMA, "dir": DETAIL_SHARD_DIR,
                  "size": 4, "count": 3, "records": 10}
    # slim's own keys are untouched siblings — the client's boardExpectedCount
    # gates on board.schema == "slim-v1" and would go blind if they moved.
    assert meta["board"]["schema"] == "slim-v1"
    assert meta["board"]["count"] == 10

    listings = json.loads((tmp_path / "listings.json").read_text())
    for i in range(10):
        shard = _read_shard(tmp_path, i // 4)
        entry = shard[i % 4]
        assert entry["comps"][0]["addr"] == f"{i} Main St"
        assert entry["cama"]["heated_sqft"] == 1500 + i
        assert listings[i]["street_address"] == f"{100 + i} Main St"
    assert len(_read_shard(tmp_path, 2)) == 2      # ragged tail, not padded


def test_empty_records_are_emitted_not_skipped(tmp_path):
    """A lead with nothing to shard still occupies its slot: index IS the join."""
    bare = Listing(source="x", source_url="u9", listing_type=ListingType.FORECLOSURE_SALE,
                   state="NC", county="Gaston", raw={"grade": {"overall": "D"}})
    write_artifact([bare, _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    shard = _read_shard(tmp_path, 0)
    assert len(shard) == 2
    assert shard[0] == {}
    assert shard[1]["comps"][0]["addr"] == "1 Main St"


def test_default_shard_size_is_declared_not_implied():
    """The client must read `size` from run_meta rather than hardcode 1000."""
    assert DETAIL_SHARD_SIZE == 1000
    assert DETAIL_SHARD_DIR == "detail_shards"


# --------------------------------------------------------------------------
# 4. Failure and staleness: remove the directory, omit the metadata, in lockstep.
# --------------------------------------------------------------------------

def test_failed_emit_removes_directory_and_omits_metadata(tmp_path, monkeypatch):
    """Half a lead is worse than the honest desktop-only note. A shard that
    cannot be written must leave NOTHING for the client to find, and no metadata
    telling it to look."""
    monkeypatch.setattr("foreclosure_scraper.web_artifact._shard_record",
                        lambda rec, det: (_ for _ in ()).throw(RuntimeError("boom")))
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)

    assert not (tmp_path / DETAIL_SHARD_DIR).exists()
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert "detail_shards" not in meta.get("board", {})
    # ...and the board itself survived the derivative's failure.
    assert len(json.loads((tmp_path / "listings.json").read_text())) == 1
    assert meta["board"]["count"] == 1


def test_stale_shards_from_a_larger_board_are_purged(tmp_path, monkeypatch):
    """A board that shrinks leaves high-numbered shards holding indices that no
    longer exist. Left on disk they would be served against the new board."""
    monkeypatch.setattr("foreclosure_scraper.web_artifact.DETAIL_SHARD_SIZE", 2)
    write_artifact([_lead(i) for i in range(9)], {"notes": "t"}, docs_dir=tmp_path)
    assert len(list((tmp_path / DETAIL_SHARD_DIR).glob("*.json.gz"))) == 5

    write_artifact([_lead(i) for i in range(3)], {"notes": "t"}, docs_dir=tmp_path)
    names = sorted(p.name for p in (tmp_path / DETAIL_SHARD_DIR).iterdir())
    assert names == ["00000.json.gz", "00001.json.gz"]
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert meta["board"]["detail_shards"]["count"] == 2
    assert meta["board"]["detail_shards"]["records"] == 3


def test_emergency_stop_removes_a_previously_written_directory(tmp_path, monkeypatch):
    """FORECLOSURE_DETAIL_SHARDS=0 deletes rather than freezes. A frozen shard
    set beside a moving board is mis-joined data on a phone."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    assert (tmp_path / DETAIL_SHARD_DIR).exists()

    monkeypatch.setenv("FORECLOSURE_DETAIL_SHARDS", "0")
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    assert not (tmp_path / DETAIL_SHARD_DIR).exists()
    meta = json.loads((tmp_path / "run_meta.json").read_text())
    assert "detail_shards" not in meta.get("board", {})


def test_shards_are_removed_when_the_slim_payload_is_not_written(tmp_path, monkeypatch):
    """Shards and slim are ONE mobile payload, advertised in one metadata block.

    Shards are only ever fetched by the LEAN client and their metadata lives
    inside the board block the slim emit owns, so a shard set written while slim
    is absent is 28 MB that nothing advertises — and, next run, 28 MB describing
    a board that has moved. When slim goes, they go with it, and mobile degrades
    to exactly what it does today.
    """
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    assert (tmp_path / DETAIL_SHARD_DIR).exists()

    monkeypatch.setenv("FORECLOSURE_SLIM", "0")
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    assert not (tmp_path / DETAIL_SHARD_DIR).exists()
    assert "board" not in json.loads((tmp_path / "run_meta.json").read_text())


def test_load_board_never_reads_the_shards(tmp_path):
    """Shards are a derivative. If load_board ever hydrated from them, a
    write_artifact round-trip would start folding them back into raw and the
    split would quietly undo itself."""
    import inspect
    from foreclosure_scraper import web_artifact
    src = inspect.getsource(web_artifact.load_board)
    assert DETAIL_SHARD_DIR not in src
    assert "shard" not in src.lower()


# --------------------------------------------------------------------------
# 5. GitHub Pages: the prefix trap that has already 404'd this site's data twice.
# --------------------------------------------------------------------------

def _pages_model():
    """The repo's OWN model of Jekyll's decision (scripts/check_pages_publish.py).

    Imported rather than re-implemented on purpose: a second copy of this logic
    in the test suite would be one more thing to drift, and the whole point is
    to assert against whatever check_pages_publish.py believes.
    """
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    try:
        import check_pages_publish as cpp                     # type: ignore
    finally:
        sys.path.pop(0)
    exclude, include = cpp.parse_config((root / "docs" / "_config.yml").read_text())
    return cpp, exclude, include


def test_shards_survive_the_pages_deploy():
    """docs/_config.yml `exclude` is a PREFIX match. Excluding `listings.json`
    already silently dropped `listings.json.gz` once, and `listings_slim.json`
    was the third instance of the same pair. A shard directory is the next thing
    someone will "tidy up" into that list — and unlike the .gz twins above it
    cannot be rescued by one `include` line, because there are 39 distinct
    filenames and the phone 404s on whichever ones you forgot."""
    cpp, exclude, include = _pages_model()
    for name in (f"{DETAIL_SHARD_DIR}/00000.json.gz", f"{DETAIL_SHARD_DIR}/00038.json.gz"):
        published, reason = cpp.decide(name, exclude, include)
        assert published, (
            f"{name} would be DROPPED from the Pages deploy ({reason}) — every "
            f"phone that opens a lead would 404. exclude={exclude}"
        )


@pytest.mark.parametrize("bad", ["_detail_shards", ".detail_shards", "#shards"])
def test_the_directory_name_avoids_jekylls_special_rule(bad):
    """Why the directory is not named `_shards`. Jekyll treats any path segment
    with a leading `_`, `.` or `#` as special, and this repo has already been
    bitten once by a name-shaped Pages rule. The chosen name must not trip it."""
    cpp, _, _ = _pages_model()
    assert cpp.is_special(f"{bad}/00000.json.gz")
    assert not cpp.is_special(f"{DETAIL_SHARD_DIR}/00000.json.gz")

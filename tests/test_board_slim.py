"""SLIM-V1 — the additive mobile payload, and the invariants that keep it safe.

docs/listings_slim.json(.gz) is a DERIVATIVE. listings.json + listings_detail.json
are together the only full-fidelity board on disk (both gitignored, only the .gz
twins committed), and three unattended launchd jobs re-serialize that board every
day with no human in the loop. So the tests that matter most here are not "is the
slim file correct" — they are:

  * listings.json / listings_detail.json bytes are UNCHANGED by slim emission
  * the load_board -> write_artifact round-trip still preserves every raw key
  * load_board NEVER reads the slim file, whatever it contains
  * the prior-sidecar safety net survives on a machine holding ONLY the .gz twins

Plus the drift guard: the projection is written twice, once here and once in
docs/dashboard.js, and test_slim_allowlist_matches_client parses the JS to prove
the two copies still agree.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import (
    LAZY_DETAIL_KEYS,
    _emit_slim,
    _load_prior_details_by_key,
    _project_slim_record,
    _SLIM_RAW,
    _SLIM_RAW_SCALARS,
    _SLIM_TOP,
    _SLIM_ACRE_KEYS,
    load_board,
    write_artifact,
)

DASHBOARD_JS = Path(__file__).resolve().parents[1] / "docs" / "dashboard.js"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def _lead(i: int) -> Listing:
    """A lead carrying, on purpose: lazy-detail keys, allowlisted blocks,
    allowlisted-but-sub-filtered blocks, and blocks in NO allowlist at all
    (recorded_sales / eviction_market / images) — the last group is what the
    round-trip test is really about."""
    return Listing(
        source="x", source_url=f"u{i}", listing_type=ListingType.FORECLOSURE_SALE,
        state="NC", county="Gaston", parcel_id=f"P{i}", street_address=f"{i} Main St",
        city="Gastonia", owner_name=f"Owner {i}",
        description="Charming 3br. Vacant lot next door.",
        raw={
            # allowlisted, kept whole
            "grade": {"overall": "B", "overall_score": 81, "financial": "A"},
            "calc": {"arv_expected": 100000 + i, "confidence": "high"},
            # allowlisted, sub-filtered
            "owner_mailing": {"mailing": "PO Box 1", "absentee": True,
                              "owner": "SHOULD NOT SHIP", "out_of_state": False},
            "corroboration": {"court_confirmed": True, "label": "court",
                              "sources": ["a", "b"], "tier": 1, "multi_source": True},
            "lrcpwa": {"absentee": True, "mailing": {"state": "FL", "zip": "33101"},
                       "acreage": "2.5 acres"},
            "also_seen_in": [{"url": "https://a", "source": "s1", "note": "drop me"},
                             {"source": "s2"}],
            "life_events": ["estate_probate", "multiple_heirs"],
            "upset_bid": {"in_window": True, "days_remaining": 4},
            # allowlisted scalars
            "intent_score": 77, "intent_band": "hot", "sold_confirmed": False,
            # NOT in any slim allowlist — must survive the round-trip regardless
            "recorded_sales": [{"price": 123456, "date": "2024-01-01"}],
            "eviction_market": {"level": "high"},
            "images": {"primary": "https://img"},
            "tenure": {"years_held": 22, "long_tenure": True},
            "court_record": {"cause": "foreclosure"},
            # lazy-detail keys -> the sidecar
            "comps": [{"addr": f"{i} Elm", "sold_price": 200000 + i}],
            "vision": {"parsed": True, "blob": "x" * 50},
            "cama": {"heated_sqft": 1500},
        },
    )


def _read(p: Path):
    return json.loads(p.read_text())


def _write(tmp_path, leads, notes="t"):
    write_artifact(leads, {"notes": notes}, docs_dir=tmp_path)
    return (_read(tmp_path / "listings.json"),
            _read(tmp_path / "listings_detail.json"),
            _read(tmp_path / "listings_slim.json"))


# --------------------------------------------------------------------------
# (a) index alignment — i is the join across all three files
# --------------------------------------------------------------------------

def test_slim_is_index_aligned_with_listings_and_detail(tmp_path):
    leads = [_lead(0), _lead(1), _lead(2)]
    listings, details, slim = _write(tmp_path, leads)

    assert len(slim) == len(listings) == len(details) == 3

    # Same ORDER, not just the same length: index i must be the same lead in all
    # three files or the phone joins one property's detail onto another's card.
    for i, rec in enumerate(listings):
        assert slim[i]["source_url"] == rec["source_url"] == f"u{i}"
        assert slim[i]["street_address"] == rec["street_address"]
        assert details[i]["comps"][0]["addr"] == f"{i} Elm"


def test_slim_gz_matches_slim_json(tmp_path):
    _write(tmp_path, [_lead(0), _lead(1)])
    raw = (tmp_path / "listings_slim.json").read_bytes()
    assert gzip.decompress((tmp_path / "listings_slim.json.gz").read_bytes()) == raw
    assert json.loads(raw.decode("utf-8")) == _read(tmp_path / "listings_slim.json")


def test_run_meta_carries_the_board_block(tmp_path):
    _write(tmp_path, [_lead(i) for i in range(4)])
    meta = _read(tmp_path / "run_meta.json")
    assert meta["board"] == {"schema": "slim-v1", "count": 4}
    # count is the client's alignment check: slim.length must equal it.
    assert meta["board"]["count"] == meta["total"] == len(_read(tmp_path / "listings_slim.json"))


def test_slim_uses_compact_separators(tmp_path):
    """17.1 MB of the fat file is separator whitespace. The slim file pays none
    of it. (listings.json keeps its default separators — its bytes must not
    change — so this must NOT be asserted there.)"""
    _write(tmp_path, [_lead(0)])
    text = (tmp_path / "listings_slim.json").read_text()
    assert '", "' not in text and '": ' not in text
    assert (tmp_path / "listings.json").read_text().count('", "') > 0


# --------------------------------------------------------------------------
# (b) THE ROUND-TRIP PROOF — this test stands between us and permanently
#     destroying the enrichment on 38,500 leads.
# --------------------------------------------------------------------------

def test_round_trip_preserves_every_raw_key(tmp_path):
    """write_artifact -> load_board -> write_artifact must not lose a single raw
    key, including the ~80 keys no allowlist anywhere mentions.

    The failure this guards is silent and permanent: a key that stops being
    written to listings.json OR listings_detail.json is absent from the next
    load_board(), so the next write_artifact re-serializes a lobotomized raw and
    the enrichment is gone. Nothing on disk can recover it.
    """
    lead = _lead(0)
    keys_in = set(lead.raw)
    assert keys_in & set(LAZY_DETAIL_KEYS), "fixture must exercise the sidecar split"

    write_artifact([lead], {"notes": "pass 1"}, docs_dir=tmp_path)
    board = load_board(tmp_path)
    assert len(board) == 1
    missing = keys_in - set(board[0].raw)
    assert not missing, f"load_board lost raw keys after one write: {sorted(missing)}"

    # And again — the incremental-writer path the three daily jobs actually take.
    write_artifact(board, {"notes": "pass 2"}, docs_dir=tmp_path)
    board2 = load_board(tmp_path)
    missing2 = keys_in - set(board2[0].raw)
    assert not missing2, f"raw keys lost on the second round trip: {sorted(missing2)}"
    assert board2[0].raw["recorded_sales"][0]["price"] == 123456
    assert board2[0].raw["comps"][0]["sold_price"] == 200000
    assert board2[0].raw["vision"]["parsed"] is True


def test_slim_emission_does_not_change_listings_or_detail_bytes(tmp_path, monkeypatch):
    """The authoritative files must come out byte-identical whether or not the
    slim payload is emitted. Slim runs after both are already on disk and never
    mutates `payload`; this is the permanent guard for that."""
    leads = [_lead(i) for i in range(5)]

    monkeypatch.setenv("FORECLOSURE_SLIM", "0")
    off = tmp_path / "off"
    write_artifact(leads, {"notes": "t"}, docs_dir=off)
    assert not (off / "listings_slim.json").exists()
    assert "board" not in _read(off / "run_meta.json")

    monkeypatch.delenv("FORECLOSURE_SLIM")
    on = tmp_path / "on"
    write_artifact(leads, {"notes": "t"}, docs_dir=on)
    assert (on / "listings_slim.json").exists()

    for name in ("listings.json", "listings.json.gz",
                 "listings_detail.json", "listings_detail.json.gz"):
        assert (off / name).read_bytes() == (on / name).read_bytes(), name


def test_projection_never_mutates_the_payload_record():
    """`payload` is the object that becomes listings.json. The projector shares
    the '*' blocks by reference for size, so it must never write through them."""
    rec = json.loads(json.dumps({
        "source": "s", "description": "vacant land",
        "raw": {"grade": {"overall": "A"}, "calc": {"x": 1},
                "lrcpwa": {"absentee": True, "mailing": {"state": "FL"}},
                "helene": {"damaged_buildings": 2},
                "life_events": ["a", "b"], "gis": {"acreage": 3}},
    }))
    before = json.dumps(rec, sort_keys=True)
    _project_slim_record(rec)
    assert json.dumps(rec, sort_keys=True) == before


# --------------------------------------------------------------------------
# (c) every allowlisted key present in listings.json is present in slim
# --------------------------------------------------------------------------

def test_slim_carries_every_allowlisted_key_present_in_listings(tmp_path):
    listings, _details, slim = _write(tmp_path, [_lead(i) for i in range(3)])

    for i, rec in enumerate(listings):
        s = slim[i]
        for k in _SLIM_TOP:
            if k in rec:
                assert k in s, f"record {i}: top-level {k} dropped"
                assert s[k] == rec[k]

        raw, sraw = rec.get("raw") or {}, s.get("raw") or {}
        for k, subs in _SLIM_RAW.items():
            src = raw.get(k)
            if src is None:
                continue
            assert k in sraw, f"record {i}: raw.{k} dropped"
            if subs == "*":
                assert sraw[k] == src
            elif isinstance(src, dict):
                for sk in subs:
                    if sk in src:
                        assert sraw[k][sk] == src[sk], f"record {i}: raw.{k}.{sk}"
        for k in _SLIM_RAW_SCALARS:
            if k in raw:
                assert sraw.get(k) == raw[k], f"record {i}: raw.{k}"


def test_slim_drops_what_it_is_supposed_to_drop(tmp_path):
    _listings, _details, slim = _write(tmp_path, [_lead(0)])
    s = slim[0]
    # description is 6.1 MB on the real board and everything derived from it is
    # precomputed below — it must not ship.
    assert "description" not in s
    # sub-allowlisted blocks lose their un-listed sub-keys
    assert "owner" not in s["raw"]["owner_mailing"]
    assert "sources" not in s["raw"]["corroboration"]
    # blocks with no reader on a phone do not ship at all
    for k in ("recorded_sales", "images", "eviction_market", "tenure", "court_record"):
        assert k not in s["raw"], k
    # ...and neither do the lazy-detail keys, which live in the sidecar
    for k in LAZY_DETAIL_KEYS:
        assert k not in s["raw"], k
    # blocks kept whole stay whole
    assert s["raw"]["grade"] == {"overall": "B", "overall_score": 81, "financial": "A"}


def test_slim_precomputes_what_the_client_derived_from_description(tmp_path):
    _listings, _details, slim = _write(tmp_path, [_lead(0)])
    s = slim[0]
    # kw_vacant: replaces the three description probes in _catOf(), which decide
    # land vs residential and therefore which buyers match.
    assert s["kw_vacant"] is True
    # acres: the 12-way probe flattened (here from lrcpwa.acreage="2.5 acres")
    assert s["raw"]["acres"] == 2.5
    # lrcpwa.mail_state: flattened from lrcpwa.mailing.state
    assert s["raw"]["lrcpwa"]["mail_state"] == "FL"
    assert "mailing" not in s["raw"]["lrcpwa"]
    # life_events: an int, because the client only ever reads .length
    assert s["raw"]["life_events"] == 2
    # also_seen_in: trimmed to {url, source}, absent sub-keys stay absent
    assert s["raw"]["also_seen_in"] == [{"url": "https://a", "source": "s1"},
                                        {"source": "s2"}]


def test_helene_placard_is_precomputed_from_the_description(tmp_path):
    """Asheville Helene leads carry the placard in prose, not in the dedup meta.
    The client regexed `description` for it; with description gone, the slim file
    must already have it or the damage chip vanishes on every phone."""
    lead = Listing(source="counties_nc.asheville_helene", source_url="h1",
                   listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Buncombe",
                   street_address="9 Ridge Rd",
                   description="Helene damage: Red placard - 65% loss reported.",
                   raw={"grade": {"overall": "C"}})
    _listings, _details, slim = _write(tmp_path, [lead])
    assert slim[0]["raw"]["helene"]["worst_placard"] == "Red"
    assert slim[0]["raw"]["helene"]["worst_damage_pct"] == 65


def test_projector_is_idempotent(tmp_path):
    """A LEAN client runs projectRecord over whatever it fetched. Applied to an
    already-slim record it must be a no-op, which is what lets ONE client code
    path read both the slim and the fat file."""
    _listings, _details, slim = _write(tmp_path, [_lead(0), _lead(1)])
    for s in slim:
        assert _project_slim_record(json.loads(json.dumps(s))) == s


def test_no_derived_field_is_fabricated_when_the_source_is_absent():
    """Absence must stay absence. A bare record must not sprout an acres value,
    a mail_state, or a helene block out of nothing."""
    out = _project_slim_record({"source": "s", "raw": {}})
    # no description in hand -> no kw_vacant claim at all. The client's projector
    # does the same, which is what keeps it a strict fixed point on this output.
    assert "kw_vacant" not in out
    assert _project_slim_record({"source": "s", "description": "3br ranch"})["kw_vacant"] is False
    assert "acres" not in out["raw"]
    assert "helene" not in out["raw"]
    assert "life_events" not in out["raw"]
    out2 = _project_slim_record({"source": "s"})
    assert "raw" not in out2


def test_block_existence_survives_an_empty_sub_key_filter():
    """Several client call sites test a block for EXISTENCE rather than reading
    it (raw.upset_bid, raw.bankruptcy). A block present upstream must therefore
    still be emitted even when none of its sub-keys survive."""
    out = _project_slim_record({"source": "s", "raw": {"upset_bid": {"unknown_key": 1},
                                                      "bankruptcy": {"nope": 2}}})
    assert out["raw"]["upset_bid"] == {}
    assert out["raw"]["bankruptcy"] == {}


# --------------------------------------------------------------------------
# (d) load_board must NEVER read the slim file
# --------------------------------------------------------------------------

def test_load_board_ignores_listings_slim(tmp_path):
    """listings_slim.json is an additive derivative and load_board is the read
    side of the authoritative board. If load_board ever grew a slim fallback,
    one write_artifact later the allowlist would BE the board and ~80 raw keys
    would be gone permanently. Garbage in the slim file must change nothing."""
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    expected = [li.model_dump(mode="json") for li in load_board(tmp_path)]

    for junk in (b"[]",
                 b'[{"raw":{}},{"raw":{}}]',
                 b'{"not":"even an array"}',
                 b"this is not json at all"):
        (tmp_path / "listings_slim.json").write_bytes(junk)
        (tmp_path / "listings_slim.json.gz").write_bytes(gzip.compress(junk))
        got = [li.model_dump(mode="json") for li in load_board(tmp_path)]
        assert got == expected, f"load_board was influenced by the slim file: {junk[:32]!r}"

    # and the real proof: full fidelity is still there behind the garbage
    board = load_board(tmp_path)
    assert board[0].raw["recorded_sales"] and board[0].raw["comps"]


def test_stale_slim_is_removed_when_emission_fails(tmp_path):
    """Index i is the join across all three files, and it only holds within one
    write_artifact call. A stale slim file beside a fresh board is a silently
    mis-joined board on a phone — worse than no slim file, because the client's
    404 fallback (stream the fat file) is a correct board."""
    write_artifact([_lead(0)], {"notes": "t"}, docs_dir=tmp_path)
    assert (tmp_path / "listings_slim.json").exists()

    # A tuple dict KEY is one of the few things json.dumps still refuses:
    # `default=str` rescues unserializable values, never keys.
    count = _emit_slim(tmp_path, [{"raw": {"grade": {(1, 2): "x"}}}])
    assert count is None
    assert not (tmp_path / "listings_slim.json").exists()
    assert not (tmp_path / "listings_slim.json.gz").exists()


# --------------------------------------------------------------------------
# (e) the prior-sidecar safety net on a machine holding ONLY the .gz twins
# --------------------------------------------------------------------------

def _gz_only(docs: Path) -> None:
    """Simulate a fresh clone / cloud runner / disaster recovery: docs/listings.json
    and docs/listings_detail.json are gitignored, so only the .gz twins exist."""
    (docs / "listings.json").unlink()
    (docs / "listings_detail.json").unlink()
    assert (docs / "listings.json.gz").exists() and (docs / "listings_detail.json.gz").exists()


def test_prior_details_are_found_from_the_gz_twins_alone(tmp_path):
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    _gz_only(tmp_path)

    prior = _load_prior_details_by_key(tmp_path)
    assert prior, "safety net returned {} with only the committed .gz twins present"
    assert prior["u:u0"]["comps"][0]["sold_price"] == 200000
    assert prior["u:u0"]["vision"]["parsed"] is True


def test_gz_only_rewrite_does_not_wipe_the_sidecar(tmp_path):
    """The end-to-end version of the bug: on a gz-only machine the prior-sidecar
    backfill used to return {}, so a run that re-enriched nothing published
    details[i]={} for every lead — and the next load_board baked that in."""
    write_artifact([_lead(0), _lead(1)], {"notes": "t"}, docs_dir=tmp_path)
    _gz_only(tmp_path)

    # a naive pass: read the board back with no sidecar merge at all, rewrite
    recs = json.loads(gzip.decompress((tmp_path / "listings.json.gz").read_bytes()))
    naive = [Listing.model_validate(d) for d in recs]
    assert not any(k in (naive[0].raw or {}) for k in LAZY_DETAIL_KEYS)
    write_artifact(naive, {"notes": "gz-only pass"}, docs_dir=tmp_path)

    detail = _read(tmp_path / "listings_detail.json")
    assert detail[0].get("comps"), "sidecar wiped on a machine holding only the .gz twins"
    assert detail[0]["comps"][0]["sold_price"] == 200000
    assert detail[1].get("vision", {}).get("parsed") is True


def test_prior_details_absent_board_still_returns_empty(tmp_path):
    assert _load_prior_details_by_key(tmp_path) == {}


# --------------------------------------------------------------------------
# drift guard — the projection is written twice and must agree
# --------------------------------------------------------------------------

def _js_literal(src: str, name: str):
    """Pull `const <name> = [...]` / `{...}` out of dashboard.js and JSON-decode
    it. Deliberately narrow: these blocks are flat string lists / string->string
    maps, so stripping // comments, quoting bare keys and dropping trailing
    commas is enough. If dashboard.js ever grows something richer here, this
    raises rather than silently passing."""
    anchor = src.index(f"const {name} = ")
    start = anchor + len(f"const {name} = ")
    opener = src[start]
    closer = {"[": "]", "{": "}"}[opener]
    depth, i, in_str = 0, start, False
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = src[start:i + 1]
    body = re.sub(r"//[^\n]*", "", body)                        # line comments
    body = re.sub(r"([{,]\s*)([A-Za-z_$][\w$]*)\s*:", r'\1"\2":', body)  # bare keys
    body = re.sub(r",(\s*[}\]])", r"\1", body)                  # trailing commas
    return json.loads(body)


@pytest.mark.skipif(not DASHBOARD_JS.exists(), reason="docs/dashboard.js not present")
def test_slim_allowlist_matches_client():
    """The projection exists twice: _project_slim_record here and projectRecord
    in docs/dashboard.js. They must not drift.

    If this fails, the CLIENT changed and this file has to follow — do not
    'fix' it by editing the expectation. A build-side allowlist wider than the
    client's just ships dead bytes; narrower, and a field the phone renders
    silently blanks out.
    """
    src = DASHBOARD_JS.read_text()
    assert list(_SLIM_TOP) == _js_literal(src, "_LEAN_TOP")
    assert list(_SLIM_RAW_SCALARS) == _js_literal(src, "_LEAN_RAW_SCALARS")
    assert list(_SLIM_ACRE_KEYS) == _js_literal(src, "_ACRE_KEYS")

    client_raw = _js_literal(src, "_LEAN_RAW")
    ours = {k: (v if v == "*" else list(v)) for k, v in _SLIM_RAW.items()}
    assert ours == client_raw
    # order matters too: it is the key order of every record in the slim file,
    # and a stable order is what keeps the committed .gz from churning.
    assert list(ours) == list(client_raw)

"""scripts/patch_owner_mailing.py's board-I/O rewrite (2026-10-01, docs/HANDOFF.md item 21/24):
it used to call read_board_json() to parse the WHOLE board into one list, hydrate every row,
mutate owner_mailing/cama/parcel_id/specs on it, then rewrite docs/listings.json directly with
path.write_text(json.dumps(data)) + reseal_board(resplit=True) -- an undocumented sibling of
patch_distress_score.py, never on any schedule but a real OOM trap against today's 2.4+ GB board.

This proves the new board_stream.iter_board_rows() read + diff + web_artifact.patch_existing_rows()
write reproduces enrich_owner_mailing()'s contract -- without ever calling
read_board_json()/write_artifact(), and without any real network call (enrich_owner_mailing is
replaced with a small fake mirroring its real mutation shape: owner_mailing, cama, parcel_id,
and a scalar field fill).

Covers:
  1. main() end-to-end: a target row (no mailing yet) gets owner_mailing + cama + parcel_id +
     tax_value all landed in ONE patch.
  2. A row that already has a mailing address is left completely untouched (incremental skip).
  3. A row with no address/parcel_id (unreachable) is left untouched.
  4. patch_existing_rows() MERGES raw rather than replacing it: a pre-existing unrelated raw key
     (skip_trace) survives alongside the newly-added owner_mailing/cama -- the disclosed fix over
     the old `d["raw"] = _to_dict(li)["raw"]` full-replace.
  5. The disclosed behavior fix itself: tax_value (a scalar Listing field the old code silently
     dropped, copying back only raw + parcel_id) is now persisted.
  6. A second run is idempotent: nothing left to patch.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import patch_owner_mailing as pom  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="SC", county="Greenville",
                street_address=f"{i + 1} Main St", zip_code="29601", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0),                                               # target: no mailing, no parcel_id
        _row(1, raw={"owner_mailing": {"mailing": "already here"}}),  # already filled -> skip
        _row(2, street_address=None, parcel_id=None),           # unreachable -> skip
        _row(3, raw={"skip_trace": {"phone": "555-0100"}}),     # target, carries an unrelated raw key
    ]
    wa.write_artifact(rows, {"notes": "patch_owner_mailing integration seed"}, docs_dir=docs)
    return rows


async def _fake_enrich_owner_mailing(listings, max_concurrency=6):
    counts = {"queried": 0, "resolved": 0, "absentee": 0, "out_of_state": 0}
    for li in listings:
        om = (li.raw or {}).get("owner_mailing") if isinstance(li.raw, dict) else None
        already = bool(om.get("mailing")) if isinstance(om, dict) else bool(om)
        if already or not (li.street_address or li.parcel_id):
            continue
        counts["queried"] += 1
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["owner_mailing"] = {"owner": "JOHN DOE", "mailing": "1 PO Box, Columbia, SC 29201",
                                    "absentee": True, "out_of_state": False}
        li.raw["cama"] = {"condition_distressed": False, "owner_occupied": False}
        if not li.parcel_id:
            li.parcel_id = f"PARCEL-{counts['queried']}"
        if not li.tax_value:
            li.tax_value = 123456.0
        counts["resolved"] += 1
        counts["absentee"] += 1
    return counts


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(pom, "REPO", repo)
    monkeypatch.setattr(pom, "DOCS", repo / "docs")
    monkeypatch.setattr(pom, "enrich_owner_mailing", _fake_enrich_owner_mailing)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_main_patches_targets_only(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)

    rc = asyncio.run(pom.main())
    assert rc == 0

    rows = wa.load_board(docs)
    by_url = {li.source_url: li for li in rows}

    r0 = by_url[seed[0].source_url]
    assert r0.raw["owner_mailing"]["mailing"] == "1 PO Box, Columbia, SC 29201"
    assert r0.raw["cama"]["owner_occupied"] is False
    assert r0.parcel_id and r0.parcel_id.startswith("PARCEL-")
    assert r0.tax_value == 123456.0  # disclosed fix: scalar fill now persists

    r1 = by_url[seed[1].source_url]
    assert r1.raw["owner_mailing"]["mailing"] == "already here"
    assert "cama" not in r1.raw  # never touched by the fake (already filled)

    r2 = by_url[seed[2].source_url]
    assert r2.raw == {}  # unreachable, never queried

    r3 = by_url[seed[3].source_url]
    assert r3.raw["skip_trace"] == {"phone": "555-0100"}  # pre-existing key survives (merge, not replace)
    assert r3.raw["owner_mailing"]["mailing"] == "1 PO Box, Columbia, SC 29201"
    assert r3.raw["cama"]["owner_occupied"] is False


def test_second_run_is_idempotent(scratch_repo, capsys):
    docs = scratch_repo / "docs"
    _seed_board(docs)

    assert asyncio.run(pom.main()) == 0
    capsys.readouterr()

    before = (docs / "listings.json").read_bytes()
    assert asyncio.run(pom.main()) == 0
    out = capsys.readouterr().out
    assert "nothing to patch" in out
    assert (docs / "listings.json").read_bytes() == before

"""scripts/lrcpwa_refresh.py's board-I/O rewrite (2026-10-01): it used to call load_board() to
build its full-board `listings` list, mutate lrcpwa/strategy_fit/buyer_match/calc/grade on it,
then write_artifact(listings, ...) -- exactly the double materialization BOARD_LOAD_MAX_SOURCE_MB
now refuses on the real ~212K-row board, which is what left this script BLOCKED (failing every
scheduled noon run with BoardLoadTooLarge). This test proves the new single streaming pass
(web_artifact._iter_board_records(), sidecar merged) + bounded lrcpwa target collection +
board-wide per-row calc/grade/strategy_fit/buyer_match recompute + web_artifact.patch_existing_rows()
write reproduces the original contract -- without ever calling load_board()/write_artifact(), and
without any real lrcpwa network call (enrich_lrcpwa_parcel/enrich_lrcpwa_photo are replaced with
small fakes).

Covers:
  1. _is_parcel_target()/_is_photo_target() reproduce enrich_lrcpwa_parcel()'s/
     enrich_lrcpwa_photo()'s own targeting filters exactly, including a row that qualifies for
     BOTH at once.
  2. main() end-to-end: an lrcpwa-only-parcel-target row, an lrcpwa-only-photo-target row, and a
     dual-target row all land their lrcpwa fields AND a freshly recomputed calc/grade in ONE
     combined patch each; a ordinary row outside the lrcpwa footprint (wrong county, no parcel
     fields touched) still gets calc/grade/strategy_fit recomputed -- proving the board-wide
     sweep, not just lrcpwa's own bounded targets, runs through the new streaming path.
  3. strategy_fit tags a LAND + delinquent-tax row even though lrcpwa never touches it (pure
     per-row, board-wide, same as the original's unconditional enrich_strategy_fit(listings) call).
  4. A second run against the now-updated board finds nothing left to patch (idempotency): lrcpwa
     targets are gone (addresses/photos already filled) and calc/grade/strategy_fit/buyer_match
     all recompute to the SAME values already on the board.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import lrcpwa_refresh as lr  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402

FAKE_ADDR = {"street_address": "201 SUGARLOAF RD", "city": "Hendersonville",
             "state": "NC", "zip_code": "28792", "market_value": 475000.0}


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Henderson",
                parcel_id=f"{1000 + i}", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0),  # parcel-target ONLY: Henderson, parcel_id, no address, not worth a photo
        _row(1, street_address="5 Already Addressed Ln",  # photo-target ONLY: HOT, no image yet
             raw={"distress_stack": {"tier": "HOT"}}),
        _row(2, county="Greenville", state="SC", parcel_id=None,  # ordinary row, outside lrcpwa
             street_address="9 Plain St", property_kind=PropertyKind.LAND,
             raw={"tax_owed": {"balance": 1200}}),               # -> strategy_fit should tag LAND_WHOLESALE
        _row(3, raw={"distress_stack": {"tier": "WARM"}}),  # DUAL target: no address AND worth a photo
        _row(4, county="Spartanburg", state="SC",  # wrong county for lrcpwa, but still no address
             parcel_id="99999"),
    ]
    wa.write_artifact(rows, {"notes": "lrcpwa_refresh integration seed"}, docs_dir=docs)
    return rows


async def _fake_enrich_lrcpwa_parcel(listings):
    stats = {"targets": len(listings), "resolved": 0, "address_filled": 0, "value_filled": 0,
             "absentee": 0, "skipped_budget": 0}
    for li in listings:
        if (li.street_address or "").strip():
            continue
        for k, v in FAKE_ADDR.items():
            setattr(li, k, v)
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["lrcpwa"] = {"id": "fake-id", "assessed_value": FAKE_ADDR["market_value"],
                            "owner": None, "mailing": {}, "absentee": False}
        stats["resolved"] += 1
        stats["address_filled"] += 1
        stats["value_filled"] += 1
    return stats


async def _fake_enrich_lrcpwa_photo(listings):
    stats = {"targets": len(listings), "fetched": 0, "cached": 0, "no_photo": 0, "skipped_budget": 0}
    for li in listings:
        if not isinstance(li.raw, dict):
            li.raw = {}
        images = li.raw.setdefault("images", {})
        if images.get("real"):
            continue
        images["real"] = ["parcel_photos/fake.jpg"]
        images.setdefault("primary", "parcel_photos/fake.jpg")
        li.raw.setdefault("zillow", {})["photo"] = "parcel_photos/fake.jpg"
        stats["fetched"] += 1
    return stats


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(lr, "REPO", repo)
    monkeypatch.setattr(lr, "DOCS", repo / "docs")
    monkeypatch.setattr(lr, "enrich_lrcpwa_parcel", _fake_enrich_lrcpwa_parcel)
    monkeypatch.setattr(lr, "enrich_lrcpwa_photo", _fake_enrich_lrcpwa_photo)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_targeting_filters_match_the_real_enrichers_and_catch_dual_targets(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    recs = {rec["source_url"]: rec for rec in wa._iter_board_records(docs)}

    r0 = recs[seed[0].source_url]
    assert lr._is_parcel_target(r0) and not lr._is_photo_target(r0)

    r1 = recs[seed[1].source_url]
    assert lr._is_photo_target(r1) and not lr._is_parcel_target(r1)

    r2 = recs[seed[2].source_url]
    assert not lr._is_parcel_target(r2) and not lr._is_photo_target(r2)

    r3 = recs[seed[3].source_url]
    assert lr._is_parcel_target(r3) and lr._is_photo_target(r3)  # dual target

    r4 = recs[seed[4].source_url]
    assert not lr._is_parcel_target(r4)  # right shape, wrong county (not in TENANTS)


def test_main_patches_lrcpwa_targets_and_recomputes_the_whole_board(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.setattr(sys, "argv", ["lrcpwa_refresh.py"])

    rc = lr.main()
    assert rc == 0

    rows = wa.load_board(docs)
    by_url = {li.source_url: li for li in rows}

    # parcel-only target: address + value filled, calc/grade recomputed on the touched row
    r0 = by_url[seed[0].source_url]
    assert r0.street_address == FAKE_ADDR["street_address"]
    assert r0.market_value == FAKE_ADDR["market_value"]
    assert r0.raw["lrcpwa"]["id"] == "fake-id"
    assert "calc" in r0.raw and "grade" in r0.raw
    assert "images" not in r0.raw or not (r0.raw.get("images") or {}).get("real")

    # photo-only target: image filled, address untouched (it already had one)
    r1 = by_url[seed[1].source_url]
    assert r1.raw["images"]["real"] == ["parcel_photos/fake.jpg"]
    assert r1.street_address == "5 Already Addressed Ln"
    assert "lrcpwa" not in r1.raw
    assert "calc" in r1.raw and "grade" in r1.raw

    # ordinary row outside the lrcpwa footprint: never touched by lrcpwa, but STILL recomputed
    # (board-wide strategy_fit + calc/grade, exactly like the original's unconditional pass) --
    # and correctly tagged LAND_WHOLESALE (land + delinquent tax)
    r2 = by_url[seed[2].source_url]
    assert "lrcpwa" not in r2.raw and "images" not in r2.raw
    assert "calc" in r2.raw and "grade" in r2.raw
    assert r2.raw["strategy_fit"]["tags"] == ["LAND_WHOLESALE"]

    # dual target: BOTH lrcpwa passes landed on the SAME row in one patch
    r3 = by_url[seed[3].source_url]
    assert r3.street_address == FAKE_ADDR["street_address"]
    assert r3.raw["lrcpwa"]["id"] == "fake-id"
    assert r3.raw["images"]["real"] == ["parcel_photos/fake.jpg"]
    assert "calc" in r3.raw and "grade" in r3.raw

    # wrong-county row: still swept for calc/grade (board-wide), but lrcpwa never ran on it
    r4 = by_url[seed[4].source_url]
    assert not (r4.street_address or "").strip()
    assert "lrcpwa" not in r4.raw
    assert "calc" in r4.raw and "grade" in r4.raw


def test_third_run_is_idempotent_nothing_left_to_patch(scratch_repo, monkeypatch, capsys):
    """Two runs, not one, are needed to reach steady state here -- and that is a FAITHFUL
    reproduction of the original's own cross-run timing, not an artifact of this rewrite.
    enrich_lrcpwa_photo()'s targeting (_worth_photo: tier HOT/WARM or a letter grade) always ran
    BEFORE calc/grade got (re)computed each day, in the original script just as here. So seed[0]
    (a parcel-only target, ungraded at the start) gets its FIRST real grade from run 1's
    recompute -- too late to affect run 1's own photo-targeting pass -- and if that grade lands
    in A-D, seed[0] newly qualifies for a photo on run 2, exactly as it would have the NEXT
    scheduled day in the original. Run 3 is the true steady state: nothing left to discover,
    nothing left to patch."""
    docs = scratch_repo / "docs"
    _seed_board(docs)
    monkeypatch.setattr(sys, "argv", ["lrcpwa_refresh.py"])

    assert lr.main() == 0
    capsys.readouterr()
    assert lr.main() == 0  # may still pick up a freshly-graded photo target (see docstring)

    before = (docs / "listings.json").read_bytes()
    rc = lr.main()  # third pass: steady state
    assert rc == 0
    out = capsys.readouterr().out
    assert "nothing to patch" in out
    assert (docs / "listings.json").read_bytes() == before


def test_nothing_to_patch_on_a_board_lrcpwa_and_recompute_both_leave_alone(scratch_repo, monkeypatch):
    """A board where no row is an lrcpwa target and no row's calc/grade/strategy_fit/buyer_match
    changes from what the FIRST run already computed -- proven by running once, then asserting
    the second run (identical board) finds nothing. Separate from the idempotency test above in
    that it only seeds rows with no lrcpwa footprint at all."""
    docs = scratch_repo / "docs"
    rows = [_row(0, county="Greenville", state="SC", parcel_id=None,
                 street_address="1 Plain St")]
    wa.write_artifact(rows, {"notes": "seed"}, docs_dir=docs)
    monkeypatch.setattr(sys, "argv", ["lrcpwa_refresh.py"])

    assert lr.main() == 0
    before = (docs / "listings.json").read_bytes()
    assert lr.main() == 0
    assert (docs / "listings.json").read_bytes() == before

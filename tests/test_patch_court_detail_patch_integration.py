"""scripts/patch_court_detail.py's board-I/O rewrite (2026-10-01, docs/HANDOFF.md item 21/24):
it used to call read_board_json() to parse the WHOLE board into one list, hydrate every row, run
both court enrichers over the full list, then rewrite docs/listings.json directly with
path.write_text(json.dumps(data)) + reseal_board(resplit=True) -- an undocumented sibling of
patch_distress_score.py, dormant since its wrapper's plist was disabled 2026-09-20 but a real OOM
trap one re-enable away from being live again.

This proves the new web_artifact._iter_board_records() (sidecar merged -- required because the
per-row calc/grade recompute reads raw['vision']/raw['cama']/raw['comps']) read + diff +
web_artifact.patch_existing_rows() write reproduces the original contract -- without ever calling
read_board_json()/write_artifact(), and without any real browser/network call (both court
enrichers are replaced with small fakes mirroring their real mutation shape).

Covers:
  1. main() end-to-end: an NC target gets nc_case_status + judgment_amount + sale_date AND a
     freshly computed calc/grade, all landed in ONE patch.
  2. An SC target picked up via the SC_COURT_INCREMENTAL "not yet court-enriched" branch gets
     court_sale_status plus calc/grade. (The OTHER SC targeting branch -- a placeholder "Lis
     Pendens " street_address -- is not exercised here: web_artifact._to_dict() nulls any
     street_address matching its own junk-address markers, "lis pendens" included, at publish
     time, so seeding one through the normal wa.write_artifact() path this test uses cannot
     survive to be read back; that is a pre-existing characteristic of the published board,
     unrelated to and unchanged by this migration.)
  3. A row with no case_number is never touched by either enricher and never recomputed (no
     court_sale_status/nc_case_status to trigger the calc/grade branch).
  4. A row that ALREADY carries a court status before this run still gets calc/grade recomputed
     (the original's own unconditional "if either status is set" branch, not just freshly-tagged
     rows) even though neither enricher re-touches its status field -- and a pre-existing
     unrelated raw key survives alongside it (merge, not replace).
  5. A second run is idempotent: nothing left to patch.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import patch_court_detail as pcd  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
                listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Mecklenburg",
                street_address=f"{i + 1} Main St", zip_code="28202", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0, case_number="26SP000111-320"),                        # NC target
        _row(1, state="SC", county="Richland", case_number="2026CP4000222",
             street_address="17 Elm St"),                             # SC target (SC_COURT_INCREMENTAL)
        _row(2, case_number=None),                                    # no case_number -> untouched
        _row(3, case_number="25SP000999-320",                         # already tagged before this run
             raw={"nc_case_status": "sold_confirmed", "skip_trace": {"phone": "555-0100"}}),
    ]
    wa.write_artifact(rows, {"notes": "patch_court_detail integration seed"}, docs_dir=docs)
    return rows


async def _fake_nc_auth(listings, max_cases=None):
    tagged = 0
    for li in listings:
        if li.state != "NC" or not (li.case_number or "").strip():
            continue
        if isinstance(li.raw, dict) and li.raw.get("nc_case_status"):
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["nc_case_status"] = "upset_bid_pending"
        li.judgment_amount = 50000.0
        li.sale_date = datetime(2026, 11, 1)
        tagged += 1
    return tagged


async def _fake_sc_detail(listings) -> None:
    for li in listings:
        if li.state != "SC" or not (li.case_number or "").strip():
            continue
        if isinstance(li.raw, dict) and li.raw.get("court_sale_status"):
            continue
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["court_sale_status"] = "sale_noticed"
        if (li.street_address or "").startswith("Lis Pendens "):
            li.street_address = "42 Resolved Ave"


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(pcd, "REPO", repo)
    monkeypatch.setattr(pcd, "DOCS", repo / "docs")
    monkeypatch.setattr(
        "foreclosure_scraper.enrichment_nc_case_status_tyler.enrich_with_nc_case_status_authenticated",
        _fake_nc_auth)
    monkeypatch.setattr(
        "foreclosure_scraper.enrichment_case_detail.enrich_case_detail_addresses",
        _fake_sc_detail)
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_main_patches_nc_and_sc_targets_with_recompute(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)

    rc = asyncio.run(pcd.main())
    assert rc == 0

    rows = wa.load_board(docs)
    by_url = {li.source_url: li for li in rows}

    r0 = by_url[seed[0].source_url]
    assert r0.raw["nc_case_status"] == "upset_bid_pending"
    assert r0.judgment_amount == 50000.0
    assert r0.sale_date == datetime(2026, 11, 1)
    assert "calc" in r0.raw and "grade" in r0.raw  # disclosed fix: sale_date now persists too

    r1 = by_url[seed[1].source_url]
    assert r1.raw["court_sale_status"] == "sale_noticed"
    assert r1.street_address == "17 Elm St"  # unchanged -- not a placeholder
    assert "calc" in r1.raw and "grade" in r1.raw

    r2 = by_url[seed[2].source_url]
    assert "nc_case_status" not in r2.raw and "court_sale_status" not in r2.raw
    assert "calc" not in r2.raw and "grade" not in r2.raw  # never tagged -> recompute branch never fires

    # already tagged before this run: neither fake re-touches its status (already set), but the
    # unconditional "if either status is set" branch still recomputes calc/grade -- AND the
    # pre-existing unrelated raw key survives (merge, not replace).
    r3 = by_url[seed[3].source_url]
    assert r3.raw["nc_case_status"] == "sold_confirmed"  # untouched by the fake
    assert r3.raw["skip_trace"] == {"phone": "555-0100"}
    assert "calc" in r3.raw and "grade" in r3.raw


def test_second_run_is_idempotent(scratch_repo, capsys):
    docs = scratch_repo / "docs"
    _seed_board(docs)

    assert asyncio.run(pcd.main()) == 0
    capsys.readouterr()

    before = (docs / "listings.json").read_bytes()
    assert asyncio.run(pcd.main()) == 0
    out = capsys.readouterr().out
    assert "nothing to patch" in out
    assert (docs / "listings.json").read_bytes() == before

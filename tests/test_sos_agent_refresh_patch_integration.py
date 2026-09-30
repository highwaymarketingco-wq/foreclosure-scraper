"""scripts/sos_agent_refresh.py's board-I/O rewrite (2026-09-30): it used to call
load_board() to build its full-board `listings` list and write_artifact(listings, ...) at the
end -- exactly the double materialization BOARD_LOAD_MAX_SOURCE_MB now refuses on the real
~217K-row board, which is what left this script BLOCKED (failing every scheduled 14:00 run).
This test proves the new two-pass streaming read (board_stream.iter_board_rows()) and the
board-write (web_artifact.patch_existing_rows(), only the resolved/propagated handful) mechanism
reproduces enrich_with_sos_agent()'s OWN cross-row contract -- propagation to co-owned leads
anywhere on the board, new-entity ranking, dedupe of already-resolved rows -- without ever
calling load_board()/write_artifact(), and without touching the network (enrichment_sos_agent's
own _batch_lookup is replaced with a small fake).

Covers:
  1. _collect_resolved_profiles() finds the one pre-existing resolved entity on the board.
  2. _collect_targets() propagates that profile (no network) to a co-owned row missing it, and
     separately ranks genuinely-new entities HOT/WARM first for the (faked) network lookup.
  3. main() end-to-end: both the propagated row and the newly-resolved row land on the board via
     patch_existing_rows(); an SC entity (out of scope) and a non-entity owner are left alone.
  4. Rows outside NC, or already carrying a sos_agent, are never touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sos_agent_refresh as sar  # noqa: E402

from foreclosure_scraper import web_artifact as wa  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _row(i: int, **kw) -> Listing:
    base = dict(source="src.seed", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               street_address=f"{i + 1} Main St", zip_code="28052", raw={})
    base.update(kw)
    return Listing(**base)


def _seed_board(docs: Path) -> list[Listing]:
    rows = [
        _row(0, owner_name="ACME HOLDINGS LLC",                      # already resolved
             raw={"sos_agent": {"sosid": "1", "best_contact_name": "Prior Officer"}}),
        _row(1, owner_name="ACME HOLDINGS LLC"),                      # co-owned -> should propagate
        _row(2, owner_name="BETA VENTURES LLC",                       # new entity, HOT -> network target
             raw={"distress_stack": {"tier": "HOT"}}),
        _row(3, owner_name="GAMMA PROPERTIES LLC"),                   # new entity, no tier -> lower priority
        _row(4, owner_name="Jane Q. Person"),                         # not a business -> skipped entirely
        _row(5, state="SC", owner_name="DELTA HOLDINGS LLC"),         # wrong state -> skipped entirely
        _row(6, owner_name="ACME HOLDINGS LLC",                       # co-owned, already has its own agent
             raw={"sos_agent": {"sosid": "9", "best_contact_name": "Different Agent"}}),
    ]
    wa.write_artifact(rows, {"notes": "sos_agent integration seed"}, docs_dir=docs)
    return rows


async def _fake_batch_lookup(names: list[str]) -> dict:
    """Mimics enrichment_sos_agent._batch_lookup()'s exact contract (name -> profile dict or
    None) without any network/Scrapling call: resolves BETA, leaves GAMMA a miss."""
    out = {}
    for n in names:
        if n == "BETA VENTURES LLC":
            out[n] = {"sosid": "42", "best_contact_name": "New Officer",
                      "best_contact_address": "1 New St, Charlotte, NC"}
        else:
            out[n] = None
    return out


@pytest.fixture
def scratch_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(sar, "REPO", repo)
    monkeypatch.setattr(sar, "DOCS", repo / "docs")
    monkeypatch.setattr(sar, "_batch_lookup", _fake_batch_lookup)
    monkeypatch.setenv("SOS_AGENT", "1")
    wa._LOAD_STAMPS.clear()
    wa._VERIFIED.clear()
    return repo


def test_collect_resolved_profiles_finds_the_one_pre_existing_entity(scratch_repo):
    docs = scratch_repo / "docs"
    _seed_board(docs)
    resolved, total, with_any = sar._collect_resolved_profiles(docs)
    assert total == 7
    assert with_any == 2  # seed[0] and seed[6] both carry a sos_agent dict
    assert set(resolved) == {"ACME HOLDINGS LLC"}
    # first-seen-with-sosid wins (seed[0], board order) -- not seed[6]'s different agent
    assert resolved["ACME HOLDINGS LLC"]["best_contact_name"] == "Prior Officer"


def test_collect_targets_propagates_and_ranks_new_entities(scratch_repo):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    resolved, _, _ = sar._collect_resolved_profiles(docs)
    name_to_keys, ranked, propagate_patches, propagated = sar._collect_targets(docs, resolved)

    # seed[1] (co-owned ACME, no agent yet) propagates for free -- seed[6] does NOT (it already
    # has its own sos_agent, so the "already resolved on this lead" branch skips it before ever
    # checking resolved_profiles).
    assert propagated == 1
    key1 = seed[1].dedupe_key()
    assert key1 in propagate_patches
    assert propagate_patches[key1]["raw"]["sos_agent"]["best_contact_name"] == "Prior Officer"

    # BETA (HOT) and GAMMA (no tier) are both new-entity targets, HOT ranked first
    names_in_rank_order = [n for _, n in sorted(ranked, key=lambda t: t[0])]
    assert names_in_rank_order[0] == "BETA VENTURES LLC"
    assert "GAMMA PROPERTIES LLC" in names_in_rank_order
    assert set(name_to_keys) == {"BETA VENTURES LLC", "GAMMA PROPERTIES LLC"}


def test_main_patches_propagated_and_newly_resolved_rows(scratch_repo, monkeypatch):
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.setattr(sys, "argv", ["sos_agent_refresh.py"])

    rc = sar.main()
    assert rc == 0

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li for li in rows}

    # propagated (no network): co-owned ACME row inherits seed[0]'s profile
    propagated_row = by_addr[seed[1].street_address]
    assert propagated_row.raw["sos_agent"]["best_contact_name"] == "Prior Officer"

    # newly resolved via the faked network batch
    beta_row = by_addr[seed[2].street_address]
    assert beta_row.raw["sos_agent"]["sosid"] == "42"
    assert beta_row.raw["sos_agent"]["best_contact_name"] == "New Officer"

    # GAMMA was queried (a miss in the fake) -> stays unresolved, untouched
    gamma_row = by_addr[seed[3].street_address]
    assert "sos_agent" not in gamma_row.raw

    # rows outside scope are completely untouched
    assert "sos_agent" not in by_addr[seed[4].street_address].raw       # non-entity owner
    assert by_addr[seed[5].street_address].raw == {}                    # wrong state (SC)
    assert by_addr[seed[6].street_address].raw["sos_agent"]["sosid"] == "9"  # its own agent, unchanged
    assert by_addr[seed[0].street_address].raw["sos_agent"]["sosid"] == "1"  # source-of-truth unchanged


def test_disabled_env_skips_network_but_still_propagates(scratch_repo, monkeypatch):
    """SOS_AGENT unset entirely (not just left at setdefault's "1") must still let the free,
    no-network propagation branch run -- only the actual _batch_lookup call is gated."""
    docs = scratch_repo / "docs"
    seed = _seed_board(docs)
    monkeypatch.delenv("SOS_AGENT", raising=False)
    monkeypatch.setattr(sys, "argv", ["sos_agent_refresh.py"])

    calls = {"n": 0}

    async def counting_fake(names):
        calls["n"] += 1
        return await _fake_batch_lookup(names)
    monkeypatch.setattr(sar, "_batch_lookup", counting_fake)

    rc = sar.main()
    assert rc == 0
    assert calls["n"] == 0  # network path gated off

    rows = wa.load_board(docs)
    by_addr = {li.street_address: li for li in rows}
    propagated_row = by_addr[seed[1].street_address]
    assert propagated_row.raw["sos_agent"]["best_contact_name"] == "Prior Officer"
    # BETA was never looked up, so it's still unresolved
    assert "sos_agent" not in by_addr[seed[2].street_address].raw

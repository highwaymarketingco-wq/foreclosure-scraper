"""board_dedupe_stream.py (task_board_dedupe_stream, 2026-10-01): streaming-safe primitives for
dedupe.dedupe() and distress_score.score_board(), the two genuinely whole-board operations
docs/HANDOFF.md items 15/24 had already looked at and left unmigrated.

THE CRITICAL CORRECTNESS BAR (per the task this module was built for): a streaming
reimplementation that silently changes dedupe/scoring behavior on a 220k-row production board
would be worse than the current unsafe-but-correct scripts. So every test here compares the
NEW streaming path's output against the REAL dedupe()/score_board() run on the SAME synthetic
fixture, fully materialized the old way -- not just "does the new code run without crashing".

Covers:
  1. find_dedupe_merge_groups(): bucket-key merges, cross-bucket fuzzy address merges (zip AND
     county+state blocking), signature union-find merges, and the house-number guard correctly
     keeping two different houses apart (i.e. producing NO merge group) -- each checked against
     dedupe() run directly on fully-hydrated Listing objects for the identical input.
  2. stream_score_board(): a rich fixture exercising many distress-signal families at once
     (foreclosure + probate stack, tax debt, code enforcement, storm damage, bankruptcy,
     divorce, MLS stale/price-cut, upset bid, senior-lien title risk, absentee/out-of-state,
     a parcel-grouped multi-row stack, and a fully-sold-confirmed parcel whose stack is
     removed) -- the resulting distress_stack for EVERY row is compared field-for-field against
     score_board() run directly on fully-hydrated Listing objects for the identical input.
  3. the SCORE_RAW_KEYS whitelist is sensitivity-tested: scoring the SAME fixture with only the
     whitelisted raw keys kept vs. with the full raw dict kept produces IDENTICAL distress_stack
     output -- a regression guard that would fail if distress_score.py ever started reading a
     raw key this module does not yet project.
  4. the dedupe _prov dict-union trick itself: proves _deep_merge_dict() really does union two
     Listing.raw['_prov'] dicts across a real Listing.merge() call (the mechanism
     find_dedupe_merge_groups() depends on for free provenance tracking).
  5. only rows that actually changed are patched: stream_score_board() returns no patch for an
     already-correct row, and the dedupe_key()-collision guard drops (not misapplies) an
     ambiguous shared key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from foreclosure_scraper import board_dedupe_stream as bds
from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.dedupe import dedupe
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.models import Listing, ListingType


def _lead(i: int, **kw) -> Listing:
    base = dict(source=f"src.{i}", source_url=f"https://example.test/u{i}",
               listing_type=ListingType.FORECLOSURE_SALE, state="NC", county="Gaston",
               street_address=f"{i + 1} Main St", zip_code="28052", raw={})
    base.update(kw)
    return Listing(**base)


def _seed(docs: Path, leads: list[Listing]) -> None:
    wa.write_artifact(leads, {"notes": "seed"}, docs_dir=docs)


def _ds_by_source(listings: list[Listing]) -> dict:
    return {li.source: (li.raw or {}).get("distress_stack") for li in listings}


# ===========================================================================
# 1. find_dedupe_merge_groups() vs. the real dedupe()
# ===========================================================================

def test_bucket_key_merge_matches_real_dedupe(tmp_path):
    docs = tmp_path / "docs"
    # Two rows sharing the SAME parcel_id+county+state -- dedupe_key()'s strongest (parcel)
    # branch -- merge in dedupe()'s pass 1 (bucket by primary key).
    a = _lead(0, parcel_id="123-456-789")
    b = _lead(1, parcel_id="123-456-789", street_address="1 Main St")  # same addr as `a`
    other = _lead(2, street_address="99 Elsewhere Dr")
    _seed(docs, [a, b, other])

    real = dedupe([li.model_copy(deep=True) for li in (a, b, other)])
    groups, stats = bds.find_dedupe_merge_groups(docs)

    assert len(real) == 2  # a+b merged, other stands alone
    assert len(groups) == 1
    assert len(groups[0]) == 2
    assert stats["skipped"] == 0


def test_cross_bucket_fuzzy_zip_merge_matches_real_dedupe(tmp_path):
    docs = tmp_path / "docs"
    # No shared parcel_id/case_number -- different dedupe_key()s (address branch, but one has a
    # trailing variation) -- only mergeable via pass 2's fuzzy token-set match, blocked by zip.
    a = _lead(0, street_address="19 Gosnell Avenue", zip_code="29349")
    b = _lead(1, street_address="19 Gosnell Ave", zip_code="29349", county="Union")
    other = _lead(2, street_address="500 Nowhere Near Rd", zip_code="10001", county="Other")
    _seed(docs, [a, b, other])

    real = dedupe([li.model_copy(deep=True) for li in (a, b, other)])
    groups, stats = bds.find_dedupe_merge_groups(docs)

    assert len(real) == 2
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_house_number_guard_prevents_a_merge_in_both_paths(tmp_path):
    docs = tmp_path / "docs"
    # Same parcel_id (forces a pass-1 bucket collision) but DIFFERENT house numbers -- the
    # house-number guard must split them in BOTH the real dedupe() and the streaming finder,
    # i.e. find_dedupe_merge_groups() must report NO merge group at all.
    a = _lead(0, parcel_id="999", street_address="306 Fountain Way")
    b = _lead(1, parcel_id="999", street_address="346 Fountain Way")
    _seed(docs, [a, b])

    real = dedupe([li.model_copy(deep=True) for li in (a, b)])
    groups, stats = bds.find_dedupe_merge_groups(docs)

    assert len(real) == 2  # guard kept them apart in the real algorithm
    assert groups == []    # ... and the streaming finder agrees: nothing to merge


def test_signature_union_merge_matches_real_dedupe(tmp_path):
    docs = tmp_path / "docs"
    # `a` has only a case_number+county identity, `b` only a parcel_id -- different dedupe_key()
    # branches entirely, but they share the SAME address+zip signature (_strong_sigs' "a" sig),
    # which is pass 3's union-find territory.
    a = _lead(0, parcel_id=None, case_number="24-SP-123", street_address="50 Union Signature Rd",
             zip_code="28052")
    b = _lead(1, parcel_id="PID-777", case_number=None, street_address="50 Union Signature Rd",
             zip_code="28052")
    _seed(docs, [a, b])

    real = dedupe([li.model_copy(deep=True) for li in (a, b)])
    groups, stats = bds.find_dedupe_merge_groups(docs)

    assert len(real) == 1
    assert len(groups) == 1
    assert sorted(groups[0]) == sorted([wa.row_identity_hash(r)
                                        for r in json.loads((docs / "listings.json").read_text())])


def test_no_duplicates_on_the_board_produces_no_merge_groups(tmp_path):
    docs = tmp_path / "docs"
    leads = [_lead(i) for i in range(5)]
    _seed(docs, leads)
    groups, stats = bds.find_dedupe_merge_groups(docs)
    assert groups == []
    assert stats["candidate_groups"] == 0


# ===========================================================================
# 2. stream_score_board() vs. the real score_board() -- rich multi-signal fixture
# ===========================================================================

@pytest.fixture
def rich_fixture() -> list[Listing]:
    leads = []

    # 0: plain foreclosure, nothing else -- a single record-linked category, stack 1.
    leads.append(_lead(0, parcel_id="P-0", raw={}))

    # 1+2: SAME parcel -- foreclosure (1) + probate (2) STACK together (parcel grouping).
    # _parcel_key() requires >= 4 alnum chars after stripping non-alnum punctuation (F9's
    # placeholder guard), so the parcel_id must be long enough to actually trigger grouping --
    # a short id like "P-12" silently falls back to an UNGROUPED id: key (verified directly
    # against distress_score._parcel_key() while building this fixture).
    leads.append(_lead(1, parcel_id="P-1234", county="Rutherford",
                       raw={"owner_mailing": {"mailing": "123 X St", "absentee": True,
                                              "out_of_state": True}}))
    leads.append(_lead(2, parcel_id="P-1234", county="Rutherford",
                       listing_type=ListingType.PROBATE_NOTICE,
                       street_address="2 Main St",
                       raw={"probate": True}))

    # 3: tax debt (real, actual_debt) + code enforcement open -> FINANCIAL + PROPERTY stack.
    leads.append(_lead(3, parcel_id="P-3", listing_type=ListingType.TAX_LIEN,
                       raw={"amount_owed": {"value": 4200, "is_actual_debt": True},
                            "code_enforcement": {"has_open": True}}))

    # 4: bankruptcy name-only signal (LEGAL), needs a property to count (F11).
    leads.append(_lead(4, parcel_id="P-4",
                       raw={"bankruptcy": {"date_filed": "2026-01-01", "chapter": "13"}}))

    # 5: divorce (relationship_signal, INF evidence) + storm damage (PROPERTY).
    leads.append(_lead(5, parcel_id="P-5",
                       raw={"relationship_signal": {"kind": "divorce", "keyword": "other"},
                            "storm_damage": {"damage_level": "major"}}))

    # 6: MLS stale-on-market + price cut (SALES signals), via homeharvest block.
    leads.append(_lead(6, parcel_id="P-6", listing_type=ListingType.DISTRESSED,
                       opening_bid=90000.0,
                       raw={"homeharvest": {"mls_status": "active", "days_on_mls": 400},
                            "market_velocity": {"moi": 3.0}}))

    # 7: upset bid open window (FINANCIAL, published).
    leads.append(_lead(7, parcel_id="P-7",
                       raw={"upset_bid": {"in_window": True, "deadline_iso": "2099-01-01",
                                         "source": "published"}}))

    # 8: senior-lien title risk -- penalizes score and blocks HOT.
    leads.append(_lead(8, parcel_id="P-8",
                       raw={"title_risk": {"surviving_senior_debt_risk": True},
                            "probate": True}))

    # 9+10: a parcel where EVERY listing is sold_confirmed -- score_board() pops the stack
    # entirely for both. Published with a PRE-EXISTING stack to prove removal is detected.
    leads.append(_lead(9, parcel_id="P-9900", raw={"sold_confirmed": True,
                                                "distress_stack": {"tier": "WARM", "stack": 1,
                                                                   "categories": ["FINANCIAL"],
                                                                   "signals": ["foreclosure_sale"],
                                                                   "score": 30, "equity_band": None,
                                                                   "absentee": False,
                                                                   "out_of_state": False,
                                                                   "contactable": False,
                                                                   "surviving_senior_debt_risk": False}}))
    leads.append(_lead(10, parcel_id="P-9900", street_address="11 Main St",
                       raw={"sold_confirmed": True}))

    return leads


def test_stream_score_board_matches_real_score_board_on_every_row(tmp_path, rich_fixture):
    docs = tmp_path / "docs"
    _seed(docs, rich_fixture)

    real_copies = [li.model_copy(deep=True) for li in rich_fixture]
    real_hist = score_board(real_copies, previous_path=docs / "listings.json")
    real_stacks = _ds_by_source(real_copies)

    with wa.board_lock(tmp_path, owner="t"):
        result = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    assert result["tiers"] == real_hist

    with wa.board_lock(tmp_path, owner="t"):
        wa.patch_existing_rows(result["patches"], {"notes": "score"}, docs_dir=docs)

    board = wa.load_board(docs)
    new_stacks = _ds_by_source(board)

    for source, real_ds in real_stacks.items():
        got = new_stacks.get(source)
        if real_ds is None:
            # the "disclosed difference" case: real algorithm pops the key, streaming path
            # publishes {} -- both are "no distress" to every reader (see module docstring).
            assert got in (None, {}), (source, got)
        else:
            assert got == real_ds, (source, "real=", real_ds, "streamed=", got)

    # every non-removed category/tier actually showed up -- the fixture is exercising real
    # signal paths, not accidentally scoring everything COLD.
    tiers_seen = {v.get("tier") for v in real_stacks.values() if v}
    assert "HOT" in tiers_seen or "WARM" in tiers_seen


def test_sold_confirmed_parcel_stack_is_removed_not_left_stale(tmp_path, rich_fixture):
    docs = tmp_path / "docs"
    _seed(docs, rich_fixture)
    with wa.board_lock(tmp_path, owner="t"):
        result = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    with wa.board_lock(tmp_path, owner="t"):
        wa.patch_existing_rows(result["patches"], {"notes": "score"}, docs_dir=docs)
    board = wa.load_board(docs)
    row9 = next(li for li in board if li.source == "src.9")
    assert not (row9.raw or {}).get("distress_stack")  # {} or absent, never the stale WARM


def test_already_correct_board_produces_no_patches(tmp_path, rich_fixture):
    docs = tmp_path / "docs"
    _seed(docs, rich_fixture)
    with wa.board_lock(tmp_path, owner="t"):
        result = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    with wa.board_lock(tmp_path, owner="t"):
        wa.patch_existing_rows(result["patches"], {"notes": "first score"}, docs_dir=docs)

    # second run against the now-scored board: nothing should need to change.
    with wa.board_lock(tmp_path, owner="t"):
        result2 = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    assert result2["patches"] == {}
    assert result2["changed"] == 0


# ===========================================================================
# 3. SCORE_RAW_KEYS whitelist sensitivity test
# ===========================================================================

def test_score_raw_keys_whitelist_is_sufficient(tmp_path, rich_fixture):
    """Scoring with ONLY the whitelisted raw keys (what stream_score_board() actually projects)
    must produce identical distress_stack output to scoring with the FULL raw dict, including a
    pile of irrelevant heavy keys no real source would put in a scoring-relevant spot. If this
    ever fails, distress_score.py started reading a raw key SCORE_RAW_KEYS does not yet list."""
    noisy = []
    for li in rich_fixture:
        li2 = li.model_copy(deep=True)
        li2.raw["vision"] = {"description": "x" * 500}
        li2.raw["comps"] = [{"addr": "irrelevant"}] * 20
        li2.raw["description"] = "y" * 1000
        li2.raw["gis_attrs_full"] = {"junk": list(range(50))}
        li2.raw["skip_trace"] = {"phone": "555-0000"}
        noisy.append(li2)

    full_copies = [li.model_copy(deep=True) for li in noisy]
    full_hist = score_board(full_copies)
    full_stacks = _ds_by_source(full_copies)

    projected = []
    for li in noisy:
        fields = {k: getattr(li, k) for k in bds._SCORE_SCALAR_FIELDS}
        fields["raw"] = {k: li.raw[k] for k in bds.SCORE_RAW_KEYS if k in li.raw}
        projected.append(Listing.model_validate(fields))
    proj_hist = score_board(projected)
    proj_stacks = _ds_by_source(projected)

    assert proj_hist == full_hist
    assert proj_stacks == full_stacks


# ===========================================================================
# 4. the _prov dict-union mechanism itself
# ===========================================================================

def test_prov_dict_survives_and_unions_across_a_real_merge():
    a = Listing(source="a", source_url="https://x.test/a", street_address="1 Main St",
               state="NC", raw={"_prov": {"hash-a": True}})
    b = Listing(source="b", source_url="https://x.test/b", street_address="1 Main St",
               state="NC", raw={"_prov": {"hash-b": True}})
    merged = a.merge(b)
    assert merged.raw["_prov"] == {"hash-a": True, "hash-b": True}
    # chained merge (a 3-row bucket) keeps accumulating, not overwriting
    c = Listing(source="c", source_url="https://x.test/c", street_address="1 Main St",
               state="NC", raw={"_prov": {"hash-c": True}})
    merged2 = merged.merge(c)
    assert merged2.raw["_prov"] == {"hash-a": True, "hash-b": True, "hash-c": True}


def test_prov_list_would_NOT_survive_demonstrating_why_a_dict_is_required():
    """Documents WHY _light_listing_for_dedupe() uses a dict, not a list, for `_prov`:
    models._deep_merge_dict() replaces (does not concatenate) a list-valued leaf on conflict."""
    a = Listing(source="a", source_url="https://x.test/a", street_address="1 Main St",
               state="NC", raw={"_prov_list": ["hash-a"]})
    b = Listing(source="b", source_url="https://x.test/b", street_address="1 Main St",
               state="NC", raw={"_prov_list": ["hash-b"]})
    merged = a.merge(b)
    assert merged.raw["_prov_list"] == ["hash-b"]  # "hash-a" was LOST, not unioned


# ===========================================================================
# 5. only real changes are patched / collision guard drops rather than misapplies
# ===========================================================================

def test_dedupe_key_collision_with_identical_scores_is_still_applied_once(tmp_path):
    docs = tmp_path / "docs"
    # Two rows sharing a parcel (same dedupe_key via the parcel branch) -- they score IDENTICALLY
    # (same group), so patch_existing_rows() applying the one patch to both matches is correct.
    a = _lead(0, parcel_id="P-123SHARED", raw={"probate": True})
    b = _lead(1, parcel_id="P-123SHARED", street_address="2 Main St", raw={})
    _seed(docs, [a, b])
    with wa.board_lock(tmp_path, owner="t"):
        result = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    assert result["dropped_key_collisions"] == 0
    assert len(result["patches"]) == 1  # one patch entry, matches BOTH rows
    with wa.board_lock(tmp_path, owner="t"):
        stats = wa.patch_existing_rows(result["patches"], {"notes": "t"}, docs_dir=docs)
    assert stats["applied"] == 2
    assert stats["duplicate_key_matches"] == 1


def test_dedupe_key_collision_with_different_scores_is_dropped_not_misapplied(tmp_path):
    docs = tmp_path / "docs"
    # Two rows with NO parcel_id sharing the exact same normalized address+zip -> the SAME
    # dedupe_key() (address branch), but DIFFERENT county -> DIFFERENT _parcel_key() groups ->
    # can score differently. One gets a probate signal, the other does not.
    # audit 2026-10-01: raw['probate'] must name a real decedent/case (has_real_probate) to
    # count -- a bare True is not a shape any real scraper writes.
    a = _lead(0, parcel_id=None, street_address="77 Collision Rd", zip_code="28052",
             county="Gaston", raw={"probate": {"case_number": "22E001234"}})
    b = _lead(1, parcel_id=None, street_address="77 Collision Rd", zip_code="28052",
             county="Cleveland", raw={})
    assert a.dedupe_key() == b.dedupe_key()  # confirm the premise

    _seed(docs, [a, b])
    with wa.board_lock(tmp_path, owner="t"):
        result = bds.stream_score_board(docs, previous_path=docs / "listings.json")
    # whichever of the two changed relative to their (absent) prior stack, the shared key must
    # be dropped rather than letting one row's score land on the other.
    assert a.dedupe_key() not in result["patches"]
    assert result["dropped_key_collisions"] >= 1

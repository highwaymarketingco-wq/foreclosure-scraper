"""scripts/backfill_heir_names.py -- closes the heir_names coverage gap on
ALREADY-PUBLISHED estate_lead rows without a re-scrape (see that script's own
module docstring for the full root-cause writeup: confirmed LIVE 2026-10-04
that 0 of 1,039 published estate_lead rows carry heir_names, because the
board predates the 2026-10-02 commit that added the field, and because every
landing path this project uses outside a full pipeline run is additive-only
-- re-running the scraper alone would not retroactively fix rows already on
the board).

Covers what's actually new here:
  1. derive_heir_names(): reconstructs the structured list from the already-
     published, ";"-joined owner_of_record string, reusing the scraper's own
     unmodified _parse_owner_field() -- must match what a live re-scrape's
     _heir_names() would have produced for the same owner_fields.
  2. build_patch(): the RAW-UPDATE GOTCHA regression pin -- patch_existing_
     rows() merges a row's raw dict only ONE level deep (plain dict.update()),
     so a patch that sets raw['heir_estate'] to a dict containing ONLY
     heir_names would silently delete owner_of_record/mailing/care_of/match.
     build_patch() must always carry every existing sibling key forward.
  3. _collect_targets()'s dedupe_key() collision guard and already-has/
     no-owner skip logic, against synthetic board-row dicts (no live board
     file read).
  4. main() end-to-end, via --rows-file-style monkeypatching of
     iter_board_rows, confirming the dry-run patches dict is correct and that
     nothing is written without --apply.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_heir_names as B  # noqa: E402


# --------------------------------------------------------------------------- #
# derive_heir_names()
# --------------------------------------------------------------------------- #

def test_derive_heir_names_matches_live_buncombe_shape():
    """Live-captured board shape (Buncombe, 2026-10-04): a single-heir row's
    already-published owner_of_record, with no second subfield."""
    out = B.derive_heir_names("ALICE METCALF HEIRS")
    assert out == [{"raw": "ALICE METCALF HEIRS", "name": "ALICE METCALF", "role": "heir"}]


def test_derive_heir_names_splits_multi_heir_join_and_matches_scraper_output():
    """Same Gaston multi-heir shape nc_heir_estate_parcels.py's own test fixture
    uses -- the backfill's reconstruction from the JOINED string must equal
    what the scraper's _heir_names() produces straight from owner_fields."""
    from foreclosure_scraper.scrapers.counties_nc.nc_heir_estate_parcels import _heir_names

    owner_fields = ["HARDIN CLARENCE HEIRS", "HARDIN OMA HEIRS"]
    joined = "; ".join(owner_fields)  # what _owner_display() actually publishes
    assert B.derive_heir_names(joined) == _heir_names(owner_fields)


def test_derive_heir_names_handles_care_of_and_estate_of_shapes():
    out = B.derive_heir_names("ESTATE OF JOHN SMITH; HUNTER LINDA PACE ET VIR")
    assert out == [
        {"raw": "ESTATE OF JOHN SMITH", "name": "JOHN SMITH", "role": "estate"},
        {"raw": "HUNTER LINDA PACE ET VIR", "name": "HUNTER LINDA PACE ET VIR", "role": "other"},
    ]


def test_derive_heir_names_empty_or_none_owner_yields_empty_list():
    assert B.derive_heir_names(None) == []
    assert B.derive_heir_names("") == []


# --------------------------------------------------------------------------- #
# build_patch() -- the RAW-UPDATE GOTCHA regression pin
# --------------------------------------------------------------------------- #

def test_build_patch_preserves_sibling_keys():
    """patch_existing_rows() replaces raw['heir_estate'] WHOLESALE (one-level
    dict.update()) -- a patch carrying only {"heir_names": [...]} would wipe
    owner_of_record/mailing/care_of/match off the published row. This is the
    exact bug class this test exists to catch."""
    existing = {
        "owner_of_record": "ALICE METCALF HEIRS",
        "mailing": "66 VERNON RDG WEAVERVILLE NC 28787",
        "care_of": "JOHN METCALF",
        "match": "heirs",
    }
    names = B.derive_heir_names(existing["owner_of_record"])
    patch = B.build_patch(existing, names)

    he = patch["raw"]["heir_estate"]
    assert he["heir_names"] == names
    assert he["owner_of_record"] == "ALICE METCALF HEIRS"
    assert he["mailing"] == "66 VERNON RDG WEAVERVILLE NC 28787"
    assert he["care_of"] == "JOHN METCALF"
    assert he["match"] == "heirs"


def test_build_patch_does_not_mutate_the_input_dict():
    """_collect_targets() hands build_patch() the SAME dict it read off the
    streamed row -- build_patch() must not mutate it in place (a later
    collision-guard re-check or a second candidate sharing the object would
    silently see heir_names already injected)."""
    existing = {"owner_of_record": "WALKER SALLY ESTATE", "mailing": None,
               "care_of": None, "match": "estate"}
    before = dict(existing)
    B.build_patch(existing, B.derive_heir_names(existing["owner_of_record"]))
    assert existing == before


# --------------------------------------------------------------------------- #
# _collect_targets()
# --------------------------------------------------------------------------- #

_GOOD_ROW = {
    "listing_type": "estate_lead",
    "source": "counties_nc.nc_heir_estate_parcels",
    "state": "NC", "county": "Buncombe", "parcel_id": "1234",
    "street_address": "123 MAIN ST", "zip_code": "28801",
    "case_number": None, "source_url": "https://example.test/gis",
    "raw": {"heir_estate": {
        "owner_of_record": "ALICE METCALF HEIRS",
        "mailing": "66 VERNON RDG WEAVERVILLE NC 28787",
        "care_of": None, "match": "heirs",
    }},
}


def _row(**overrides) -> dict:
    import copy
    rec = copy.deepcopy(_GOOD_ROW)
    for k, v in overrides.items():
        if k == "raw_heir_estate":
            rec["raw"]["heir_estate"] = v
        else:
            rec[k] = v
    return rec


def test_collect_targets_finds_eligible_row(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([_row()]))
    scanned, eligible, already_has, no_owner, key_counts, candidates = \
        B._collect_targets(tmp_path)
    assert scanned == 1
    assert eligible == 1
    assert already_has == 0
    assert no_owner == 0
    assert len(candidates) == 1
    key, he = candidates[0]
    assert key is not None
    assert he["owner_of_record"] == "ALICE METCALF HEIRS"


def test_collect_targets_skips_row_that_already_has_heir_names(monkeypatch, tmp_path):
    row = _row(raw_heir_estate={
        "owner_of_record": "ALICE METCALF HEIRS", "mailing": None,
        "care_of": None, "match": "heirs",
        "heir_names": [{"raw": "ALICE METCALF HEIRS", "name": "ALICE METCALF", "role": "heir"}],
    })
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([row]))
    _, eligible, already_has, _, _, candidates = B._collect_targets(tmp_path)
    assert eligible == 0
    assert already_has == 1
    assert candidates == []


def test_collect_targets_skips_wrong_source_and_wrong_listing_type(monkeypatch, tmp_path):
    other_source = _row(source="national.estate_sales")
    other_type = _row(listing_type="probate_notice")
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([other_source, other_type]))
    _, eligible, already_has, no_owner, _, candidates = B._collect_targets(tmp_path)
    assert eligible == 0
    assert candidates == []


def test_collect_targets_counts_missing_owner_separately(monkeypatch, tmp_path):
    row = _row(raw_heir_estate={"owner_of_record": None, "mailing": None,
                                "care_of": None, "match": "heirs"})
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([row]))
    _, eligible, already_has, no_owner, _, candidates = B._collect_targets(tmp_path)
    assert eligible == 0
    assert no_owner == 1
    assert candidates == []


def test_collect_targets_counts_a_shared_dedupe_key_for_the_collision_guard(monkeypatch, tmp_path):
    """Two board rows (even across unrelated sources) sharing one dedupe_key()
    must both be counted in key_counts -- main()'s collision guard drops a
    candidate whose key appears more than once anywhere on the board, not
    just among other heir rows."""
    a = _row()
    b = _row(source="national.estate_sales")  # same identity fields -> same key
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([a, b]))
    _, _, _, _, key_counts, candidates = B._collect_targets(tmp_path)
    assert len(candidates) == 1
    (key, _he), = candidates
    assert key_counts[key] == 2


# --------------------------------------------------------------------------- #
# main() end-to-end
# --------------------------------------------------------------------------- #

def test_main_dry_run_builds_patches_but_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([_row()]))
    monkeypatch.setattr(sys, "argv", ["backfill_heir_names.py"])
    monkeypatch.setattr(B, "REPO", tmp_path)

    called = {"patch_existing_rows": False}

    def _boom(*a, **kw):
        called["patch_existing_rows"] = True
        raise AssertionError("patch_existing_rows() must never be called on a dry run")

    import foreclosure_scraper.web_artifact as wa
    monkeypatch.setattr(wa, "patch_existing_rows", _boom)

    rc = B.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY RUN" in out
    assert "total patches ready: 1" in out
    assert called["patch_existing_rows"] is False


def test_main_dry_run_is_the_default_without_apply_flag(monkeypatch, tmp_path):
    """No --dry-run flag needs to be passed -- the absence of --apply alone
    must be enough to refuse writing (the task this script was built under
    forbids live board-file writes; a caller forgetting a flag must never
    accidentally write)."""
    monkeypatch.setattr(B, "iter_board_rows", lambda path: iter([]))
    monkeypatch.setattr(sys, "argv", ["backfill_heir_names.py"])
    monkeypatch.setattr(B, "REPO", tmp_path)
    rc = B.main()
    assert rc == 0

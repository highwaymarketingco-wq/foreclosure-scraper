"""scripts/backfill_york_stokes_jail_crosscounty.py: _scan()'s candidate-selection logic, on
synthetic fixtures. No real board, no real network -- board_stream.iter_board_rows() is
monkeypatched to yield board-shaped dicts, the same convention test_backfill_cchs_lien_sweep.py
uses. The real matching primitives (match_rosters, match_cross_county, _load_roster) are
existing, independently-tested code this script only calls -- not re-tested here; this file
pins only the one genuinely new piece of logic: splitting one streaming board pass into
same-county candidates (every York SC / Stokes NC row, unconditionally) and cross-county
candidates (rows elsewhere whose owner's normalized name is in the wanted set, state-scoped,
never re-offering an already-flagged jail_booking_new row).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_york_stokes_jail_crosscounty as bb  # noqa: E402

from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402


def _listing(**kw) -> Listing:
    base = dict(source="counties_sc.spartanburg_flc", source_url="https://example/1",
                listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.UNKNOWN,
                state="SC", county="York", parcel_id="12345", owner_name="SMITH JOHN")
    base.update(kw)
    return Listing(**base)


def _board_dict(li: Listing, raw: dict | None = None) -> dict:
    d = li.model_dump(mode="json")
    if raw:
        d["raw"] = {**(d.get("raw") or {}), **raw}
    return d


def _fake_iter(rows, monkeypatch):
    monkeypatch.setattr(bb, "iter_board_rows", lambda *_a, **_kw: iter(rows))


def _wanted(state: str, last: str, first: str) -> dict:
    """wanted_names shape _scan() expects: state -> set of normalized (last, first) keys."""
    return {state: {bb._norm_key(last, first)}}


def test_a_target_county_row_always_goes_to_same_county(monkeypatch):
    row = _board_dict(_listing(state="NC", county="Stokes", owner_name="ANYONE AT ALL"))
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert len(same_county) == 1
    assert cross == []


def test_a_row_elsewhere_with_a_wanted_name_becomes_a_cross_candidate(monkeypatch):
    row = _board_dict(_listing(state="SC", county="Greenville", owner_name="DOE JANE"))
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert same_county == []
    assert len(cross) == 1
    assert cross[0].owner_name == "DOE JANE"


def test_a_wanted_name_in_the_wrong_state_is_excluded(monkeypatch):
    # York's roster is SC-scoped; an NC row sharing the same name is not a candidate for it
    # (match_cross_county itself never cross-references across state, by construction).
    row = _board_dict(_listing(state="NC", county="Guilford", owner_name="DOE JANE"))
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert cross == []


def test_a_row_outside_target_counties_with_no_matching_name_is_excluded(monkeypatch):
    row = _board_dict(_listing(state="SC", county="Greenville", owner_name="NOBODY MATCHES"))
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert same_county == []
    assert cross == []


def test_a_row_already_flagged_jail_booking_new_is_never_reoffered(monkeypatch):
    row = _board_dict(_listing(state="SC", county="Greenville", owner_name="DOE JANE"),
                       raw={"jail_booking_new": {"county": "York", "state": "SC"}})
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert cross == [], "a row already carrying jail_booking_new must not be re-staged"


def test_a_row_with_no_owner_name_is_skipped_from_cross_candidates(monkeypatch):
    row = _listing(state="SC", county="Greenville", owner_name="").model_dump(mode="json")
    _fake_iter([row], monkeypatch)

    same_county, cross = bb._scan(Path("/x"), _wanted("SC", "DOE", "JANE"))
    assert cross == []


def test_one_pass_handles_both_target_counties_and_name_matches_together(monkeypatch):
    rows = [
        _board_dict(_listing(state="SC", county="York", owner_name="A", parcel_id="1")),
        _board_dict(_listing(state="NC", county="Stokes", owner_name="B", parcel_id="2")),
        _board_dict(_listing(state="SC", county="Greenville", owner_name="DOE JANE", parcel_id="3")),
        _board_dict(_listing(state="NC", county="Guilford", owner_name="ROE RICK", parcel_id="4")),
        _board_dict(_listing(state="SC", county="Greenville", owner_name="NOBODY", parcel_id="5")),
    ]
    _fake_iter(rows, monkeypatch)

    wanted = {"SC": {bb._norm_key("DOE", "JANE")}, "NC": {bb._norm_key("ROE", "RICK")}}
    same_county, cross = bb._scan(Path("/x"), wanted)
    assert len(same_county) == 2
    assert {li.owner_name for li in cross} == {"DOE JANE", "ROE RICK"}

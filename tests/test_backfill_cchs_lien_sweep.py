"""scripts/backfill_cchs_lien_sweep.py: _all_county_rows()'s candidate-selection logic, on
synthetic fixtures. No real board, no real network -- board_stream.iter_board_rows() is
monkeypatched to yield board-shaped dicts (Listing.model_dump(mode="json")), the same convention
test_backfill_multiyear_tax_restatement.py/test_backfill_deed_ref_bound.py use. The network
sweep (rod.county_sweeps.CchsClassicReader/sweep/stamp_for) and the board-write side
(board_lock()/patch_existing_rows()) are existing, independently-tested primitives this script
only calls -- not re-tested here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_cchs_lien_sweep as bb  # noqa: E402

from foreclosure_scraper.models import Listing, ListingType, PropertyKind  # noqa: E402


def _listing(**kw) -> Listing:
    base = dict(source="counties_nc.nc_tax_foreclosure", source_url="https://example/1",
                listing_type=ListingType.TAX_SALE, property_kind=PropertyKind.UNKNOWN,
                state="NC", county="Caldwell", parcel_id="12345", owner_name="SMITH JOHN")
    base.update(kw)
    return Listing(**base)


def _board_dict(li: Listing, raw: dict | None = None) -> dict:
    """What iter_board_rows() would actually yield: a plain dict (not a Listing), raw merged in
    the same place board_stream itself puts it."""
    d = li.model_dump(mode="json")
    if raw:
        d["raw"] = {**(d.get("raw") or {}), **raw}
    return d


def _fake_iter(rows, monkeypatch):
    monkeypatch.setattr(bb, "iter_board_rows", lambda *_a, **_kw: iter(rows))


def test_eligible_row_in_a_target_county_is_collected(monkeypatch):
    rows = [_board_dict(_listing(county="Caldwell", owner_name="SMITH JOHN"))]
    _fake_iter(rows, monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Caldwell", "Dare"))
    assert len(out["Caldwell"]) == 1
    assert out["Dare"] == []
    key, li = out["Caldwell"][0]
    assert li.owner_name == "SMITH JOHN"
    assert key == li.dedupe_key()


def test_a_row_with_an_existing_rod_lien_sweep_stamp_is_never_reoffered(monkeypatch):
    stamped = _board_dict(_listing(county="Dare", owner_name="A OWNER"),
                           raw={"rod_lien_sweep": {"status": "none_found", "checked_at": "2026-01-01"}})
    fresh = _board_dict(_listing(county="Dare", owner_name="B OWNER", parcel_id="99"))
    _fake_iter([stamped, fresh], monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Caldwell", "Dare"))
    owners = {li.owner_name for _k, li in out["Dare"]}
    assert owners == {"B OWNER"}, "a row that already carries a real rod_lien_sweep must not be re-staged"


def test_a_row_with_no_owner_name_is_skipped(monkeypatch):
    no_owner = _listing(county="Gates", owner_name="").model_dump(mode="json")
    _fake_iter([no_owner], monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Caldwell", "Dare", "Gates"))
    assert out["Gates"] == []


def test_rows_outside_nc_are_excluded_even_if_the_county_name_matches(monkeypatch):
    # "Union" exists as both an NC and an SC county; only the NC one is in HOSTED_CCHS/our scope.
    sc_row = _board_dict(_listing(state="SC", county="Union", owner_name="SAME NAME"))
    _fake_iter([sc_row], monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Union",))
    assert out["Union"] == [], "a non-NC row must never be collected, even with a matching county name"


def test_rows_outside_the_requested_counties_are_excluded(monkeypatch):
    other = _board_dict(_listing(county="Mecklenburg", owner_name="X"))
    _fake_iter([other], monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Caldwell", "Dare"))
    assert out["Caldwell"] == []
    assert out["Dare"] == []


def test_one_pass_partitions_several_counties_at_once(monkeypatch):
    rows = [
        _board_dict(_listing(county="Caldwell", owner_name="A", parcel_id="1")),
        _board_dict(_listing(county="Dare", owner_name="B", parcel_id="2")),
        _board_dict(_listing(county="Gates", owner_name="C", parcel_id="3")),
    ]
    _fake_iter(rows, monkeypatch)

    out = bb._all_county_rows(Path("/x"), ("Caldwell", "Dare", "Gates", "Currituck"))
    assert len(out["Caldwell"]) == 1
    assert len(out["Dare"]) == 1
    assert len(out["Gates"]) == 1
    assert out["Currituck"] == []

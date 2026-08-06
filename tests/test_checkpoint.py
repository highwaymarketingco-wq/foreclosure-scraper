"""Crash durability.

A Mac reboot 44.6 hours into the 2026-08-06 run destroyed everything: the
merged 47,090-lead board plus GIS, geocoding, owner resolution, parcel lookups
and comps. Nothing had touched disk in 44 hours because the only write was the
final publish.

The invariants that matter here are not "does it save" but "can a crash at the
worst possible moment still lose data".
"""
from __future__ import annotations

import gzip
import json

import pytest

from foreclosure_scraper import checkpoint as C
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


@pytest.fixture(autouse=True)
def _tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", tmp_path / "ck")
    monkeypatch.setattr(C, "ENABLED", True)


def _leads(n=3):
    return [Listing(source="s", source_url=f"https://e.com/{i}",
                    listing_type=ListingType.TAX_LIEN,
                    property_kind=PropertyKind.UNKNOWN,
                    state="NC", county="Buncombe", street_address=f"{i} A ST",
                    owner_name=f"OWNER {i}", latitude=35.0 + i, longitude=-82.0,
                    raw={"deep": {"nested": [1, 2, {"x": i}]}, "tax_owed": {"balance": i}})
            for i in range(n)]


def test_round_trip_preserves_full_raw_fidelity():
    """write_artifact SLIMS raw for publication. A checkpoint must not — a
    resume that silently dropped comps/vision would be worse than no resume."""
    C.save(_leads(), "phase1")
    back = C.load()
    assert len(back) == 3
    assert back[0].raw["deep"]["nested"][2] == {"x": 0}
    assert back[1].owner_name == "OWNER 1"
    assert back[2].latitude == 37.0


def test_a_crash_during_a_checkpoint_cannot_corrupt_the_previous_one(monkeypatch):
    """The whole point of the atomic write. If the process dies mid-save, the
    last good checkpoint must still load."""
    C.save(_leads(2), "good")
    real = C.json.dump

    def boom(*a, **kw):
        raise OSError("simulated crash mid-write")
    monkeypatch.setattr(C.json, "dump", boom)
    assert C.save(_leads(9), "doomed") is False      # must not raise
    monkeypatch.setattr(C.json, "dump", real)

    back = C.load()
    assert back is not None and len(back) == 2, "previous checkpoint was destroyed"
    assert C.manifest()["phase"] == "good"


def test_save_never_raises_so_it_cannot_kill_a_healthy_run(monkeypatch):
    monkeypatch.setattr(C, "CHECKPOINT_DIR", C.Path("/nonexistent/nope/deny"))
    assert C.save(_leads(), "x") is False


def test_a_stale_checkpoint_is_refused():
    """Resuming onto week-old data would republish it as if it were fresh."""
    C.save(_leads(), "old")
    assert C.load(max_age_h=100) is not None
    assert C.load(max_age_h=-1) is None


def test_no_checkpoint_returns_none_not_an_error():
    assert C.load() is None
    assert C.manifest() is None


def test_clear_removes_it():
    C.save(_leads(), "p")
    assert C.load() is not None
    C.clear()
    assert C.load() is None


def test_empty_list_is_not_checkpointed():
    """Saving an empty board over a good one would turn a crash into data loss."""
    C.save(_leads(), "good")
    assert C.save([], "empty") is False
    assert len(C.load()) == 3


def test_one_unparseable_row_does_not_void_the_whole_resume():
    C.save(_leads(3), "p")
    p = C.CHECKPOINT_DIR / C.BOARD_FILE
    with gzip.open(p, "rt") as fh:
        recs = json.load(fh)
    recs.insert(1, {"garbage": True})
    with gzip.open(p, "wt") as fh:
        json.dump(recs, fh)
    back = C.load()
    assert len(back) == 3, "a single bad row discarded the good ones"


def test_disabled_is_a_no_op(monkeypatch):
    monkeypatch.setattr(C, "ENABLED", False)
    assert C.save(_leads(), "p") is False
    assert C.load() is None

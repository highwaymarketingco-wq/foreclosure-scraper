"""Crash durability for scripts/merge_today_sources.py.

A laptop power loss killed a live run 2026-08-09, ~16.5 hours into it (past
`resolve_name_to_property` and into the sync valuation/scoring phase, per the
log's last line, `sc_cama.enriched`). Nothing had touched disk, because the
only write in the whole script is `write_artifact` at the very end — the
EXACT "44.6h run, nothing saved" failure mode `checkpoint.py` exists to
prevent, just never wired into this script.

These tests cover the plumbing that's new here: an isolated checkpoint
directory (so this script's checkpoint is never confused with the main
engine's), and that a stale one is correctly refused. Full round-trip
fidelity of the checkpoint module itself is already covered by
test_checkpoint.py; these tests don't re-litigate that, only this script's
use of it.
"""
from __future__ import annotations

import importlib
import os

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
                    owner_name=f"OWNER {i}")
            for i in range(n)]


def test_merge_script_points_at_its_own_checkpoint_dir(monkeypatch):
    """The env var must be set BEFORE foreclosure_scraper.checkpoint is
    imported (CHECKPOINT_DIR is a module-level constant read once at import
    time), and it must NOT be the main engine's own data/checkpoint — a
    shared directory would make a checkpoint's origin ambiguous, and this
    script's caller (post_run_catchup_chain.sh) explicitly waits for the
    main engine to release ITS checkpoint before this script even starts."""
    monkeypatch.delenv("FORECLOSURE_CHECKPOINT_DIR", raising=False)
    import scripts.merge_today_sources as mts  # noqa: F401
    importlib.reload(mts)
    assert os.environ["FORECLOSURE_CHECKPOINT_DIR"] == "data/checkpoint_merge"
    assert os.environ["FORECLOSURE_CHECKPOINT_DIR"] != "data/checkpoint"


def test_resolved_checkpoint_round_trips_for_resume():
    """What _resolve() saves (phase='resolved') is exactly what main()'s
    resume branch loads. If either side drifts, a resume silently loses the
    address-resolution chain's output."""
    leads = _leads(5)
    assert C.save(leads, "resolved") is True
    resumed = C.load()
    assert resumed is not None
    assert len(resumed) == 5
    assert {li.owner_name for li in resumed} == {li.owner_name for li in leads}


def test_scored_checkpoint_also_resumable():
    """The second checkpoint (post valuation/scoring, pre-publish) must be
    just as resumable as the first — a crash there shouldn't force a re-run
    of the (much more expensive) address-resolution chain either."""
    leads = _leads(2)
    for li in leads:
        li.raw = {"calc": {"arv": 100000}, "grade": {"tier": "A"}}
    assert C.save(leads, "scored") is True
    resumed = C.load()
    assert resumed is not None
    assert resumed[0].raw.get("calc", {}).get("arv") == 100000


def test_ancient_checkpoint_is_refused_not_silently_resumed():
    """A checkpoint old enough to predate the CURRENT source set must not be
    resumed onto — that would silently republish stale data as fresh, with
    no error. This is the module's own MAX_AGE_H guard; asserted here because
    main()'s resume logic depends on load() returning None in this case."""
    leads = _leads(2)
    C.save(leads, "resolved")
    # Back-date the manifest past the default 48h window.
    import json as _json
    m = C._dir() / C.MANIFEST_FILE
    manifest = _json.loads(m.read_text())
    manifest["saved_at"] = "2020-01-01T00:00:00+00:00"
    m.write_text(_json.dumps(manifest))
    assert C.load() is None, "a 48h+ old checkpoint must not be resumed onto"


def test_clear_removes_the_isolated_checkpoint_only():
    """checkpoint.clear() after a successful publish must actually remove
    the directory main()'s resume check looks at — a no-op clear() would
    make every future run resume onto the just-published (now stale) board."""
    C.save(_leads(1), "scored")
    assert C.load() is not None
    C.clear()
    assert C.load() is None

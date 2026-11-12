"""The single-load driver must run the fixes in dependency order, refuse an unknown step, keep the
row count, and stay a dry run unless told otherwise. Uses synthetic Listings, never the board."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import apply_board_fixes as D  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402


def _li(**kw):
    base = dict(source="counties_nc.x", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC",
                county="Gaston", raw={})
    base.update(kw)
    return Listing(**base)


def test_order_matches_the_documented_dependencies():
    keys = [k for k, _m, _n in D.STEPS]
    assert keys.index("resolver") < keys.index("ptscloud") < keys.index("county") < keys.index("flip")
    assert keys.index("county") < keys.index("address") < keys.index("join")
    assert keys.index("accounts") < keys.index("address")
    # the address-to-parcel resolver needs the county (it reads the county's own cache) and must precede the join
    assert keys.index("county") < keys.index("parcel") < keys.index("address") < keys.index("join")
    assert keys.index("resolver") < keys.index("parcel")          # never resolve from a name-only guess withdrawn later
    # the repair replaces a parcel the join has already been fed, so it runs right after `parcel` and before anything copies from a parcel
    assert keys.index("parcel") < keys.index("parcel_repair") < keys.index("address") < keys.index("join")
    assert keys.index("county") < keys.index("parcel_repair")


def test_every_step_module_exposes_apply_rows():
    for key, mod, _note in D.STEPS:
        if mod:
            assert callable(getattr(importlib.import_module(mod), "apply_rows", None)), key


def test_light_steps_run_dry_and_keep_the_row_count():
    rows = [_li(), _li(county=None), _li(listing_type=ListingType.FORECLOSURE_SALE, county="New Hanover")]
    out = D.run_steps(rows, {"flip", "divorce", "phones"}, dry_run=True, log=lambda m: None)
    assert set(out) == {"flip", "divorce", "phones"}
    assert len(rows) == 3
    # a dry run stamps nothing
    assert all("scope" not in (li.raw or {}) for li in rows)


def test_a_step_that_changes_the_row_count_aborts(monkeypatch):
    class Bad:
        BACKUP_NAME = None

        @staticmethod
        def apply_rows(rows, *, dry_run=False):
            rows.pop()
            return {}

    monkeypatch.setattr(D, "STEPS", [("bad", "fake_bad_mod", "x")])
    monkeypatch.setitem(sys.modules, "fake_bad_mod", Bad)
    with pytest.raises(RuntimeError, match="row count"):
        D.run_steps([_li(), _li()], None, dry_run=True, log=lambda m: None)


def test_unknown_step_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["apply_board_fixes.py", "--steps", "nope"])
    assert D.main() == 2

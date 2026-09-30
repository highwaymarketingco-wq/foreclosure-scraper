"""scripts/catchup_failed_enrichers.py -- the resolve_name addition.

2026-09-29: added `resolve_name` (enrichment_resolve_name_to_property) as a fourth
catch-up option, because it has the same "never got to run this cycle" failure mode
as the original three (incarceration/jail_bookings/skip_trace) -- see the script's
own docstring and docs/extraction_gaps.md's "Unlocatable" section.

Nothing here hits a live GIS endpoint or the real board: `_run_one` is exercised with
the real dispatch table but a monkeypatched `enrich_resolve_name_to_property`, so this
tests the WIRING (does --only resolve_name call the right function and return its
stats), not the resolver's own matching logic (which is exercised elsewhere / by the
module's own runtime-verified docstring claims).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import catchup_failed_enrichers as cfe  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402


def _li(**kw) -> Listing:
    return Listing(source="counties_nc.test", source_url="u", **kw)


def test_resolve_name_is_a_valid_only_choice():
    # the real contract: argparse must accept it without raising SystemExit
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append",
                    choices=["incarceration", "jail_bookings", "skip_trace", "resolve_name"])
    ns = ap.parse_args(["--only", "resolve_name"])
    assert ns.only == ["resolve_name"]


@pytest.mark.asyncio
async def test_run_one_dispatches_resolve_name_and_returns_its_stats(monkeypatch):
    calls = {}

    async def fake_enrich(listings):
        calls["listings"] = listings
        return {"targets": 2, "resolved": 1}

    monkeypatch.setattr(
        "foreclosure_scraper.enrichment_resolve_name_to_property."
        "enrich_resolve_name_to_property",
        fake_enrich,
    )

    listings = [_li(owner_name="Jane Doe")]
    stats = await cfe._run_one("resolve_name", listings, dry_run=False)

    assert stats == {"targets": 2, "resolved": 1}
    assert calls["listings"] is listings


@pytest.mark.asyncio
async def test_run_one_still_raises_on_a_truly_unknown_name():
    with pytest.raises(ValueError):
        await cfe._run_one("not_a_real_enricher", [], dry_run=False)


def test_unlocatable_counts_leads_with_neither_address_nor_parcel():
    leads = [
        _li(street_address=None, parcel_id=None),          # unlocatable
        _li(street_address="", parcel_id="  "),            # blank strings -> unlocatable
        _li(street_address="12 Oak St", parcel_id=None),    # has an address
        _li(street_address=None, parcel_id="P-001"),        # has a parcel
        _li(street_address="9 Elm Dr", parcel_id="P-002"),  # has both
    ]
    assert cfe._unlocatable(leads) == 2

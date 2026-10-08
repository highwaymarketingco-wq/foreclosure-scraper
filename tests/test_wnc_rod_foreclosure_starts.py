"""counties_nc.wnc_rod_foreclosure_starts — party-join + image-key wiring.

`enrichment_rod_lookup.bulk_by_date()` walks the Haywood/Clay/Yancey "The
Lookup" party index one entity at a time, so a single instrument's rows
arrive scattered across several fetches; `_dedupe()` groups them back by
(date, book, type) before `_to_listing()` builds one Listing per instrument.
This file locks in that join (already correct — regression guard, not a new
fix) and the new image-key wiring (a real finding: the "Image?" column links
a free scanned copy of the instrument, live-confirmed 2026-10-01, that the
scraper never captured at all).
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc.wnc_rod_foreclosure_starts import (
    WNCRodForeclosureStarts, _dedupe, _to_listing,
)


def _party(recorded, book_info, doc_type, role, name, kind, image_key=None, image_type=None):
    return {
        "recorded": recorded, "book_info": book_info, "doc_type": doc_type,
        "party_role": role, "party": name, "reverse_party": "",
        "kind": kind, "image_key": image_key, "image_type": image_type,
    }


def test_multiple_borrowers_on_one_instrument_are_all_kept():
    """A substitution of trustee naming two borrowers (e.g. spouses) plus the
    lender and two trustees — all real parties must survive into defendant."""
    rows = [
        _party("09/11/2026", "RB 1161 815", "S/T", "GRANTOR", "SMITH JOHN", "substitution_of_trustee"),
        _party("09/11/2026", "RB 1161 815", "S/T", "GRANTOR", "SMITH JANE", "substitution_of_trustee"),
        _party("09/11/2026", "RB 1161 815", "S/T", "GRANTEE", "ACME BANK NA", "substitution_of_trustee"),
        _party("09/11/2026", "RB 1161 815", "S/T", "GRANTEE", "DOE TRUSTEE SERVICES LLC", "substitution_of_trustee"),
    ]
    groups = _dedupe(rows)
    assert len(groups) == 1
    key, parties = next(iter(groups.items()))
    li = _to_listing("counties_nc.wnc_rod_foreclosure_starts", "haywood", "NC", key, parties)
    assert li is not None
    assert "SMITH JOHN" in li.defendant
    assert "SMITH JANE" in li.defendant
    assert li.listing_type == ListingType.LIS_PENDENS


def test_dedupe_merges_the_same_instrument_fetched_across_two_entity_batches():
    """bulk_by_date() walks the party index entity-by-entity, so the SAME
    instrument's rows can arrive in different response bodies. _dedupe() must
    still fold them into one group keyed by (date, book, type)."""
    batch1 = [_party("09/11/2026", "RB 1161 815", "S/T", "GRANTOR", "SMITH JOHN", "substitution_of_trustee")]
    batch2 = [_party("09/11/2026", "RB 1161 815", "S/T", "GRANTOR", "SMITH JANE", "substitution_of_trustee")]
    groups = _dedupe(batch1 + batch2)
    assert len(groups) == 1
    parties = next(iter(groups.values()))
    names = {p["party"] for p in parties}
    assert names == {"SMITH JOHN", "SMITH JANE"}


def test_image_key_is_wired_into_raw_with_a_session_caveat():
    """The 'Image?' column's view_image.php key is session-scoped (confirmed
    live) so it must never be emitted as a plain document_url a later,
    different-session OCR pass would silently fail against -- it should land
    in raw with an explicit note instead."""
    rows = [
        _party("09/11/2026", "RB 1161 815", "S/INS", "GRANTOR", "ARUNDEL ANNE",
               None, image_key="1dcca814cdcff1363cbf5bee602dce00", image_type="tif"),
    ]
    groups = _dedupe(rows)
    key, parties = next(iter(groups.items()))
    # S/INS isn't a recognized kind, so stub a recognized one directly for the
    # listing-type gate while keeping the image-bearing party row.
    parties[0]["kind"] = "substitution_of_trustee"
    li = _to_listing("counties_nc.wnc_rod_foreclosure_starts", "haywood", "NC", key, parties)
    assert li is not None
    wnc = li.raw["wnc_rod"]
    assert wnc["image_key"] == "1dcca814cdcff1363cbf5bee602dce00"
    assert wnc["image_type"] == "tif"
    assert "view_image.php?key=1dcca814cdcff1363cbf5bee602dce00&type=tif" == wnc["image_url_path"]
    assert "session" in wnc["image_note"].lower()


def test_no_image_key_omits_image_fields_entirely():
    rows = [_party("09/11/2026", "RB 1 1", "S/T", "GRANTOR", "DOE JANE", "substitution_of_trustee")]
    groups = _dedupe(rows)
    key, parties = next(iter(groups.items()))
    li = _to_listing("counties_nc.wnc_rod_foreclosure_starts", "haywood", "NC", key, parties)
    wnc = li.raw["wnc_rod"]
    assert "image_key" not in wnc
    assert "image_url_path" not in wnc


# --------------------------------------------------------------------------- event-loop safety
#
# enrichment_rod_lookup.bulk_by_date() is entirely synchronous (curl_cffi
# Session, time.sleep throttle) and fetch() used to call it with zero `await`
# points in the coroutine -- live-confirmed 2026-10-01: asyncio.wait_for on a
# direct fetch() call could not interrupt it even at 3x the intended bound,
# the same event-loop-freezing bug zombie_properties.py's own test file
# (test_zombie_properties_event_loop.py) documents and fixes. Mirrors that
# file's heartbeat-race pattern.

@pytest.mark.asyncio
async def test_fetch_does_not_block_the_event_loop():
    def _slow_bulk_by_date(county, state, a, b):
        time.sleep(0.3)  # simulates real synchronous network+throttle work
        return []

    heartbeats = {"n": 0}

    async def _heartbeat():
        while True:
            await asyncio.sleep(0.01)
            heartbeats["n"] += 1

    with patch(
        "foreclosure_scraper.scrapers.counties_nc.wnc_rod_foreclosure_starts.bulk_by_date",
        side_effect=_slow_bulk_by_date,
    ):
        hb_task = asyncio.create_task(_heartbeat())
        await WNCRodForeclosureStarts().fetch()
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    assert heartbeats["n"] > 3, (
        f"only {heartbeats['n']} heartbeats ticked while fetch() ran -- "
        "the event loop was blocked"
    )


def test_institution_only_instrument_is_dropped():
    rows = [
        _party("09/11/2026", "RB 1 1", "S/T", "GRANTOR", "ACME BANK NA", "substitution_of_trustee"),
        _party("09/11/2026", "RB 1 1", "S/T", "GRANTEE", "DOE TRUSTEE LLC", "substitution_of_trustee"),
    ]
    groups = _dedupe(rows)
    key, parties = next(iter(groups.items()))
    assert _to_listing("counties_nc.wnc_rod_foreclosure_starts", "haywood", "NC", key, parties) is None


# --------------------------------------------------------------------------- timeout salvage
# 2026-10-08 gated run: Clay and Haywood finished (Haywood had substitutions of trustee), then
# Yancey ran past the 900 s soft timeout. The leads lived only in _fetch_sync's local list, so
# safe_run had nothing to salvage and the run published 0. Each county's leads are now banked
# in self.partial as soon as that county finishes.

@pytest.mark.asyncio
async def test_a_timeout_in_a_later_county_still_ships_the_finished_counties(monkeypatch):
    import threading
    release = threading.Event()

    def _bulk(county, state, a, b):
        if county == "haywood":
            return [
                _party("10/01/2026", "RB 9 9", "S/T", "GRANTOR", "DOE JOHN", "substitution_of_trustee"),
                _party("10/01/2026", "RB 9 9", "S/T", "GRANTEE", "ACME BANK NA", "substitution_of_trustee"),
            ]
        if county == "yancey":
            release.wait(5)      # the slow county: still running when the timeout fires
        return []

    s = WNCRodForeclosureStarts()
    monkeypatch.setattr(s, "timeout_s", 0.5)
    with patch(
        "foreclosure_scraper.scrapers.counties_nc.wnc_rod_foreclosure_starts.bulk_by_date",
        side_effect=_bulk,
    ):
        out = await s.safe_run()
        release.set()
    assert [li.defendant for li in out] == ["DOE JOHN"]
    assert s.last_outcome != "TIMEOUT"

"""Buncombe septic-permit distress signal.

Drives the real classify -> index -> summarize -> enrich path against a saved
slice of the live layer (tests/fixtures/buncombe_septic_cases.json). Every
fixture record is a REAL Buncombe permit row, so the supersession, sentinel-date
and unjoinable-parcel cases below are the ones the county actually publishes.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import datetime, timezone

import pytest

from foreclosure_scraper import enrichment_septic_status as septic
from foreclosure_scraper.enrichment_septic_status import (
    ADVERSE_STATUSES, OPEN_STATUSES, STALE_DAYS,
    classify_status, index_by_parcel, summarize_parcel,
    enrich_with_septic_status,
)
from foreclosure_scraper.models import Listing, ListingType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "buncombe_septic_cases.json"
#: Frozen "now" so staleness assertions never rot.
NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)

# Real parcels in the fixture, by the role each one plays.
P_CLEAN = "0628228822"            # single Finaled CA, nothing else
P_REPAIR = "9763526029"           # Finaled SEPTIC REPAIR — history, not distress
P_OPEN_1995 = "9633144146"        # 'Received', 1900-01-01 sentinel date, SEP1995 case
P_SUPERSEDED = "8696855845"       # Permit Suspended (2015) then S19A - OP Issued (2015)
P_ADVERSE = "9676765715"          # Finaled (2004) then Cancelled (2005)


def _features():
    return json.loads(FIXTURE.read_text())["features"]


def _ms(y, m=1, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------- classify ---
def test_every_adverse_status_classifies_adverse():
    for s in ADVERSE_STATUSES:
        assert classify_status(s) == "adverse", s


def test_every_open_status_classifies_open():
    for s in OPEN_STATUSES:
        assert classify_status(s) == "open", s


@pytest.mark.parametrize("status", [
    "OP Issued", "S19A - OP Issued", "W10 - COC Issued", "COCIP Issued",
    "Authorization to Operate", "S-31 Authorization to Operate", "Finaled",
    "S-30A NOI Complete", "S13 - Ex System Approved", "S12 - EX System Approved MHP",
])
def test_favourable_statuses(status):
    assert classify_status(status) == "favourable"


def test_explicit_membership_beats_the_substring_markers():
    """'Completeness Review Approved' contains 'approved' but no permit has been
    issued — it is an OPEN file, and 3+ years of it is stalled. If the substring
    markers ran first, 376 unresolved county files would read as approved."""
    assert "Completeness Review Approved" in OPEN_STATUSES
    assert classify_status("Completeness Review Approved") == "open"


def test_blank_and_unknown_status():
    assert classify_status(None) == "unknown"
    assert classify_status("   ") == "unknown"
    assert classify_status("Some Future County Workflow Step") == "unknown"


# ------------------------------------------------------------------ index ---
def test_index_drops_rows_without_a_parcel():
    feats = _features()
    assert any(not (f["attributes"].get("ParcelNum") or "").strip() for f in feats), \
        "fixture must contain an unjoinable row"
    idx = index_by_parcel(feats)
    assert all(p for p in idx)
    assert sum(len(v) for v in idx.values()) == len(feats) - 1


def test_index_collapses_the_zero_padded_pin():
    # The layer stores the 10-digit PIN padded to 15; the shared normalizer must
    # collapse it so it joins a board parcel_id.
    idx = index_by_parcel(_features())
    assert P_ADVERSE in idx
    assert all(len(p) <= 15 for p in idx)


# -------------------------------------------------------------- summarize ---
def test_unsuperseded_adverse_is_the_hard_signal():
    idx = index_by_parcel(_features())
    s = summarize_parcel(idx[P_ADVERSE], now=NOW)
    assert s["latest_status"] == "Cancelled"
    assert s["latest_status_class"] == "adverse"
    assert s["septic_adverse"] is True
    assert s["land_distress"] is True
    assert s["cases"] == 2


def test_a_later_favourable_record_clears_an_earlier_adverse_one():
    """The whole point: a 2015 'Permit Suspended' followed by a 2015
    'S19A - OP Issued' is a permit that got granted, NOT distress."""
    idx = index_by_parcel(_features())
    s = summarize_parcel(idx[P_SUPERSEDED], now=NOW)
    assert s["adverse_records_ever"] == 1        # the history is still recorded
    assert s["latest_status_class"] == "favourable"
    assert s["septic_adverse"] is False
    assert s["land_distress"] is False


def test_repair_history_is_recorded_but_never_marks_distress():
    idx = index_by_parcel(_features())
    s = summarize_parcel(idx[P_REPAIR], now=NOW)
    assert s["septic_repair_history"] is True
    assert s["repair_records"] == 1
    assert s["septic_adverse"] is False and s["septic_stalled"] is False
    assert s["land_distress"] is False


def test_clean_parcel_raises_no_flag():
    idx = index_by_parcel(_features())
    s = summarize_parcel(idx[P_CLEAN], now=NOW)
    assert (s["septic_adverse"], s["septic_stalled"], s["septic_repair_history"]) \
        == (False, False, False)
    assert s["land_distress"] is False


def test_sentinel_dated_open_case_falls_back_to_the_case_year():
    """The county's legacy null date is 1900-01-01, which is rejected as a real
    date. An open file it cannot date must not read as a live application."""
    idx = index_by_parcel(_features())
    recs = idx[P_OPEN_1995]
    assert recs[0]["CaseNumber"].startswith("SEP1995")
    s = summarize_parcel(recs, now=NOW)
    assert s["latest_status_class"] == "open"
    assert s["days_since_last_action"] is None      # honestly undated
    assert s["septic_stalled"] is True              # ...but plainly abandoned
    assert s["land_distress"] is True


def test_fresh_open_application_is_not_distress():
    rec = [{"CaseNumber": "SEP2026-00001", "ParcelNum": "961879632600000",
            "LatestStatus": "Received", "LatestStatusDate": _ms(2026, 7, 1),
            "ReceivedDate": _ms(2026, 7, 1), "SubType": "IMPROVEMENT PERMIT"}]
    s = summarize_parcel(rec, now=NOW)
    assert s["latest_status_class"] == "open"
    assert s["septic_stalled"] is False
    assert s["land_distress"] is False


def test_open_application_crosses_the_stale_threshold():
    base = {"CaseNumber": "SEP2020-00001", "ParcelNum": "961879632600000",
            "LatestStatus": "Received", "SubType": "IMPROVEMENT PERMIT"}
    just_inside = dict(base, LatestStatusDate=_ms(2023, 8, 6))   # < 3y before NOW
    just_outside = dict(base, LatestStatusDate=_ms(2023, 8, 5))  # exactly 3y
    assert (NOW - datetime(2023, 8, 6, tzinfo=timezone.utc)).days < STALE_DAYS
    assert (NOW - datetime(2023, 8, 5, tzinfo=timezone.utc)).days == STALE_DAYS
    assert summarize_parcel([just_inside], now=NOW)["septic_stalled"] is False
    assert summarize_parcel([just_outside], now=NOW)["septic_stalled"] is True


def test_undated_record_never_becomes_the_parcels_latest_state():
    """An undated row must not outrank a real dated one — otherwise a sentinel
    1900 'Received' would override a 2024 'OP Issued' and invent distress."""
    recs = [
        {"CaseNumber": "SEP2024-00002", "ParcelNum": "961879632600000",
         "LatestStatus": "OP Issued", "LatestStatusDate": _ms(2024, 5, 1)},
        {"CaseNumber": "SEP1998-00003", "ParcelNum": "961879632600000",
         "LatestStatus": "Received", "LatestStatusDate": 0, "ReceivedDate": 0},
    ]
    s = summarize_parcel(recs, now=NOW)
    assert s["latest_status"] == "OP Issued"
    assert s["land_distress"] is False


def test_summarize_empty_is_none():
    assert summarize_parcel([]) is None


def test_naive_now_is_accepted():
    idx = index_by_parcel(_features())
    s = summarize_parcel(idx[P_ADVERSE], now=datetime(2026, 8, 4))
    assert s["septic_adverse"] is True


# ----------------------------------------------------------------- enrich ---
def _listing(parcel, county="Buncombe", state="NC"):
    return Listing(source="x", source_url="http://x", listing_type=ListingType.UNKNOWN,
                   state=state, county=county, parcel_id=parcel)


def _run(listings, monkeypatch):
    async def fake_fetch(_http):
        return _features()

    class _NullClient:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(septic, "fetch_septic_records", fake_fetch)
    monkeypatch.setattr(septic, "client", lambda **kw: _NullClient())
    return asyncio.run(enrich_with_septic_status(listings))


def test_enrich_tags_only_matching_buncombe_parcels(monkeypatch):
    hit = _listing("9676765715")            # adverse
    padded = _listing("967676571500000")    # same parcel, padded form
    miss = _listing("0000000001")
    stats = _run([hit, padded, miss], monkeypatch)
    assert stats["matched"] == 2 and stats["adverse"] == 2
    assert hit.raw["septic"]["septic_adverse"] is True
    assert hit.raw["land_distress"] is True
    assert padded.raw["septic"]["latest_case"] == hit.raw["septic"]["latest_case"]
    assert "septic" not in (miss.raw or {})


def test_enrich_ignores_other_counties_and_states(monkeypatch):
    other = _listing("9676765715", county="Henderson")
    sc = _listing("9676765715", county="Buncombe", state="SC")
    assert _run([other, sc], monkeypatch) is None
    assert "septic" not in (other.raw or {})


def test_enrich_ignores_listings_without_a_parcel(monkeypatch):
    li = _listing(None)
    assert _run([li], monkeypatch) is None


def test_enrich_does_not_set_land_distress_for_repair_history(monkeypatch):
    li = _listing("9763526029")
    stats = _run([li], monkeypatch)
    assert stats["repair_history"] == 1 and stats["adverse"] == 0
    assert li.raw["septic"]["septic_repair_history"] is True
    assert "land_distress" not in li.raw


def test_kill_switch(monkeypatch):
    monkeypatch.setenv(septic.ENV_OFF, "1")
    li = _listing("9676765715")
    assert asyncio.run(enrich_with_septic_status([li])) is None
    assert "septic" not in (li.raw or {})


def test_out_fields_is_enumerated_never_star():
    assert "*" not in septic.OUT_FIELDS
    for f in ("CaseNumber", "ParcelNum", "OwnerName", "LatestStatus", "SubType"):
        assert f in septic.OUT_FIELDS
    # Nothing personal beyond the property/permit record.
    low = septic.OUT_FIELDS.lower()
    for banned in ("ssn", "dob", "birth", "phone", "email", "license", "driver"):
        assert banned not in low

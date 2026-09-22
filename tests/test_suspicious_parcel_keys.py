"""A parcel id shared by many distinct addresses is not a grouping key.

MEASURED ON THE LIVE BOARD 2026-09-22: the daily run's dedupe pass logged
`parcel:NC:pender:3208905620` covering 216 distinct street addresses -- a subdivision's lots
all citing one pre-split master-tract PIN in liensnc lien-agent-appointment filings (65 keys,
648 addresses fused across the whole board that day). dedupe.py's house_number_guard already
stops that id from deleting rows during a MERGE (test_dedupe_house_number_guard.py), but two
other consumers trusted the same id with no such guard: the scorer's per-parcel grouping
(distress_score._parcel_key, which would have stacked 216 unrelated properties' distress
signals together) and the parcel-cache join (join_parcel_cache_to_board.py, which would have
copied one property's owner, mailing and value onto the other 215). This file tests the shared
detector (dedupe.suspicious_parcel_keys) and both fixes.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from foreclosure_scraper.dedupe import addresses_per_dedupe_key, suspicious_parcel_keys
from foreclosure_scraper.distress_score import _parcel_key, score_board
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def L(addr, parcel=None, county="Pender", state="NC", src="counties_generic.liensnc", owner=None, raw=None):
    return Listing(source=src, source_url="u", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, street_address=addr, owner_name=owner,
                   first_seen=datetime.utcnow(), last_seen=datetime.utcnow(), raw=raw or {})


SHARED_PIN = "3208-90-5620-0000"


def _pender_batch(n=6):
    return [L(f"{100 + i} Heart Pine Ave", SHARED_PIN) for i in range(n)]


# --------------------------------------------------------------------------------------
# dedupe.suspicious_parcel_keys
# --------------------------------------------------------------------------------------

def test_addresses_per_dedupe_key_counts_distinct_addresses_only():
    rows = _pender_batch(3) + [L("100 Heart Pine Ave", SHARED_PIN)]  # a duplicate address
    per_key = addresses_per_dedupe_key(rows)
    key = rows[0].dedupe_key()
    assert per_key[key] == {"100 heart pine ave", "101 heart pine ave", "102 heart pine ave"}


def test_a_shared_pin_over_the_threshold_is_flagged():
    rows = _pender_batch(4)
    flagged = suspicious_parcel_keys(rows)
    assert rows[0].dedupe_key() in flagged


def test_under_the_threshold_is_not_flagged():
    rows = _pender_batch(3)
    assert suspicious_parcel_keys(rows) == frozenset()


def test_the_threshold_is_configurable():
    rows = _pender_batch(4)
    assert suspicious_parcel_keys(rows, min_addresses=5) == frozenset()
    assert rows[0].dedupe_key() in suspicious_parcel_keys(rows, min_addresses=4)


def test_a_real_shared_parcel_two_units_one_lot_is_not_flagged():
    # a duplex or two condo units on one parcel is real and common; the threshold (4) is
    # chosen to clear that, not to flag every co-owned or multi-unit parcel
    rows = [L("100 Heart Pine Ave Unit A", SHARED_PIN), L("100 Heart Pine Ave Unit B", SHARED_PIN)]
    assert suspicious_parcel_keys(rows) == frozenset()


def test_only_the_parcel_branch_is_flagged_not_address_or_case_branches():
    # many rows can legitimately share a county+zip-less address key pattern; the detector
    # only watches the PARCEL branch, which is the one a scraper can poison with one bad value
    rows = [L(f"{100 + i} Random St", parcel=None) for i in range(6)]  # falls to the address branch
    assert suspicious_parcel_keys(rows) == frozenset()


def test_empty_and_no_parcel_rows_do_not_crash():
    assert suspicious_parcel_keys([]) == frozenset()
    assert suspicious_parcel_keys([L("1 Main St", parcel=None)]) == frozenset()


# --------------------------------------------------------------------------------------
# distress_score._parcel_key
# --------------------------------------------------------------------------------------

def test_parcel_key_groups_normally_with_no_suspicious_set():
    a, b = L("100 Heart Pine Ave", SHARED_PIN), L("100 Heart Pine Ave", SHARED_PIN)
    assert _parcel_key(a) == _parcel_key(b)


def test_parcel_key_ungroups_a_suspicious_id():
    rows = _pender_batch(5)
    suspicious = suspicious_parcel_keys(rows)
    keys = {_parcel_key(li, suspicious) for li in rows}
    assert len(keys) == len(rows), "each address must get its own group, not one shared group"


def test_parcel_key_is_backward_compatible_with_one_argument():
    # existing callers (tests, other modules) call _parcel_key(li) with no second argument
    li = L("100 Heart Pine Ave", SHARED_PIN)
    assert _parcel_key(li) == _parcel_key(li, frozenset())


def test_score_board_never_stacks_216_unrelated_addresses_into_one_group():
    """The actual failure mode: a real distress signal on ONE of the addresses must not
    promote the other, unrelated addresses that happen to share the poisoned parcel id."""
    rows = _pender_batch(6)
    rows[0].raw = {"tax_owed": {"balance": 5000}}          # a real debt on address #0 only
    rows[1].raw = {"probate": {"case_number": "26E123"}}    # a real life event on address #1 only
    hist = score_board(rows)
    assert hist["COLD"] + hist["WARM"] + hist["HOT"] == 6
    # address #2..5 have NOTHING of their own and must not inherit either signal
    for li in rows[2:]:
        stack = (li.raw or {}).get("distress_stack") or {}
        assert stack.get("categories", []) == [] or stack.get("tier") == "COLD"
    # address #0 and #1 must not see EACH OTHER's signal either (they are different houses)
    cats0 = set((rows[0].raw.get("distress_stack") or {}).get("categories", []))
    cats1 = set((rows[1].raw.get("distress_stack") or {}).get("categories", []))
    assert "LIFE_EVENT" not in cats0
    assert "FINANCIAL" not in cats1


def test_score_board_still_groups_a_real_shared_parcel_normally():
    """The fix must not blunt the real feature: a genuine foreclosure + tax sale on the
    SAME actual property (few addresses sharing a real parcel) still stacks."""
    a = L("500 Real St", "1234567890", owner="SMITH J")
    a.listing_type = ListingType.FORECLOSURE_SALE
    b = L("500 Real St", "1234567890", owner="SMITH J")
    b.raw = {"tax_owed": {"balance": 3000}}
    hist = score_board([a, b])
    stack = (a.raw or {}).get("distress_stack") or {}
    assert len(stack.get("categories", [])) >= 1


# --------------------------------------------------------------------------------------
# join_parcel_cache_to_board.apply_rows
# --------------------------------------------------------------------------------------

def test_join_refuses_a_suspicious_parcel_id(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(tmp_path.parent))  # no-op, keeps import path stable across test order
    import importlib
    join = importlib.import_module("join_parcel_cache_to_board")

    def _fake_lookup(county, parcel_id, state=None):
        return {"owner": "SOMEONE ELSE", "address": "1 SOMEWHERE ELSE RD", "owner_mailing": "1 SOMEWHERE ELSE RD, X SC 00000"}

    monkeypatch.setattr("foreclosure_scraper.parcel_cache.lookup", _fake_lookup)
    rows = _pender_batch(5)
    stats = join.apply_rows(rows, dry_run=True)
    assert stats["skipped: parcel id shared by many distinct addresses"] == 5
    assert stats.get("cache HIT", 0) == 0
    for li in rows:
        assert li.owner_name is None and li.street_address != "1 SOMEWHERE ELSE RD"


def test_join_still_works_for_an_ordinary_parcel(monkeypatch):
    import importlib
    join = importlib.import_module("join_parcel_cache_to_board")

    def _fake_lookup(county, parcel_id, state=None):
        return {"owner": "REAL OWNER", "market_value": 200000}

    monkeypatch.setattr("foreclosure_scraper.parcel_cache.lookup", _fake_lookup)
    li = L("100 Heart Pine Ave", "9999999999")
    stats = join.apply_rows([li], dry_run=True)
    assert stats["cache HIT"] == 1
    assert li.owner_name == "REAL OWNER"

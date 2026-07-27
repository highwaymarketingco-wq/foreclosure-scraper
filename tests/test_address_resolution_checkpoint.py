"""Checkpoint / routing logic for the standalone address resolver.

The whole point of scripts/resolve_addresses.py is that it can be killed at any
moment and the next run picks up where it left off. That property lives entirely
in these pure functions, so they are tested without touching the network, the
board, or a county GIS.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from resolve_addresses import (  # noqa: E402
    LANES,
    allocate,
    bucket_targets,
    classify_outcome,
    is_placeholder_point,
    lane_degraded,
    lead_key,
    load_checkpoint,
    placeholder_coords,
    route_lane,
    save_checkpoint,
    should_bank,
    should_skip,
    stripe_by_county,
)

from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

NOW = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)


def _li(url="u1", **kw) -> Listing:
    base = dict(
        source="counties_nc.nc_ecourts_lis_pendens",
        source_url=url,
        listing_type=ListingType.LIS_PENDENS,
        state="NC",
        county="Buncombe",
    )
    base.update(kw)
    return Listing(**base)


# --- lead_key ---------------------------------------------------------------

def test_lead_key_stable_across_everything_the_lanes_write():
    """Resolving a lead must not change its key, or the next run would treat it
    as brand new and re-attempt it forever. The lanes write street_address /
    city / zip_code (verified: none of them assigns li.owner_name), so those
    are the fields the key has to survive."""
    li = _li(url="https://x/case/1", parcel_id="9648-12-3456")
    before = lead_key(li)
    li.street_address = "123 Main St"
    li.city = "Asheville"
    li.zip_code = "28803"
    assert lead_key(li) == before


def test_gaining_a_parcel_id_rekeys_on_purpose():
    """The geo lane DOES write parcel_id. Re-keying costs at most one extra
    attempt on a lead that now has a much better handle to resolve on — the
    opposite trade (a loose key) silently strands thousands of leads."""
    li = _li(url="https://x/case/1", latitude=35.5, longitude=-82.5)
    before = lead_key(li)
    li.parcel_id = "9648-12-3456"
    assert lead_key(li) != before


def test_lead_key_separates_leads_sharing_one_source_url():
    """THE collision that matters: bulk sources publish one PDF/portal URL for
    thousands of leads (2,227 McDowell tax leads share a single URL). Keying on
    source_url alone would checkpoint all of them off the first attempt."""
    url = "https://mcdowellnc.gov/ADVERTISEMENT-LIST-FINAL-2025.pdf"
    a = _li(url=url, county="McDowell", parcel_id="079700586730", defendant="LND TST")
    b = _li(url=url, county="McDowell", parcel_id="172800898126A", defendant="OLD FORT LLC")
    c = _li(url=url, county="McDowell", parcel_id="077000420045", defendant="7F RENOVATIONS")
    assert len({lead_key(a), lead_key(b), lead_key(c)}) == 3


def test_lead_key_separates_same_url_same_party_different_description():
    url = "https://bcpwa.ncptscloud.com/"
    a = _li(url=url, defendant="MOORE, BILLY JOE", description="bill 2024")
    b = _li(url=url, defendant="MOORE, BILLY JOE", description="bill 2025")
    assert lead_key(a) != lead_key(b)


def test_lead_key_is_deterministic_across_calls():
    li = _li(url="https://x/1", parcel_id="P1", defendant="SMITH")
    assert lead_key(li) == lead_key(li)


# --- routing ----------------------------------------------------------------

def test_route_lane_prefers_parcel_then_geo_then_owner():
    assert route_lane(_li(parcel_id="P1", latitude=35.5, longitude=-82.5,
                          defendant="SMITH JOHN")) == "parcel"
    assert route_lane(_li(latitude=35.5, longitude=-82.5, defendant="SMITH JOHN")) == "geo"
    assert route_lane(_li(defendant="SMITH JOHN")) == "owner"


def test_route_lane_none_when_address_present_or_nothing_to_go_on():
    assert route_lane(_li(street_address="1 Main St", parcel_id="P1")) is None
    assert route_lane(_li(county=None)) is None


def test_owner_name_only_leads_are_not_routed_to_the_owner_lane():
    """Both owner enrichers select on li.defendant, so an owner_name-only lead
    would be admitted and then silently skipped — wasting a batch slot and
    banking a failure for work never done."""
    assert route_lane(_li(owner_name="Woodridge Apartments")) is None
    assert route_lane(_li(defendant="SMITH JOHN", owner_name="Woodridge")) == "owner"


# --- should_skip ------------------------------------------------------------

def test_resolved_entries_are_skipped_forever():
    old = {"status": "resolved", "ts": (NOW - timedelta(days=900)).isoformat()}
    assert should_skip(old, NOW, retry_after_days=14) is True


def test_recent_failure_skipped_but_stale_failure_retried():
    recent = {"status": "failed", "ts": (NOW - timedelta(days=3)).isoformat()}
    stale = {"status": "failed", "ts": (NOW - timedelta(days=30)).isoformat()}
    assert should_skip(recent, NOW, retry_after_days=14) is True
    assert should_skip(stale, NOW, retry_after_days=14) is False


def test_unknown_or_corrupt_entries_fail_open_to_retry():
    assert should_skip(None, NOW, 14) is False
    assert should_skip({}, NOW, 14) is False
    assert should_skip({"status": "failed", "ts": "not-a-date"}, NOW, 14) is False
    assert should_skip({"status": "failed"}, NOW, 14) is False


# --- checkpoint round-trip --------------------------------------------------

def test_checkpoint_round_trips(tmp_path):
    p = tmp_path / "sub" / "address_resolution.json"
    cp = load_checkpoint(p)  # missing file
    assert cp["entries"] == {}
    cp["entries"]["u:https://x/1"] = {"status": "resolved", "address": "123 Main St",
                                      "ts": NOW.isoformat()}
    save_checkpoint(p, cp)
    again = load_checkpoint(p)
    assert again["entries"]["u:https://x/1"]["address"] == "123 Main St"
    assert again["updated"]


def test_corrupt_checkpoint_does_not_raise(tmp_path):
    p = tmp_path / "address_resolution.json"
    p.write_text("{ this is not json")
    assert load_checkpoint(p)["entries"] == {}
    p.write_text(json.dumps(["wrong", "shape"]))
    assert load_checkpoint(p)["entries"] == {}


def test_save_is_atomic_leaves_no_tmp(tmp_path):
    p = tmp_path / "cp.json"
    save_checkpoint(p, {"entries": {}})
    assert p.exists()
    assert not list(tmp_path.glob("*.tmp"))


# --- placeholder coordinates ------------------------------------------------

def test_placeholder_coords_flags_shared_points_only():
    shared = [_li(url=f"s{i}", latitude=35.6, longitude=-82.55) for i in range(4)]
    unique = _li(url="uniq", latitude=34.1234, longitude=-81.4321)
    coords = placeholder_coords(shared + [unique])
    assert is_placeholder_point(shared[0], coords) is True
    assert is_placeholder_point(unique, coords) is False


def test_placeholder_coords_ignores_missing_coords():
    assert placeholder_coords([_li(url="a"), _li(url="b"), _li(url="c")]) == set()


# --- bucketing + allocation -------------------------------------------------

def _board():
    parcels = [_li(url=f"p{i}", parcel_id=f"PID{i}") for i in range(5)]
    # geo leads must come from a source whose lat/lng IS the property
    geos = [Listing(source="counties_nc.asheville_helene", source_url=f"g{i}",
                    listing_type=ListingType.DISTRESSED, state="NC", county="Buncombe",
                    latitude=35.0 + i / 100, longitude=-82.0 - i / 100) for i in range(5)]
    owners = [_li(url=f"o{i}", defendant=f"SMITH JOHN {i}") for i in range(5)]
    return parcels + geos + owners


def test_bucket_targets_routes_all_three_lanes():
    b = bucket_targets(_board(), {"entries": {}}, NOW)
    assert [len(b[k]) for k in LANES] == [5, 5, 5]


def test_bucket_targets_drops_checkpointed_leads():
    board = _board()
    cp = {"entries": {
        lead_key(board[0]): {"status": "resolved", "ts": NOW.isoformat()},
        lead_key(board[1]): {"status": "failed", "ts": (NOW - timedelta(days=1)).isoformat()},
        lead_key(board[2]): {"status": "failed", "ts": (NOW - timedelta(days=99)).isoformat()},
    }}
    b = bucket_targets(board, cp, NOW, retry_after_days=14)
    assert len(b["parcel"]) == 3  # 5 - resolved - recent failure; stale failure retried
    assert lead_key(board[2]) in {lead_key(li) for li in b["parcel"]}


def test_resumability_second_pass_picks_up_new_leads_only():
    """The core promise: run, checkpoint what was touched, run again and get
    only the untouched remainder — never a restart from zero."""
    board = _board()
    cp = {"entries": {}}
    first = allocate(bucket_targets(board, cp, NOW), 6)
    flat1 = [li for lane in LANES for li in first[lane]]
    for li in flat1:
        cp["entries"][lead_key(li)] = {"status": "resolved", "ts": NOW.isoformat()}

    second = allocate(bucket_targets(board, cp, NOW), 6)
    flat2 = [li for lane in LANES for li in second[lane]]
    assert len(flat2) == 6
    assert not ({lead_key(li) for li in flat1} & {lead_key(li) for li in flat2})

    # Everything eventually gets attempted; nothing is stranded.
    for li in flat2:
        cp["entries"][lead_key(li)] = {"status": "resolved", "ts": NOW.isoformat()}
    remaining = bucket_targets(board, cp, NOW)
    assert sum(len(remaining[k]) for k in LANES) == 3


def test_bucket_targets_excludes_untrusted_geo_points():
    """A court-filing coordinate can be a party's mailing address, and a shared
    coordinate is a county centroid. Neither may be point-snapped to a parcel."""
    court_geo = _li(url="cg", latitude=35.5, longitude=-82.5)  # lis_pendens source
    shared = [Listing(source="counties_nc.asheville_helene", source_url=f"sh{i}",
                      listing_type=ListingType.DISTRESSED, state="NC", county="Buncombe",
                      latitude=35.6, longitude=-82.6) for i in range(3)]
    board = [court_geo] + shared
    b = bucket_targets(board, {"entries": {}}, NOW, ph_coords=placeholder_coords(board))
    assert b["geo"] == []


def test_bucket_targets_honours_only_path():
    b = bucket_targets(_board(), {"entries": {}}, NOW, only_path="owner")
    assert len(b["owner"]) == 5
    assert b["parcel"] == [] and b["geo"] == []


def test_allocate_splits_round_robin_across_lanes():
    b = bucket_targets(_board(), {"entries": {}}, NOW)
    got = allocate(b, 6)
    assert [len(got[k]) for k in LANES] == [2, 2, 2]


def test_allocate_drains_remaining_lanes_when_one_runs_dry():
    b = {"parcel": [_li(url="p1", parcel_id="A")], "geo": [], "owner": []}
    b["owner"] = [_li(url=f"o{i}", defendant=f"X {i}") for i in range(5)]
    got = allocate(b, 4)
    assert len(got["parcel"]) == 1
    assert len(got["owner"]) == 3


def test_allocate_never_exceeds_limit_or_repeats():
    b = bucket_targets(_board(), {"entries": {}}, NOW)
    got = allocate(b, 100)
    flat = [li for lane in LANES for li in got[lane]]
    assert len(flat) == 15
    assert len({id(li) for li in flat}) == 15


def test_allocate_zero_limit_is_a_noop():
    b = bucket_targets(_board(), {"entries": {}}, NOW)
    assert allocate(b, 0) == {lane: [] for lane in LANES}


# --- county striping --------------------------------------------------------

def test_stripe_by_county_spreads_a_dominant_county():
    """McDowell is 2,247 of the 6,374 parcel leads. Unstriped, every batch for
    weeks is McDowell — so a county with no situs field eats the whole budget."""
    heavy = [_li(url=f"m{i}", county="McDowell", parcel_id=f"M{i}") for i in range(10)]
    light = [_li(url=f"o{i}", county="Oconee", state="SC", parcel_id=f"O{i}") for i in range(2)]
    out = stripe_by_county(heavy + light)
    assert len(out) == 12
    assert len({(li.county) for li in out[:4]}) == 2   # both counties in the first 4


def test_stripe_by_county_is_deterministic_and_lossless():
    pool = ([_li(url=f"a{i}", county="Union", state="SC", parcel_id=f"A{i}") for i in range(4)]
            + [_li(url=f"b{i}", county="Hyde", parcel_id=f"B{i}") for i in range(3)])
    first = [lead_key(li) for li in stripe_by_county(pool)]
    second = [lead_key(li) for li in stripe_by_county(pool)]
    assert first == second
    assert sorted(first) == sorted(lead_key(li) for li in pool)


def test_stripe_by_county_handles_empty_and_single_county():
    assert stripe_by_county([]) == []
    one = [_li(url=f"s{i}", county="Hyde", parcel_id=f"S{i}") for i in range(3)]
    assert [lead_key(li) for li in stripe_by_county(one)] == [lead_key(li) for li in one]


# --- degraded lanes must not bank failures ----------------------------------

def test_lane_degraded_detects_budget_timeout_and_errors():
    assert lane_degraded({"situs": "BUDGET_TIMEOUT", "situs_secs": 15.0}) is True
    assert lane_degraded({"owner_v2": "ERROR: ConnectError: boom"}) is True
    assert lane_degraded({"targets": 9, "skipped_no_budget": ["parcel_lookup"]}) is True


def test_lane_degraded_false_for_a_clean_run():
    clean = {"targets": 20, "situs": {"queried": 18, "wrote_address": 5},
             "situs_secs": 12.9, "parcel_lookup": "ok"}
    assert lane_degraded(clean) is False
    assert lane_degraded({}) is False
    assert lane_degraded(None) is False


def test_lane_degraded_ignores_a_zero_result_dict():
    """A lane that genuinely tried everything and resolved nothing is NOT
    degraded — those failures are real and should be checkpointed."""
    assert lane_degraded({"targets": 20, "parcel_from_geo": {"queried": 20, "resolved": 0}}) is False


# --- outcome classification -------------------------------------------------

def _before(li):
    return {"street_address": "", "city": "", "zip_code": "",
            "parcel_id": (li.parcel_id or ""), "owner_name": ""}


def test_real_address_counts_as_resolved():
    li = _li(parcel_id="P1")
    before = _before(li)
    li.street_address = "1234 Sweeten Creek Rd"
    li.city = "Asheville"
    status, gained, addr = classify_outcome(before, li)
    assert status == "resolved"
    assert addr == "1234 Sweeten Creek Rd"
    assert "city" in gained


def test_gis_padding_is_collapsed_on_a_newly_written_address():
    """County situs fields come back padded ('104   WHITLEY RD'), which breaks
    exact-match dedupe against other sources and reads badly in a mail-merge."""
    li = _li(parcel_id="P1")
    before = _before(li)
    li.street_address = "104   WHITLEY  RD"
    status, _gained, addr = classify_outcome(before, li)
    assert status == "resolved"
    assert addr == "104 WHITLEY RD"
    assert li.street_address == "104 WHITLEY RD"


def test_synthesized_non_address_is_reverted_not_counted():
    """parcel_lookup synthesizes 'Lis Pendens <case>' style strings when the GIS
    misses. Writing that hides the lead from every later resolver, so it must be
    rolled back rather than banked as a win."""
    li = _li(parcel_id="P1")
    before = _before(li)
    li.street_address = "Lis Pendens 24CV001234"
    status, _gained, _addr = classify_outcome(before, li)
    assert status == "junk"
    assert li.street_address is None


def test_no_change_is_failed_but_side_gains_are_recorded():
    li = _li(defendant="SMITH JOHN")
    before = _before(li)
    li.parcel_id = "9648-12-3456"      # matched a parcel, no situs on the layer
    status, gained, addr = classify_outcome(before, li)
    assert status == "failed"
    assert addr is None
    assert gained == ["parcel_id"]


def test_preexisting_address_is_not_double_counted():
    li = _li(street_address="9 Old St")
    before = {"street_address": "9 Old St", "city": "", "zip_code": "",
              "parcel_id": "", "owner_name": ""}
    status, _g, _a = classify_outcome(before, li)
    assert status == "failed"
    assert li.street_address == "9 Old St"   # untouched


# --- regression: dry-run must never bank a 'resolved' entry ------------------
# A dry-run finds the address in memory but does NOT write the board. Banking it
# as 'resolved' made should_skip() hide the lead forever while the board stayed
# address-less — silent, permanent data loss. Caught in review 2026-07-27 after
# it had already stranded 15 real leads.

def test_dryrun_never_banks_resolved():
    assert should_bank("resolved", write=True) is True
    assert should_bank("resolved", write=False) is False


def test_failures_bank_in_both_modes():
    for status in ("failed", "junk"):
        assert should_bank(status, write=True) is True
        assert should_bank(status, write=False) is True


def test_banked_resolved_is_skipped_forever_but_dryrun_resolved_is_not():
    """The two halves of the invariant, together: what dry-run refuses to bank is
    exactly what should_skip would have hidden forever."""
    now = datetime.now(timezone.utc)
    banked = {"status": "resolved", "ts": now.isoformat()}
    assert should_skip(banked, now, 14) is True      # a written resolve: skip forever
    assert should_bank("resolved", write=False) is False  # so dry-run must not create one

"""scripts/audit_checks/additions.py: each invariant catches the 10/8 defect it was written for, on
made-up rows (no real names, ids or addresses), and the static checks hold on the real repo."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from audit_checks import additions as A  # noqa: E402


def _by_name():
    return {c.name: c for c in A.make_checks()}


def _feed(check, rows):
    for r in rows:
        check.feed(r)
    return check.finish()


def test_every_check_has_the_interface_and_unique_names():
    cs = A.make_checks()
    names = [c.name for c in cs]
    assert len(names) == len(set(names))
    assert all(n.startswith("addition-") or n.startswith("additions-") for n in names)
    for c in cs:
        out = c.finish()
        assert set(out) == {"name", "checked", "violations", "max_violations", "ok", "detail"}


def test_static_checks_hold_on_the_repo():
    cs = _by_name()
    for n in ("additions-publish-shape", "additions-profile-flags", "additions-ledger-complete"):
        out = cs[n].finish()
        assert out["ok"], out["detail"]


def test_floor_only_judged_on_a_full_board(monkeypatch):
    monkeypatch.setattr(A, "FULL_BOARD_ROWS", 3)
    c = _by_name()["addition-src-horry-probate"]
    rows = [{"source": "counties_sc.horry_probate", "last_seen": "2026-10-08"}] + \
           [{"source": "x", "last_seen": "2026-10-08"}] * 3
    out = _feed(c, rows)
    assert not out["ok"] and "< floor" in out["detail"]


def test_fresh_floor_tells_a_run_from_carried_rows(monkeypatch):
    monkeypatch.setattr(A, "FULL_BOARD_ROWS", 1)
    c = _by_name()["addition-enr-generic-rod-platforms"]
    old = {"source": "x", "last_seen": "2026-10-08",
           "raw": {"rod": {"source": "generic_rod", "fetched_at": "2026-09-01T00:00:00"}}}
    out = _feed(c, [old] * 5)
    assert not out["ok"] and "fresh rows" in out["detail"]


def test_ceiling_catches_retail_homepath(monkeypatch):
    monkeypatch.setattr(A, "FULL_BOARD_ROWS", 1)
    out = _feed(_by_name()["addition-apr-homepath-reo-only"],
                [{"source": "national.homepath_json", "last_seen": "2026-10-08"}] * 301)
    assert not out["ok"] and "ceiling" in out["detail"]


def test_heir_relations_and_private_blocks():
    cs = _by_name()
    ok = {"raw": {"heir_candidates": [{"name": "Sample Person", "relation": "son"}]}}
    bad = {"raw": {"heir_candidates": [{"name": "Sample Person", "relation": "grandson"},
                                       {"name": "Other Person", "relation": "spouse", "phone": "x"}]}}
    out = _feed(cs["additions-heir-relations"], [ok, bad])
    assert out["violations"] == 2
    out = _feed(cs["additions-private-blocks"], [{"raw": {"obituary_match": {"status": "attached"}}}])
    assert out["violations"] == 1


def test_sos_profile_on_a_government_row_is_caught():
    row = {"owner_name": "SAMPLE COUNTY", "county": "Testco", "parcel_id": "1",
           "raw": {"sos_agent": {"legal_name": "Unrelated Ventures LLC", "sosid": "7"}}}
    own = {"owner_name": "UNRELATED VENTURES LLC",
           "raw": {"sos_agent": {"legal_name": "Unrelated Ventures LLC", "sosid": "7"}}}
    out = _feed(_by_name()["additions-sos-agent-bound"], [row, own])
    assert out["violations"] == 1 and out["checked"] == 2


def test_alias_to_a_short_id_is_caught():
    out = _feed(_by_name()["additions-alias-is-pin"],
                [{"raw": {"parcel_id_alias": {"short": "1600001", "long": "1600009"}}},
                 {"raw": {"parcel_id_alias": {"short": "00777", "long": "3600000001"}}}])
    assert out["violations"] == 1


def test_chain_binding_check():
    c = _by_name()["additions-rod-chain-binding"]
    rows = [
        {"raw": {"rod_chain": {"status": "ok", "fetched_at": "2026-10-10T00:00:00"}}},          # unbound new
        {"raw": {"rod_chain": {"status": "ok", "fetched_at": "2026-10-01T00:00:00"}}},          # old: counted
        {"raw": {"rod_chain": {"status": "ok", "binding": {"status": "contradicted"}}}},         # must be unbound
        {"raw": {"rod_chain": {"status": "unbound", "binding": {"status": "contradicted"}}}},
        {"raw": {"rod_chain": {"status": "ok", "binding": {"status": "sale_date"}}}},
    ]
    out = _feed(c, rows)
    assert out["violations"] == 2 and out["checked"] == 5


def test_window_lane_aging_is_caught():
    c = _by_name()["additions-window-lanes-not-aging"]
    spi = {"case_number": "2026CP1000001", "date_filed": "09/01/2026", "status": "Pending", "date_disposed": ""}
    aging = {"source": "national.sc_public_index", "state": "SC", "county": "Charleston",
             "raw": {"sc_public_index": dict(spi), "pulled_sale": {"presumed_withdrawn": True}}}
    held = {"source": "national.sc_public_index", "state": "SC", "county": "Charleston",
            "raw": {"sc_public_index": dict(spi)}}
    disposed = {"source": "national.sc_public_index", "state": "SC", "county": "Charleston",
                "raw": {"sc_public_index": dict(spi, date_disposed="09/15/2026"),
                        "pulled_sale": {"presumed_withdrawn": True}}}
    out = _feed(c, [aging, held, disposed])
    assert out["checked"] == 3 and out["violations"] == 1 and not out["ok"]


def test_rod_binding_and_near_beach_and_richland():
    cs = _by_name()
    rod = {"owner_name": "TESTER ALVIN", "raw": {"rod": {"source": "generic_rod", "instruments": [
        {"grantor": "SAMPLE CORA", "grantee": "EXAMPLE DORA"}]}}}
    assert _feed(cs["additions-rod-binds-owner"], [rod] * 40)["ok"] is False
    nb = {"raw": {"near_beach_drive": {"distance_m": 3000, "max_m": 2500, "ocean_facing_m": 100,
                                       "geo_precise": True}}}
    assert _feed(cs["additions-near-beach-bar"], [nb])["violations"] == 1
    rp = {"state": "SC", "county": "Lexington", "raw": {"richland_parcel": {"matched": True}}}
    assert _feed(cs["additions-richland-county"], [rp])["violations"] == 1

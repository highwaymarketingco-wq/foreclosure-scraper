"""scripts/audit_checks/regressions.py: the invariants that would have caught what the gated d42058b3
run lost against the 10/7 board (audit 2026-10-09, area regressions). Rows are invented."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "audit_checks"))
sys.path.insert(0, str(REPO / "src"))

import regressions as RG  # noqa: E402

KEYS = {"name", "checked", "violations", "max_violations", "ok", "detail"}


def _roll(i, county="Rutherford", misses=0, **kw):
    raw = {"rutherford_tax": {"parcel": f"{400000 + i}"}}
    if misses:
        raw["pulled_sale"] = {"consecutive_misses": misses}
    d = {"source": "counties_nc.rutherford_tax", "state": "NC", "county": county, "raw": raw}
    d.update(kw)
    return d


def _baseline(rows):
    rk, sh = RG._RollRecordsKept({}), RG._SourceHeld({})
    for r in rows:
        rk.feed(r)
        sh.feed(r)
    return {"roll_records": {s: RG._encode(v) for s, v in rk.young.items() if v},
            "source_rows": sh.counts}


def _run(check, rows):
    for r in rows:
        check.feed(r)
    res = check.finish()
    assert KEYS <= set(res) and res["ok"] == (res["violations"] <= res["max_violations"])
    return res


def test_a_fused_roll_is_caught_and_an_aged_record_is_not(monkeypatch):
    live = [_roll(i) for i in range(40)] + [_roll(100 + i, misses=3) for i in range(20)]
    base = _baseline(live)
    # the same board is fine
    assert _run(RG._RollRecordsKept(base), live)["violations"] == 0
    # 20 records aged out (3 misses on the baseline: allowed) and 9 young ones gone: under the floor
    cand = [_roll(i) for i in range(31)]
    assert _run(RG._RollRecordsKept(base), cand)["violations"] == 0
    # 15 young records fused away: over ROLL_LOST_MIN
    res = _run(RG._RollRecordsKept(base), [_roll(i) for i in range(25)])
    assert res["violations"] == 1 and "15 of 40" in res["detail"]


def test_a_record_counts_under_any_primary_source_and_by_county():
    base = _baseline([_roll(i) for i in range(30)])
    # every record still on the board, now on rows whose primary source is another roll
    moved = [dict(_roll(i), source="counties_nc.nc_heir_estate_parcels") for i in range(30)]
    assert _run(RG._RollRecordsKept(base), moved)["violations"] == 0
    # the same ids in ANOTHER county are other records
    other = [_roll(i, county="Polk") for i in range(30)]
    assert _run(RG._RollRecordsKept(base), other)["violations"] == 1


def test_a_relabeled_source_is_held_and_a_lost_one_is_not():
    rows = [{"source": "counties_nc.test_roll", "raw": {}} for _ in range(300)]
    base = _baseline(rows)
    relabeled = ([{"source": "counties_nc.test_roll", "raw": {}} for _ in range(200)]
                 + [{"source": "counties_nc.other", "raw": {"also_seen_in": [
                     {"source": "counties_nc.test_roll", "url": "u"}]}} for _ in range(100)])
    assert _run(RG._SourceHeld(base), relabeled)["violations"] == 0
    res = _run(RG._SourceHeld(base), rows[:260])
    assert res["violations"] == 1 and "counties_nc.test_roll 300->260" in res["detail"]
    # small sources (a weekly sale list) are not judged
    small = _baseline([{"source": "law_firms.test", "raw": {}} for _ in range(150)])
    assert _run(RG._SourceHeld(small), [])["violations"] == 0


def test_an_absorbed_estate_record_must_be_scored():
    row = {"source": "counties_nc.test_roll", "source_url": "https://example.invalid/roll",
           "listing_type": "tax_lien", "state": "NC", "county": "Rutherford", "parcel_id": "1600000001",
           "raw": {"also_seen_in": [{"source": "counties_nc.nc_heir_estate_parcels",
                                     "url": "https://example.invalid/heir", "listing_type": "estate_lead"}],
                   "distress_stack": {"tier": "COLD", "signals": ["tax_lien"]}}}
    res = _run(RG._AbsorbedLifeTypes(), [row])
    assert res["violations"] == 1
    scored = json.loads(json.dumps(row))
    scored["raw"]["distress_stack"]["signals"] = ["estate_lead", "tax_lien"]
    assert _run(RG._AbsorbedLifeTypes(), [scored])["violations"] == 0


def test_make_checks_and_the_baseline_round_trip(tmp_path, monkeypatch):
    names = [c.name for c in RG.make_checks()]
    assert names == ["regressions-roll-records-kept", "regressions-source-held",
                     "regressions-absorbed-life-types"]
    assert all(n == n.lower() and " " not in n for n in names)
    hashes = {1, 2 ** 63 + 5, 2 ** 64 - 1}
    assert sorted(RG._decode(RG._encode(hashes))) == sorted(hashes)
    # no baseline: the checks say so and pass
    res = _run(RG._RollRecordsKept({}), [_roll(1)])
    assert res["violations"] == 0 and "no baseline" in res["detail"]

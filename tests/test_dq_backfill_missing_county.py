"""backfill_missing_county: the evidence rules. A county is filled only when ZIP / city / parcel evidence is
unambiguous and consistent; a ZIP that spans two counties, a board that disagrees, or a conflict all skip."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_missing_county as B  # noqa: E402


def _ev(cache_zip=None, cache_city=None, board_zip=None, board_city=None):
    ev = B.Evidence()
    for k, v in (cache_zip or {}).items():
        ev.cache_zip[k] = Counter(v)
    for k, v in (cache_city or {}).items():
        ev.cache_city[k] = Counter(v)
    for k, v in (board_zip or {}).items():
        ev.board_zip[k] = Counter(v)
    for k, v in (board_city or {}).items():
        ev.board_city[k] = Counter(v)
    return ev


def test_unique_needs_volume_and_share():
    assert B.unique(Counter({"Jackson": 90, "Swain": 1}), 5, 0.98)[0] == "Jackson"   # 98.9%
    assert B.unique(Counter({"Jackson": 80, "Swain": 4}), 5, 0.98)[0] is None        # 95%: a stray county is not noise
    assert B.unique(Counter({"Jackson": 91}), 5, 0.98)[0] == "Jackson"
    assert B.unique(Counter({"Jackson": 4}), 5, 0.98)[0] is None                    # too few rows
    assert B.unique(Counter({"Alamance": 60, "Caswell": 40}), 5, 0.98)[0] is None  # a genuinely shared ZIP


def test_zip_with_one_county_in_cache_and_agreeing_board_resolves():
    ev = _ev(cache_zip={"NC|28717": {"Jackson": 86}}, board_zip={"NC|28717": {"Jackson": 12}})
    r = ev.resolve("NC", "28717", None, None)
    assert r["status"] == "resolved" and r["county"] == "Jackson" and r["evidence"] == "zip"


def test_board_disagreement_blocks_a_blind_spot_zip():
    # cache only sees Buncombe rows (Henderson's cached mailing has no ZIP); the board knows Henderson holds 218 of them
    ev = _ev(cache_zip={"NC|28732": {"Buncombe": 533}}, board_zip={"NC|28732": {"Buncombe": 140, "Henderson": 218}})
    r = ev.resolve("NC", "28732", None, None)
    assert r["status"] == "ambiguous" and r["county"] is None


def test_cache_only_evidence_needs_real_volume_when_the_board_is_silent():
    thin = _ev(cache_zip={"NC|28999": {"Swain": 6}})
    assert thin.resolve("NC", "28999", None, None)["status"] == "none"
    strong = _ev(cache_zip={"NC|28999": {"Swain": 40}})
    assert strong.resolve("NC", "28999", None, None)["county"] == "Swain"


def test_a_zip_spanning_two_counties_is_ambiguous():
    ev = _ev(cache_zip={"NC|27302": {"Alamance": 1322, "Caswell": 513}})
    r = ev.resolve("NC", "27302", None, None)
    assert r["status"] == "ambiguous" and r["county"] is None


def test_zip_and_city_that_disagree_skip_the_row():
    ev = _ev(cache_zip={"NC|28110": {"Union": 300}}, board_zip={"NC|28110": {"Union": 300}},
             cache_city={"NC|monroe": {"Mecklenburg": 300}}, board_city={"NC|monroe": {"Mecklenburg": 300}})
    r = ev.resolve("NC", "28110", "Monroe", None)
    assert r["status"] == "ambiguous" and "conflict" in r["note"]


def test_city_alone_resolves_only_when_unique_and_inside_the_zip_county_set():
    ev = _ev(cache_city={"NC|franklin": {"Macon": 200}}, board_city={"NC|franklin": {"Macon": 51}})
    assert ev.resolve("NC", None, "Franklin", None)["county"] == "Macon"
    ev = _ev(cache_zip={"NC|28105": {"Union": 92, "Mecklenburg": 60}}, cache_city={"NC|matthews": {"Union": 200}},
             board_city={"NC|matthews": {"Union": 100}})
    assert ev.resolve("NC", "28105", "Matthews", None)["status"] == "resolved"          # Union is one of the ZIP's counties
    ev = _ev(cache_zip={"NC|28105": {"Mecklenburg": 60, "Iredell": 60}}, cache_city={"NC|matthews": {"Union": 200}},
             board_city={"NC|matthews": {"Union": 100}})
    assert ev.resolve("NC", "28105", "Matthews", None)["status"] == "ambiguous"         # city county not among the ZIP's


def test_state_is_part_of_every_key():
    ev = _ev(cache_zip={"SC|29125": {"Sumter": 50}})
    assert ev.resolve("NC", "29125", None, None)["status"] == "none"


def test_court_district_rows_with_no_zip_city_or_parcel_stay_blank():
    r = _ev().resolve("SC", None, None, None)
    assert r["status"] == "none" and r["county"] is None


def test_parcel_evidence_is_weak_in_a_state_with_partial_cache_coverage(monkeypatch):
    ev = _ev()
    monkeypatch.setattr(ev, "_parcel", lambda st, pid: ("Colleton", "one_cache"))
    # SC has no full cache set: a TMS found in one cache proves nothing (115-00-00-100.000 is in Cherokee AND Colleton)
    assert ev.resolve("SC", None, None, "115-00-00-100.000")["status"] == "none"
    # ... and it contradicts a ZIP answer instead of overriding it
    ev.cache_zip["SC|29340"] = Counter({"Cherokee": 100})
    r = ev.resolve("SC", "29340", None, "115-00-00-100.000")
    assert r["status"] == "ambiguous"


def test_parcel_evidence_decides_where_the_states_caches_are_complete(monkeypatch):
    ev = _ev()
    ev.caches["NC"] = [("C%d" % i, None) for i in range(B.COMPLETE_CACHES["NC"])]
    monkeypatch.setattr(ev, "_parcel", lambda st, pid: ("Jackson", "one_cache"))
    r = ev.resolve("NC", None, None, "7582-11-0649")
    assert r["status"] == "resolved" and r["county"] == "Jackson" and r["evidence"] == "parcel_cache"


def test_zip5_and_city_key():
    assert B.zip5("28717-1234") == "28717" and B.zip5(None) == "" and B.zip5("abc") == ""
    assert B.city_key("  Mt. Holly ") == "mt holly"

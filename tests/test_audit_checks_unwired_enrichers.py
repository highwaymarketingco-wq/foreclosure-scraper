"""scripts/audit_checks/unwired_enrichers.py: every invariant fires on the defect it is for and is
quiet once the wired tail steps ran. Made-up rows only."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import foreclosure_scraper.enrichment_dnc as D
import foreclosure_scraper.enrichment_tail_extras as TE
from foreclosure_scraper.models import Listing

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ue_checks", REPO / "scripts" / "audit_checks" / "unwired_enrichers.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
TABLE = {"county_rent": {"3714999999": {"efficiency": 700, "1br": 800, "2br": 900, "3br": 1200, "4br": 1400,
                                        "year": "2026", "area_name": "Polk County, NC"}},
         "metro_rent": {}, "county_fips": {"NC": {"polk": "3714999999"}}}


def _run(checks, rows):
    for c in checks:
        c.now = NOW
        for r in rows:
            c.feed(r)
    return {c.name: c.finish() for c in checks}


def _row(**kw):
    raw = kw.pop("raw", {})
    return {"source": "test", "state": "NC", "county": "Polk", "parcel_id": "P-1", "raw": raw, **kw}


def test_constants_agree_with_the_modules():
    assert U.RESCRUB_DAYS == D.RESCRUB_DAYS
    assert U.DNC_BLOCKED == D.NOT_DIALABLE
    assert {D.CLEAR, D.ON_REGISTRY, D.ON_INTERNAL, D.UNVERIFIED, *D.BLOCKED} == U.DNC_STATUSES
    from foreclosure_scraper.call_ready import DNC_BLOCKED
    assert DNC_BLOCKED == U.DNC_BLOCKED
    prof = json.loads((REPO / "deploy" / "oracle" / "run_profile.json").read_text())
    assert set(U.RETIRED_KEY_BASELINE) == set(prof["frozen_keys_known"])
    names = [c.name for c in U.make_checks()]
    assert len(names) == len(set(names)) and all(n.startswith("unwired-") for n in names)


def test_dnc_checks():
    old = (NOW - timedelta(days=40)).isoformat()
    rows = [
        _row(raw={"owner_phone": {"phone": "8285550101"}}),                                  # never scrubbed
        _row(raw={"owner_phone": {"phone": "8285550101"}, "skip_trace": {"phone_numbers": ["8645550102"]},
                  "dnc_scrub": [{"phone": "8285550101", "dnc_status": "unverified"}]}),      # one phone missing
        _row(raw={"owner_phone": {"phone": "8285550103"},
                  "dnc_scrub": [{"phone": "8285550103", "dnc_status": "registered"}]}),      # old name
        _row(raw={"owner_phone": {"phone": "8285550104"},
                  "dnc_scrub": [{"phone": "8285550104", "dnc_status": "clear", "dnc_registered": False,
                                 "scrubbed_at": old}]}),                                      # expired clear
        _row(raw={"owner_phone": {"phone": "8285550105"}, "call_ready": {"tier": "A"},
                  "dnc_scrub": [{"phone": "8285550105", "dnc_status": "on_registry", "dnc_registered": True}]}),
    ]
    out = _run([U.DncEveryPhone(), U.DncStatusValid(), U.DncCallReadyAgrees()], rows)
    assert out["unwired-dnc-every-phone-scrubbed"]["violations"] == 2
    assert out["unwired-dnc-status-valid"]["violations"] == 2
    assert out["unwired-dnc-call-ready-agrees"]["violations"] == 1


def test_quiet_once_the_wired_steps_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_DNC_SET", {"8285550101", *(f"86455{i:05d}" for i in range(5))})
    monkeypatch.setattr(D, "_INTERNAL_PATH", tmp_path / "none.csv")
    monkeypatch.setattr(TE, "load_fmr_table", lambda path=None: TABLE)
    monkeypatch.setattr(TE, "SEPTIC_CACHE", tmp_path / "septic.json.gz")
    lis = [Listing(source="test", source_url="https://example.com/a", state="NC", county="Polk", parcel_id="P-1",
                   bedrooms=3, raw={"owner_phone": {"phone": "8285550101", "source": "county_published"},
                                    "skip_trace": {"phone_numbers": ["8285550102"]},
                                    "flood": {"zone": "AE", "in_sfha": True}}),
           Listing(source="test", source_url="https://example.com/b", state="NC", county="Polk",
                   raw={"flood": {"zone": "X", "in_sfha": False}})]
    D.enrich_dnc_scrub(lis, now=NOW)
    TE.enrich_local_pre_gate(lis, now=NOW)
    TE.enrich_local_after_qa(lis)
    rows = [json.loads(li.model_dump_json()) for li in lis]
    checks = [c for c in U.make_checks() if c.name != "unwired-property-category-current"]
    out = _run(checks, rows)
    bad = {k: v for k, v in out.items() if not v["ok"]}
    assert not bad, bad
    assert out["unwired-dnc-every-phone-scrubbed"]["checked"] == 1
    assert out["unwired-flood-zone-mirrors-flood"]["checked"] == 2
    assert out["unwired-hud-fmr-matches-table"]["checked"] == 2
    assert out["unwired-property-category-present"]["checked"] == 2


def test_today_shape_fails():
    rows = [_row(raw={"flood": {"zone": "AE", "in_sfha": True},
                      "flood_zone": {"zone": None, "flood_risk": "unknown", "in_sfha": False},
                      "septic": {"latest_status": "x"}, "land_distress": True,
                      "bt_appraisal_card": {"heated_sqft": 1500, "card_url": "u"},
                      "wetlands": []})]
    c = U.HudFmrMatchesTable()
    c.table = TABLE
    out = _run([U.FloodZoneMirror(), U.SepticCurrent(), U.PropertyCategoryPresent(), U.BtCardApplied(),
                U.WetlandsShape(), c], rows)
    assert all(v["violations"] == 1 for v in out.values()), out


def test_source_consistency_flag_check():
    row = _row(source_url="https://www.auction.com/details/100-test-st-shelby-nc-1000001", city="CLEVELAND",
               county="Cleveland", raw={"qa_flags": []})
    out = _run([U.SourceConsistencyFlags()], [row])["unwired-source-consistency-flags"]
    assert out["checked"] == 1 and out["violations"] == 1
    row["raw"]["qa_flags"] = ["source_url_city_conflict"]
    assert _run([U.SourceConsistencyFlags()], [row])["unwired-source-consistency-flags"]["violations"] == 0


def test_retired_keys_not_growing():
    rows = [_row(raw={"rod_name_index": {"x": 1}}) for _ in range(U.RETIRED_KEY_BASELINE["rod_name_index"] + 1)]
    rows.append(_row(raw={"census_tract": "1"}))
    out = _run([U.RetiredKeysNotGrowing()], rows)["unwired-retired-keys-not-growing"]
    assert out["violations"] == 2 and "rod_name_index 8 > 7" in out["detail"]


def test_set_source_reads_the_board_time(tmp_path):
    (tmp_path / "board.manifest.json").write_text(json.dumps({"run_time": "2026-10-07T17:09:03Z"}))
    c = U.SepticCurrent()
    c.set_source("board", tmp_path / "listings.json.gz")
    assert c.now == datetime(2026, 10, 7, 17, 9, 3, tzinfo=timezone.utc)

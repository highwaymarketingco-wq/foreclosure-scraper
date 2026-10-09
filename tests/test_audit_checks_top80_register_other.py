"""scripts/audit_checks/top80_register_other.py on made-up rows, plus the live repo configuration."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("top80_register_other",
                                              REPO / "scripts" / "audit_checks" / "top80_register_other.py")
T = importlib.util.module_from_spec(spec)
sys.modules["top80_register_other"] = T
spec.loader.exec_module(T)


def by_name(checks):
    return {c.name: c for c in checks}


def row(county="Pitt", state="NC", raw=None, owner="ZZTEST ALICE"):
    return {"state": state, "county": county, "owner_name": owner, "raw": raw or {}}


def finish(c, rows):
    for r in rows:
        c.feed(r)
    return c.finish()


def clean_stamp(platform="nc_cott_v4"):
    return {"instrument_count": 0, "instruments": [], "screened_none_found": True, "platform": platform,
            "fetched_at": "2026-10-10T00:00:00+00:00"}


def test_none_found_shape():
    c = by_name(T.make_checks())["top80-other-none-found-shape"]
    ok = finish(c, [row(raw={"rod": clean_stamp()}), row(raw={"rod": clean_stamp("nc_ors")}),
                    row(raw={"rod": {**clean_stamp("gaston"), "instrument_count": 4}})])   # not this group's platform
    assert ok["ok"] and ok["checked"] == 2
    c = by_name(T.make_checks())["top80-other-none-found-shape"]
    bad = finish(c, [row(raw={"rod": {**clean_stamp(), "instrument_count": 2}}),
                     row(raw={"rod": {**clean_stamp(), "has_mortgage": True}}),
                     row(raw={"rod": {k: v for k, v in clean_stamp().items() if k != "fetched_at"}})])
    assert not bad["ok"] and bad["violations"] == 3


def test_county_silent_needs_a_full_enough_county():
    c = by_name(T.make_checks())["top80-other-county-silent"]
    small = finish(c, [row("Pitt") for _ in range(5)])
    assert small["ok"] and small["checked"] == 0
    c = by_name(T.make_checks())["top80-other-county-silent"]
    rows = [row("Pitt") for _ in range(T.MIN_OWNERS)] + [row("Onslow", raw={"rod": clean_stamp()})
                                                          for _ in range(T.MIN_OWNERS)]
    res = finish(c, rows)
    assert not res["ok"] and "NC/Pitt" in res["detail"] and "NC/Onslow" not in res["detail"]


def test_marriage_bound():
    good = {"source": "register_checks", "spouse_name": "Zz", "book": "1", "checked_at": "x"}
    nm = {"source": "register_checks", "status": "no_match", "checked_at": "x"}
    c = by_name(T.make_checks())["top80-other-marriage-bound"]
    assert finish(c, [row("Onslow", raw={"marriage_license": good}), row("Rutherford", raw={"marriage_license": nm}),
                      row("Pitt", raw={"marriage_license": {"source": "aumentum_rod"}})])["ok"]
    c = by_name(T.make_checks())["top80-other-marriage-bound"]
    res = finish(c, [row("Pitt", raw={"marriage_license": nm}),                      # no marriage index in Pitt
                     row("Onslow", raw={"marriage_license": {"source": "register_checks", "status": "no_match"}}),
                     row("Onslow", raw={"marriage_license": {"source": "register_checks", "checked_at": "x"}})])
    assert res["violations"] == 3


def test_marriage_sweep_blocks_need_a_window():
    sw = {"source": "cott_v4_marriage_sweep", "status": "no_match", "checked_at": "x",
          "window_from": "2020-01-01", "window_to": "2026-10-09"}
    c = by_name(T.make_checks())["top80-other-marriage-bound"]
    assert finish(c, [row("Onslow", raw={"marriage_license": sw}),
                      row("Alamance", raw={"marriage_license": {**sw, "status": "found", "spouse_name": "Zz",
                                                                "license_no": "9"}})])["ok"]
    c = by_name(T.make_checks())["top80-other-marriage-bound"]
    res = finish(c, [row("Onslow", raw={"marriage_license": {k: v for k, v in sw.items() if k != "window_from"}}),
                     row("Onslow", raw={"marriage_license": {**sw, "window_from": "2027-01-01"}}),
                     row("Pitt", raw={"marriage_license": sw})])
    assert res["violations"] == 3


def test_sweep_shape():
    ok = {"platform": "cott_v4_lien_sweep", "status": "none_found", "checked_at": "2026-10-10",
          "window_from": "2020-01-01", "window_to": "2026-10-09", "instruments": []}
    found = {**ok, "status": "found", "instruments": [{"t": "FORCL"}]}
    c = by_name(T.make_checks())["top80-other-sweep-shape"]
    assert finish(c, [row("Onslow", raw={"rod_lien_sweep": ok}), row("Nash", raw={"rod_lien_sweep": found}),
                      row("Horry", state="SC", raw={"rod_lien_sweep": {"platform": "other"}})])["ok"]
    c = by_name(T.make_checks())["top80-other-sweep-shape"]
    bad = finish(c, [row("Onslow", raw={"rod_lien_sweep": {**ok, "instruments": [{"t": "x"}]}}),    # none_found with a hit
                     row("Onslow", raw={"rod_lien_sweep": {**found, "instruments": []}}),           # found with none
                     row("Rowan", raw={"rod_lien_sweep": ok}),                                     # a walled county
                     row("Nash", raw={"rod_lien_sweep": {**ok, "window_from": "2027-01-01"}})])
    assert bad["violations"] == 4


def test_a_swept_row_counts_against_the_silent_county_check():
    c = by_name(T.make_checks())["top80-other-county-silent"]
    rows = [row("Pitt", raw={"rod_lien_sweep": {"platform": "cott_v4_lien_sweep"}}) for _ in range(T.MIN_OWNERS)]
    assert finish(c, rows)["ok"]


def test_config_is_consistent_in_this_repo():
    res = by_name(T.make_checks())["top80-other-config-consistent"].finish()
    assert res["ok"], res["detail"]


def test_config_breaks_when_a_flag_is_off(tmp_path):
    (tmp_path / "deploy" / "oracle").mkdir(parents=True)
    (tmp_path / "deploy" / "oracle" / "run_profile.json").write_text('{"flags": {"FORECLOSURE_NC_COTT_ROD": "0"}}')
    (tmp_path / "deploy" / "oracle" / "vm_lib.sh").write_text("")
    c = T._ConfigConsistent(tmp_path)
    res = c.finish()
    assert not res["ok"] and "FORECLOSURE_NC_COTT_ROD not 1" in res["detail"]

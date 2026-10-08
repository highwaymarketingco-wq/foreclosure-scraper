"""scripts/audit_checks/call_ready.py: the call-ready invariants (audit 2026-10-09). Made-up rows."""
from __future__ import annotations

import copy
import importlib.util
from datetime import date
from pathlib import Path

from foreclosure_scraper import call_ready as CR

_FX = Path(__file__).resolve().parent / "test_call_ready.py"
_fspec = importlib.util.spec_from_file_location("call_ready_fixtures", _FX)
_fx = importlib.util.module_from_spec(_fspec)
_fspec.loader.exec_module(_fx)
accela_phone, heirs_row, row, tax_record, voter_phone = (_fx.accela_phone, _fx.heirs_row, _fx.row, _fx.tax_record,
                                                         _fx.voter_phone)

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "call_ready.py"
_spec = importlib.util.spec_from_file_location("audit_call_ready", _PATH)
ac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ac)

KEYS = {"name", "checked", "violations", "max_violations", "ok", "detail"}
TODAY = date(2026, 10, 8)


def stamped(r):
    CR.stamp_board([r], TODAY)
    return r


def run(check, rows):
    for r in rows:
        check.feed(r)
    return check.finish()


def test_interface():
    checks = ac.make_checks()
    assert [c.name for c in checks] == ["call-ready-present", "call-ready-call-evidence",
                                        "call-ready-no-dead-owner-call", "call-ready-public-safe",
                                        "call-ready-recompute"]
    for c in checks:
        c.feed(stamped(row(raw={"owner_phone": accela_phone()})))
        res = c.finish()
        assert set(res) == KEYS and res["ok"], res


def test_a_board_without_the_gate_fails_present():
    res = run(ac.Present(), [row()])
    assert not res["ok"] and res["violations"] == 1 and "missing" in res["detail"]


def test_tier_a_without_a_fresh_county_check_is_caught():
    r = stamped(row(raw={"owner_phone": accela_phone()}))
    assert r["raw"]["call_ready"]["tier"] == "A"
    # a later step (or a hand edit) leaves the block but the evidence is 40 days old
    r["raw"]["verification"] = [tax_record(checked="2026-08-29T00:00:00Z")]
    res = run(ac.CallEvidence(), [r])
    assert not res["ok"] and "tax_tax_check_old" in res["detail"]


def test_tier_a_with_a_name_only_phone_is_caught():
    r = stamped(row(raw={"owner_phone": voter_phone()}))
    assert r["raw"]["call_ready"]["tier"] == "B"
    r["raw"]["call_ready"]["tier"] = "A"
    res = run(ac.CallEvidence(), [r])
    assert not res["ok"] and "tier_a_phone_not_tied" in res["detail"]


def test_owner_call_to_an_estate_is_caught():
    r = stamped(heirs_row())
    blk = r["raw"]["call_ready"]
    assert blk["lane"] == "C"
    blk["lane"] = "A"
    res = run(ac.NoDeadOwnerCall(), [r])
    assert not res["ok"] and "estate_or_heirs_owner" in res["detail"]


def test_public_safe_flags_a_phone_but_not_dates_or_amounts():
    ok = stamped(row(raw={"owner_phone": accela_phone()}))
    assert run(ac.PublicSafe(), [ok])["ok"]
    bad = copy.deepcopy(ok)
    bad["raw"]["call_ready"]["reason"] += " Call 828-555-0142."
    res = run(ac.PublicSafe(), [bad])
    assert not res["ok"] and "digit_run" in res["detail"]


def test_recompute_catches_a_stale_block():
    r = stamped(row(raw={"owner_phone": accela_phone()}))
    assert run(ac.Recompute(), [r])["ok"]
    r["raw"]["verification"] = [tax_record(verdict="stale", total=0.0, years=0)]   # paid after stamping
    res = run(ac.Recompute(), [r])
    assert not res["ok"] and "A/A->A/D" in res["detail"]

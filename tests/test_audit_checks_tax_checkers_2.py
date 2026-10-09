"""scripts/audit_checks/tax_checkers_2.py: the county tax-checker invariants (audit 2026-10-09).
Made-up rows."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "tax_checkers_2.py"
_spec = importlib.util.spec_from_file_location("audit_tax_checkers_2", _PATH)
tk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tk)

KEYS = {"name", "checked", "violations", "max_violations", "ok", "detail"}


def row(state, county, **kw):
    r = {"state": state, "county": county, "listing_type": "code_violation", "source": "counties_x.test",
         "parcel_id": "1234567890", "street_address": "1 TEST ST",
         "raw": {"tax_owed": {"balance": 500.0, "year": 2025, "kind": "delinquent_tax"}}}
    r.update(kw)
    return r


def test_shape():
    checks = tk.make_checks()
    assert [c.name for c in checks] == ["tax-claim-has-checker", "tax-claim-gate-verifier-agree"]
    for c in checks:
        assert set(c.finish()) == KEYS


def test_a_county_with_no_checker_and_no_recorded_wall_is_counted():
    c = tk.ClaimHasChecker()
    c.feed(row("NC", "Person"))                    # no checker, no wall card: counted (Chowan got one 2026-10-09)
    c.feed(row("NC", "Lincoln"))                   # Avalon wall card: recorded
    c.feed(row("NC", "Gates"))                     # no per-year source: recorded
    c.feed(row("SC", "Greenville", parcel_id="0999000100100"))     # tax_lien_greenville takes it
    c.feed(row("NC", "Person", raw={}))            # no tax claim: not counted at all
    out = c.finish()
    assert (out["checked"], out["violations"]) == (4, 1) and "NC:Person" in out["detail"]


def test_a_gate_claim_no_verifier_takes_in_a_covered_county_is_a_violation():
    c = tk.GateVerifierAgree()
    c.feed(row("SC", "Spartanburg"))               # a tax_owed claim: qPayBill takes it (since 2026-10-09)
    c.feed(row("NC", "Lincoln"))                   # not a covered county: not checked here
    out = c.finish()
    assert (out["checked"], out["violations"], out["ok"]) == (1, 0, True)
    # a verifier that ignored the gate's claim (the 2026-10-08 selection) is caught
    c2 = tk.GateVerifierAgree()
    real = c2.verifiers
    c2.verifiers = [v for v in real if v.name != "tax_lien_qpaybill"] + [
        type(real[0])(**{**real[0].__dict__, "name": "old_qpaybill", "applies": _old_qpaybill_applies})]
    c2.configured[("SC", "Spartanburg")] = True
    c2.feed(row("SC", "Spartanburg"))
    assert c2.finish()["violations"] == 1


def _old_qpaybill_applies(r):
    """The pre-2026-10-09 rule: a listing type or an aging flag, never a bare tax_owed balance."""
    from foreclosure_scraper.verification.verifiers import _tax_common as tc
    return str(r.get("county")) == "Spartanburg" and (tc.listing_tax_claim(r) or tc.aging_claim(r))

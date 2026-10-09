"""scripts/audit_checks/top80_verify.py: each invariant flags its defect class (made-up rows)."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import gap_matrix as gm  # noqa: E402
from audit_checks import top80_verify as C  # noqa: E402


def _run(check, rows):
    for r in rows:
        check.feed(r)
    d = check.finish()
    assert set(d) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
    return d


def _court(**kw):
    r = {"state": "NC", "county": "Wake", "source": "counties_nc.nc_ecourts_divorce",
         "listing_type": "divorce_notice", "street_address": "1 Main St", "parcel_id": "123",
         "raw": {"nc_ecourts": {"caseNumber": "26CVD000001-910", "cause": "FAM - Divorce",
                                "civilJudgmentStatus": "Open", "judgmentId": "1",
                                "orderedDate": "2026-09-01"}}}
    r.update(kw)
    return r


def test_interface():
    names = [c.name for c in C.make_checks()]
    assert len(names) == len(set(names)) and all(n.startswith("top80v-") for n in names)


def test_ledger_names_are_registered():
    d = _run(C.CubeLedgerNamesRegistered(), [])
    assert d["ok"] and d["checked"] > 30


def test_ledger_name_check_catches_an_unregistered_signal(monkeypatch):
    bad = dict(gm.SPECS)
    bad["lt_divorce_notice"] = dataclasses.replace(gm.SPECS["lt_divorce_notice"], ledger="no_such_signal")
    monkeypatch.setattr(gm, "SPECS", bad)
    d = _run(C.CubeLedgerNamesRegistered(), [])
    assert not d["ok"] and "lt_divorce_notice:no_such_signal" in d["detail"]


def test_the_cube_must_name_the_verifier_that_covers_the_rows(monkeypatch):
    row = {"state": "NC", "county": "Gaston", "source": "counties_nc.nc_ecourts_lis_pendens",
           "listing_type": "lis_pendens", "raw": {"nc_ecourts": {
               "caseNumber": "26CV000001-360", "cause": "CV - Lis Pendens", "civilJudgmentStatus": "Open",
               "judgmentId": "9", "orderedDate": "2026-09-01"}}}
    assert _run(C.CubeNamesTheVerifier(), [row])["ok"]
    # the original defect: the column named a signal that is registered but not the covering one
    old = dict(gm.SPECS)
    old["lt_lis_pendens"] = dataclasses.replace(gm.SPECS["lt_lis_pendens"], ledger="foreclosure_rod")
    monkeypatch.setattr(gm, "SPECS", old)
    d = _run(C.CubeNamesTheVerifier(), [row])
    assert not d["ok"] and d["violations"] == 1 and "lt_lis_pendens:nc_ecourts_case" in d["detail"]


def test_court_feed_has_a_verifier():
    ok = _court()
    d = _run(C.CourtFeedHasVerifier(), [ok, _court(source="national.zillow", listing_type="reo")])
    assert d["checked"] == 1 and d["ok"]


def test_tax_claim_has_a_verifier_or_a_declared_wall():
    walled = {"state": "NC", "county": "Iredell", "source": "counties_generic.liensnc", "listing_type": "tax_lien",
              "raw": {}}
    live = {"state": "NC", "county": "Iredell", "source": "counties_nc.iredell_delinquent_tax",
            "listing_type": "tax_lien", "parcel_id": "3774626057.000",
            "raw": {"iredell_delinquent_tax": {"years_unpaid": [2025]}}}
    other_county = dict(live, county="Wake")                        # not in this group's scope
    d = _run(C.TaxClaimHasVerifier(), [walled, live, other_county])
    assert d["checked"] == 2 and d["ok"]
    # an Iredell tax_lien row that no verifier takes (not a tax claim, no block) is a violation
    orphan = {"state": "NC", "county": "Iredell", "source": "counties_nc.iredell_delinquent_tax",
              "listing_type": "tax_sale", "raw": {}, "parcel_id": "1"}
    import foreclosure_scraper.verification.verifiers.tax_lien_itsnet as itsnet
    orphan_applies = itsnet.applies(orphan)
    d = _run(C.TaxClaimHasVerifier(), [orphan])
    assert d["violations"] == (0 if orphan_applies else 1)


def _heir(**kw):
    hp = {"is_quiet_title": True, "kind": "quiet_title", "decedents": ["EXAMPLE TESTER"], "parcel_id": "1-2-3",
          "case_number": "25SP000001-500"}
    r = {"state": "NC", "county": "Johnston", "source": "public_notices.nc_heir_notices",
         "listing_type": "probate_notice", "raw": {"heir_naming_publication": hp,
                                                   "column": {"text": "Quiet Title Action under File No"}}}
    r.update(kw)
    return r


def test_nc_heir_notice_shape():
    good = _heir()
    bad_county = _heir(county="Atlantis")
    nothing = _heir(raw={"heir_naming_publication": {"is_quiet_title": False, "kind": "x"}})
    no_block = _heir(raw={})
    d = _run(C.NcHeirNoticeShape(), [good, bad_county, nothing, no_block, _heir(source="other.slug", county="Atlantis")])
    assert d["checked"] == 4 and d["violations"] == 3 and not d["ok"]


def test_quiet_title_flag_needs_the_phrase():
    ok = _heir()
    bad = _heir(raw={"heir_naming_publication": {"is_quiet_title": True},
                     "column": {"text": "notice to heirs of someone, partition"}})
    not_flagged = _heir(raw={"heir_naming_publication": {"is_quiet_title": False}, "column": {"text": "x"}})
    d = _run(C.QuietTitleFlagHasText(), [ok, bad, not_flagged])
    assert d["checked"] == 2 and d["violations"] == 1

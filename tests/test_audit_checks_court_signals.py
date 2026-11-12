"""scripts/audit_checks/court_signals.py: each invariant flags its defect class (made-up rows)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_checks import court_signals as C  # noqa: E402


def _row(sigs, tier="WARM", **kw):
    r = {"state": "NC", "county": "Gaston", "source": "law_firms.example", "listing_type": "lis_pendens",
         "raw": {"distress_stack": {"signals": list(sigs), "tier": tier}}}
    raw = kw.pop("raw", {})
    r.update(kw)
    r["raw"].update(raw)
    return r


def _run(check, rows):
    for r in rows:
        check.feed(r)
    d = check.finish()
    assert set(d) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
    return d


def test_interface():
    names = [c.name for c in C.make_checks()]
    assert len(names) == len(set(names)) and all(n.startswith("court-") for n in names)


def test_upset_bid_needs_a_sale():
    bad = _row(["lis_pendens", "upset_bid"], source="counties_nc.nc_ecourts_lis_pendens",
               raw={"upset_bid": {"in_window": True, "statute": "NCGS"}})
    pub = _row(["upset_bid"], raw={"upset_bid": {"source": "published", "in_window": True}})
    derived = _row(["upset_bid"], sale_date="2026-10-01", raw={"upset_bid": {"source_signal": "x"}})
    d = _run(C.UpsetBidNeedsSale(), [bad, pub, derived])
    assert d["checked"] == 3 and d["violations"] == 1 and not d["ok"]


def test_ended_record_is_not_scored():
    bad = _row(["lis_pendens"], source="nc_ecourts_judgments",
               raw={"nc_ecourts": {"civil_judgment_status": "Canceled"}})
    ok = _row(["lis_pendens"], source="nc_ecourts_judgments",
              raw={"nc_ecourts": {"civil_judgment_status": "Active"}})
    gone = _row([], source="nc_ecourts_judgments", raw={"nc_ecourts": {"civil_judgment_status": "Satisfied"}})
    d = _run(C.EndedRecordNotScored(), [bad, ok, gone])
    assert d["violations"] == 1


def test_bankruptcy_needs_a_property():
    bad = _row(["bankruptcy"], listing_type="bankruptcy", street_address="Sample Person — 26-00001")
    good = _row(["bankruptcy"], listing_type="bankruptcy", street_address="12 Example Rd")
    d = _run(C.BankruptcyHasProperty(), [bad, good])
    assert d["checked"] == 2 and d["violations"] == 1


def test_hot_needs_a_property():
    bad = _row(["lis_pendens"], tier="HOT")
    good = _row(["lis_pendens"], tier="HOT", parcel_id="123")
    warm = _row(["lis_pendens"], tier="WARM")
    d = _run(C.HotHasProperty(), [bad, good, warm])
    assert d["checked"] == 2 and d["violations"] == 1


def test_hot_rows_a_verifier_covers_carry_its_record():
    heir = {"source": "counties_nc.nc_heir_estate_parcels",
            "source_url": "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1",
            "county": "Edgecombe", "parcel_id": "4700-11-2233", "listing_type": "estate_lead"}
    bad = _row(["estate_lead"], tier="HOT", **heir)
    good = _row(["estate_lead"], tier="HOT", **heir,
                raw={"verification": [{"signal": "heir_roll", "verdict": "confirmed",
                                       "checked_at": "2026-10-08T00:00:00Z",
                                       "expires_at": "2099-01-01T00:00:00Z"}]})
    expired = _row(["estate_lead"], tier="HOT", **heir,
                   raw={"verification": [{"signal": "heir_roll", "verdict": "confirmed",
                                          "expires_at": "2020-01-01T00:00:00Z"}]})
    d = _run(C.HotVerified(), [bad, good, expired])
    assert d["checked"] == 3 and d["violations"] == 2


def test_probate_decedent_binds_to_the_owner():
    bad = _row(["probate"], parcel_id="1", owner_name="ROE RICHARD", raw={"probate": {"decedent": "Jane Doe"}})
    good = _row(["probate"], parcel_id="2", owner_name="DOE JANE HEIRS",
                raw={"probate": {"decedent": "Jane Doe"}, "gis": {"owner": "DOE JANE HEIRS"}})
    d = _run(C.ProbateDecedentBinds(), [bad, good])
    assert d["checked"] == 2 and d["violations"] == 1


def test_bankruptcy_filing_binds_by_name():
    base = {"listing_type": "bankruptcy", "parcel_id": "1"}
    bad = _row(["bankruptcy"], **base, defendant="Mary Doe",
               raw={"courtlistener": {"case_name": "Mary Doe"}, "gis": {"owner": "DOE ALPHA"}})
    good = _row(["bankruptcy"], **base, defendant="Jane Doe",
                raw={"courtlistener": {"case_name": "Jane Doe"}, "gis": {"owner": "DOE JANE"}})
    d = _run(C.BankruptcyFilingBinds(), [bad, good])
    assert d["checked"] == 2 and d["violations"] == 1


def test_lis_pendens_is_lis_pendens():
    lien = _row(["lis_pendens"], source="counties_nc.nc_ecourts_lis_pendens",
                raw={"nc_ecourts": {"cause": "CV - Claim of Lien"}})
    retyped = _row(["lien_claim"], source="counties_nc.nc_ecourts_lis_pendens", listing_type="lien_claim",
                   raw={"nc_ecourts": {"cause": "CV - Claim of Lien", "signal": "lien_claim"}})
    real = _row(["lis_pendens"], source="counties_nc.nc_ecourts_lis_pendens",
                raw={"nc_ecourts": {"cause": "CV - Lis Pendens"}})
    d = _run(C.LisPendensIsLisPendens(), [lien, retyped, real])
    assert d["checked"] == 2 and d["violations"] == 1

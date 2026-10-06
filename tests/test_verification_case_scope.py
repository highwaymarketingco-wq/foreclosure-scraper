"""Case-scoped verifier identity (IDENTITY = "case", 2026-10-06).

The ledger keyed every verdict by PROPERTY, so a placeholder parcel holding unrelated filings
gave all of them one verdict (about 37 bankruptcy filings on one Anderson SC parcel, 91 jail
rows on one city-owned Anderson parcel). A case-scoped verifier keys by case id + property: two
cases on one parcel are two entries, the same case on two rows of one property is one, and a
case is never matched to a row of a different parcel. Made-up names and parcels throughout.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import apply as A
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification import ledger as L
from foreclosure_scraper.verification.registry import ContractError, Verifier, discover, from_module
from foreclosure_scraper.verification.verifiers import bankruptcy_stay as BK
from foreclosure_scraper.verification.verifiers import jail_booking as JB

T0 = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parent.parent
REG = {v.name: v for v in discover()}


# --------------------------------------------------------------------------- core

def test_case_id_is_a_normalized_hash_and_never_a_property_prefix():
    a = core.case_id("bk", "ncwb", "3:26-bk-10161")
    assert a == core.case_id("bk", "NCWB", "326BK10161") and a.startswith("bk:") and len(a) == 19
    assert a != core.case_id("bk", "nceb", "3:26-bk-10161")
    assert "10161" not in a                            # no docket number in a public key
    assert core.case_id("bk", "", None) is None
    for bad in ("parcel", "addr", "case", "row", "Bk", "1x", ""):
        with pytest.raises(ValueError):
            core.case_id(bad, "x")


def test_scoped_keys_split_back_and_plain_keys_never_split():
    keys = ["parcel:NC:lincoln:1111111111", "addr:NC:lincoln:12 main st @ rear", "case:NC:lincoln:26cvs1"]
    cid = core.case_id("bk", "ncwb", "26-10001")
    sk = core.scoped_keys(keys, cid)
    assert [core.split_key(k) for k in sk] == [(cid, k) for k in keys]
    assert [core.split_key(k) for k in keys] == [(None, k) for k in keys]
    assert core.scoped_keys(keys, None) == keys


# --------------------------------------------------------------------------- registry

def _mod(**kw):
    async def verify(row, client):  # pragma: no cover
        raise AssertionError
    base = dict(SIGNAL="x_sig", VERSION="v1", TTL_DAYS=3, applies=lambda r: True, verify=verify)
    base.update(kw)
    return SimpleNamespace(__name__="pkg.x_mod", **base)


def test_contract_case_identity_required_and_identity_values_checked():
    with pytest.raises(ContractError, match="case_identity"):
        from_module(_mod(IDENTITY="case"))
    with pytest.raises(ContractError, match="IDENTITY"):
        from_module(_mod(IDENTITY="parcel"))
    assert from_module(_mod()).identity == "property"
    v = from_module(_mod(IDENTITY="case", case_identity=lambda r: None))
    assert v.identity == "case"


def test_the_real_case_scoped_verifiers_and_the_property_ones_stay_as_they_were():
    assert REG["bankruptcy_stay"].identity == "case" and REG["jail_booking"].identity == "case"
    for name in ("tax_lien_buncombe", "code_enforcement_henderson",
                 "vacant_structure_hendersonville", "elderly_disabled", "divorce_sc_wall"):
        assert REG[name].identity == "property"
        row = {"state": "NC", "county": "Buncombe", "parcel_id": "9649123456", "raw": {}}
        assert REG[name].ledger_keys(row) == core.row_keys(row)


def test_a_case_scoped_row_naming_no_case_is_keyed_by_its_own_fingerprint():
    v = from_module(_mod(IDENTITY="case", case_identity=lambda r: None))
    r1 = {"state": "NC", "county": "Lincoln", "parcel_id": "1111111111", "source": "a"}
    r2 = dict(r1, source="b")
    k1, k2 = v.ledger_keys(r1), v.ledger_keys(r2)
    assert core.split_key(k1[0])[1] == core.split_key(k2[0])[1] == "parcel:NC:lincoln:1111111111"
    assert core.split_key(k1[0])[0] != core.split_key(k2[0])[0]       # never shared


# --------------------------------------------------------------------------- bankruptcy rows

def _bk_row(docket, *, court="ncwb", parcel="1111111111", addr="12 Placeholder Rd",
            county="Lincoln", state="NC", case_name="Odell Ray Brisco"):
    return {"source": "s", "source_url": "https://x/r", "listing_type": "lis_pendens",
            "state": state, "county": county, "parcel_id": parcel, "street_address": addr,
            "owner_name": "BRISCO ODELL R", "defendant": "BRISCO ODELL R",
            "raw": {"bankruptcy": {"court": court, "docket_number": docket,
                                   "case_name": case_name, "absolute_url": "/docket/7/x/",
                                   "date_filed": "2026-09-01"}}}


def _res(signal, verdict, verifier, **ev):
    return core.result(signal, verdict, ev, source="src", version="v2", verifier=verifier, now=T0)


def _record(led, v, row, verdict, **ev):
    return led.record(row, _res(v.signal, verdict, v.name, **ev), ttl_days=v.ttl_days,
                      governs=v.governs, keys=v.ledger_keys(row), now=T0)


def test_two_cases_on_one_parcel_are_two_entries_and_the_same_case_shares_one():
    v = REG["bankruptcy_stay"]
    led = L.Ledger("bankruptcy_stay")
    a1 = _bk_row("26-10001")
    a2 = _bk_row("26-10001", parcel=None)                    # same case, found by address
    b = _bk_row("26-10002", case_name="Tamsin Lee Vanterpool")
    _record(led, v, a1, "confirmed")
    _record(led, v, b, "refuted")
    assert len(led.rows) == 2
    assert led.find(v.ledger_keys(a2))[1]["latest"]["verdict"] == "confirmed"
    assert led.find(v.ledger_keys(b))[1]["latest"]["verdict"] == "refuted"
    e = led.find(v.ledger_keys(a1))[1]
    assert e["case"] == BK.case_identity(a1) and all(k.startswith(e["case"] + "@") for k in e["keys"])
    _record(led, v, a2, "confirmed")
    assert len(led.rows) == 2                                # the same case: one entry


def test_a_case_is_never_matched_to_a_row_of_a_different_parcel():
    v = REG["bankruptcy_stay"]
    led = L.Ledger("bankruptcy_stay")
    _record(led, v, _bk_row("26-10001"), "refuted")
    other = _bk_row("26-10001", parcel="2222222222")        # same case + address, other parcel
    assert led.find(v.ledger_keys(other)) == (None, None)


def test_case_identity_reads_a_listing_like_a_board_dict():
    row = _bk_row("26-10001")
    li = Listing.model_validate(row)
    assert BK.case_identity(li) == BK.case_identity(row) is not None
    listing_row = {"source": "courtlistener_bankruptcy", "listing_type": "bankruptcy",
                   "source_url": "https://www.courtlistener.com/docket/123/x/", "state": "NC",
                   "county": "Lincoln", "parcel_id": "1111111111", "case_number": "26-10001",
                   "defendant": "Odell Ray Brisco", "raw": {"courtlistener": {"court": "ncwb"}}}
    assert BK.case_identity(listing_row) == BK.case_identity(row)          # court + docket
    assert BK.case_identity(Listing.model_validate(listing_row)) == BK.case_identity(row)
    assert BK.case_identity({"raw": {}}) is None


def test_jail_case_identity_booking_id_or_name_and_arrest_date():
    stamp = {"county": "Anderson", "state": "SC", "matched_name": "ODELL BRISCO",
             "arrest_date": "2026-09-30", "confidence": "name_only_low"}
    row = {"source": "s", "source_url": "http://x", "state": "SC", "county": "Anderson",
           "parcel_id": "1111111111", "raw": {"jail_booking": stamp}}
    c = JB.case_identity(row)
    assert c.startswith("jail:") and "BRISCO" not in c
    assert JB.case_identity(dict(row, raw={"jail_booking": dict(stamp, matched_name="TAMSIN VANTERPOOL")})) != c
    assert JB.case_identity(dict(row, raw={"jail_booking": dict(stamp, arrest_date="2026-10-02")})) != c
    with_id = dict(row, raw={"jail_booking": dict(stamp, detail_id="88")})
    assert JB.case_identity(with_id) == JB.case_identity(
        dict(row, raw={"jail_booking": dict(stamp, detail_id="88", arrest_date="x")}))
    assert JB.case_identity(Listing.model_validate(row)) == c
    assert JB.case_identity(dict(row, raw={"jail_booking": {"vendor": "jail_bookings_scraper"}})) is None


# --------------------------------------------------------------------------- apply

def _li(docket, **kw):
    return Listing.model_validate(_bk_row(docket, **kw))


def test_apply_gives_each_case_on_a_parcel_its_own_verdict(tmp_path):
    v = REG["bankruptcy_stay"]
    led = L.Ledger("bankruptcy_stay")
    _record(led, v, _bk_row("26-10001"), "confirmed")
    _record(led, v, _bk_row("26-10002"), "refuted")
    led.save(tmp_path / "bankruptcy_stay.json")
    a, b, c = _li("26-10001"), _li("26-10002"), _li("26-10003")      # c: never checked
    out = A.apply_verification([a, b, c], tmp_path, now=T0)
    assert [r["verdict"] for r in a.raw["verification"]] == ["confirmed"]
    assert [r["verdict"] for r in b.raw["verification"]] == ["refuted"]
    assert "verification" not in c.raw
    assert out["rows"] == 2 and out["suppressing"] == 1


def test_apply_never_attaches_a_property_keyed_verdict_of_a_case_scoped_verifier(tmp_path):
    """An entry written before case scoping names no case: attaching it to every case on the
    parcel is the bug. A property-keyed entry of another writer (the human lane's shape) in the
    same ledger is still attached when no case entry matches."""
    led = L.Ledger("bankruptcy_stay")
    row = _bk_row("26-10001")
    led.record(row, _res("bankruptcy_stay", "refuted", "bankruptcy_stay"), ttl_days=30,
               governs=("bankruptcy",), now=T0)                    # plain row_keys(): legacy
    led.save(tmp_path / "bankruptcy_stay.json")
    li = _li("26-10001")
    A.apply_verification([li], tmp_path, now=T0)
    assert "verification" not in li.raw

    led2 = L.Ledger("bankruptcy_stay")
    led2.record(row, _res("bankruptcy_stay", "refuted", "human_lane_bk"), ttl_days=30,
                governs=("bankruptcy",), now=T0)
    led2.save(tmp_path / "bankruptcy_stay.json")
    li = _li("26-10001")
    A.apply_verification([li], tmp_path, now=T0)
    assert li.raw["verification"][0]["verifier"] == "human_lane_bk"


# --------------------------------------------------------------------------- migration

def _legacy(led, row, verdict, **ev):
    """A property-keyed entry, as the sweep wrote them before case scoping."""
    led.record(row, _res("bankruptcy_stay", verdict, "bankruptcy_stay", **ev), ttl_days=30,
               governs=("bankruptcy", "bankruptcy_stay"), now=T0)


def test_migration_scopes_attributes_or_marks_for_recheck_and_never_drops_an_entry(tmp_path):
    v = REG["bankruptcy_stay"]
    led = L.Ledger("bankruptcy_stay")
    single = _bk_row("26-10001", parcel="1000000001", addr="1 A St")
    coll_a = _bk_row("26-10002", parcel="1000000002", addr="2 B St")
    coll_b = _bk_row("26-10003", parcel="1000000002", addr="2 B St")
    attr_a = _bk_row("26-10004", parcel="1000000003", addr="3 C St")
    attr_b = _bk_row("26-10005", parcel="1000000003", addr="3 C St")
    other = _bk_row("26-10006", parcel="1000000004", addr="4 D St")
    gone = _bk_row("26-10007", parcel="1000000005", addr="5 E St")
    gone2 = _bk_row("26-10008", parcel="1000000006", addr="6 F St")
    _legacy(led, single, "refuted", decided_by="no_positional_match")
    _legacy(led, coll_a, "refuted", decided_by="middle_conflict")
    _legacy(led, attr_a, "stale", court="ncwb", docket_number="26-10005")
    _legacy(led, other, "confirmed", court="ncwb", docket_number="26-99999")
    _legacy(led, gone, "stale", court="ncwb", docket_number="26-10007")
    _legacy(led, gone2, "refuted")
    board = [single, coll_a, coll_b, attr_a, attr_b, other, {"state": "NC", "raw": {}}]
    rep = L.migrate_to_case_scope(led, v, board, now=T0)
    assert {k: rep[k] for k in ("entries", "scoped", "attributed", "scoped_from_evidence",
                                "recheck")} == {"entries": 6, "scoped": 1, "attributed": 1,
                                                "scoped_from_evidence": 1, "recheck": 3}
    why = {ln["key"].split(":")[-1]: (ln["outcome"], ln["reason"]) for ln in rep["lines"]}
    assert why["1000000002"] == ("recheck", "case_collision")
    assert why["1000000004"] == ("recheck", "evidence_names_another_case")
    assert why["1000000006"] == ("recheck", "no_case_on_board")
    assert len(led.rows) == 6
    f = lambda r: led.find(v.ledger_keys(r))[1]  # noqa: E731
    assert f(single)["latest"]["verdict"] == "refuted" and f(single)["migrated"]["how"] == "scoped"
    assert f(attr_b)["latest"]["verdict"] == "stale" and f(attr_a) is None
    assert f(gone)["latest"]["verdict"] == "stale"
    assert f(coll_a) is None and f(coll_b) is None and f(other) is None
    marked = [e for e in led.rows.values() if "recheck" in e]
    assert len(marked) == 3 and all("latest" not in e and e["superseded"] for e in marked)
    assert led.counts()["rows"] == 6 and led.counts()["refuted"] == 1
    # nothing the migration could not attribute is attached to any row
    led.save(tmp_path / "bankruptcy_stay.json")
    lis = [Listing.model_validate(r) for r in (coll_a, coll_b, other, attr_a)]
    A.apply_verification(lis, tmp_path, now=T0)
    assert all("verification" not in li.raw for li in lis)
    # idempotent
    again = L.migrate_to_case_scope(L.Ledger.load("bankruptcy_stay", tmp_path), v, board, now=T0)
    assert again["entries"] == 0 and again["lines"] == []


def test_the_sweep_queues_each_case_on_a_parcel_and_one_check_per_case(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("verification_sweep",
                                                  REPO / "scripts" / "verification_sweep.py")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    rows = [_bk_row("26-10001"), _bk_row("26-10001", addr="12 Placeholder Rd Unit 0"),
            _bk_row("26-10002"), _bk_row("26-10003")]
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "listings.json.gz").write_bytes(gzip.compress(json.dumps(rows).encode()))
    v = REG["bankruptcy_stay"]
    plan, why = sweep.select(docs / "listings.json.gz", [v], {"bankruptcy_stay": L.Ledger("bankruptcy_stay")},
                             county=None, cap=10, now=T0)
    assert len(plan["bankruptcy_stay"]) == 3 and why["bankruptcy_stay"]["same_property_queued"] == 1


# --------------------------------------------------------------------------- the committed ledgers

@pytest.mark.parametrize("signal,verifier", [("bankruptcy_stay", "bankruptcy_stay"),
                                             ("jail_booking", "jail_booking")])
def test_committed_ledgers_hold_no_property_keyed_verdict_of_a_case_scoped_verifier(signal, verifier):
    p = REPO / "docs" / "handoff" / "verification" / f"{signal}.json"
    if not p.exists():
        pytest.skip("no ledger")
    led = L.Ledger.load_file(p)
    for ek, e in led.rows.items():
        cid, _ = core.split_key(ek)
        if cid is None:
            assert "latest" not in e and e.get("recheck"), ek
        else:
            assert e.get("case") == cid and all(core.split_key(k)[0] == cid for k in e["keys"]), ek

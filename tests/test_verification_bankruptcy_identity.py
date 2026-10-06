"""bankruptcy_stay v3: `stale` needs a verified identity, and a docket must be in the property's
district. Defect 7 of the 2026-10-06 recheck of all stale verdicts:

  A completed Chapter 13 in the Middle District of North Carolina (discharge orders and a final
  decree in 2024) was called stale for a McDowell County row, though McDowell is in the Western
  District, the docket caption has no middle name, and the same docket was attached by name to five
  board rows: almost certainly someone else.
  A Buncombe row's W.D.N.C. Chapter 13, dismissed 2026-09-21, was a CORRECT stale: the NC voter file
  holds exactly one registrant with the debtor's first name, middle name and last name, living at
  the row's address.

The docket and entry bodies are made-up names and numbers in the real CourtListener shapes (the
captured fixture of tests/test_verification_bankruptcy_stay.py serves the Tolland case); the voter
file and parcel roll are tiny made-up copies in the real column layouts. No network, and never the
real data/ directory.
"""
from __future__ import annotations

import asyncio
import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import bankruptcy_stay as b

FIX = Path(__file__).parent / "fixtures" / "verification" / "courtlistener_bankruptcy_stay.json.gz"
SERVED: dict = json.loads(gzip.decompress(FIX.read_bytes()))
TODAY = date(2026, 10, 6)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIFY_NCVOTER_DIR", str(tmp_path / "no_voter"))
    monkeypatch.setattr(b, "_roll_owner", lambda row: None, raising=False)


def run(row, extra=()):
    f = ReplayFetcher({**SERVED, **dict(extra)})
    return asyncio.run(b.verify(row, f, today=TODAY)), f


def _bk(court, case, dn, did):
    return {"court": court, "case_name": case, "docket_number": dn,
            "absolute_url": f"/docket/{did}/x/", "match_strategy": "strict_subset"}


def _row(owner, bk, county="Buncombe", address="1 MAIN ST", **kw):
    r = {"state": "NC", "county": county, "listing_type": "tax_lien", "owner_name": owner,
         "defendant": owner, "street_address": address, "parcel_id": "1111-11-1111-00000",
         "raw": {"bankruptcy": bk}}
    r.update(kw)
    return r


def _docket(did, court, dn, case, filed, terminated=None, entries=()):
    """The CourtListener search hit and the newest entries of one made-up docket."""
    hit = {"count": 1, "next": None, "previous": None, "results": [{
        "caseName": case, "case_name_full": "", "chapter": "13", "court_id": court,
        "dateFiled": filed, "dateTerminated": terminated, "docketNumber": dn,
        "docket_absolute_url": f"/docket/{did}/x/", "docket_id": did, "party": [case]}]}
    ents = {"count": len(entries), "next": None, "previous": None, "results": [
        {"date_filed": d, "description": "", "entry_number": n, "recap_documents": [{"description": t}]}
        for d, n, t in entries]}
    return [(b.SEARCH_BY_ID.format(id=did), json.dumps(hit)),
            (b.ENTRIES_URL.format(id=did), json.dumps(ents))]


# the shape of a completed M.D.N.C. Chapter 13 with a made-up debtor (no middle name in the caption)
QUILL = _docket(6684251, "ncmb", "16-10555", "Jamie Quill", "2016-06-27", entries=[
    ("2024-02-02", 156, "Final Decree/Case Closed"), ("2024-02-02", 155, "Bankruptcy Case Closed"),
    ("2024-01-16", 152, "Discharge of Debtor"), ("2024-01-16", 150, "Order Discharging Debtor"),
    ("2023-12-12", 148, "Trustee's Final Report")])


def quill_row(county="McDowell", **kw):
    return _row("QUILL JAMIE R", _bk("ncmb", "Jamie Quill", "16-10555", 6684251), county=county,
                address="000123 EXAMPLE DRIVE", **kw)


# ---------------------------------------------------------------------------
# the district table (28 U.S.C. 113)
# ---------------------------------------------------------------------------

def test_the_table_partitions_the_100_nc_counties_into_the_statutes_three_districts():
    t = b.NC_COUNTY_COURTS
    assert len(t) == 100
    single = {c: next(iter(v)) for c, v in t.items() if len(v) == 1}
    assert len(single) == 95 and {c for c in t if len(t[c]) == 2} == {
        "durham", "hoke", "moore", "richmond", "scotland"}            # Butner FCI / Fort Bragg
    assert sorted({v for v in single.values()}) == ["nceb", "ncmb", "ncwb"]
    assert (sum(v == "nceb" for v in single.values()), sum(v == "ncmb" for v in single.values()),
            sum(v == "ncwb" for v in single.values())) == (44, 19, 32)
    for county, court in [("mcdowell", "ncwb"), ("buncombe", "ncwb"), ("mecklenburg", "ncwb"),
                          ("cabarrus", "ncmb"), ("rowan", "ncmb"), ("guilford", "ncmb"),
                          ("wake", "nceb"), ("new hanover", "nceb"), ("pitt", "nceb")]:
        assert t[county] == frozenset({court}), county
    assert b.expected_courts("NC", "McDowell County") == frozenset({"ncwb"})
    assert b.expected_courts("SC", "Greenville") == frozenset({"scb"})
    assert b.expected_courts("NC", "Nowhere") is None and b.expected_courts("GA", "Fulton") is None


def test_wrong_district():
    assert b.wrong_district("ncmb", "NC", "McDowell") == frozenset({"ncwb"})
    assert b.wrong_district("ncwb", "NC", "McDowell") is None
    assert b.wrong_district("ncmb", "NC", "Moore") is None            # split county: both courts
    assert b.wrong_district("ncwb", "NC", "Moore") == frozenset({"ncmb", "nceb"})
    assert b.wrong_district("scb", "SC", "Aiken") is None
    assert b.wrong_district("ncwb", "SC", "Aiken") == frozenset({"scb"})
    assert b.wrong_district("ncwb", "NC", "Nowhere") is None          # unknown county: no claim


# ---------------------------------------------------------------------------
# bk:829544e1bea29bb7: stale -> unconfirmed
# ---------------------------------------------------------------------------

def test_a_completed_middle_district_case_on_a_western_district_county_is_not_stale():
    """v2: stale (closed + positional_match_unverified). v3: the court cannot cover McDowell."""
    r, f = run(quill_row(), QUILL)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "wrong_district"
    assert r.evidence["court"] == "ncmb" and r.evidence["expected_courts"] == ["ncwb"]
    assert b.ENTRIES_URL.format(id=6684251) not in f.asked              # decided before the entries


def test_the_same_case_in_a_county_of_its_district_still_needs_a_verified_identity():
    """Same docket, a Guilford (M.D.N.C.) row: right district, but the caption has no middle name
    and the owner has one: unverified, so a closed case is unconfirmed, not stale."""
    r, _ = run(quill_row(county="Guilford"), QUILL)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "identity_unverified"
    assert r.evidence["status"] == "closed" and r.evidence["owner_match"] == "unverified"
    assert r.evidence["decided_by"] == "closed+positional_match_unverified"


def test_an_open_case_with_an_unverified_identity_stays_confirmed():
    """Only 'stale' (the case is over, the signal comes out of the score) needs identity: a
    confirmed answer changes no score."""
    open_ = _docket(6684252, "ncwb", "26-10999", "Jamie Quill", "2026-08-01", entries=[
        ("2026-09-30", 20, "Motion to Extend"), ("2026-09-01", 12, "Notice of Hearing")])
    row = _row("QUILL JAMIE R", _bk("ncwb", "Jamie Quill", "26-10999", 6684252), county="Buncombe")
    r, _ = run(row, open_)
    assert r.verdict == "confirmed" and r.evidence["owner_match"] == "unverified"


# ---------------------------------------------------------------------------
# bk:6f14fdaf7289b8ad: the corroborated stale
# ---------------------------------------------------------------------------

TOLLAND = _row("TOLLAND, BRIAN", _bk("ncwb", "Brian Carl Tolland", "26-10161", 73600081),
               address="539 EXAMPLE VIEW RD")


def _voter(tmp_path, monkeypatch, people):
    d = tmp_path / "voter"
    d.mkdir(exist_ok=True)
    head = ["county_id", "county_desc", "voter_reg_num", "ncid", "last_name", "first_name", "middle_name",
            "name_suffix_lbl", "status_cd", "voter_status_desc", "res_street_address", "res_city_desc"]
    lines = ["\t".join(f'"{h}"' for h in head)]
    for i, (last, first, mid, status, addr) in enumerate(people):
        cells = ["11", "BUNCOMBE", f"{i:012d}", f"X{i}", last, first, mid, "", status[0], status, f"{addr}   ", "ASHEVILLE"]
        lines.append("\t".join(f'"{c}"' for c in cells))
    (d / "ncvoter11.txt").write_text("\n".join(lines) + "\n")
    monkeypatch.setenv("VERIFY_NCVOTER_DIR", str(d))


def test_one_voter_with_the_full_name_at_the_property_corroborates_the_stale(tmp_path, monkeypatch):
    _voter(tmp_path, monkeypatch, [("TOLLAND", "BRIAN", "CARL", "ACTIVE", "539 EXAMPLE VIEW RD"),
                                   ("TOLLAND", "BRIAN", "XAVIER", "ACTIVE", "12 ELSEWHERE LN"),
                                   ("TOLLAND", "BRYAN", "CARL", "ACTIVE", "539 EXAMPLE VIEW RD")])
    r, _ = run(TOLLAND)
    assert r.verdict == "stale" and r.evidence["identity_corroborated_by"] == "ncvoter"
    assert r.evidence["owner_match"] == "unverified"


@pytest.mark.parametrize("people,why", [
    ([("TOLLAND", "BRIAN", "CARL", "ACTIVE", "12 ELSEWHERE LN")], "lives elsewhere"),
    ([("TOLLAND", "BRIAN", "CARL", "ACTIVE", "539 EXAMPLE VIEW RD"),
      ("TOLLAND", "BRIAN", "C", "INACTIVE", "77 OTHER RD")], "two people with the full name"),
    ([("TOLLAND", "BRIAN", "CARL", "REMOVED", "539 EXAMPLE VIEW RD")], "removed from the rolls"),
    ([("TOLLAND", "BRIAN", "KEITH", "ACTIVE", "539 EXAMPLE VIEW RD")], "another middle name"),
    ([], "nobody"),
])
def test_anything_less_than_exactly_one_resident_with_the_full_name_does_not_corroborate(
        tmp_path, monkeypatch, people, why):
    _voter(tmp_path, monkeypatch, people)
    r, _ = run(TOLLAND)
    assert (r.verdict, r.evidence["reason"]) == ("unconfirmed", "identity_unverified"), why


def test_the_parcel_roll_corroborates_when_it_names_exactly_one_person_with_the_full_name(monkeypatch):
    monkeypatch.setattr(b, "_roll_owner", lambda row: "TOLLAND BRIAN C")
    r, _ = run(TOLLAND)
    assert r.verdict == "stale" and r.evidence["identity_corroborated_by"] == "parcel_roll"
    for owner in ("TOLLAND BRIAN C & TOLLAND ANN", "TOLLAND BRIAN C (DECEASED)", "TOLLAND BRIAN K",
                  "TOLLAND BRIAN", "TOLLAND HOLDINGS LLC"):
        monkeypatch.setattr(b, "_roll_owner", lambda row, o=owner: o)
        r, _ = run(TOLLAND)
        assert r.verdict == "unconfirmed", owner


def test_no_corroboration_is_possible_when_the_caption_has_no_middle_name(tmp_path, monkeypatch):
    """The completed-case shape: the caption names no middle, so no voter / roll entry can confirm it."""
    _voter(tmp_path, monkeypatch, [("QUILL", "JAMIE", "R", "ACTIVE", "123 EXAMPLE DR")])
    assert b.debtor_full_name("QUILL JAMIE R", "Jamie Quill") is None
    assert b.debtor_full_name("TOLLAND, BRIAN", "Brian Carl Tolland") == ("BRIAN", "CARL", "TOLLAND")
    assert b.debtor_full_name("TOLLAND BRIAN", "Ann Tolland and Brian Carl Tolland") == ("BRIAN", "CARL", "TOLLAND")
    r, _ = run(quill_row(county="Guilford"), QUILL)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "identity_unverified"


def test_the_voter_scan_reads_the_real_column_layout(tmp_path, monkeypatch):
    _voter(tmp_path, monkeypatch, [("VAN DYKE", "ANNA", "MARIE", "ACTIVE", "10 ELM ST")])
    got = b._voter_matches("Buncombe", ("ANNA", "MARIE", "VAN DYKE"), tmp_path / "voter")
    assert got == [{"address": "10 ELM ST"}]
    assert b._voter_matches("Henderson", ("ANNA", "MARIE", "VAN DYKE"), tmp_path / "voter") is None   # no file


def test_corroboration_never_raises_and_publishes_only_its_source(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "_roll_owner", lambda row: (_ for _ in ()).throw(RuntimeError("boom")))
    assert b.corroborate_identity(TOLLAND, "TOLLAND BRIAN", "Brian Carl Tolland") is None
    _voter(tmp_path, monkeypatch, [("TOLLAND", "BRIAN", "CARL", "ACTIVE", "539 EXAMPLE VIEW RD")])
    r, _ = run(TOLLAND)
    blob = json.dumps(r.evidence).upper()
    for w in ("TOLLAND", "BRIAN", "CARL", "EXAMPLE VIEW", "539"):
        assert w not in blob


def test_version_is_v4():
    """v4 (name patterns): the wrong_district / identity corroboration rules above are v3's and
    are unchanged."""
    assert b.VERSION == "v4"

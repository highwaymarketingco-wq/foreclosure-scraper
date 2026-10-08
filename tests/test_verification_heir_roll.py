"""heir_roll: the county roll re-read for an heirs/estate lead (made-up fixtures, no network)."""
from __future__ import annotations

import asyncio
import json

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.verifiers import heir_roll as H

ONEMAP = "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1"


def _row(**kw) -> dict:
    row = {"state": "NC", "county": "Edgecombe", "source": H.HEIR_SOURCE, "source_url": ONEMAP,
           "listing_type": "estate_lead", "parcel_id": "4700-11-2233", "owner_name": "SAMPLE ALPHA HEIRS",
           "first_seen": "2026-10-02T21:15:07",
           "raw": {"heir_estate": {"owner_of_record": "SAMPLE ALPHA HEIRS",
                                   "heir_names": [{"raw": "SAMPLE ALPHA HEIRS", "name": "SAMPLE ALPHA",
                                                   "role": "heir"}], "match": "heirs"},
                   "relationship_signal": {"kind": "probate", "keyword": "heir_estate_owner_of_record",
                                           "source": H.HEIR_SOURCE}}}
    raw = kw.pop("raw", None)
    row.update(kw)
    if raw:
        row["raw"].update(raw)
    return row


def _first_url(row: dict) -> str:
    from foreclosure_scraper.enrichment_owner_mailing import _pid_variants
    spec = H.layer_spec(row)
    cand = _pid_variants(row["parcel_id"])[0]
    cc = f" AND UPPER(cntyname)='{row['county'].upper()}'"
    return H.query_url(spec, f"parno LIKE '%{cand}%'{cc}", True)


def _answer(owner: str, parno: str = "4700-11-2233", **extra) -> str:
    a = {"parno": parno, "ownname": owner, "ownname2": None, "cntyname": "Edgecombe"}
    a.update(extra)
    return json.dumps({"features": [{"attributes": a}]})


def _run(row, responses):
    return asyncio.run(H.verify(row, ReplayFetcher(responses)))


def test_registered_and_scoped():
    v = {x.name: x for x in registry.discover()}["heir_roll"]
    assert v.signal == "heir_roll" and v.ttl_days == 30
    assert set(v.governs) == {"estate_lead", "probate_deed"}
    assert H.applies(_row())
    assert not H.applies(_row(county="Buncombe"))          # probate_heir_buncombe's
    assert not H.applies(_row(source="counties.example"))
    assert not H.applies(_row(parcel_id=None))


def test_roll_still_names_the_heirs_is_confirmed():
    r = _run(_row(), {_first_url(_row()): _answer("SAMPLE ALPHA HEIRS")})
    assert r.verdict == "confirmed" and r.evidence["reason"] == "roll_still_says_heirs"
    assert "SAMPLE" not in json.dumps(r.evidence)


def test_conveyed_to_an_unrelated_owner_is_stale_and_governs_both():
    r = _run(_row(), {_first_url(_row()): _answer("EXAMPLE HOLDINGS LLC", saledatetx="2026-10-05")})
    assert r.verdict == "stale" and r.evidence["reason"] == "conveyed_out"
    assert H.governs_for(r.to_dict()) == ("estate_lead", "probate_deed")


def test_a_sale_long_before_the_claim_is_not_stale():
    r = _run(_row(), {_first_url(_row()): _answer("EXAMPLE BUYER", saledatetx="2019-03-01")})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "sale_predates_claim"


def test_titled_to_family_is_unconfirmed():
    r = _run(_row(), {_first_url(_row()): _answer("SAMPLE BETA")})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "titled_to_family"


def test_no_death_word_then_or_now_is_refuted():
    row = _row(owner_name="SHEIRMAN ALPHA",
               raw={"heir_estate": {"owner_of_record": "SHEIRMAN ALPHA", "heir_names": []}})
    r = _run(row, {_first_url(row): _answer("SHEIRMAN ALPHA")})
    assert r.verdict == "refuted" and r.evidence["reason"] == "no_death_word_on_roll"


def test_another_parcel_returned_by_like_is_not_this_one():
    r = _run(_row(), {_first_url(_row()): _answer("SAMPLE ALPHA HEIRS", parno="14700-11-22339")})
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "parcel_not_found"


def test_layer_error_is_transient():
    row = _row()
    from foreclosure_scraper.enrichment_owner_mailing import _pid_variants
    spec = H.layer_spec(row)
    cc = f" AND UPPER(cntyname)='{row['county'].upper()}'"
    err = json.dumps({"error": {"code": 500}})
    resp = {}
    for cand in _pid_variants(row["parcel_id"]):
        for pf in ("parno", "altparno"):
            resp[H.query_url(spec, f"{pf} LIKE '%{cand}%'{cc}", True)] = err
    r = _run(row, resp)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "layer_error"
    v = {x.name: x for x in registry.discover()}["heir_roll"]
    assert v.is_transient(r.to_dict())


def test_a_deed_based_probate_deed_is_not_governed():
    row = _row(raw={"relationship_signal": {"kind": "probate", "keyword": "ESTATE OF",
                                            "source": "counties.example_deeds"}})
    r = _run(row, {_first_url(row): _answer("EXAMPLE HOLDINGS LLC", saledatetx="2026-10-05")})
    assert r.verdict == "stale"
    assert H.governs_for(r.to_dict()) == ("estate_lead",)

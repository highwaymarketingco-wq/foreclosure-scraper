"""obituary_match + heir_candidates. Every name is made up; no network."""
from __future__ import annotations

import gzip
import json

import pytest

from foreclosure_scraper.enrichment_heir_candidates import (
    candidates_for,
    deceased_signals,
    enrich_heir_candidates,
)
from foreclosure_scraper.enrichment_obituary_match import (
    enrich_obituary_match,
    match_rows,
    name_level,
    obit_person,
    owner_readings,
)
from foreclosure_scraper.heirs_store import ObituaryStore, read_heir_candidates
from foreclosure_scraper.models import Listing, ListingType

SURV = [
    {"name": "Lunetta Brask Tandry", "relation": "spouse"},
    {"name": "Corwin Tandry", "relation": "son"},
    {"name": "Rudd", "relation": "in_law", "spouse_of": "Wynnie Tandry Holcomb"},
    {"name": "Wynnie Tandry Holcomb", "relation": "daughter"},
]


def _obit(**kw):
    rec = {"url": "https://example-funeral.test/obituary/orvel-tandry", "source": "public_notices.obituary_feeds",
           "decedent": "Orvel Quimby Tandry", "state": "NC", "county": "Buncombe", "residence_city": "Weaverville",
           "age": 84, "birth_date": "1942-03-02", "death_date": "2026-09-28", "survivors": SURV,
           "unnamed": [{"relation": "grandchild", "count": 7}]}
    rec.update(kw)
    return rec


def _lead(owner, county="Buncombe", state="NC", **raw):
    return {"source": "counties_nc.buncombe_tax", "source_url": "https://example-county.test/parcel/1",
            "listing_type": "tax_lien", "owner_name": owner, "county": county, "state": state,
            "parcel_id": "9999-00-1111", "raw": dict(raw)}


# --------------------------------------------------------------------------- name rule

def test_name_levels():
    dec = obit_person("Orvel Quimby Tandry")
    full = owner_readings("TANDRY ORVEL QUIMBY")[0][0]
    init = owner_readings("TANDRY ORVEL Q")[0][0]
    bare = owner_readings("TANDRY ORVEL")[0][0]
    other = owner_readings("TANDRY ORVEL BAXTER")[0][0]
    assert name_level(full, dec)[0] == "full"
    assert name_level(init, dec)[0] == "middle_initial"
    lvl, why = name_level(bare, dec)
    assert lvl == "given_surname" and "no middle name" in why[0]
    assert name_level(other, dec)[0] is None
    jr = owner_readings("TANDRY ORVEL QUIMBY JR")[0][0]
    assert name_level(jr, dec)[0] is None          # a different suffix is another person


def test_trailing_v_on_roll_is_a_middle_initial():
    p = owner_readings("POPE HARLAN V HEIRS")[0][0]
    assert p.given == ["HARLAN", "V"] and p.suffix is None
    assert obit_person("Harlan V. Pope").given == ["HARLAN", "V"]


# --------------------------------------------------------------------------- match

def test_full_fit_attaches_with_survivors():
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    st = match_rows([lead], [_obit()])
    m = lead["raw"]["obituary_match"]
    assert st["attached"] == 1 and m["status"] == "attached"
    assert m["name_fit"]["level"] == "full"
    assert "Weaverville" in m["county_fit"]
    assert m["url"].endswith("orvel-tandry") and m["date"] == "2026-09-28"
    assert [s["name"] for s in m["survivors"]][:2] == ["Lunetta Brask Tandry", "Corwin Tandry"]


def test_no_middle_name_attaches_only_with_another_death_sign():
    dead = _lead("TANDRY ORVEL HEIRS")
    alive = _lead("TANDRY ORVEL")
    match_rows([dead, alive], [_obit()])
    assert dead["raw"]["obituary_match"]["status"] == "attached"
    assert dead["raw"]["obituary_match"]["name_fit"]["level"] == "given_surname"
    assert alive["raw"]["obituary_match"]["status"] == "ambiguous"
    assert "survivors" not in alive["raw"]["obituary_match"]


def test_middle_name_conflict_and_other_county_do_not_match():
    a = _lead("TANDRY ORVEL BAXTER HEIRS")
    b = _lead("TANDRY ORVEL QUIMBY HEIRS", county="McDowell")
    match_rows([a, b], [_obit()])
    assert "obituary_match" not in a["raw"]
    assert "obituary_match" not in b["raw"]


def test_funeral_home_county_stands_in_when_no_residence():
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    match_rows([lead], [_obit(residence_city=None)])
    assert "funeral home or paper" in lead["raw"]["obituary_match"]["county_fit"]


def test_two_different_deaths_are_ambiguous_and_not_attached():
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    other = _obit(url="https://example-paper.test/obits/orvel-tandry-1990", death_date="1990-01-05",
                  birth_date="1911-01-01", age=79)
    match_rows([lead], [_obit(), other])
    m = lead["raw"]["obituary_match"]
    assert m["status"] == "ambiguous" and len(m["candidates"]) == 2
    assert "survivors" not in m


def test_same_death_in_two_sources_is_one_death():
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    twin = _obit(url="https://example-aggregator.test/us/obituaries/nc/weaverville/orvel-tandry-1")
    match_rows([lead], [_obit(), twin])
    assert lead["raw"]["obituary_match"]["status"] == "attached"


def test_date_checks_rule_out():
    young = _lead("TANDRY ORVEL QUIMBY HEIRS", jail_booking={"roster_dob": "1990-05-05"})
    bought_after = _lead("TANDRY ORVEL QUIMBY", gis={"last_sale": {"date": "2026-10-01"}})
    match_rows([young, bought_after], [_obit()])
    assert "obituary_match" not in young["raw"]
    assert "obituary_match" not in bought_after["raw"]


def test_obituary_without_middle_fitting_two_different_owners_is_ambiguous():
    a = _lead("TANDRY ORVEL ALLEN HEIRS")
    b = _lead("TANDRY ORVEL BAXTER HEIRS")
    b["parcel_id"] = "9999-00-2222"
    match_rows([a, b], [_obit(decedent="Orvel Tandry")])
    assert a["raw"]["obituary_match"]["status"] == "ambiguous"
    assert b["raw"]["obituary_match"]["status"] == "ambiguous"


def test_obituary_rows_are_not_matched_to_themselves():
    row = _lead("Orvel Quimby Tandry")
    row["source"] = "public_notices.funeral_home_rss"
    match_rows([row], [_obit()])
    assert "obituary_match" not in row["raw"]


def test_store_harvest_and_pipeline_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    obit_row = Listing(source="public_notices.obituary_feeds", source_url="https://example-paper.test/obit/1",
                       listing_type=ListingType.PROBATE_NOTICE, state="NC", county="Polk",
                       owner_name="Velma Juno Crisp",
                       raw={"obituary": {"decedent": "Velma Juno Crisp", "county": "Polk", "state": "NC",
                                         "death_date": "2026-09-30", "residence_city": "Tryon"},
                            "obituary_private": {"survivors": [{"name": "Walt Crisp", "relation": "son"}]}})
    lead = Listing(source="counties_nc.polk_tax", source_url="https://example-county.test/p/2",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Polk", owner_name="CRISP VELMA JUNO",
                   parcel_id="P1")
    st = enrich_obituary_match([obit_row, lead])
    assert st["attached"] == 1
    assert lead.raw["obituary_match"]["survivors"][0]["name"] == "Walt Crisp"
    # a later run with no obituary row still matches from the private store
    lead2 = Listing(source="counties_nc.polk_tax", source_url="https://example-county.test/p/2",
                    listing_type=ListingType.TAX_LIEN, state="NC", county="Polk", owner_name="CRISP VELMA JUNO",
                    parcel_id="P1")
    st2 = enrich_obituary_match([lead2])
    assert st2["store_size"] == 1 and lead2.raw["obituary_match"]["status"] == "attached"
    assert ObituaryStore(tmp_path).load().records


# --------------------------------------------------------------------------- heir candidates

def test_signals():
    assert deceased_signals(_lead("ACME REAL ESTATE HOLDINGS LLC")) == []
    assert [s["kind"] for s in deceased_signals(_lead("TANDRY ORVEL HEIRS"))] == ["roll_heirs_estate"]
    row = _lead("TANDRY ORVEL", verification=[{"signal": "probate_heir", "verdict": "confirmed"}])
    assert [s["kind"] for s in deceased_signals(row)] == ["death_index"]


def test_obituary_survivors_become_candidates_in_laws_do_not():
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    match_rows([lead], [_obit()])
    c = candidates_for(lead)
    names = {(x["name"], x["relation"], x["source_kind"]) for x in c}
    assert ("Lunetta Brask Tandry", "spouse", "obituary_survivor") in names
    assert ("Corwin Tandry", "son", "obituary_survivor") in names
    assert ("Wynnie Tandry Holcomb", "daughter", "obituary_survivor") in names
    assert not any(x["name"] == "Rudd" for x in c)
    assert all(x["label"] == "candidate" and "not a finding" in x["confidence_note"] for x in c)
    assert all(x["source_url"].endswith("orvel-tandry") and x["source_date"] == "2026-09-28" for x in c)


def test_probate_representatives_with_printed_address_only():
    sc = _lead("Theron Mabry Wick", county="Cherokee", state="SC",
               sc_probate_notice={"estate": "Theron Mabry Wick", "case_number": "2026ES1100303",
                                  "personal_representative": "Ulla Wick Danner",
                                  "pr_address": "18 Pine Knob Dr, Gaffney, SC 29340"})
    c = candidates_for(sc)
    assert c[0]["source_kind"] == "probate_notice_personal_representative"
    assert c[0]["address"] == "18 Pine Knob Dr, Gaffney, SC 29340"
    assert "printed in the public notice" in c[0]["address_note"]
    nc = _lead("Oswin Tate", probate={"decedent": "Oswin Tate", "es_case_number": "26E001234",
                                     "personal_representative": "Philippa Rowan and Quill Tate",
                                     "pr_role": "Co-Executor"})
    c2 = candidates_for(nc)
    assert {x["name"] for x in c2} == {"Philippa Rowan", "Quill Tate"}
    assert all("address" not in x for x in c2)


def test_county_record_coowners_and_care_of():
    row = _lead("TANDRY ORVEL HEIRS; TANDRY LUNETTA B",
                heir_estate={"owner_of_record": "TANDRY ORVEL HEIRS; TANDRY LUNETTA B; C/O TANDRY CORWIN",
                             "heir_names": [{"raw": "TANDRY ORVEL HEIRS", "name": "TANDRY ORVEL", "role": "heir"},
                                            {"raw": "TANDRY LUNETTA B", "name": "TANDRY LUNETTA B", "role": "other"},
                                            {"raw": "C/O TANDRY CORWIN", "name": "C/O TANDRY CORWIN", "role": "other"},
                                            {"raw": "TANDRY ORVEL JR", "name": "TANDRY ORVEL JR", "role": "other"}]})
    c = candidates_for(row)
    got = {(x["name"], x["relation"]) for x in c}
    assert ("TANDRY LUNETTA B", "co-owner of record on the tax roll") in got
    assert ("TANDRY CORWIN", "care-of addressee on the tax roll") in got
    assert ("TANDRY ORVEL JR", "co-owner of record on the tax roll") in got     # the son, not the decedent
    assert not any(x["name"] in ("TANDRY ORVEL",) for x in c)


def test_enricher_summary_has_no_names_and_private_file_does(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRS_PRIVATE_DIR", str(tmp_path))
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    match_rows([lead], [_obit()])
    st = enrich_heir_candidates([lead, _lead("SMITH ALIVE PERSON")])
    assert st["dead_owner_leads"] == 1 and st["with_candidates"] == 1
    summ = lead["raw"]["heir_candidates_summary"]
    blob = json.dumps(summ)
    for nm in ("Lunetta", "Corwin", "Wynnie", "Tandry"):
        assert nm not in blob
    assert summ["count"] == 3 and summ["by_source_kind"] == {"obituary_survivor": 3}
    assert summ["obituary_match"] == "attached"
    priv = read_heir_candidates(tmp_path)
    assert priv and priv[0]["heir_candidates"][0]["name"] == "Lunetta Brask Tandry"


def test_publish_keeps_summary_and_drops_names():
    from foreclosure_scraper.web_artifact import _slim_raw
    lead = _lead("TANDRY ORVEL QUIMBY HEIRS")
    match_rows([lead], [_obit()])
    enrich_heir_candidates([lead], private_out=False)
    pub = _slim_raw(lead["raw"])
    assert "heir_candidates" not in pub and "obituary_match" not in pub
    assert pub["heir_candidates_summary"]["count"] == 3
    assert "Lunetta" not in json.dumps(pub)

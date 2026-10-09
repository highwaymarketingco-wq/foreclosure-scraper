"""Register 'checked' verdicts + marriage index (rod/register_checks.py, enrichment_register_checks.py).
Made-up owners, books and pages; the register lookups are replaced by fakes, so nothing touches a network."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

import foreclosure_scraper.enrichment_register_checks as E
from foreclosure_scraper.rod import cott, nc_cott_v4, nc_ors, nc_tyler, sc_cott_esearch
from foreclosure_scraper.rod import register_checks as RC
from foreclosure_scraper.rod.nc_chain import IndexRecord, OwnerName, parse_owner

NOW = "2026-10-10T00:00:00+00:00"


def rec(doc_type="DEED", g=("ZZTEST, ALICE",), e=("ZZOTHER, BOB",), index_code=None, book="1", page="2"):
    return IndexRecord(recorded="2020-01-02", book=book, page=page, doc_type=doc_type, grantors=list(g),
                       grantees=list(e), index_code=index_code)


# ---- pure helpers ---------------------------------------------------------------------------------

def test_marriage_block_names_the_other_spouse_and_keeps_the_book_page():
    who = parse_owner("ZZTEST ALICE")
    r = rec(doc_type="MARRIAGE", g=("ZZTEST, ALICE",), e=("ZZSPOUSE, CAROL",), book="42", page="777")
    b = RC.marriage_block([r], who, county="Onslow", now_iso=NOW)
    assert b["spouse_name"] == "Zzspouse, Carol" and (b["book"], b["page"]) == ("42", "777")
    assert b["match_confidence"] == "high" and b["checked_at"] == NOW and b["source"] == "register_checks"


def test_a_blank_type_row_under_the_mar_index_is_a_marriage():
    who = parse_owner("ZZTEST ALICE")
    r = rec(doc_type="", index_code="MAR", g=("ZZSPOUSE, CAROL",), e=("ZZTEST, ALICE",))
    assert RC.is_marriage_record(r)
    assert RC.marriage_block([r], who, county="Alamance", now_iso=NOW)["spouse_name"] == "Zzspouse, Carol"


def test_a_deed_is_not_a_marriage_and_another_surname_does_not_match():
    who = parse_owner("ZZTEST ALICE")
    assert RC.marriage_block([rec(doc_type="DEED")], who, county="Onslow", now_iso=NOW) is None
    other = rec(doc_type="MARRIAGE", g=("QQNOPE, DAN",), e=("QQNOPE, EVE",))
    assert RC.marriage_block([other], who, county="Onslow", now_iso=NOW) is None


def test_first_name_stem_has_to_agree():
    who = parse_owner("ZZTEST ALICE")
    r = rec(doc_type="MARRIAGE", g=("ZZTEST, ZACHARY",), e=("ZZSPOUSE, CAROL",))
    assert RC.marriage_block([r], who, county="Onslow", now_iso=NOW) is None


def test_entity_owner_matching_needs_its_first_two_words():
    ent = OwnerName(raw="ACME HOLDINGS LLC", last="ACME HOLDINGS", entity=True)
    assert RC.owner_instruments([rec(g=("ACME HOLDINGS LLC",))], ent)
    assert not RC.owner_instruments([rec(g=("ACME ROOFING LLC",))], ent)


def test_empty_block_counts_as_a_pull_with_nothing_in_it():
    b = RC.empty_rod_block(NOW, "cott_esearch_v4")
    assert b["instrument_count"] == 0 and b["instruments"] == [] and b["screened_none_found"] is True
    assert b["fetched_at"] == NOW and b["has_mortgage"] is False and b["has_adverse_lien"] is False


def test_marriage_verdicts_only_stamp_index_counties():
    for co in ("Onslow", "Alamance", "Alexander", "Pamlico", "Edgecombe", "Rutherford"):
        assert RC.marriage_stampable("NC", co)
    for co in ("Pitt", "Polk", "Graham", "Nash", "Rowan", "Forsyth", "Davidson"):
        assert not RC.marriage_stampable("NC", co)
        assert RC.marriage_verdict("NC", co)["evidence"]
    assert RC.marriage_verdict("NC", "Onslow County")["verdict"] == "index"


def test_marriage_adapter_counties_are_exactly_the_index_counties():
    assert sorted(RC.MARRIAGE_ADAPTER.counties) == ["Alamance", "Alexander", "Edgecombe", "Onslow", "Pamlico",
                                                    "Rutherford"]
    assert RC.MARRIAGE_ADAPTER.platform != "cott_esearch_v4"        # its own per-county lookup budget


# ---- the status interface generic_rod stamps from -------------------------------------------------

@pytest.mark.parametrize("mod", [nc_cott_v4, nc_tyler, nc_ors, cott, sc_cott_esearch])
def test_every_module_of_the_group_reports_a_status(mod):
    assert asyncio.iscoroutinefunction(mod.search_by_name_status)


def test_cott_polk_status_goes_through_the_paced_v4_adapter(monkeypatch):
    seen = {}

    async def fake(state, county, name, max_docs):
        seen["args"] = (state, county, name)
        return [], "ok", False

    monkeypatch.setattr(nc_cott_v4.ADAPTER, "search_by_name_status", fake)
    assert asyncio.run(cott.search_by_name_status("NC", "Polk", "ZZTEST ALICE")) == ([], "ok", False)
    assert seen["args"] == ("NC", "Polk", "ZZTEST ALICE")
    assert asyncio.run(cott.search_by_name_status("NC", "Nowhere", "ZZTEST ALICE"))[1] == "error"


def test_generic_rod_stamps_a_clean_empty_answer_for_a_cott_county(monkeypatch):
    import foreclosure_scraper.enrichment_generic_rod as G

    async def status(state, county, name, max_docs):
        return [], "ok", False

    monkeypatch.setattr(nc_cott_v4, "search_by_name_status", status)
    monkeypatch.setenv("FORECLOSURE_NC_COTT_ROD", "1")
    from foreclosure_scraper.models import Listing, ListingType
    li = Listing(source="t", source_url="https://example.org/x", listing_type=ListingType.TAX_LIEN, state="NC",
                 county="Pitt", owner_name="ZZTEST ALICE")
    asyncio.run(G.enrich_generic_rod([li]))
    assert li.raw["rod"]["screened_none_found"] is True and li.raw["rod"]["instrument_count"] == 0


# ---- the marriage enricher, lookups faked ---------------------------------------------------------

def lead(county="Onslow", owner="ZZTEST ALICE", state="NC", raw=None):
    return NS(state=state, county=county, owner_name=owner, raw=raw if raw is not None else {}, sale_date=None)


@pytest.fixture
def fake(monkeypatch):
    box = {"mar": ("ok", [], False), "calls": []}

    def marriage(county, owner):
        box["calls"].append(county)
        st, recs, tr = box["mar"]
        return st, recs, tr, parse_owner(owner)

    monkeypatch.setattr(E, "marriage_lookup", marriage)
    monkeypatch.setenv(E.COTT_FLAG, "1")
    monkeypatch.setenv(E.SWEEP_FLAG, "0")            # the sweeps have their own tests (test_cott_sweep.py)
    monkeypatch.delenv(E.ENV_FLAG, raising=False)
    return box


def run(leads):
    return asyncio.run(E.enrich_register_checks(leads))


def test_clean_answer_is_a_dated_no_match_only_in_index_counties(fake):
    L = [lead("Onslow"), lead("Pitt"), lead("Forsyth"), lead("Rowan")]
    st = run(L)
    assert L[0].raw["marriage_license"]["status"] == "no_match" and L[0].raw["marriage_license"]["checked_at"]
    assert all("marriage_license" not in x.raw for x in L[1:])
    assert fake["calls"] == ["Onslow"] and st["no_match"] == 1


def test_match_is_written_with_the_spouse(fake):
    fake["mar"] = ("ok", [rec(doc_type="MARRIAGE", g=("ZZTEST, ALICE",), e=("ZZSPOUSE, CAROL",))], False)
    L = [lead("Rutherford")]
    run(L)
    assert L[0].raw["marriage_license"]["spouse_name"] == "Zzspouse, Carol"


@pytest.mark.parametrize("status,trunc", [("walled", False), ("capped", False), ("too_many", False),
                                          ("error", False), ("ok", True)])
def test_failed_or_truncated_answers_stamp_nothing(fake, status, trunc):
    fake["mar"] = (status, [], trunc)
    L = [lead("Onslow")]
    run(L)
    assert "marriage_license" not in L[0].raw


def test_existing_blocks_are_not_searched_again(fake):
    L = [lead("Onslow", raw={"marriage_license": {"status": "no_match", "checked_at": NOW}})]
    run(L)
    assert not fake["calls"]


def test_an_entity_owner_is_not_marriage_searched():
    assert E.marriage_lookup("Onslow", "ACME HOLDINGS LLC")[0] == "noname"


def test_flags(fake, monkeypatch):
    monkeypatch.setenv(E.ENV_FLAG, "0")
    L = [lead("Onslow")]
    assert run(L).get("disabled") and not fake["calls"]
    monkeypatch.delenv(E.ENV_FLAG)
    monkeypatch.setenv(E.COTT_FLAG, "0")
    assert run([lead("Onslow")])["disabled_counties"] >= 1 and not fake["calls"]


def test_a_walled_county_stops_after_the_first_answer(fake):
    fake["mar"] = ("walled", [], False)
    run([lead("Onslow"), lead("Onslow", owner="ZZTEST BOB")])
    assert fake["calls"] == ["Onslow"]

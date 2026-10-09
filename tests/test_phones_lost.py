"""Audit 2026-10-09 phones_lost: owner phones the reconciled board lost against the live board.
All names, ids, addresses and phones below are made up.

Three defects, one test group each:
  1. verification.core.address_key kept a comma-less city ("900 X RD CHARLOTTE NC 28207") and read
     "AV" as a street word, so a LiensNC filing for the row's own house read as another address and
     block_binding removed the filing and the owner's own phone with it;
  2. a filing's phone was judged by its address only: a builder's number in the filing's "Owner"
     section stayed on the homeowner's row (one number on rows of six owners);
  3. Lincoln delinquent-tax rows keyed by the county's short AKPAR id: validation nulled it, the
     older PIN row of the same property was dropped by the next run, and its phone with it.
"""
from __future__ import annotations

import json
from datetime import datetime

from foreclosure_scraper import block_binding as bb
from foreclosure_scraper import nc_lincoln_bulk as lb
from foreclosure_scraper import parcel_alias as pa
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.validation import validate
from foreclosure_scraper.verification.core import address_key, address_relation

# --------------------------------------------------------------------------------------------
# 1. the address relation
# --------------------------------------------------------------------------------------------


def test_comma_less_city_state_zip_tail_is_not_part_of_the_street():
    assert address_relation("900 SAMPLE RD CHARLOTTE NC 28207", "900 Sample Rd") == "match"
    assert address_relation("617 TESTER ST DAVIDSON NC 28036", "617 Tester St") == "match"
    assert address_key("100 N MAPLE ST NE CHARLOTTE NC 28202") == address_key("100 N Maple St NE")
    # a city that is itself a suffix word stays out too
    assert address_relation("12 HIGH POINT RD HIGH POINT NC", "12 High Point Rd") == "match"


def test_av_is_avenue():
    assert address_relation("2323 SAMPLE AV", "2323 Sample Ave") == "match"


def test_a_different_house_still_conflicts_and_no_suffix_drops_nothing():
    assert address_relation("31 SAMPLE RD ASHEVILLE NC", "86 Sample Rd") == "conflict"
    assert address_relation("31 SAMPLE RD ASHEVILLE NC", "31 Other Rd") == "conflict"
    # no suffix before the state: the city cannot be told from the street, so nothing is dropped
    num, name, _ = address_key("5 SAMPLE CHARLOTTE NC")
    assert num == "5" and name == frozenset({"SAMPLE", "CHARLOTTE"})


# --------------------------------------------------------------------------------------------
# 2. LiensNC filing contacts
# --------------------------------------------------------------------------------------------

def _filing(addr: str, owner_line: str) -> dict:
    return {"entry_number": "1000001", "filing_type": "Appointment of Lien Agent",
            "address": addr, "owner_text": f"{owner_line}\n{addr}"}


def _phone(num: str = "(704) 555-0101") -> dict:
    return {"phone": num, "additional_phones": [], "source": "liensnc_filing",
            "match": "self_filed_lien_agent_appointment", "needs_dnc_scrub": True}


def _row(owner: str, addr: str, filing_owner: str, phone: str = "(704) 555-0101",
         source: str = "counties_nc.nc_metro_demolition_permits", parcel: str = "11111111") -> dict:
    return {"source": source, "state": "NC", "county": "Mecklenburg", "parcel_id": parcel,
            "street_address": addr, "owner_name": owner,
            "raw": {"liensnc": _filing(addr.split(" CHARLOTTE")[0].title(), filing_owner),
                    "owner_phone": _phone(phone),
                    "gis": {"owner": owner}}}


def _scrub(rows: list[dict]) -> list[tuple]:
    rec: list = []
    bb.scrub_unbound_blocks(rows, record=rec, points=set())
    return rec


def test_the_owners_own_filing_phone_stays_when_the_row_address_has_a_city_tail():
    row = _row("PAT Q SAMPLE", "900 SAMPLE RD CHARLOTTE NC 28207", "Pat Sample")
    assert _scrub([row]) == []
    assert row["raw"]["owner_phone"]["phone"] == "(704) 555-0101"
    assert "liensnc" in row["raw"]


def test_a_filing_phone_that_names_the_builder_leaves_the_homeowners_row():
    row = _row("PAT Q SAMPLE", "900 SAMPLE RD CHARLOTTE NC 28207", "Example Builders")
    rec = _scrub([row])
    assert ("owner_phone" in {r[1] for r in rec}) and "owner_phone" not in row["raw"]
    assert dict((r[1], r[2]) for r in rec)["owner_phone"] == "other_person"


def test_a_filing_phone_on_its_own_liensnc_row_naming_the_builder_leaves_it():
    row = _row("PAT Q SAMPLE", "900 SAMPLE RD", "Example Builders", source="counties_generic.liensnc")
    _scrub([row])
    assert "owner_phone" not in row["raw"]


def _three_owners():
    return [_row("PAT Q SAMPLE", "900 SAMPLE RD", "Pat Sample", source="counties_generic.liensnc",
                 parcel="11111111"),
            _row("LEE R EXAMPLE", "12 OTHER ST", "Lee Example", source="counties_generic.liensnc",
                 parcel="22222222"),
            _row("KIM TESTER", "5 THIRD AVE", "Kim Tester", source="counties_generic.liensnc",
                 parcel="44444444")]


def test_one_filing_phone_on_rows_of_three_owners_is_the_filers_line():
    rec = _scrub(_three_owners())
    assert {(r[0], r[1], r[2]) for r in rec} == {(i, "owner_phone", "shared_copy") for i in (0, 1, 2)}


def test_an_owner_and_their_company_on_one_number_keep_it():
    a = _row("PAT Q SAMPLE", "900 SAMPLE RD", "Pat Sample", source="counties_generic.liensnc",
             parcel="11111111")
    b = _row("EXAMPLE VENTURES INC", "12 OTHER ST", "Example Ventures Inc",
             source="counties_generic.liensnc", parcel="22222222")
    assert _scrub([a, b]) == []


def test_one_owner_with_two_properties_keeps_the_filing_phone_on_both():
    a = _row("PAT Q SAMPLE", "900 SAMPLE RD", "Pat Sample", source="counties_generic.liensnc",
             parcel="11111111")
    b = _row("PAT Q SAMPLE", "12 OTHER ST", "Pat Sample", source="counties_generic.liensnc",
             parcel="22222222")
    assert _scrub([a, b]) == []


def test_a_builder_line_stays_on_the_builders_lots_and_leaves_a_buyers_row():
    lots = [_row("EXAMPLE BUILDERS LLC", f"{n} NEW LOT LN", "Example Builders LLC",
                 source="counties_generic.liensnc", parcel=f"3333333{n}") for n in (1, 2, 3)]
    buyer = _row("PAT Q SAMPLE", "4 NEW LOT LN", "Pat Sample", source="counties_generic.liensnc",
                 parcel="33333334")
    rec = _scrub(lots + [buyer])
    assert {(r[0], r[1]) for r in rec} == {(3, "owner_phone")}
    assert all("owner_phone" in r["raw"] for r in lots)


# --------------------------------------------------------------------------------------------
# 2b. scrub order: a person verdict is not taken from a block leaving in the same round
# --------------------------------------------------------------------------------------------

def test_the_roll_owners_phone_stays_when_the_block_backing_the_row_owner_is_unbound():
    row = {"source": "counties_nc.asheville_str_permits", "state": "NC", "county": "Buncombe",
           "parcel_id": "9600000001", "street_address": "2 SAMPLE RD", "owner_name": "PERMIT HOLDER",
           "raw": {
               "gis": {"owner": "ROLL OWNER"},
               # a roll mailing of ANOTHER parcel that happens to name the permit holder
               "owner_mailing": {"owner": "PERMIT HOLDER", "parcel_id": "9600000999",
                                 "mailing": "9 ELSEWHERE RD", "source": "county_gis"},
               "owner_phone": {"phone": "(828) 555-0102", "source": "buncombe_accela",
                               "county_owner": "ROLL OWNER", "match": "parcel_id"},
           }}
    rec = _scrub([row])
    assert ("owner_mailing", "other_parcel") in {(r[1], r[2]) for r in rec}
    assert "owner_phone" in row["raw"]


# --------------------------------------------------------------------------------------------
# 3. Lincoln AKPAR rows
# --------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 9, 2, 0, 0)
PRIOR_T = datetime(2026, 10, 7, 15, 0, 0)
SRC = "counties_nc.nc_county_pdf_delinquent_tax"


def lincoln_tax(parcel_id, short="59001", addr="10 SAMPLE HWY") -> Listing:
    return Listing(source=SRC, source_url="https://example.invalid/lincoln.pdf",
                   listing_type=ListingType.TAX_LIEN, state="NC", county="Lincoln",
                   parcel_id=parcel_id, street_address=addr, first_seen=NOW, last_seen=NOW,
                   raw={"nc_county_pdf_delinquent_tax": {"county": "Lincoln", "county_id": short,
                                                         "id_is_parcel": True}})


def test_adopt_pin_gives_an_akpar_row_its_pin_and_keeps_the_short_id():
    li = lincoln_tax("59001")
    assert lb.adopt_pin(li, {"parcel_id": "3600000001", "akpar": "59001"})
    assert li.parcel_id == "3600000001"
    assert li.raw["parcel_id_alias"] == {"short": "59001", "long": "3600000001"}
    # a row already on its PIN, or a record whose PIN is not 10 digits, is left alone
    assert not lb.adopt_pin(lincoln_tax("3600000001"), {"parcel_id": "3600000001", "akpar": "59001"})
    assert not lb.adopt_pin(lincoln_tax("59001"), {"parcel_id": "36000", "akpar": "59001"})


def test_alias_source_registered_for_lincoln_akpar():
    assert pa.ALIAS_SOURCES[SRC] == ("nc_county_pdf_delinquent_tax", "county_id")
    # a Catawba / McDowell row carries county_id == parcel_id and is never re-keyed
    same = lincoln_tax("1234567890", short="1234567890").model_dump(mode="json")
    keys = pa.fresh_short_keys([lincoln_tax("59001")])
    assert pa.canonical_prior(same, {}, keys, None)[1] is None
    # McDowell's county_id is a 12-digit parcel number of its own: never a second (alias) id
    assert pa.short_id_of(lincoln_tax("065800000001", short="172800000002")) is None
    assert pa.short_id_of(lincoln_tax("59001")) == "59001"


def test_the_next_scrape_folds_the_pin_row_and_keeps_its_phone(tmp_path):
    pin_row = lincoln_tax("3600000001")                   # the PIN row a resolver / adopt_pin gave
    pin_row.first_seen = pin_row.last_seen = PRIOR_T
    pin_row.raw["owner_phone"] = {"phone": "(704) 555-0103", "source": "lincoln_taxpayer"}
    nulled = lincoln_tax("59001")                         # the parcel-less copy of the same row
    nulled.first_seen = nulled.last_seen = PRIOR_T
    validate([nulled])
    assert nulled.parcel_id is None
    (tmp_path / "listings.json").write_text(
        json.dumps([r.model_dump(mode="json") for r in (pin_row, nulled)]))
    fresh = lincoln_tax("59001")                          # the scrape prints the short id again
    merged, _st = merge_prior_board([fresh], docs_dir=tmp_path, now=NOW)
    same = [li for li in merged if (li.street_address or "") == "10 SAMPLE HWY"]
    assert len(same) == 1
    assert (same[0].raw or {}).get("owner_phone", {}).get("phone") == "(704) 555-0103"


# --------------------------------------------------------------------------------------------
# the invariants (scripts/audit_checks/phones_lost.py)
# --------------------------------------------------------------------------------------------

def _checks():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "phones_lost.py"
    spec = importlib.util.spec_from_file_location("audit_phones_lost", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {c.name: c for c in mod.make_checks()}


def test_invariants_pass_a_clean_board_and_catch_each_defect():
    cs = _checks()
    clean = [_row("PAT Q SAMPLE", "900 SAMPLE RD CHARLOTTE NC 28207", "Pat Sample", parcel="11111111"),
             lincoln_tax("3600000001").model_dump(mode="json")]
    for r in clean:
        for c in cs.values():
            c.feed(r)
    assert all(c.finish()["ok"] for c in cs.values())

    cs = _checks()
    unkeyed = lincoln_tax(None).model_dump(mode="json")
    unkeyed["raw"]["lincoln_bulk"] = {"parcel_id": "3600000001", "akpar": "59001"}
    dup_pin = lincoln_tax("3600000001").model_dump(mode="json")
    for r in (*_three_owners(), unkeyed, dup_pin):
        for c in cs.values():
            c.feed(r)
    got = {n: c.finish() for n, c in cs.items()}
    assert got["phones-filing-line-shared"]["violations"] == 3
    assert got["phones-lincoln-akpar-unkeyed"]["violations"] == 1
    assert got["phones-lincoln-akpar-duplicate"]["violations"] == 1


def test_the_normalizer_check_flags_a_city_tail_conflict(monkeypatch):
    cs = _checks()
    c = cs["phones-address-tail-normalizer"]
    row = _row("PAT Q SAMPLE", "900 SAMPLE RD CHARLOTTE NC 28207", "Pat Sample")
    row["city"] = "Charlotte"
    c.feed(row)
    assert c.finish() | {} and c.checked == 1 and c.violations == 0
    # the old normalizer called these two one house a conflict
    monkeypatch.setitem(type(c).feed.__globals__, "address_relation", lambda a, b: "conflict")
    c2 = type(c)()
    c2.feed(row)
    assert c2.finish()["violations"] == 1

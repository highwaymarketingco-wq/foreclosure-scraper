"""The probate_heir verifier (verification/verifiers/probate_heir_buncombe.py): Buncombe NC probate /
heir-estate claims against the ROD DEATHS index, the county parcel layer and the decedent's own
ROD instruments, with heir voter liveness as evidence only.

What these pin:
  * the live verdicts of 2026-10-06 reproduce exactly from the sweep's own responses
    (tests/fixtures/verification/probate_heir_buncombe.json.gz: county-layer JSON, DEATHS and CRP
    result pages reduced to the grid, voter searches; every person-name word replaced through ONE
    mapping that keeps first letters, middle initials, suffixes and markers; the rows in
    probate_heir_cases.json, pseudonymized the same way);
  * every verdict path on constructed grids: confirmed (death record + heirs / decedent of
    record), stale (A vesting deed out of the decedent after the death, B the decedent acquired
    and an unrelated buyer took title after the death, C the roll's own heirs title conveyed since
    it was read, D a deed out the layer has not caught up with), refuted only on positive contrary
    evidence (R0 the roll never named a death, R1 sold alive two years before the death, R2 the
    "decedent" signed for this parcel after the claim), each guard, and unconfirmed otherwise;
  * identity: a parent's record (grantee side), a wife indexed "<husband> MRS", a middle-initial
    conflict, JR vs SR, the reading order of ALL-CAPS heirs lines, an ambiguous common name;
  * a block is wall and stops later rows; a row with no decedent makes no request;
  * no person name, voter id or address in any published evidence; heir liveness is counts only
    and never changes a verdict;
  * scoring: refuted / stale drop probate, probate_notice, estate_lead and probate_deed; the other
    verdicts change nothing. All names in this file are made up.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import foreclosure_rod_buncombe as F
from foreclosure_scraper.verification.verifiers import probate_heir_buncombe as ph

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 6)


@pytest.fixture(autouse=True)
def _fresh_run_state():
    F._RUNS.clear()
    yield
    F._RUNS.clear()


def _doc(n, *, date=None, year=None, type_="DEED", grantors=(), grantees=(), matched=(),
         side="grantor", bp=None, desc="", refs=()):
    return {"n": n, "date": date, "year": year or (int(date[:4]) if date else None), "type": type_,
            "grantors": list(grantors), "grantees": list(grantees), "matched": list(matched),
            "matched_side": side, "desc": desc, "bp": bp, "refs": list(refs)}


def _claim(**kw):
    c = {"listing_type": "estate_lead", "source": "counties_nc.nc_heir_estate_parcels",
         "dates": {"first_seen": "2026-07-22"}, "death_by": "2026-07-22"}
    c.update(kw)
    return c


def _parcel(owner, **kw):
    a = {"pin": "9700000001", "pinext": "00000", "owner": owner, "DeedBook": "1200",
         "DeedPage": "0300", "DeedDate": "19800801", "Instrument": "DEE", "Stamps": 0.0,
         "SalePrice": 0.0, "HouseNumber": "12", "streetname": "QUILL", "SubName": "", "SubLot": "",
         "PlatBook": "", "PlatPage": ""}
    a.update(kw)
    return a


DEC = ("PELLWORTH", "ODESSA", "M")
MATCHED = {"match": "matched", "basis": "middle_agrees", "recorded_year": 2015, "book_page": "102/77"}
NOT_FOUND = {"match": "not_found"}


def decide(parcel, death=MATCHED, chain=None, claim=None, dec=DEC, **kw):
    return ph.decide(claim or _claim(), parcel, dec, death, chain, others=kw.pop("others", []),
                     today=TODAY, **kw)


# ---------------------------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------------------------

def test_the_registry_finds_it_with_its_contract():
    v = next(v for v in discover() if v.signal == "probate_heir")
    assert v.name == "probate_heir_buncombe" and v.version == ph.VERSION
    assert v.governs == ("probate", "probate_notice", "estate_lead", "probate_deed")
    assert v.ttl_days == 30 and v.retry_days == 7 and not v.wall and v.identity == "case"
    assert ph.ROW_SUMMARY_EXCLUDE == ("owner_name", "street_address")


def test_its_ledger_is_not_the_human_lanes():
    from foreclosure_scraper import verification_human_lane as hl
    assert ph.SIGNAL not in hl.LEDGER_TTL_DAYS
    assert {"probate", "heir_estate"} <= set(hl.LEDGER_TTL_DAYS)


def test_governs_only_names_the_scorer_knows():
    for name in ph.GOVERNS:
        assert name in ds.SIGNAL_CATEGORY and ds.SIGNAL_CATEGORY[name] == "LIFE_EVENT"


# ---------------------------------------------------------------------------------------------
# applies / the decedent / the claim
# ---------------------------------------------------------------------------------------------

BUN = {"state": "NC", "county": "Buncombe"}


@pytest.mark.parametrize("row,ok", [
    ({**BUN, "listing_type": "probate_notice"}, True),
    ({**BUN, "listing_type": "estate_lead"}, True),
    ({"state": "NC", "county": "Henderson", "listing_type": "probate_notice"}, False),
    ({"state": "SC", "county": "Buncombe", "listing_type": "probate_notice"}, False),
    ({**BUN, "listing_type": "tax_lien", "raw": {"probate": {"decedent": "Odessa Pellworth"}}}, True),
    ({**BUN, "listing_type": "tax_lien", "raw": {"probate": {"date_of_death": "2026-01-01"}}}, False),
    ({**BUN, "listing_type": "tax_lien", "raw": {"heir_estate": {"owner_of_record": "X Y HEIRS"}}}, True),
    ({**BUN, "listing_type": "tax_lien", "owner_name": "ODESSA PELLWORTH HEIRS",
      "raw": {"life_events": ["estate_probate"]}}, True),
    ({**BUN, "listing_type": "tax_lien", "owner_name": "PELLWORTH ODESSA",
      "raw": {"life_events": ["estate_probate"]}}, False),
    ({**BUN, "listing_type": "tax_lien",
      "raw": {"relationship_signal": {"kind": "probate", "keyword": "obituary"}}}, False),
])
def test_applies(row, ok):
    assert ph.applies(row) is ok


@pytest.mark.parametrize("row,field,first", [
    ({"raw": {"probate": {"decedent": "Odessa M. Pellworth"}}, "defendant": "Someone Else",
      "listing_type": "probate_notice"}, "probate.decedent", ("PELLWORTH", "ODESSA", "M")),
    ({"raw": {"probate": {"decedent": "deceased"}}, "listing_type": "probate_notice",
      "defendant": "Said Deceased To Exhibit",
      "description": "NOTICE TO CREDITORS Having qualified as Administrator of the Estate of "
                     "Odessa M Pellworth, deceased, late of Buncombe County"},
     "description", ("PELLWORTH", "ODESSA", "M")),
    ({"listing_type": "probate_notice",
      "description": "All persons having claims against Quentin Arlo O’Varra a/k/a Quentin "
                     "O’Varra, late of Buncombe County"},
     "description", ("OVARRA", "QUENTIN", "A")),
    ({"raw": {"obituary": {"decedent": "Quentin “Quint” Van Hollen"}},
      "listing_type": "probate_notice"}, "obituary.decedent", ("VAN HOLLEN", "QUENTIN", "")),
    ({"raw": {"heir_estate": {"owner_of_record": "ODESSA M PELLWORTH HEIRS",
                              "heir_names": [{"name": "ODESSA M PELLWORTH", "role": "heir"}]}},
      "listing_type": "estate_lead"}, "heir_estate.heir_names", ("PELLWORTH", "ODESSA", "M")),
    ({"raw": {"heir_estate": {"owner_of_record": "HEIRS OF ODESSA M PELLWORTH",
                              "heir_names": [{"name": "OF ODESSA M PELLWORTH", "role": "heir"}]}},
      "listing_type": "estate_lead"}, "heir_estate.heir_names", ("PELLWORTH", "ODESSA", "M")),
    ({"raw": {"heir_estate": {"owner_of_record": "QUILLAN (HEIRS) WARD EVERT"}},
      "listing_type": "estate_lead"}, "heir_estate.owner_of_record", ("QUILLAN", "WARD", "E")),
    ({"owner_name": "WARD E QUILLAN JR HEIRS", "listing_type": "tax_lien",
      "raw": {"life_events": ["estate_probate"]}}, "owner_name", ("QUILLAN", "WARD", "E")),
    ({"defendant": "WARD QUILLAN (HEIRS)", "owner_name": "BRAND NEW OWNER",
      "listing_type": "estate_lead"}, "defendant", ("QUILLAN", "WARD", "")),
])
def test_decedent_of(row, field, first):
    d = ph.decedent_of({**BUN, **row})
    assert d["field"] == field and d["persons"][0] == first


def test_initials_only_and_junk_names_are_not_searchable():
    d = ph.decedent_of({**BUN, "listing_type": "tax_lien", "owner_name": "J A QUILLAN HEIRS",
                        "raw": {"life_events": ["estate_probate"]}})
    assert d["persons"] == []
    assert ph.decedent_of({**BUN, "listing_type": "estate_lead", "description": "Hunt Estate"}) is None
    assert ph.candidates("GLADYS E QUILLAN HEIRS QUILLAN CEMETERY") == []


def test_two_decedents_on_one_heirs_line_keep_the_first():
    assert ph.clean_name("WARD F QUILLAN ( ) ODESSA QUILLAN ( )") == "WARD F QUILLAN"
    assert ph.candidates("WARD F QUILLAN (HEIRS) ODESSA QUILLAN (HEIRS)")[0] == ("QUILLAN", "WARD", "F")


def test_all_caps_reads_first_last_then_surname_first():
    assert ph.candidates("ODESSA PELLWORTH") == [("PELLWORTH", "ODESSA", ""), ("ODESSA", "PELLWORTH", "")]
    assert ph.candidates("QUILLAN WARD T JR") == [("QUILLAN", "WARD", "T")]   # "T" is no surname
    assert ph.suffix_of("QUILLAN WARD T JR") == "JR" and ph.suffix_of("Ward Quillan, Sr.") == "SR"


def test_claim_dates():
    c = ph.claim_of({**BUN, "listing_type": "probate_notice", "case_number": "26E001234-100",
                     "first_seen": "2026-08-06T13:35:57"})
    assert c["case_year"] == 2026 and c["death_by"] == "2026-08-06"
    o = ph.claim_of({**BUN, "listing_type": "probate_notice", "first_seen": "2026-09-22T15:26:43",
                     "raw": {"obituary": {"pub_date": "Tue, 22 Sep 2026 13:34:01 +0000"}}})
    assert o["dates"]["obituary_published"] == "2026-09-22" and o["death_by"] == "2026-09-22"


def test_case_identity_is_reading_order_free_and_per_decedent():
    a = {**BUN, "listing_type": "estate_lead", "raw": {"heir_estate": {"owner_of_record": "ODESSA PELLWORTH HEIRS"}}}
    b = {**BUN, "listing_type": "tax_lien", "owner_name": "PELLWORTH ODESSA HEIRS",
         "raw": {"life_events": ["estate_probate"]}}
    c = {**BUN, "listing_type": "probate_notice", "raw": {"probate": {"decedent": "Odessa Pellworth"}}}
    other = {**BUN, "listing_type": "probate_notice", "raw": {"probate": {"decedent": "Ward Quillan"}}}
    assert ph.case_identity(a) == ph.case_identity(b) == ph.case_identity(c) != ph.case_identity(other)
    assert ph.case_identity(a).startswith("estate:") and "PELL" not in ph.case_identity(a).upper()
    li = Listing(source="public_notices.nc_notices_counties", source_url="https://x/y",
                 listing_type=ListingType.PROBATE_NOTICE, state="NC", county="Buncombe",
                 raw={"probate": {"decedent": "Odessa Pellworth"}})
    assert ph.case_identity(li) == ph.case_identity(c)
    assert ph.case_identity({**BUN, "listing_type": "tax_lien"}) is None
    v = next(v for v in discover() if v.signal == "probate_heir")
    k1 = v.ledger_keys({**c, "parcel_id": "9700000001"})[0]
    k2 = v.ledger_keys({**other, "parcel_id": "9700000001"})[0]
    assert k1 != k2 and k1.split("@")[1] == k2.split("@")[1]   # one parcel, two estates, two entries


# ---------------------------------------------------------------------------------------------
# the DEATHS index
# ---------------------------------------------------------------------------------------------

def _dgrid(*docs):
    return {"count": len(docs), "docs": list(docs)}


def test_a_parents_record_is_not_the_persons_death():
    g = _dgrid(_doc(1, year=1958, grantors=["PELLWORTH, INFANT MALE"],
                    grantees=["PELLWORTH, ODESSA MAE", "QUILLAN, ROSE"],
                    matched=["PELLWORTH, ODESSA MAE"], side="grantee", bp="45/212"))
    m = ph.death_match(g, DEC, _claim())
    assert m["match"] == "not_found" and m["named_as_parent"] == 1


def test_a_wife_indexed_under_her_husbands_name_is_not_him():
    g = _dgrid(_doc(1, year=1960, grantors=["QUILLAN, WARD DOKE"], matched=["QUILLAN, WARD DOKE"], bp="47/1"),
               _doc(2, year=1935, grantors=["QUILLAN, WARD D MRS"], matched=["QUILLAN, WARD D MRS"], bp="22/47"))
    m = ph.death_match(g, ("QUILLAN", "WARD", "D"), _claim())
    assert m["match"] == "matched" and m["recorded_year"] == 1960 and m["basis"] == "middle_agrees"
    assert m["identity"] == {"subject": "W.D.Q.", "record": "W.D.Q.", "middle": "agrees"}


def test_another_middle_initial_is_another_person():
    g = _dgrid(_doc(1, year=2023, grantors=["PELLWORTH, ODESSA JUNE"], matched=["PELLWORTH, ODESSA JUNE"], bp="110/717"))
    m = ph.death_match(g, DEC, _claim())
    assert m["match"] == "conflict_only" and m["other_middle"] == 1


def test_a_common_name_without_middle_is_ambiguous():
    g = _dgrid(_doc(1, year=2008, grantors=["QUILLAN, WARD HAROLD"], matched=["QUILLAN, WARD HAROLD"], bp="95/421"),
               _doc(2, year=1992, grantors=["QUILLAN, WARD DEWITT"], matched=["QUILLAN, WARD DEWITT"], bp="79/505"))
    assert ph.death_match(g, ("QUILLAN", "WARD", ""), _claim())["match"] == "ambiguous"
    one = _dgrid(g["docs"][0])
    m = ph.death_match(one, ("QUILLAN", "WARD", ""), _claim())
    assert m["match"] == "matched" and m["basis"] == "first_last"


def test_the_suffix_picks_among_agreeing_records_and_jr_is_not_sr():
    g = _dgrid(_doc(1, year=2021, grantors=["QUILLAN, WARD TALBERT"], matched=["QUILLAN, WARD TALBERT"], bp="108/3326"),
               _doc(2, year=2021, grantors=["QUILLAN, WARD TALBERT JR."], matched=["QUILLAN, WARD TALBERT JR."], bp="108/2810"))
    assert ph.death_match(g, ("QUILLAN", "WARD", "T"), _claim())["match"] == "ambiguous"
    m = ph.death_match(g, ("QUILLAN", "WARD", "T"), _claim(), "JR")
    assert m["match"] == "matched" and m["book_page"] == "108/2810" and m["basis"] == "middle_and_suffix_agree"
    sr = _dgrid(_doc(1, year=2021, grantors=["QUILLAN, WARD TALBERT SR."], matched=["QUILLAN, WARD TALBERT SR."], bp="1/1"))
    assert ph.death_match(sr, ("QUILLAN", "WARD", "T"), _claim(), "JR")["match"] == "conflict_only"


def test_a_record_after_the_claim_or_long_before_the_estate_file_does_not_count():
    g = _dgrid(_doc(1, year=1990, grantors=["PELLWORTH, ODESSA MAE"], matched=["PELLWORTH, ODESSA MAE"], bp="77/1"))
    m = ph.death_match(g, DEC, _claim(case_year=2026, death_by="2026-06-19"))
    assert m["match"] == "not_found" and m["outside_claim_dates"] == 1
    late = _dgrid(_doc(1, year=2026, grantors=["PELLWORTH, ODESSA MAE"], matched=["PELLWORTH, ODESSA MAE"], bp="113/1"))
    assert ph.death_match(late, DEC, _claim(death_by="2025-12-01"))["match"] == "not_found"


DEATHS_PAGE = """<html><body>
<span id="lblIndexTypeCaption"><strong>DEATHS</strong> Valid From <strong>1/1/1913</strong> Thru
<strong>10/2/2026</strong></span><span>Your search returned <strong> 2</strong> results</span>
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments">
<tr class="cottPagedGridViewHeaderStyle"><th>x</th></tr>
<tr class="cottPagedGridViewRowStyle"><td>1</td><td>**/**/2023<br><span>Date Filed<br />**/**/2023</span></td>
<td>DTH</td><td>&nbsp;</td><td><div><table><tr><td colspan='2'><b>PELLWORTH, ODESSA MAE</b></td></tr></table></div></td>
<td><div><table><tr><td colspan='2'>PELLWORTH, ARLO</td></tr><tr><td colspan='2'>VANCE, LILA</td></tr></table></div></td>
<td><div><table></table></div></td><td></td><td><div><a> 110 / 717</a></div></td><td></td><td>1</td><td></td><td></td><td></td></tr>
<tr class="cottPagedGridViewAltRowStyle"><td>2</td><td>03/14/1958</td><td>DTH</td><td>&nbsp;</td>
<td><div><table><tr><td colspan='2'>PELLWORTH, INFANT MALE</td></tr></table></div></td>
<td><div><table><tr><td colspan='2'><b>PELLWORTH, ODESSA MAE</b></td></tr></table></div></td>
<td></td><td></td><td><div><a> 45 / 212</a></div></td><td></td><td>1</td><td></td><td></td><td></td></tr>
</table></body></html>"""


def test_parse_deaths_reads_masked_years_parties_and_valid_thru():
    g = ph.parse_deaths(DEATHS_PAGE)
    assert g["count"] == 2 and g["valid_thru"] == "2026-10-02"
    a, b = g["docs"]
    assert (a["year"], a["date"], a["bp"], a["matched_side"]) == (2023, None, "110/717", "grantor")
    assert (b["year"], b["date"], b["matched_side"]) == (1958, "1958-03-14", "grantee")
    m = ph.death_match(g, DEC, _claim())
    assert m["match"] == "matched" and m["recorded_year"] == 2023 and m["named_as_parent"] == 1


def test_the_deaths_body_is_the_vendor_name_search_on_the_dth_index():
    b = ph.death_body("PELLWORTH", "ODESSA")
    assert b[F._P + "ddlIndexType"] == "DTH" and b[F._P + "txtFirmSurname"] == "PELLWORTH"
    assert not any("captcha" in k.lower() or "captcha" in str(v).lower() for k, v in b.items())


# ---------------------------------------------------------------------------------------------
# the owner of record
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("owner,others,want", [
    ("PELLWORTH ODESSA MAE", [], "titled_to_decedent"),
    ("QUILLAN WARD;PELLWORTH ODESSA M", [], "titled_to_decedent"),
    ("ODESSA M PELLWORTH (HEIRS)", [], "heirs_of_record"),
    ("PELLWORTH (HEIRS) ODESSA MAE", [], "heirs_of_record"),
    ("HEIRS OF ODESSA M PELLWORTH", [], "heirs_of_record"),
    ("WARD QUILLAN HEIRS", [], "heirs_of_other"),
    ("PELLWORTH ARLO", [], "family"),
    ("VANCE LILA", [("VANCE", "ROSE", "")], "family"),
    ("BLUE RIDGE HOLDINGS LLC", [], "entity"),
    ("VANCE LILA;VANCE ROSE", [], "unrelated"),
    ("PELLWORTH ODESSA JUNE", [], "family"),             # same name, another middle: not her
])
def test_owner_relation(owner, others, want):
    assert ph.owner_relation(owner, DEC, others)["relation"] == want


# ---------------------------------------------------------------------------------------------
# the decision
# ---------------------------------------------------------------------------------------------

def _chain(*docs, complete=True, narrowed=False):
    return {"grid": {"count": len(docs), "docs": list(docs)}, "complete": complete, "narrowed": narrowed}


def test_confirmed_death_record_and_heirs_of_record():
    v, ev = decide(_parcel("ODESSA M PELLWORTH HEIRS"), chain=_chain())
    assert (v, ev["decided_by"], ev["transfer"]["category"]) == \
        ("confirmed", "death_record_and_heirs_of_record", "heirs_of_record")


def test_confirmed_death_record_and_still_titled_to_the_decedent():
    v, ev = decide(_parcel("PELLWORTH ODESSA MAE"), chain=None)
    assert (v, ev["decided_by"]) == ("confirmed", "death_record_and_titled_to_decedent")


@pytest.mark.parametrize("death,reason", [(NOT_FOUND, "death_record_not_found"),
                                          ({"match": "conflict_only"}, "death_record_not_found"),
                                          ({"match": "ambiguous"}, "death_record_ambiguous"),
                                          ({"match": "not_checked"}, "death_record_not_checked")])
def test_unsettled_without_a_death_record_is_unconfirmed(death, reason):
    v, ev = decide(_parcel("ODESSA M PELLWORTH HEIRS"), death=death)
    assert (v, ev["reason"]) == ("unconfirmed", reason)


def test_no_parcel_is_unconfirmed():
    assert decide(None) == ("unconfirmed", {"reason": "no_property_identity"})


def _out_deed(date_, *, grantee="VANCE, LILA", grantor="PELLWORTH, ODESSA MAE", bp="5000/100", type_="DEED"):
    return _doc(9, date=date_, type_=type_, grantors=[grantor], grantees=[grantee],
                matched=[grantor], side="grantor", bp=bp)


SOLD = dict(DeedBook="5000", DeedPage="0100", Stamps=300.0, SalePrice=150000.0, Instrument="WDT")


def test_stale_A_the_vesting_deed_came_out_of_the_decedent_after_the_death():
    p = _parcel("VANCE LILA", DeedDate="20180301", **SOLD)
    v, ev = decide(p, chain=_chain(_out_deed("2018-03-01")))
    assert (v, ev["decided_by"], ev["transfer"]["category"]) == \
        ("stale", "vesting_deed_from_decedent_after_death", "conveyed_out")
    assert ev["deciding"][0]["book_page"] == "5000/100" and ev["deciding"][0]["tie"] == "vesting_deed"


def test_stale_A_an_estate_marked_grantor_needs_no_death_record():
    p = _parcel("VANCE LILA", DeedDate="20180301", **SOLD)
    v, ev = decide(p, death=NOT_FOUND, chain=_chain(_out_deed("2018-03-01", grantor="PELLWORTH, ODESSA MAE ESTATE")))
    assert v == "stale" and ev["deciding"][0]["estate_marker"] is True


def test_a_conveyance_in_the_masked_death_year_is_timing_unclear():
    p = _parcel("VANCE LILA", DeedDate="20150601", **SOLD)
    v, ev = decide(p, chain=_chain(_out_deed("2015-06-01")))
    assert (v, ev["reason"]) == ("unconfirmed", "conveyance_timing_unclear")
    exact = {**MATCHED, "recorded": "2015-02-01"}       # an unmasked record date decides it
    assert decide(p, death=exact, chain=_chain(_out_deed("2015-06-01")))[0] == "stale"


def test_a_conveyance_without_consideration_or_to_the_family_is_not_stale():
    p = _parcel("VANCE LILA", DeedDate="20180301", DeedBook="5000", DeedPage="0100")
    assert decide(p, chain=_chain(_out_deed("2018-03-01")))[1]["reason"] == "conveyed_without_consideration"
    fam = _parcel("PELLWORTH ARLO", DeedDate="20180301", **SOLD)
    assert decide(fam, chain=_chain(_out_deed("2018-03-01", grantee="PELLWORTH, ARLO")))[1]["reason"] == \
        "owner_shares_decedent_surname"
    married = _parcel("VANCE LILA", DeedDate="20180301", **SOLD)
    v, ev = decide(married, chain=_chain(_out_deed("2018-03-01", grantee="PELLWORTH, LILA")))
    assert (v, ev["reason"]) == ("unconfirmed", "conveyed_to_decedent_surname")


def test_stale_B_the_decedent_acquired_and_an_unrelated_buyer_took_title_after_the_death():
    a = _parcel("VANCE LILA", DeedDate="20190910", SubName="LAUREL PARK", SubLot="7", **SOLD)
    acq = _doc(3, date="1988-05-02", grantors=["QUILLAN, ROSE"], grantees=["PELLWORTH, ODESSA MAE"],
               matched=["PELLWORTH, ODESSA MAE"], side="grantee", bp="1500/20", desc="LOT 7 LAUREL PARK")
    v, ev = decide(a, chain=_chain(acq))
    assert (v, ev["decided_by"]) == ("stale", "conveyed_after_death")
    assert decide(a, death=NOT_FOUND, chain=_chain(acq))[1]["reason"] == "owner_unrelated_no_tie"


def test_stale_C_the_rolls_own_heirs_title_was_conveyed_since_it_was_read():
    a = _parcel("VANCE LILA", DeedDate="20260901", **SOLD)
    v, ev = decide(a, death=NOT_FOUND, chain=_chain(), claim=_claim(heir_roll_on_pin=True))
    assert (v, ev["decided_by"]) == ("stale", "conveyed_after_heirs_of_record")
    before = _parcel("VANCE LILA", DeedDate="20250101", **SOLD)
    assert decide(before, death=NOT_FOUND, chain=_chain(), claim=_claim(heir_roll_on_pin=True))[0] == "unconfirmed"


def test_stale_D_a_deed_out_the_layer_has_not_caught_up_with():
    a = _parcel("ODESSA M PELLWORTH HEIRS", SubName="LAUREL PARK", SubLot="7")
    out = _out_deed("2026-08-20", bp="6620/5", type_="DEED")
    out["desc"] = "LOT 7 LAUREL PARK"
    v, ev = decide(a, chain=_chain(out))
    assert (v, ev["decided_by"]) == ("stale", "deed_out_not_yet_on_layer")
    weak = dict(out, desc="QUILL RD")                      # a street tie is not enough
    assert decide(a, chain=_chain(weak))[0] == "confirmed"
    old = dict(out, date="2024-01-02")                      # past LAYER_LAG_DAYS: the layer would show it
    assert decide(a, chain=_chain(old))[0] == "confirmed"


def test_refuted_R1_the_decedent_sold_it_alive_years_before_the_death():
    p = _parcel("VANCE LILA", DeedDate="20050301", **SOLD)
    v, ev = decide(p, chain=_chain(_out_deed("2005-03-01")))
    assert (v, ev["decided_by"], ev["transfer"]["category"]) == \
        ("refuted", "conveyed_before_death", "conveyed_before_death")


@pytest.mark.parametrize("change", ["no_middle", "incomplete", "narrowed", "estate_marker", "one_year", "no_death"])
def test_no_R1_without_every_condition(change):
    p = _parcel("VANCE LILA", DeedDate="20050301", **SOLD)
    deed = _out_deed("2005-03-01")
    dec, death, kw = DEC, MATCHED, {}
    if change == "no_middle":
        deed = _out_deed("2005-03-01", grantor="PELLWORTH, ODESSA")
    elif change == "incomplete":
        kw["complete"] = False
    elif change == "narrowed":
        kw["narrowed"] = True
    elif change == "estate_marker":
        deed = _out_deed("2005-03-01", grantor="PELLWORTH, ODESSA MAE EST")
    elif change == "one_year":
        p = _parcel("VANCE LILA", DeedDate="20140301", **SOLD)
        deed = _out_deed("2014-03-01")
    elif change == "no_death":
        death = NOT_FOUND
    assert decide(p, death=death, chain=_chain(deed, **kw), dec=dec)[0] != "refuted"


def test_refuted_R2_the_decedent_signed_for_this_parcel_after_the_claim():
    a = _parcel("PELLWORTH ODESSA MAE", DeedBook="1200", DeedPage="0300")
    dot = _doc(4, date="2026-09-30", type_="DEED OF TRUST", grantors=["PELLWORTH, ODESSA MAE"],
               grantees=["FIRST LENDER BANK"], matched=["PELLWORTH, ODESSA MAE"], bp="6630/1",
               desc="LOT 7 LAUREL PARK")
    a.update(SubName="LAUREL PARK", SubLot="7")
    claim = _claim(death_by="2026-05-01", dates={"first_seen": "2026-05-01"})
    v, ev = decide(a, death=NOT_FOUND, chain=_chain(dot), claim=claim)
    assert (v, ev["decided_by"]) == ("refuted", "decedent_acted_after_death_claim")


@pytest.mark.parametrize("change", ["death_matched", "within_90_days", "weak_tie", "no_middle", "incomplete", "satisfaction"])
def test_no_R2_without_every_condition(change):
    a = _parcel("PELLWORTH ODESSA MAE", SubName="LAUREL PARK", SubLot="7")
    dot = _doc(4, date="2026-09-30", type_="DEED OF TRUST", grantors=["PELLWORTH, ODESSA MAE"],
               grantees=["FIRST LENDER BANK"], matched=["PELLWORTH, ODESSA MAE"], bp="6630/1",
               desc="LOT 7 LAUREL PARK")
    claim = _claim(death_by="2026-05-01", dates={"first_seen": "2026-05-01"})
    death, kw = NOT_FOUND, {}
    if change == "death_matched":
        death = MATCHED
    elif change == "within_90_days":
        dot["date"] = "2026-06-15"
    elif change == "weak_tie":
        dot["desc"] = "QUILL RD"
    elif change == "no_middle":
        dot["grantors"] = dot["matched"] = ["PELLWORTH, ODESSA"]
    elif change == "incomplete":
        kw["complete"] = False
    elif change == "satisfaction":
        dot["type"] = "DEED OF TRUST SATISFACTION"
    assert decide(a, death=death, chain=_chain(dot, **kw), claim=claim)[0] != "refuted"


def test_an_unrelated_owner_with_nothing_tying_the_decedent_is_unconfirmed():
    v, ev = decide(_parcel("VANCE LILA", DeedDate="20200417", **SOLD), chain=_chain())
    assert (v, ev["reason"], ev["transfer"]["category"]) == ("unconfirmed", "owner_unrelated_no_tie", "unrelated_no_tie")
    assert decide(_parcel("BLUE RIDGE HOLDINGS LLC"), chain=_chain())[1]["reason"] == "owner_entity_no_tie"
    assert decide(_parcel("WARD QUILLAN HEIRS"), chain=_chain())[1]["reason"] == "parcel_heirs_of_other_person"


# ---------------------------------------------------------------------------------------------
# verify() end to end on constructed responses
# ---------------------------------------------------------------------------------------------

def _gis(owner, pin="9700000001", **kw):
    a = _parcel(owner, pin=pin, **kw)
    return json.dumps({"features": [{"attributes": a}]})


class Voters(ReplayFetcher):
    """A ReplayFetcher that also answers voter searches (elderly_disabled's test hook)."""

    def __init__(self, responses, voters=None):
        super().__init__(responses)
        self.voters = voters or {}
        self.voter_asked = []

    async def voter_search(self, first, last, county):
        self.voter_asked.append((first, last, county))
        return self.voters.get((first, last), {"ok": True, "rows": [], "total": 0})


def _vrow(name, status, city=""):
    return {"FullName": name, "StatusDesc": status, "ResAddressCSZ": city, "VoterRegNum": "VR7310442",
            "NCID": "NCID98765", "CountyName": "BUNCOMBE"}


def _heir_row(owner="ODESSA M PELLWORTH HEIRS", **kw):
    row = {**BUN, "source": "counties_nc.nc_heir_estate_parcels", "listing_type": "estate_lead",
           "parcel_id": "9700000001", "street_address": "12 QUILL RD", "first_seen": "2026-07-22T20:45:25",
           "owner_name": owner, "defendant": owner,
           "raw": {"heir_estate": {"owner_of_record": owner, "care_of": "LILA VANCE",
                                   "mailing": "5 OAK CT WEAVERVILLE NC 28787", "match": "heirs",
                                   "heir_names": [{"raw": owner, "name": ph.clean_name(owner), "role": "heir"}]}}}
    row.update(kw)
    return row


def _responses(owner_now="ODESSA M PELLWORTH HEIRS", deaths=DEATHS_PAGE, crp=None):
    return {F.gis_url_pin("970000000100000"): _gis(owner_now),
            F.SEARCH_URL: "<html><body><div id='ucSrchNames'>search</div></body></html>",
            form_key(F.SEARCH_URL, ph.death_body("PELLWORTH", "ODESSA")): deaths,
            form_key(F.SEARCH_URL, F.name_body("PELLWORTH", "ODESSA")): crp or
            "<html><span>Your search returned <strong> 0</strong> results</span></html>"}


def run(row, client):
    return asyncio.run(ph.verify(row, client, today=TODAY))


def test_verify_confirmed_with_heir_liveness_as_counts_only():
    voters = {("Lila", "Vance"): {"ok": True, "total": 2, "rows": [_vrow("VANCE, LILA ROSE", "ACTIVE", "WEAVERVILLE, NC 28787"),
                                                                   _vrow("VANCE, LILA", "REMOVED")]},
              ("Odessa", "Pellworth"): {"ok": True, "total": 1, "rows": [_vrow("PELLWORTH, ODESSA MAE", "REMOVED")]}}
    c = Voters(_responses(), voters)
    res = run(_heir_row(), c)
    assert res.verdict == "confirmed" and res.evidence["decided_by"] == "death_record_and_heirs_of_record"
    hl = res.evidence["heir_liveness"]
    assert hl == {"named": 2, "searched": 2, "decedent_named": {"removed": 1}, "care_of": {"active": 1}}
    assert ("Odessa", "Pellworth", "ALL") in c.voter_asked
    blob = json.dumps(res.evidence)
    for tok in ("PELLWORTH", "ODESSA", "VANCE", "LILA", "WEAVERVILLE", "QUILL", "VR7310442", "NCID98765"):
        assert tok.lower() not in blob.lower(), tok


def test_heir_liveness_never_changes_the_verdict():
    dead_everywhere = {("Lila", "Vance"): {"ok": True, "rows": [_vrow("VANCE, LILA", "REMOVED")]}}
    a = run(_heir_row(), Voters(_responses(), dead_everywhere))
    b = run(_heir_row(), Voters(_responses(), {}))
    assert a.verdict == b.verdict == "confirmed"


def test_R0_a_roll_that_names_no_death_is_refuted():
    owner = "QUILLHEIR ARLO B;VANCE LILA M"            # "HEIR" only inside a surname
    row = _heir_row(owner)
    row["raw"]["heir_estate"]["heir_names"] = [{"raw": "QUILLHEIR ARLO B", "name": "QUILLHEIR ARLO B", "role": "other"}]
    assert ph.roll_only_without_death_word(row)
    c = Voters({F.gis_url_pin("970000000100000"): _gis(owner)})
    res = run(row, c)
    assert (res.verdict, res.evidence["decided_by"]) == ("refuted", "no_death_word_on_roll")
    assert c.asked == [F.gis_url_pin("970000000100000")]           # the layer only
    c2 = Voters({F.gis_url_pin("970000000100000"): _gis("ARLO B QUILLHEIR HEIRS")})
    assert run(row, c2).evidence["reason"] == "county_shows_death_word_now"


def test_a_rows_pin_is_authoritative_and_a_layer_error_is_a_failure():
    """Live 2026-10-06 (v1): the layer answered the PIN query with an ArcGIS error body, and the
    address fallback resolved the row's street_address, which on an unpaid-bill row is the
    owner's MAILING address, to another parcel. v2: a PIN row never falls back; the error is
    retried once and then reported."""
    row = _heir_row(street_address="116 OTHER PARK CT")
    err = json.dumps({"error": {"code": 500, "message": "Error performing query operation", "details": []}})
    r = _responses()
    r[F.gis_url_pin("970000000100000")] = err
    r[F.gis_url_address("116", "OTHER PARK")] = _gis("BLUE RIDGE HOLDINGS LLC", pin="9600000002")
    c = Voters(r)
    res = run(row, c)
    assert (res.verdict, res.evidence["reason"]) == ("unconfirmed", "county_layer_failed")
    assert c.asked.count(F.gis_url_pin("970000000100000")) == 2          # one retry
    assert F.gis_url_address("116", "OTHER PARK") not in c.asked        # never the address
    r[F.gis_url_pin("970000000100000")] = json.dumps({"features": []})  # PIN not in the layer
    F._RUNS.clear()
    c2 = Voters(r)
    res2 = run(row, c2)
    assert res2.evidence["reason"] == "no_property_identity" and F.gis_url_address("116", "OTHER PARK") not in c2.asked
    nopin = {k: v for k, v in row.items() if k != "parcel_id"}
    F._RUNS.clear()
    c3 = Voters(r)
    run(nopin, c3)
    assert F.gis_url_address("116", "OTHER PARK") in c3.asked          # no PIN: the address


def test_a_row_without_a_decedent_makes_no_request():
    c = Voters({})
    res = run({**BUN, "source": "national.estate_sales", "listing_type": "estate_lead",
               "description": "Hunt Estate"}, c)
    assert (res.verdict, res.evidence["reason"]) == ("unconfirmed", "no_decedent_name") and c.asked == []


@pytest.mark.parametrize("blocked,why", [
    ({"status": 403, "url": F.SEARCH_URL, "text": "Forbidden"}, "http_403"),
    ({"status": 200, "url": "https://registerofdeeds.buncombenc.gov/External/User/Login.aspx?x=1",
      "text": "<input type=password>"}, "login_redirect")])
def test_a_block_is_wall_and_stops_the_runs_later_rows(blocked, why):
    r = _responses()
    r[F.SEARCH_URL] = blocked
    c = Voters(r)
    res = run(_heir_row(), c)
    assert (res.verdict, res.evidence["blocked"]) == ("wall", why)
    n = len(c.asked)
    res2 = run(_heir_row(), c)
    assert res2.evidence["reason"] == "rod_blocked_earlier_this_run"
    assert c.asked[n:] == []                          # nothing more was asked, of any host


def test_a_rod_failure_is_unconfirmed():
    r = _responses()
    del r[form_key(F.SEARCH_URL, ph.death_body("PELLWORTH", "ODESSA"))]
    res = run(_heir_row(), Voters(r))
    assert (res.verdict, res.evidence["reason"]) == ("unconfirmed", "rod_fetch_failed")


def test_public_evidence_is_a_whitelist():
    ev = ph.public_evidence("confirmed", {
        "decided_by": "x", "grantor": "DOE, JANE", "owner": "DOE",
        "claim": {"source": "s", "decedent": "Jane Doe"},
        "decedent": {"field": "probate.decedent", "raw": "Jane Doe", "initials": "J.D."},
        "death": {"match": "matched", "identity": {"subject": "J.D.", "record": "J.D.", "middle": "agrees", "name": "DOE"},
                  "grantor": "DOE, JANE"},
        "heir_liveness": {"care_of": {"active": 1, "Jane Doe": 1}, "named": 1, "names": ["Jane Doe"]}})
    assert ev == {"decided_by": "x", "claim": {"source": "s"},
                  "decedent": {"field": "probate.decedent", "initials": "J.D."},
                  "death": {"match": "matched", "identity": {"subject": "J.D.", "record": "J.D.", "middle": "agrees"}},
                  "heir_liveness": {"care_of": {"active": 1}, "named": 1}}
    assert "human_lane" in ph.public_evidence("unconfirmed", {"reason": "r"})


# ---------------------------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------------------------

def _vrec(verdict):
    checked = datetime(2026, 10, 6, tzinfo=timezone.utc)
    return {"signal": ph.SIGNAL, "verdict": verdict, "evidence": {}, "source": ph.SOURCE,
            "checked_at": core.iso_z(checked), "verifier_version": ph.VERSION, "verifier": ph._NAME,
            "expires_at": core.iso_z(checked + timedelta(days=ph.TTL_DAYS)), "governs": list(ph.GOVERNS)}


def _listing(lt, verification=None, **raw):
    if verification is not None:
        raw["verification"] = verification
    return Listing(source="public_notices.nc_notices_counties", source_url="https://x/y", listing_type=lt,
                   state="NC", county="Buncombe", parcel_id="9700000001", street_address="12 QUILL RD",
                   owner_name="Odessa M Pellworth", raw=raw)


BLOCKS = {"probate": {"decedent": "Odessa M Pellworth", "es_case_number": "26E001234-100"},
          "relationship_signal": {"kind": "probate", "keyword": "EXECUTOR"}}


@pytest.mark.parametrize("lt", [ListingType.PROBATE_NOTICE, ListingType.ESTATE_LEAD])
@pytest.mark.parametrize("verdict,kept", [("refuted", False), ("stale", False), ("confirmed", True),
                                          ("unconfirmed", True), ("wall", True)])
def test_scoring(lt, verdict, kept):
    base = {n for n, _c, _w in ds._signals_for(_listing(lt, **copy.deepcopy(BLOCKS)), today=TODAY)}
    assert {lt.value, "probate", "probate_deed"} <= base
    got = {n for n, _c, _w in ds._signals_for(_listing(lt, [_vrec(verdict)], **copy.deepcopy(BLOCKS)), today=TODAY)}
    for name in (lt.value, "probate", "probate_deed"):
        assert (name in got) is kept
    facets = _facet_signals(_listing(lt, [_vrec(verdict)], **copy.deepcopy(BLOCKS)), TODAY)
    assert ("probate" in facets) is kept and ("probate_deed" in facets) is kept


def test_an_expired_verdict_changes_nothing():
    rec = _vrec("stale")
    rec["expires_at"] = "2026-09-01T00:00:00Z"
    got = {n for n, _c, _w in ds._signals_for(_listing(ListingType.PROBATE_NOTICE, [rec], **copy.deepcopy(BLOCKS)), today=TODAY)}
    assert "probate_notice" in got

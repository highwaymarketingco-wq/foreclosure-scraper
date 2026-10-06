"""The code-enforcement / vacancy verifiers (verification/verifiers/code_enforcement_henderson.py,
vacant_structure_hendersonville.py) and the source-qualified scoring rule they govern.

What these pin:
  * applies(): only rows carrying THAT source's block (the Henderson County OVT dashboard block
    claiming an open case; the Hendersonville register's code_enforcement or vacancy block);
  * every verdict and every unconfirmed path, against REAL captured responses: the whole OVT
    layer (3,301 cases, two 2000-row pages) and the whole register (52 rows) exactly as one
    live run of the verifiers fetched them through the Fetcher on 2026-10-06
    (tests/fixtures/verification/*_ovt.json.gz, *_register.json.gz, unedited: neither layer is
    ever asked for an owner, phone, email or note column, so there was nothing to scrub);
  * one layer load per sweep run whatever the number of rows, and a failed, empty or
    incomplete layer never yields refuted or stale;
  * vacant_structure v2 (the three agents' live re-check of 2026-10-06: 91 of 103 stale verdicts
    held, 8 did not): the notes and the demolition read only from the matched live register row
    (never the board's copy), negation- and tense-aware, a mention needs the county parcel layer,
    an occupancy value from the frozen register is too old to end a vacancy claim;
  * privacy: the requested columns, the evidence and the ledger row summary carry no owner,
    complainant, phone, email or free text;
  * scoring: "code_enforcement:<source>" / "vacant_structure:<source>" end the credit of that
    source's block only, never another source's block on the same parcel, in both readers.
"""
from __future__ import annotations

import asyncio
import copy
import gzip
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from foreclosure_scraper import distress_score as ds
from foreclosure_scraper.enrichment_lead_signals import _facet_signals
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.verification import core
from foreclosure_scraper.verification.apply import apply_verification
from foreclosure_scraper.verification.fetch import ReplayFetcher
from foreclosure_scraper.verification.ledger import Ledger
from foreclosure_scraper.verification.registry import discover
from foreclosure_scraper.verification.verifiers import _arcgis_layer as agl
from foreclosure_scraper.verification.verifiers import code_enforcement_henderson as ovt
from foreclosure_scraper.verification.verifiers import vacant_structure_hendersonville as vsr

FIX = Path(__file__).parent / "fixtures" / "verification"
TODAY = date(2026, 10, 6)
OVT_SRC = ovt.CE_SOURCE
REG_SRC = vsr.REG_SOURCE


def _bundle(name: str) -> dict:
    with gzip.open(FIX / name, "rt", encoding="utf-8") as fh:
        return json.load(fh)["responses"]


OVT_RESP = _bundle("code_enforcement_henderson_ovt.json.gz")
REG_RESP = _bundle("vacant_structure_hendersonville_register.json.gz")


@pytest.fixture(autouse=True)
def _no_run_cache():
    agl._RUNS.clear()


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# rows                                                                        #
# --------------------------------------------------------------------------- #

def _ovt_row(pin="9681135571", address="23 MONO LN", cases=(), types=(), *, source=None,
             has_open=True, **kw):
    ce = {"county": "Henderson", "has_open": has_open, "source": OVT_SRC,
          "violation_types": list(types),
          "violations": [{"case_id": c, "violation": t, "status": "x", "date": "2026-01-01"}
                         for c, t in zip(cases, list(types) + ["?"] * len(cases))]}
    row = {"state": "NC", "county": "Henderson", "parcel_id": pin, "street_address": address,
           "source": source or "counties_nc.henderson_code_violations",
           "first_seen": "2026-09-21T21:48:51", "raw": {"code_enforcement": ce}}
    row.update(kw)
    return row


def _reg_row(address="1001 TEMON ST", *, demolished=False, first_seen="2026-09-21T21:48:51",
             vacancy=True, ce=True, source="counties_nc.hendersonville_vacant_structures"):
    raw = {}
    if ce:
        raw["code_enforcement"] = {"jurisdiction": "City of Hendersonville",
                                   "kind": "vacant_structure_register",
                                   "has_open": not demolished, "demolished": demolished,
                                   "violation_types": ["Vacant Structure"], "source": REG_SRC}
    if vacancy:
        raw["vacancy"] = {"vacant": True, "boarded_up": None, "source": REG_SRC}
    return {"state": "NC", "county": "Henderson", "parcel_id": None, "street_address": address,
            "source": source, "first_seen": first_seen, "raw": raw}


def _check_ovt(row, resp=None):
    return run(ovt.verify(row, ReplayFetcher(OVT_RESP if resp is None else resp)))


def _check_reg(row, resp=None):
    return run(vsr.verify(row, ReplayFetcher(REG_RESP if resp is None else resp)))


# --------------------------------------------------------------------------- #
# contract                                                                    #
# --------------------------------------------------------------------------- #

def test_both_are_discovered_with_their_contract():
    vs = {v.name: v for v in discover()}
    a, b = vs["code_enforcement_henderson"], vs["vacant_structure_hendersonville"]
    assert (a.signal, a.ttl_days, a.retry_days) == ("code_enforcement", 14, 3)
    assert (b.signal, b.ttl_days, b.retry_days) == ("vacant_structure", 30, 7)
    assert a.governs == (f"code_enforcement:{OVT_SRC}",)
    assert b.governs == (f"vacant_structure:{REG_SRC}", f"code_enforcement:{REG_SRC}")
    # the base names are the scorer's own
    for g in a.governs + b.governs:
        assert g.split(":", 1)[0] in ds.SIGNAL_CATEGORY
    assert ovt.ROW_SUMMARY_EXCLUDE == vsr.ROW_SUMMARY_EXCLUDE == ("owner_name",)


def test_applies_ovt():
    assert ovt.applies(_ovt_row())
    assert ovt.applies(_ovt_row(source="counties_generic.arcgis_distress."
                                       "hendersonville_flood_zone_structures"))
    assert not ovt.applies(_ovt_row(has_open=False))
    assert not ovt.applies({**_ovt_row(), "county": "Buncombe"})
    assert not ovt.applies({**_ovt_row(), "state": "SC"})
    assert not ovt.applies(_reg_row())                         # the register's block
    sp = {"state": "SC", "county": "Spartanburg", "raw": {"code_enforcement": True}}
    assert not ovt.applies(sp)
    assert not ovt.applies({"state": "NC", "county": "Henderson", "raw": None})


def test_applies_register():
    assert vsr.applies(_reg_row())
    assert vsr.applies(_reg_row(ce=False))                     # vacancy block alone
    assert vsr.applies(_reg_row(vacancy=False))                # code_enforcement block alone
    assert not vsr.applies(_reg_row(ce=False, vacancy=False))
    assert not vsr.applies(_ovt_row())
    assert not vsr.applies({**_reg_row(), "county": "Buncombe"})


# --------------------------------------------------------------------------- #
# Henderson County OVT: verdicts on the real layer                            #
# --------------------------------------------------------------------------- #

def test_confirmed_open_distress_case():
    res = _check_ovt(_ovt_row("9681135571", "23 MONO LN", ["469", "346", "184", "102", "75"],
                              ["General", "Junkyard", "Vehicle Graveyard"]))
    assert res.verdict == "confirmed"
    ev = res.evidence
    assert ev["matched_by"] == ["pin"] and ev["open_distress"] >= 1
    assert ev["cases"][0]["open"] is True                      # open cases first
    assert {c["category"] for c in ev["cases"]} >= {"Vehicle Graveyard", "General"}
    assert ev["layer_count"] == ev["layer_rows_loaded"] == 3301
    assert ev["layer_data_last_edit"].startswith("2026-10-")
    assert (res.signal, res.verifier, res.verifier_version) == (
        "code_enforcement", "code_enforcement_henderson", "v1")


def test_stale_when_the_distress_case_closed():
    res = _check_ovt(_ovt_row("9660054549", "110 OAKWOOD RD", ["1994"], ["Solid Waste"]))
    assert res.verdict == "stale" and res.evidence["reason"] == "case_closed"
    c = res.evidence["cases"][0]
    assert c["case_id"] == "1994" and c["open"] is False and c["distress"] is True
    assert c["status"] == "Owner Resolved Issue - No Further Action" and c.get("closed")


def test_refuted_open_zoning_case():
    """FINDINGS #3 Finding A: a Zoning case riding the distress flag."""
    res = _check_ovt(_ovt_row("9661405931", "1772 HOWARD GAP ROAD", ["844"], ["Zoning"]))
    assert res.verdict == "refuted" and res.evidence["reason"] == "category_not_distress"
    assert res.evidence["open_other"] >= 1 and res.evidence["open_distress"] == 0
    assert res.evidence["cases"][0]["category"] == "Zoning"


def test_refuted_closed_general_case():
    res = _check_ovt(_ovt_row("9652327300", "5360 HENDERSONVILLE RD", ["1211"], ["General"]))
    assert res.verdict == "refuted" and res.evidence["reason"] == "category_not_distress"


def test_old_closed_nuisance_does_not_make_a_zoning_claim_stale():
    """204 Gull Ave: the board claims an open General case; a 2000s Nuisance case there is
    closed. The claim never was distress: refuted, not stale."""
    res = _check_ovt(_ovt_row("9577984987", "204 Gull Ave", ["272"], ["General"]))
    assert res.verdict == "refuted" and res.evidence["closed_distress"] >= 1


def test_refuted_when_the_claimed_case_is_on_another_parcel():
    """637 Spartanburg Hwy (a merged flood-zone row on the 2026-10-06 board) carries case 3356,
    which the county files at a different PIN; this parcel has no case at all."""
    res = _check_ovt(_ovt_row("9568943079", "637 SPARTANBURG HWY", ["3356"], ["Nuisance"],
                              source="counties_generic.arcgis_distress."
                                     "hendersonville_flood_zone_structures"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "case_on_other_parcel"
    assert res.evidence["claimed_cases_elsewhere"] == [{"case_id": "3356",
                                                        "at_pin": "9577865348"}]


def test_a_case_elsewhere_does_not_hide_an_open_case_here():
    """1718 Sugarloaf Mountain Rd claims case 3260 (filed at 1987 Sugarloaf), but the parcel
    has its own open Nuisance case: confirmed, the mismatch recorded."""
    res = _check_ovt(_ovt_row("0611949460", "1718 SUGARLOAF MOUNTAIN RD", ["3260"],
                              ["Solid Waste"]))
    assert res.verdict == "confirmed"
    assert res.evidence["claimed_cases_elsewhere"][0]["case_id"] == "3260"


def test_refuted_when_nothing_on_the_whole_layer_matches():
    res = _check_ovt(_ovt_row("9999999999", "1 NOWHERE LN", ["999999"], ["Nuisance"]))
    assert res.verdict == "refuted" and res.evidence["reason"] == "no_case_on_layer"


def test_address_match_when_the_row_has_no_parcel():
    res = _check_ovt(_ovt_row(None, "2226 Spartanburg Hwy"))
    assert res.verdict == "confirmed" and res.evidence["matched_by"] == ["address"]


def test_a_bare_road_name_never_matches_by_address():
    res = _check_ovt(_ovt_row(None, "SPARTANBURG HWY"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_identity"


def test_tab_prefixed_county_pins_match():
    raw = [json.loads(b) for u, b in OVT_RESP.items() if "outFields" in u]
    tabbed = next(a["attributes"] for page in raw for a in page["features"]
                  if str(a["attributes"]["PIN"] or "").startswith("\t"))
    res = _check_ovt(_ovt_row(tabbed["PIN"].strip(), None))
    assert res.verdict in ("confirmed", "stale", "refuted")
    assert res.evidence["matched_by"] == ["pin"]


def test_blank_status_placeholder_decides_nothing():
    res = _check_ovt(_ovt_row("9651402705", "113 PUMA DR", ["1470"], ["Solid Waste"]))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "status_blank"
    assert res.evidence["blank_status_records"] == 1


def test_no_identity():
    res = _check_ovt(_ovt_row(None, None))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_identity"


@pytest.mark.parametrize("damage,reason", [
    ("none", "layer_unavailable"),          # every request fails
    ("count0", "layer_empty"),
    ("short", "layer_unavailable"),         # the second page never answers
    ("count_more", "layer_incomplete"),     # the layer claims more rows than the pages hold
    ("arcgis_error", "layer_unavailable"),
])
def test_a_bad_layer_is_never_decisive(damage, reason):
    resp = dict(OVT_RESP)
    cnt = agl.count_url(ovt.layer())
    if damage == "none":
        resp = {}
    elif damage == "count0":
        resp[cnt] = json.dumps({"count": 0})
    elif damage == "short":
        p2 = agl.page_url(ovt.layer(), out_fields=ovt.OUT_FIELDS, order_by=ovt.ORDER_BY,
                          offset=2000, page=2000)
        resp.pop(p2)
    elif damage == "count_more":
        resp[cnt] = json.dumps({"count": 3302})
    elif damage == "arcgis_error":
        resp[cnt] = json.dumps({"error": {"code": 400, "message": "Invalid query"}})
    for row in (_ovt_row("9999999999", "1 NOWHERE LN", ["999999"], ["Nuisance"]),
                _ovt_row("9660054549", "110 OAKWOOD RD", ["1994"], ["Solid Waste"])):
        agl._RUNS.clear()
        res = _check_ovt(row, resp)
        assert res.verdict == "unconfirmed" and res.evidence["reason"] == reason


def test_one_layer_load_per_run_for_any_number_of_rows():
    client = ReplayFetcher(OVT_RESP)
    rows = [_ovt_row(p) for p in ("9681135571", "9660054549", "9661405931", "9652327300",
                                  "9568943079", "0611949460")] * 3

    async def go():
        return await asyncio.gather(*(ovt.verify(r, client) for r in rows))
    out = run(go())
    assert len(out) == 18 and len(client.asked) == 4           # meta, count, 2 pages
    assert len(set(client.asked)) == 4


def test_ovt_never_asks_for_the_owner_column():
    client = ReplayFetcher(OVT_RESP)
    run(ovt.verify(_ovt_row(), client))
    pages = [u for u in client.asked if "outFields" in u]
    assert len(pages) == 2
    for url in pages:
        asked = set(parse_qs(urlsplit(url).query)["outFields"][0].split(","))
        assert asked == {"OBJECTID", "caseID", "dateReceived", "violationType", "PIN",
                         "dispositionStatus", "dispositionDate", "address"}
    assert not any("parcelOwner" in u for u in client.asked)


# --------------------------------------------------------------------------- #
# Hendersonville register: verdicts on the real (frozen) register              #
# --------------------------------------------------------------------------- #

def test_register_confirmed_vacant():
    res = _check_reg(_reg_row("1001 TEMON ST"))
    assert res.verdict == "confirmed"
    ev = res.evidence
    assert ev["occupied"] is False and ev["matched_by"] == "address"
    assert ev["layer_data_last_edit"] == "2024-07-24T19:51:20Z"   # the frozen snapshot
    assert ev["register_age_days"] > 800
    assert ev["layer_count"] == 52 and isinstance(ev["register_fid"], int)


def test_register_confirmed_boarded_with_blank_occupancy():
    res = _check_reg(_reg_row("601 E PACE ST"))
    assert res.verdict == "confirmed"
    assert res.evidence["occupied"] is None and res.evidence["boarded_up"] is True


def test_register_occupied_from_the_frozen_layer_is_too_old_to_end_a_vacancy_claim():
    """902 Sylvan Blvd: the only basis of v1's stale was OCCUPIED=YES on a row listed 2024-04-25 in
    a layer last edited 2024-07-24 (803 days before the sweep). Too old to decide: unconfirmed."""
    res = _check_reg(_reg_row("902 SYLVAN BLVD"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "register_occupancy_too_old"
    assert res.evidence["occupied"] is True and res.evidence["listed_date"] == "2024-04-25"
    assert res.evidence["register_age_days"] > 365 and res.evidence["register_row_age_days"] > 180


def _reg_resp(*, edited: str | None = None, dates: dict | None = None, edit: dict | None = None):
    """The register fixture with the layer's last data edit (ISO date) and/or some rows' DATE
    (FID -> value) and/or other cells ({FID: {col: value}}) changed."""
    resp = dict(REG_RESP)
    if edited:
        meta_url = next(u for u in resp if u.endswith("/0?f=json"))
        meta = json.loads(resp[meta_url])
        meta["editingInfo"]["dataLastEditDate"] = int(
            datetime.fromisoformat(edited).replace(tzinfo=timezone.utc).timestamp() * 1000)
        resp[meta_url] = json.dumps(meta)
    if dates or edit:
        page_url = next(u for u in resp if "outFields" in u)
        page = json.loads(resp[page_url])
        for f in page["features"]:
            a = f["attributes"]
            if dates and a["FID"] in dates:
                a["DATE"] = dates[a["FID"]]
            for col, val in ((edit or {}).get(a["FID"]) or {}).items():
                a[col] = val
        resp[page_url] = json.dumps(page)
    return resp


def test_register_marked_occupied_still_ends_the_claim_when_the_register_is_fresh():
    """The rule is about AGE: a layer edited within a year, or an occupied row dated within the
    last 180 days, still decides (stale, marked_occupied)."""
    res = _check_reg(_reg_row("902 SYLVAN BLVD"), _reg_resp(edited=date.today().isoformat()))
    assert res.verdict == "stale" and res.evidence["reason"] == "marked_occupied"
    recent = (date.today() - timedelta(days=60)).isoformat()
    res = _check_reg(_reg_row("902 SYLVAN BLVD"), _reg_resp(dates={48: recent}))
    assert res.verdict == "stale" and res.evidence["reason"] == "marked_occupied"
    assert res.evidence["register_row_age_days"] == 60
    old_row = (date.today() - timedelta(days=200)).isoformat()      # layer old, row older than 180 d
    res = _check_reg(_reg_row("902 SYLVAN BLVD"), _reg_resp(dates={48: old_row}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "register_occupancy_too_old"


def test_register_a_blank_row_date_is_never_recent():
    res = _check_reg(_reg_row("902 SYLVAN BLVD"), _reg_resp(dates={48: None}))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "register_occupancy_too_old"
    assert "register_row_age_days" not in res.evidence


def test_register_stale_demolished_from_the_register():
    res = _check_reg(_reg_row("201 BLUE RIDGE ST"))
    assert res.verdict == "stale" and res.evidence["reason"] == "structure_demolished"
    assert res.evidence["demolished_basis"] == "register DELINQUENT_TAX"
    assert res.evidence["demolition_note"] == "completed"


def test_register_a_completed_note_is_decisive_alone_and_asks_no_one_else():
    """1030 N Justice St: NOTES 'DEMOED 7/25/2023'. A completed demolition word in the matched
    row's own notes decides; the county layer is not even asked."""
    client = ReplayFetcher(REG_RESP)
    res = run(vsr.verify(_reg_row("1030 N JUSTICE ST"), client))
    assert res.verdict == "stale" and res.evidence["reason"] == "structure_demolished"
    assert res.evidence["demolished_basis"] == "register NOTES"
    assert not [u for u in client.asked if "hendersoncountync" in u]


def test_register_the_boards_demolished_flag_is_never_a_source():
    """112 N Blue Ridge Ave (the live case): the board's block carries the 'pulling demo permit'
    note of the row next door (120, FID 7: its listed date, occupancy and a demolished flag) while
    the matched register row (FID 4) holds a person's name, no date and no demolition word, and the
    county layer shows the house standing (building value 13,900). v1 trusted the board's copy:
    stale (structure_demolished). Now the matched live row is the only source."""
    row = _reg_row("112 N BLUE RIDGE AVE", demolished=True)
    row["parcel_id"] = "9579230754"
    row["raw"]["code_enforcement"].update({"listed_date": "2023-02-13", "occupied": False,
                                            "boarded_up": False, "condemned": None})
    res = _check_reg(row)
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "occupancy_not_recorded"
    assert ev["register_fid"] == 4 and "demolished" not in ev and "demolition_note" not in ev
    assert ev["board_block_agrees"] is False and ev["board_demolished_flag_ignored"] is True
    assert ev["county_matched_by"] == "pin" and ev["county_building_value"] == 13900.0


def test_register_112_and_120_n_blue_ridge_cannot_cross():
    """Each address matches its own register row whatever block the board row carries, by the
    whole normalized address (house number included), in either direction."""
    for addr, fid in (("112 N BLUE RIDGE AVE", 4), ("120 N BLUE RIDGE AVE", 7)):
        for demolished in (False, True):
            res = _check_reg(_reg_row(addr, demolished=demolished))
            assert res.evidence["register_fid"] == fid, (addr, demolished)
    assert vsr._addr("112 N Blue Ridge Ave.") != vsr._addr("120 N. Blue Ridge Avenue")
    a, b = _check_reg(_reg_row("112 N BLUE RIDGE AVE")), _check_reg(_reg_row("120 N BLUE RIDGE AVE"))
    assert "listed_date" not in a.evidence and b.evidence["listed_date"] == "2023-02-13"


def test_register_a_block_that_agrees_with_its_row_is_recorded_as_agreeing():
    row = _reg_row("120 N BLUE RIDGE AVE")
    row["parcel_id"] = "9579232596"
    row["raw"]["code_enforcement"].update({"listed_date": "2023-02-13", "occupied": False,
                                            "boarded_up": False, "condemned": None})
    res = _check_reg(row)
    assert res.evidence.get("board_block_agrees") is None        # only a disagreement is recorded
    assert vsr.block_agrees(row["raw"]["code_enforcement"], vsr.register_view(
        {"FID": 7, "DATE": "2023-02-13", "OCCUPIED": "NO", "BOARDED_UP": "NO", "CONDEMNED": None})) is True
    assert vsr.block_agrees(row["raw"]["code_enforcement"], vsr.register_view(
        {"FID": 4, "DATE": None, "OCCUPIED": None})) is False
    assert vsr.block_agrees(None, {}) is None and vsr.block_agrees({"demolished": True}, {}) is None


def test_register_two_rows_at_one_address_pick_the_one_the_board_block_names():
    """410 Midway St has two register rows (FID 27 listed 2023-03-14, FID 28 listed 2023-10-09):
    the first wins, as in the scraper, unless the board block's listed date names the other."""
    row = _reg_row("410 MIDWAY ST")
    first = _check_reg(row)
    assert first.evidence["register_rows_at_address"] == 2 and first.evidence["register_fid"] == 27
    row["raw"]["code_enforcement"]["listed_date"] = "2023-10-09"
    second = _check_reg(row)
    assert second.evidence["register_fid"] == 28 and second.evidence["listed_date"] == "2023-10-09"
    assert second.evidence.get("board_block_agrees") is None            # it agrees with the row it picked


def test_register_a_planned_demolition_is_stale_only_when_the_county_layer_agrees():
    """120 N Blue Ridge Ave: the note says 'pulling demo permit to tear this down' (a plan, not a
    demolition). The county layer (building value 0, no heated area, class VACANT LAND) backs it:
    stale. Without the county layer's agreement it is unconfirmed (one weak source alone)."""
    row = _reg_row("120 N BLUE RIDGE AVE", demolished=True)
    row["parcel_id"] = "9579232596"
    res = _check_reg(row)
    ev = res.evidence
    assert res.verdict == "stale" and ev["reason"] == "structure_demolished"
    assert ev["demolition_note"] == "planned" and ev["demolished_basis"] == "county parcel layer and register NOTES"
    assert ev["county_building_value"] == 0.0 and ev["county_land_class"] == "VACANT LAND"
    assert ev["county_snapshot"] == "2023-07-07" and ev["county_matched_by"] == "pin"
    # the board's flag alone changes nothing
    assert _check_reg(_reg_row("120 N BLUE RIDGE AVE", demolished=True)).verdict == "stale"   # (by address)
    # the county layer unreachable: the plan stands alone
    nocounty = {u: b for u, b in REG_RESP.items() if "hendersoncountync" not in u}
    res = _check_reg(row, nocounty)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "demolition_not_established"
    assert res.evidence["demolition_note"] == "planned" and "county_building_value" not in res.evidence
    # the county layer shows a building: the plan did not happen (yet)
    standing = dict(REG_RESP)
    url = vsr.county_url_pin("9579232596")
    d = json.loads(standing[url])
    d["features"][0]["attributes"]["TOTAL_BLDG_VALUE_ASSESSED"] = 88000.0
    standing[url] = json.dumps(d)
    res = _check_reg(row, standing)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "demolition_not_established"
    assert res.evidence["county_building_value"] == 88000.0


def test_register_no_plans_to_demo_is_not_a_demolition():
    """618 Ferncliff Ln (the live case): NOTES 'NO IMMEDIATE PLANS TO DEMO AND REBUILD'. The
    scraper's keyword read 'DEMO' as demolished and v1 took the board's flag: stale. The county
    layer still carries building value 1,200 and 630 sq ft, so nothing here shows the structure
    gone: unconfirmed (the aerials that do show it gone cannot be read by code)."""
    row = _reg_row("618 FERNCLIFF", demolished=True)
    row["parcel_id"] = "9569344337"
    res = _check_reg(row)
    ev = res.evidence
    assert res.verdict == "unconfirmed" and ev["reason"] == "demolition_not_established"
    assert ev["demolition_note"] == "negated" and "demolished" not in ev
    assert ev["boarded_up"] is True and ev["condemned"] is True       # the register still says vacant
    assert ev["county_building_value"] == 1200.0 and ev["county_heated_area"] == 630.0
    # the same row with no county answer, or asked by address, decides nothing either
    row2 = _reg_row("618 FERNCLIFF", demolished=True)                  # no PIN: matched by address
    res2 = _check_reg(row2)
    assert res2.verdict == "unconfirmed" and res2.evidence["county_matched_by"] == "address"


def test_register_the_county_layer_alone_never_ends_a_row_the_notes_never_call_demolished():
    """The board says demolished, the matched row never mentions it, and only the county layer
    shows an empty parcel (building value 0): one weak source alone."""
    row = _reg_row("112 N BLUE RIDGE AVE", demolished=True)
    row["parcel_id"] = "9579230754"
    empty = dict(REG_RESP)
    url = vsr.county_url_pin("9579230754")
    d = json.loads(empty[url])
    d["features"][0]["attributes"].update(TOTAL_BLDG_VALUE_ASSESSED=0.0, HEATED_AREA=None)
    empty[url] = json.dumps(d)
    res = _check_reg(row, empty)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "demolition_not_established"
    assert res.evidence["board_demolished_flag_ignored"] is True


@pytest.mark.parametrize("text,kind", [
    ("DEMOED 7/25/2023", "completed"),
    ("HOUSE DEMOLISHED 2023", "completed"),
    ("NOT OCCUPIED - HOUSE TORN DOWN", "completed"),          # the dash starts a new clause
    ("STRUCTURE WAS RAZED; ENUMERATION", "completed"),
    ("BUILDING REMOVED IN 2022", "completed"),
    ("DEMOLITION COMPLETE", "completed"),
    ("JANE ROE - 2/13/2023 PULLING DEMO PERMIT TO TEAR THIS DOWN", "planned"),
    ("TO BE DEMOLISHED", "planned"),
    ("WILL BE DEMOLISHED SOON", "planned"),
    ("DEMOLITION PERMIT ISSUED", "planned"),
    ("PENDING DEMO", "planned"),
    ("CITY ORDERED HOUSE DEMOLISHED", "planned"),
    ("FIRE DAMAGE; HOUSE BOARDED UP NO IMMEDIATE PLANS TO DEMO AND REBUILD", "negated"),
    ("NOT DEMOLISHED", "negated"),
    ("NOT YET TORN DOWN", "negated"),
    ("FIRE/VACANT - 2/17/2022 - CAME IN FOR A BUILDING PERMIT FOR REMODEL AND REPAIR", None),
    ("YARD LEVELED, TRASH REMOVED", None),
    ("", None), (None, None)])
def test_classify_demolition(text, kind):
    assert vsr.classify_demolition(text) == kind


def test_classify_demolition_completed_beats_planned_beats_negated():
    assert vsr.classify_demolition("NO PLANS TO DEMO", "DEMOED") == "completed"
    assert vsr.classify_demolition("NO PLANS TO DEMO", "PULLING DEMO PERMIT") == "planned"


def test_house_street_matches_the_register_and_the_county_spellings():
    assert vsr.house_street("112 N BLUE RIDGE AVE") == ("112", "BLUE")
    assert vsr.house_street("618 FERNCLIFF") == vsr.house_street("618 FERNCLIFF LN") == ("618", "FERNCLIFF")
    assert vsr.house_street("0 FERNCLIFF") is None and vsr.house_street("FERNCLIFF LN") is None
    assert vsr.house_street("112 N BLUE RIDGE AVE") != vsr.house_street("120 N BLUE RIDGE AVE")


def test_county_parcel_must_be_this_address_and_falls_back_to_the_address_query():
    """The board's PIN can be a resolver's mistake: a PIN whose parcel sits at another address is
    not used, and the register's own address is asked instead."""
    row = {"parcel_id": "9569419828", "street_address": "618 FERNCLIFF"}          # 902 Sylvan's PIN
    res = run(vsr.county_parcel(row, "618 FERNCLIFF", ReplayFetcher(REG_RESP)))
    assert res["matched_by"] == "address" and res["building_value"] == 1200.0 and not res["no_building"]
    assert run(vsr.county_parcel({"parcel_id": None}, "", ReplayFetcher(REG_RESP))) is None
    assert run(vsr.county_parcel(row, "618 FERNCLIFF", ReplayFetcher({}))) is None   # unreachable
    err = {vsr.county_url_pin("9569419828"): json.dumps({"error": {"code": 400}}),
           vsr.county_url_address("618 FERNCLIFF"): json.dumps({"features": []})}
    assert run(vsr.county_parcel(row, "618 FERNCLIFF", ReplayFetcher(err))) is None


def test_county_view_no_building_needs_an_explicit_zero():
    assert vsr.county_view({"TOTAL_BLDG_VALUE_ASSESSED": 0.0, "HEATED_AREA": None})["no_building"] is True
    assert vsr.county_view({"TOTAL_BLDG_VALUE_ASSESSED": 0, "HEATED_AREA": 0})["no_building"] is True
    assert vsr.county_view({"TOTAL_BLDG_VALUE_ASSESSED": None, "HEATED_AREA": None})["no_building"] is False
    assert vsr.county_view({"TOTAL_BLDG_VALUE_ASSESSED": 0.0, "HEATED_AREA": 630})["no_building"] is False
    assert vsr.county_view({"TOTAL_BLDG_VALUE_ASSESSED": 1200.0, "HEATED_AREA": None})["no_building"] is False


def test_county_layer_is_the_parcel_caches_and_never_asks_for_an_owner():
    from foreclosure_scraper.parcel_cache import PARCEL_LAYERS
    assert vsr.COUNTY_LAYER + "/query" == PARCEL_LAYERS["Henderson"]["url"]
    asked = set(vsr.COUNTY_FIELDS.split(","))
    assert asked == {"PIN", "LOCATION_ADDR", "LAND_CLASS", "TOTAL_BLDG_VALUE_ASSESSED", "HEATED_AREA",
                     "AUT_SNAPSHOT_DATE"}
    assert not any(c.startswith(("PROPERTY_OWNER", "OWNER_MAIL")) for c in asked)
    for u in (vsr.county_url_pin("9579230754"), vsr.county_url_address("O'NEAL ST")):
        assert "OWNER" not in u.upper().replace("LOCATION_ADDR", "")
    assert "O%27%27NEAL" in vsr.county_url_address("o'neal st")          # a quote cannot break the query


def test_register_refuted_when_the_register_has_not_changed_since_the_row_was_seen():
    """113 S Justice St (a UST row on the 2026-10-06 board carrying the register's block): no
    entry at this address, and the register's last data edit (2024-07-24) predates the row."""
    res = _check_reg(_reg_row("113 S JUSTICE ST", demolished=True,
                              source="counties_generic.state_contamination.nc_ust_incidents"))
    assert res.verdict == "refuted" and res.evidence["reason"] == "not_on_register"


def test_register_stale_dropped_off_when_edited_since_the_row_was_seen():
    res = _check_reg(_reg_row("113 S JUSTICE ST", first_seen="2024-01-02T00:00:00"))
    assert res.verdict == "stale" and res.evidence["reason"] == "dropped_off_register"
    res = _check_reg({**_reg_row("113 S JUSTICE ST"), "first_seen": None})
    assert res.verdict == "stale"


def test_register_blank_occupancy_is_unconfirmed():
    res = _check_reg(_reg_row("1744 MEADOWBROOK TER"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "occupancy_not_recorded"
    assert res.evidence["occupied"] is None


def test_register_no_numbered_address():
    res = _check_reg(_reg_row("MEADOWBROOK TER"))
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == "no_numbered_address"


@pytest.mark.parametrize("damage,reason", [("none", "layer_unavailable"),
                                           ("count0", "layer_empty"),
                                           ("count_more", "layer_incomplete")])
def test_register_bad_layer_is_never_decisive(damage, reason):
    resp = dict(REG_RESP)
    cnt = agl.count_url(vsr.layer())
    if damage == "none":
        resp = {}
    elif damage == "count0":
        resp[cnt] = json.dumps({"count": 0})
    else:
        resp[cnt] = json.dumps({"count": 53})
    res = _check_reg(_reg_row("113 S JUSTICE ST", first_seen="2024-01-02T00:00:00"), resp)
    assert res.verdict == "unconfirmed" and res.evidence["reason"] == reason


def test_register_one_load_per_run_and_only_safe_columns():
    client = ReplayFetcher(REG_RESP)
    rows = [_reg_row(a) for a in ("1001 TEMON ST", "601 E PACE ST", "902 SYLVAN BLVD",
                                  "1744 MEADOWBROOK TER", "201 BLUE RIDGE ST")] * 4

    async def go():
        return [await vsr.verify(r, client) for r in rows]
    run(go())
    assert len(client.asked) == 3                               # meta, count, one page
    page = next(u for u in client.asked if "outFields" in u)
    asked = set(parse_qs(urlsplit(page).query)["outFields"][0].split(","))
    assert asked == {"FID", "DATE", "ADDRESS", "OCCUPIED", "BOARDED_UP", "CONDEMNED",
                     "DELINQUENT_TAX", "NOTES"}              # NOTES: classified in memory, never kept
    assert not asked & set(vsr.NEVER_FIELDS)
    assert "NOTES" not in vsr.NEVER_FIELDS and "OWNER" in vsr.NEVER_FIELDS and "EMAIL" in vsr.NEVER_FIELDS
    assert vsr._fields_are_safe()


# --------------------------------------------------------------------------- #
# privacy of what is published                                                 #
# --------------------------------------------------------------------------- #

_OVT_EVIDENCE_KEYS = {"board_pin", "claimed_case_ids", "claimed_categories", "layer",
                      "fetched_at", "layer_count", "layer_rows_loaded", "layer_data_last_edit",
                      "layer_error", "reason", "matched_by", "cases", "cases_matched",
                      "open_distress", "open_other", "closed_distress", "blank_status_records",
                      "claimed_cases_elsewhere"}
_CASE_KEYS = {"case_id", "category", "distress", "status", "open", "opened", "closed"}
_REG_EVIDENCE_KEYS = {"layer", "fetched_at", "layer_count", "layer_rows_loaded",
                      "layer_data_last_edit", "layer_error", "register_age_days", "reason",
                      "matched_by", "register_fid", "listed_date", "occupied", "boarded_up",
                      "condemned", "condemned_date", "register_rows_at_address", "demolished",
                      "demolished_basis", "row_first_seen",
                      # v2
                      "register_row_age_days", "demolition_note", "board_block_agrees",
                      "board_demolished_flag_ignored", "county_matched_by", "county_building_value",
                      "county_heated_area", "county_land_class", "county_snapshot"}


def test_evidence_is_a_closed_whitelist():
    ovt_rows = [_ovt_row(*a) for a in (
        ("9681135571", "23 MONO LN", ["469"], ["General"]),
        ("9660054549", "110 OAKWOOD RD", ["1994"], ["Solid Waste"]),
        ("9568943079", "637 SPARTANBURG HWY", ["3356"], ["Nuisance"]),
        ("9651402705", "113 PUMA DR", ["1470"], ["Solid Waste"]))]
    for r in ovt_rows:
        agl._RUNS.clear()
        ev = _check_ovt(r).evidence
        assert set(ev) <= _OVT_EVIDENCE_KEYS, set(ev) - _OVT_EVIDENCE_KEYS
        for c in ev.get("cases", []):
            assert set(c) <= _CASE_KEYS
    for a in ("1001 TEMON ST", "601 E PACE ST", "902 SYLVAN BLVD", "113 S JUSTICE ST",
              "1744 MEADOWBROOK TER", "201 BLUE RIDGE ST", "1030 N JUSTICE ST", "618 FERNCLIFF",
              "112 N BLUE RIDGE AVE", "120 N BLUE RIDGE AVE"):
        agl._RUNS.clear()
        ev = _check_reg(_reg_row(a, demolished=True)).evidence
        assert set(ev) <= _REG_EVIDENCE_KEYS, set(ev) - _REG_EVIDENCE_KEYS
        blob = json.dumps(ev)
        for note in ("DOE", "ROE", "PERMIT", "REBUILD", "ENUMERATION", "TENANT"):   # no note text, no name
            assert note not in blob.upper()


#: the register page's NOTES cells in the fixture: the notes the verdicts turn on, in their real
#: wording with every name replaced, and the placeholder NOTE for all others (officers' notes
#: hold names and an owner's email; the live classification of every row is preserved)
_FIXTURE_NOTES = {None, "NOTE", "DEMOED 7/25/2023", "JANE ROE", "FIRE DAMAGE ; ENUMERATION",
                  "JOHN DOE - 2/13/2023 PULLING DEMO PERMIT TO TEAR THIS DOWN",
                  "FIRE DAMAGE; HOUSE BOARDED UP NO IMMEDIATE PLANS TO DEMO AND REBUILD",
                  "FIRE/VACANT/ENUMERATION - 2/17/2022 - A CONTRACTOR CAME IN TO GET A BUILDING PERMIT "
                  "FOR REMODEL AND REPAIR", "TENANT IS JANE ROE, UTILITIES ACTIVE"}


def test_fixtures_hold_no_personal_columns():
    for resp in (OVT_RESP, REG_RESP):
        for url, body in resp.items():
            d = json.loads(body)
            for f in d.get("features") or []:
                cols = set(f["attributes"])
                assert not cols & {"parcelOwner", "OWNER", "MAILING_ADDRESS", "PHONE__", "EMAIL",
                                   "column19", "MAIL_CITY", "ZIP", "ST", "PROPERTY_OWNER",
                                   "OWNER_MAIL_1", "OWNER_MAIL_CITY"}
                if "NOTES" in cols:
                    assert url in REG_RESP and f["attributes"]["NOTES"] in _FIXTURE_NOTES
    assert not re.search(r"@|\d{3}[-. ]\d{3}[-. ]\d{4}", "".join(REG_RESP.values()))


def test_ledger_row_summary_drops_owner_name(tmp_path):
    """The sweep pops ROW_SUMMARY_EXCLUDE from every entry it records (verification_sweep)."""
    led = Ledger("code_enforcement", path=tmp_path / "code_enforcement.json")
    row = {**_ovt_row(), "owner_name": "TESTOWNER PATRICK"}
    res = _check_ovt(row)
    entry = led.record(row, res, ttl_days=ovt.TTL_DAYS, governs=ovt.GOVERNS)
    for f in ovt.ROW_SUMMARY_EXCLUDE:
        entry["row"].pop(f, None)
    led.save()
    text = (tmp_path / "code_enforcement.json").read_text()
    assert "TESTOWNER" not in text and "parcelOwner" not in text


# --------------------------------------------------------------------------- #
# scoring: the source-qualified partial rule, in both readers                   #
# --------------------------------------------------------------------------- #

def test_qualifiers_helper():
    drop = {"tax_lien", f"code_enforcement:{OVT_SRC}", "code_enforcement:", "incarceration:jail"}
    assert core.qualifiers(drop, "code_enforcement") == {OVT_SRC}
    assert core.qualifiers(drop, "vacant_structure") == set()
    assert core.qualifiers(None, "x") == set()
    assert core.block_suppressed({"source": OVT_SRC}, {OVT_SRC})
    assert not core.block_suppressed({"source": REG_SRC}, {OVT_SRC})
    assert not core.block_suppressed(True, {OVT_SRC})
    assert not core.block_suppressed({"source": OVT_SRC}, set())


def _vrec(signal, verdict, governs, *, expires_in_days=10):
    checked = datetime(2026, 10, 6, tzinfo=timezone.utc)
    return {"signal": signal, "verdict": verdict, "evidence": {}, "source": "x",
            "checked_at": core.iso_z(checked), "verifier_version": "v1", "verifier": "x",
            "expires_at": core.iso_z(checked + timedelta(days=expires_in_days)),
            "governs": list(governs)}


def _li(ce=None, vacancy=None, verification=None, parcel="9681135571", source=None):
    raw = {}
    if ce is not None:
        raw["code_enforcement"] = ce
    if vacancy is not None:
        raw["vacancy"] = vacancy
    if verification is not None:
        raw["verification"] = verification
    return Listing(source=source or "counties_nc.henderson_code_violations",
                   source_url="https://example.invalid/x", listing_type=ListingType.UNKNOWN,
                   state="NC", county="Henderson", parcel_id=parcel,
                   street_address="23 MONO LN", raw=raw)


_OVT_CE = {"has_open": True, "open_violations": 1, "violation_types": ["Zoning"],
           "severe": False, "source": OVT_SRC}
_REG_CE = {"has_open": True, "open_violations": 1, "kind": "vacant_structure_register",
           "source": REG_SRC}
_REG_VAC = {"vacant": True, "boarded_up": None, "source": REG_SRC}
_OTHER_CE = {"has_open": True, "open_violations": 1, "kind": "condemnation",
             "source": "spartanburg_city_master_condemnation_list"}


def _scored(li):
    return {n for n, _c, _w in ds._signals_for(li, today=TODAY)}


def _facets(li):
    return _facet_signals(li, TODAY)


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_ovt_verdict_ends_the_ovt_block_only(verdict):
    rec = _vrec("code_enforcement", verdict, ovt.GOVERNS)
    assert "code_enforcement" in _scored(_li(_OVT_CE))          # baseline: scored today
    hit = _li(_OVT_CE, verification=[rec])
    assert "code_enforcement" not in _scored(hit) and "code_enforcement" not in _facets(hit)
    for other in (_REG_CE, _OTHER_CE):                          # same parcel, other source
        keep = _li(other, verification=[rec])
        assert "code_enforcement" in _scored(keep) and "code_enforcement" in _facets(keep)


@pytest.mark.parametrize("verdict", ["refuted", "stale"])
def test_register_verdict_ends_the_register_blocks_only(verdict):
    rec = _vrec("vacant_structure", verdict, vsr.GOVERNS)
    base = _li(_REG_CE, _REG_VAC)
    assert {"code_enforcement", "vacant_structure"} <= _scored(base)
    hit = _li(_REG_CE, _REG_VAC, verification=[rec])
    assert not {"code_enforcement", "vacant_structure"} & _scored(hit)
    assert not {"code_enforcement", "vacant_structure"} & _facets(hit)
    other_vac = {**_REG_VAC, "source": "some_other_vacancy_register"}
    keep = _li(_OVT_CE, other_vac, verification=[rec])
    assert {"code_enforcement", "vacant_structure"} <= _scored(keep)
    assert {"code_enforcement", "vacant_structure"} <= _facets(keep)


@pytest.mark.parametrize("verdict", ["confirmed", "unconfirmed", "wall"])
def test_other_verdicts_change_nothing(verdict):
    recs = [_vrec("code_enforcement", verdict, ovt.GOVERNS),
            _vrec("vacant_structure", verdict, vsr.GOVERNS)]
    for li_args in ((_OVT_CE,), (_REG_CE, _REG_VAC)):
        assert _scored(_li(*li_args, verification=recs)) == _scored(_li(*li_args))
        assert _facets(_li(*li_args, verification=recs)) == _facets(_li(*li_args))


def test_an_expired_verdict_changes_nothing():
    rec = _vrec("code_enforcement", "refuted", ovt.GOVERNS, expires_in_days=-1)
    assert "code_enforcement" in _scored(_li(_OVT_CE, verification=[rec]))


def test_vacancy_adjacent_false_still_wins_without_a_verdict():
    """The scraper's own 2026-10-02 gate is untouched: a Zoning-only block that says
    vacancy_adjacent False does not score with or without a verification."""
    assert "code_enforcement" not in _scored(_li({**_OVT_CE, "vacancy_adjacent": False}))


def test_apply_then_score_end_to_end(tmp_path):
    """Ledger -> apply_verification -> _signals_for, with verdicts produced by the verifiers on
    the real layers: the Zoning parcel and the closed-case parcel lose code_enforcement, the
    confirmed parcel keeps it, the register's demolished structure (201 Blue Ridge St, DEMOED)
    loses both register signals."""
    pairs = [
        (_ovt_row("9661405931", "1772 HOWARD GAP ROAD", ["844"], ["Zoning"]), ovt, "refuted"),
        (_ovt_row("9660054549", "110 OAKWOOD RD", ["1994"], ["Solid Waste"]), ovt, "stale"),
        (_ovt_row("9681135571", "23 MONO LN", ["469"], ["Junkyard"]), ovt, "confirmed"),
        (_reg_row("201 BLUE RIDGE ST"), vsr, "stale"),
        (_reg_row("1001 TEMON ST"), vsr, "confirmed"),
    ]
    leds = {m.SIGNAL: Ledger(m.SIGNAL, path=tmp_path / f"{m.SIGNAL}.json") for m in (ovt, vsr)}
    listings = []
    for row, mod, want in pairs:
        agl._RUNS.clear()
        res = run(mod.verify(row, ReplayFetcher(OVT_RESP if mod is ovt else REG_RESP)))
        assert res.verdict == want
        leds[mod.SIGNAL].record(row, res, ttl_days=mod.TTL_DAYS, governs=mod.GOVERNS)
        raw = {k: dict(v) for k, v in row["raw"].items()}
        listings.append(Listing(source=row["source"], source_url="https://example.invalid/x",
                                listing_type=ListingType.UNKNOWN, state="NC",
                                county="Henderson", parcel_id=row["parcel_id"],
                                street_address=row["street_address"], raw=raw))
    for led in leds.values():
        led.save()
    before = [_scored(li) for li in listings]
    counts = apply_verification(listings, directory=tmp_path,
                                now=datetime(2026, 10, 6, 12, tzinfo=timezone.utc))
    assert counts["records"] == 5 and counts["suppressing"] == 3
    after = [_scored(li) for li in listings]
    assert "code_enforcement" in before[0] and "code_enforcement" not in after[0]
    assert "code_enforcement" in before[1] and "code_enforcement" not in after[1]
    assert after[2] == before[2] and "code_enforcement" in after[2]
    assert {"code_enforcement", "vacant_structure"} <= before[3]
    assert not {"code_enforcement", "vacant_structure"} & after[3]
    assert after[4] == before[4] and "vacant_structure" in after[4]


# --------------------------------------------------------------------------- #
# the 2026-10-06 live sweep, reproduced                                        #
# --------------------------------------------------------------------------- #
# tests/fixtures/verification/code_enforcement_cases.json: the board rows the bounded live sweep
# (43119aaa, --max-rows 50 per signal, HOT/WARM first) checked, cut to the fields the verifiers
# read (no owner, no notes), with the verdict it pushed. The layer fixtures above are that same
# sweep's responses (byte-identical to its --capture-dir).

_CASES = json.loads((FIX / "code_enforcement_cases.json").read_text())["cases"]


#: the three register verdicts vacant_structure v2 changed on the live sweep's own rows (the
#: fixture's verdict/reason are what v1 answered): the keyword false positive (618 Ferncliff Ln),
#: the occupied row from a layer 803 days old (902 Sylvan Blvd), and the block cross-wired from the
#: row next door (112 N Blue Ridge Ave); see the tests of each above
V2_CHANGED = {"parcel:NC:henderson:9569344337": ("unconfirmed", "demolition_not_established"),
              "parcel:NC:henderson:9569419828": ("unconfirmed", "register_occupancy_too_old"),
              "parcel:NC:henderson:9579230754": ("unconfirmed", "occupancy_not_recorded")}


def test_the_live_sweep_verdicts_reproduce_exactly():
    clients = {"code_enforcement": (ovt, ReplayFetcher(OVT_RESP)),
               "vacant_structure": (vsr, ReplayFetcher(REG_RESP))}

    async def go():
        out = []
        for c in _CASES:
            mod, client = clients[c["signal"]]
            assert mod.applies(c["row"])
            res = await mod.verify(c["row"], client)
            out.append((c["key"], res.verdict, res.evidence.get("reason")))
        return out
    got = run(go())
    want = [(c["key"], *V2_CHANGED.get(c["key"], (c["verdict"], c["reason"]))) if c["signal"] == "vacant_structure"
            else (c["key"], c["verdict"], c["reason"]) for c in _CASES]
    assert got == want
    assert len(_CASES) == 100
    # one load per layer for all 100 properties
    assert len(clients["code_enforcement"][1].asked) == 4
    vs = clients["vacant_structure"][1].asked
    assert len([u for u in vs if "hendersoncountync" not in u]) == 3
    assert len([u for u in vs if "hendersoncountync" in u]) == 3        # only the three rows that need it


def test_the_live_split():
    """The sweep's split as v1 answered it (the fixture); V2_CHANGED moves three vacant_structure
    rows (two stale and one more to unconfirmed): v2 is stale 2, unconfirmed 19."""
    from collections import Counter
    split = Counter((c["signal"], c["verdict"]) for c in _CASES)
    assert split == Counter({("code_enforcement", "confirmed"): 37,
                             ("code_enforcement", "refuted"): 12,
                             ("code_enforcement", "stale"): 1,
                             ("vacant_structure", "confirmed"): 28,
                             ("vacant_structure", "unconfirmed"): 16,
                             ("vacant_structure", "stale"): 5,
                             ("vacant_structure", "refuted"): 1})

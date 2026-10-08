"""A county tax debt binds only to its own parcel (tax_binding.py, 2026-10-08).

Every parcel, owner and address here is made up."""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

from foreclosure_scraper import tax_binding as tb
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

TODAY = date(2026, 10, 8)
NOW = datetime(2026, 10, 8)
CSV = "counties_nc.nc_county_csv_delinquent_tax"
PTS = "counties_nc.nc_ptscloud_delinquent_tax"


def _li(source=CSV, parcel="R11111-001-001-001", county="Sample", state="NC", street=None, raw=None,
        url="https://x.invalid/roll.csv", lt=ListingType.TAX_LIEN):
    return Listing(source=source, source_url=url, listing_type=lt, property_kind=PropertyKind.UNKNOWN,
                   state=state, county=county, parcel_id=parcel, street_address=street,
                   first_seen=NOW, last_seen=NOW, raw=raw or {})


def _csv_block(pid, owed=4100.01, situs=None, county="Sample"):
    return {"county": county, "county_id": pid, "id_is_parcel": True, "principal_tax_due": owed,
            "bill_years": ["2019", "2020", "2021"], "year_span": "2019-2021", "owner": "TEST OWNER",
            **({"situs": situs} if situs else {})}


def _derived(owed):
    return {"tax_owed": {"balance": owed, "kind": "delinquent_tax", "source": CSV, "year": 2019,
                         "basis": "own_record"},
            "tax_aging_surfaced": {"tax_year": 2019, "years_delinquent": 7, "status": "delinquent",
                                   "source": "tax_owed"},
            "tax_aging_high": True,
            "amount_owed": {"value": owed, "source": "tax_owed", "is_actual_debt": True}}


# ---- the per-row rule ----------------------------------------------------------------------------

def test_own_parcel_block_binds():
    li = _li(raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001")})
    assert tb.bind_block(li, "nc_county_csv_delinquent_tax", li.raw["nc_county_csv_delinquent_tax"]) == "own_parcel"


def test_another_parcels_block_is_removed_with_everything_derived_from_it():
    # the finding: one roll entry copied onto a row of a DIFFERENT parcel of the same county
    li = _li(parcel="R22222-002-002-002",
             raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"), **_derived(4100.01),
                  "two_year_delinquent": {"is_two_year_plus": True, "years": 3}})
    stats = tb.scrub_unbound_tax([li])
    assert stats["by_reason"] == {"other_parcel": 1, "tax_owed_block_removed": 1}
    for k in ("nc_county_csv_delinquent_tax", "tax_owed", "tax_aging_surfaced", "tax_aging_high",
              "amount_owed", "two_year_delinquent"):
        assert k not in li.raw, k


def test_a_block_from_another_county_never_binds():
    # a PTS Cloud bill whose tenant (county) is not the row's: Lincoln row, Pitt bill
    blk = {"tenant": "Pitt", "parcel": "54321", "principal_tax_due": 500.37, "tax_year": "2006"}
    li = _li(source="counties_nc.lincoln_vacant", parcel=None, county="Lincoln",
             raw={"nc_ptscloud_delinquent_tax": blk,
                  "also_seen_in": [{"source": PTS, "url": "https://x.invalid/pts"}],
                  **_derived(500.37)})
    assert tb.bind_block(li, "nc_ptscloud_delinquent_tax", blk) == "foreign_county"
    tb.scrub_unbound_tax([li])
    assert "nc_ptscloud_delinquent_tax" not in li.raw and "tax_owed" not in li.raw


def test_placeholder_ids_are_no_key():
    for pid in ("0", "0000000000", "ID", "ESCROW :", "TRUE", "", None, "123"):
        assert not tb.usable_id(tb.norm_id(pid)), pid
    assert tb.usable_id(tb.norm_id("R11111-001-001-001"))
    # a placeholder in the block cannot prove or disprove anything: the own-source rule decides
    blk = {"tenant": "Sample", "parcel": "0", "principal_tax_due": 100.0, "tax_year": "2024"}
    li = _li(source=PTS, parcel="9999123456", raw={"nc_ptscloud_delinquent_tax": blk})
    assert tb.bind_block(li, "nc_ptscloud_delinquent_tax", blk) == "own_source"


def test_two_numbering_systems_are_not_compared():
    # a 5-digit roll account against a 10-digit PIN: neither the same nor a different parcel
    blk = {"tenant": "Sample", "parcel": "20009", "principal_tax_due": 3500.91, "tax_year": "2017"}
    li = _li(source=PTS, parcel="9000000357", raw={"nc_ptscloud_delinquent_tax": blk})
    assert tb.id_relation(["20009"], ["9000000357"]) == "not_comparable"
    assert tb.bind_block(li, "nc_ptscloud_delinquent_tax", blk) == "own_source"
    tb.scrub_unbound_tax([li])
    assert "nc_ptscloud_delinquent_tax" in li.raw


def test_same_parcel_written_two_ways():
    assert tb.same_id(tb.norm_id("9667-32-2507-00000"), tb.norm_id("966732250700000"))
    assert tb.same_id("00412345", "412345")
    assert not tb.same_id(tb.norm_id("45-453-167"), tb.norm_id("45-453-168"))
    assert tb.id_relation(["45-453-167"], ["45-453-168"]) == "different"


def test_address_evidence_when_there_is_no_comparable_key():
    blk = {"principal_tax_due": 800.4, "situs": "12 SAMPLE CREEK RD"}
    li = _li(source="counties_x.code_cases", parcel=None, street="12 Sample Creek Road",
             raw={"county_tax_list": blk})
    assert tb.bind_block(li, "county_tax_list", blk) == "own_address"
    li2 = _li(source="counties_x.code_cases", parcel=None, street="14 Sample Creek Road",
              raw={"county_tax_list": dict(blk)})
    assert tb.bind_block(li2, "county_tax_list", li2.raw["county_tax_list"]) == "other_address"


def test_no_evidence_is_not_a_binding_but_a_recorded_merge_is():
    blk = {"principal_tax_due": 77.0, "tax_year": 2024}
    li = _li(source="counties_x.code_cases", parcel=None, raw={"county_tax_list": blk})
    assert tb.bind_block(li, "county_tax_list", blk) == "no_evidence"
    li.raw["also_seen_in"] = [{"source": "counties_x.county_tax_list", "url": "https://x.invalid/2"}]
    assert tb.bind_block(li, "county_tax_list", blk) == "own_source"


def test_alias_short_id_binds_to_the_pin_row():
    # Lincoln: the PDF roll keys the bill by the county's short PARCELID; the vacant-land row carries
    # the PIN as parcel_id and the short id in its own block
    blk = {"county": "Lincoln", "county_id": "51099", "id_is_parcel": True, "principal_tax_due": 400.6,
           "tax_year": 2025}
    li = _li(source="counties_nc.lincoln_vacant", parcel="3600000001", county="Lincoln",
             raw={"lincoln_vacant": {"PARCELID": "51099", "PIN": "3600000001"},
                  "nc_county_pdf_delinquent_tax": blk,
                  "also_seen_in": [{"source": "counties_nc.nc_county_pdf_delinquent_tax", "url": "u"}]})
    assert tb.bind_block(li, "nc_county_pdf_delinquent_tax", blk) == "own_parcel"
    # a different short id of the same numbering system is another parcel
    li.raw["nc_county_pdf_delinquent_tax"] = dict(blk, county_id="51098")
    assert tb.bind_block(li, "nc_county_pdf_delinquent_tax", li.raw["nc_county_pdf_delinquent_tax"]) == "other_parcel"


def test_alias_table_maps_a_short_block_id_to_the_rows_pin():
    blk = {"parcel": "1600009", "amount_owed": 300.7, "bill_count": 1, "tax_year": "2025"}
    li = _li(source="counties_nc.nc_heir_estate_parcels", parcel="1500000095", county="Rutherford",
             raw={"rutherford_tax": blk})
    assert tb.bind_block(li, "rutherford_tax", blk) == "no_evidence"
    table = {("NC", "rutherford", "1600009"): "1500000095"}
    assert tb.bind_block(li, "rutherford_tax", blk, table) == "own_parcel"


# ---- the shared test (one roll entry on two different properties) --------------------------------

def test_a_block_copied_onto_many_rows_stays_only_on_its_own_parcel():
    own = _li(parcel="R11111-001-001-001", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"),
                                               **_derived(4100.01)})
    copies = [_li(parcel=f"R3333{n}-00{n}-00{n}-00{n}", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"),
                                                            **_derived(4100.01)})
              for n in range(1, 6)]
    stats = tb.scrub_unbound_tax([own, *copies])
    assert "tax_owed" in own.raw and "nc_county_csv_delinquent_tax" in own.raw
    assert all("tax_owed" not in c.raw and "nc_county_csv_delinquent_tax" not in c.raw for c in copies)
    assert stats["tax_owed_removed"] == 5 and stats["rows_scrubbed"] == 5


def test_a_shared_block_without_a_parcel_binds_nowhere():
    # an invoice on two different properties: neither row can show it is its own
    blk = {"invoice_number": "2099-0000001", "tax_year": 2025, "total_due": 300.04, "delinquent": True}
    a = _li(source="counties_sc.sample_paystar_tax", parcel="100-00-00-001", state="SC",
            raw={"sample_paystar_tax": dict(blk)})
    b = _li(source="counties_sc.sample_paystar_tax", parcel="200-00-00-002", state="SC",
            raw={"sample_paystar_tax": dict(blk)})
    tb.scrub_unbound_tax([a, b])
    assert "sample_paystar_tax" not in a.raw and "sample_paystar_tax" not in b.raw


def test_two_rows_of_one_property_keep_their_shared_block():
    blk = {"invoice_number": "2099-0000002", "tax_year": 2025, "total_due": 90.0}
    a = _li(source="counties_sc.sample_paystar_tax", parcel="100-00-00-003", state="SC",
            raw={"sample_paystar_tax": dict(blk)})
    b = _li(source="counties_sc.sample_paystar_tax", parcel="1000000003", state="SC",
            raw={"sample_paystar_tax": dict(blk)})
    tb.scrub_unbound_tax([a, b])
    assert "sample_paystar_tax" in a.raw and "sample_paystar_tax" in b.raw


def test_a_generic_block_is_never_called_shared():
    # cycle flags with no id and no amount (pickens_delinquent) are the same on thousands of
    # parcels and attach no debt: left alone
    flags = {"chronic": False, "repeat_delinquent": False, "cycle_count": 1, "first_cycle": 2022,
             "latest_cycle": 2022}
    rows = [_li(source="counties_sc.sample_delinquent_parcels", parcel=f"40{n}0-00-00-000{n}", state="SC",
                raw={"sample_delinquent": dict(flags)}) for n in range(1, 4)]
    tb.scrub_unbound_tax(rows)
    assert all("sample_delinquent" in r.raw for r in rows)


def _owed_row(pid, owed, source="counties_nc.sample_vacant", year=2025):
    return _li(source=source, parcel=pid,
               raw={"tax_owed": {"balance": owed, "kind": "delinquent_tax", "year": year,
                                 "source": source, "basis": "own_record"},
                    "tax_aging_surfaced": {"years_delinquent": 1, "source": "tax_owed"}})


def test_an_unbacked_balance_copied_across_sources_goes():
    # no block on either row states the balance, and rows of two unrelated sources (different
    # parcels) owe the same cents in the same year: a copy
    a = _owed_row("3600000011", 4000.41, source="national.sample_listings")
    b = _owed_row("3600000012", 4000.41, source="counties_x.sample_court_index")
    c = _owed_row("3600000013", 902.5)
    tb.scrub_unbound_tax([a, b, c])
    assert "tax_owed" not in a.raw and "tax_owed" not in b.raw
    assert "tax_aging_surfaced" not in a.raw
    assert c.raw["tax_owed"]["balance"] == 902.5


def test_equal_bills_on_a_few_roll_lots_stay_but_a_mass_copy_goes():
    lots = [_owed_row(f"36000001{n:02d}", 270.99, source="counties_sc.sample_delinquent_parcels")
            for n in range(5)]
    stray = _owed_row("3600000199", 270.99, source="counties_x.sample_flood_damage")
    tb.scrub_unbound_tax([*lots, stray])
    assert all(li.raw["tax_owed"]["balance"] == 270.99 for li in lots)    # the roll's own rows
    assert "tax_owed" not in stray.raw                                    # a copy on a non-roll row
    mass = [_owed_row(f"36000002{n:02d}", 160.04, source="counties_sc.sample_delinquent_parcels")
            for n in range(tb.MASS_COPY_PROPERTIES)]
    tb.scrub_unbound_tax(mass)
    assert all("tax_owed" not in li.raw for li in mass)


def test_an_unbacked_balance_equal_to_a_removed_copy_goes():
    # one block copied onto two other properties is removed from both; a third row kept only the
    # balance taken from it (its block was stripped earlier): that balance goes too
    copies = [_li(parcel=f"R2222{n}-002-002-002", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001", 100.44)})
              for n in (1, 2)]
    leftover = _owed_row("R33333-003-003-003", 100.44, source="counties_x.sample_permits")
    stats = tb.scrub_unbound_tax([*copies, leftover])
    assert "tax_owed" not in leftover.raw
    assert stats["by_reason"]["tax_owed_copied_balance"] == 1
    # a block removed from ONE row only is no evidence about an equal bill elsewhere
    one = _li(parcel="R44444-004-004-004", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001", 60.81)})
    lot = _owed_row("R55555-005-005-005", 60.81, source="counties_x.sample_permits")
    tb.scrub_unbound_tax([one, lot])
    assert lot.raw["tax_owed"]["balance"] == 60.81


def test_other_liens_are_left_alone():
    # a state tax lien is a person's: the same lien on two of the debtor's properties is right
    lien = {"balance": 7000.11, "source": "sc_dew_lien_registry", "owner": "TEST DEBTOR"}
    a = _li(source="counties_sc.sc_dew_lien_registry", parcel="9-99-08-005.00", state="SC",
            raw={"sc_state_tax_lien": dict(lien)})
    b = _li(source="counties_sc.sc_dew_lien_registry", parcel="9-99-08-006.00", state="SC",
            raw={"sc_state_tax_lien": dict(lien)})
    tb.scrub_unbound_tax([a, b])
    assert "sc_state_tax_lien" in a.raw and "sc_state_tax_lien" in b.raw


def test_scrub_is_idempotent_and_works_on_board_row_dicts():
    rows = [_li(parcel=f"R4444{n}-00{n}-00{n}-00{n}", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"),
                                                          **_derived(4100.01)}).model_dump(mode="json")
            for n in range(1, 4)]
    first = tb.scrub_unbound_tax(rows)
    assert first["rows_scrubbed"] == 3
    again = tb.scrub_unbound_tax(rows)
    assert again["rows_scrubbed"] == 0 and again["blocks_removed"] == 0


def test_the_record_hook_names_each_removal_without_personal_data():
    li = _li(parcel="R22222-002-002-002", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"),
                                              **_derived(4100.01)})
    rec = []
    tb.scrub_unbound_tax([li], record=rec)
    assert rec == [(0, "nc_county_csv_delinquent_tax", "other_parcel"), (0, "tax_owed", "block_removed")]


# ---- enrich_tax_owed applies the rule before it normalizes ---------------------------------------

def test_enrich_tax_owed_never_stamps_another_parcels_balance():
    own = _li(parcel="R11111-001-001-001", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001")})
    copy_row = _li(parcel="R55555-005-005-005", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001")})
    stats = enrich_tax_owed([own, copy_row], today=TODAY)
    assert own.raw["tax_owed"]["balance"] == 4100.01
    assert own.raw["tax_owed"]["parcel"] == "R11111-001-001-001"
    assert "tax_owed" not in copy_row.raw
    assert stats["unbound"]["blocks_removed"] == 1


def test_cross_reference_needs_a_real_key_and_one_balance():
    tax = _li(source="counties_nc.buncombe_delinquent_tax", parcel="9678-12-3456",
              raw={"buncombe_delinquent_tax": {"principal_tax_due": 920.0, "pin": "9678123456"}})
    court = _li(source="national.courtlistener_bankruptcy", parcel="9678123456", raw={})
    enrich_tax_owed([tax, court], today=TODAY)
    assert court.raw["tax_owed"]["basis"] == "parcel_cross_ref"
    assert court.raw["tax_owed"]["parcel"] == "9678123456"
    # a short id is no cross-reference key
    t2 = _li(source="counties_nc.buncombe_delinquent_tax", parcel="12345",
             raw={"buncombe_delinquent_tax": {"principal_tax_due": 50.0}})
    c2 = _li(source="national.courtlistener_bankruptcy", parcel="12345", raw={})
    enrich_tax_owed([t2, c2], today=TODAY)
    assert "tax_owed" not in c2.raw
    # two different balances under one id: no cross reference
    a = _li(source="counties_nc.buncombe_delinquent_tax", parcel="9678-12-9999",
            raw={"buncombe_delinquent_tax": {"principal_tax_due": 100.0, "pin": "9678129999"}})
    b = _li(source="counties.multi_year_delinquent_tax", parcel="9678129999",
            raw={"multi_year_delinquent_tax": {"total_due": 900.0, "parcel_key": "9678129999"}})
    c = _li(source="national.courtlistener_bankruptcy", parcel="9678129999", raw={})
    stats = enrich_tax_owed([a, b, c], today=TODAY)
    assert "tax_owed" not in c.raw and stats["cross_ref_keys_ambiguous"] == 1


def test_an_old_cross_reference_is_rebuilt_or_dropped_never_promoted():
    court = _li(source="national.courtlistener_bankruptcy", parcel="9678120000",
                raw={"tax_owed": {"balance": 920.0, "kind": "delinquent_tax", "year": 2024,
                                  "source": "counties_nc.buncombe_delinquent_tax", "basis": "parcel_cross_ref"},
                     "tax_aging_surfaced": {"years_delinquent": 2, "source": "tax_owed"},
                     "tax_aging_high": True})
    enrich_tax_owed([court], today=TODAY)       # the tax row is gone this run
    assert "tax_owed" not in court.raw
    assert "tax_aging_surfaced" not in court.raw and "tax_aging_high" not in court.raw


def test_gate_off_keeps_the_old_behaviour(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_TAX_BINDING", "0")
    copy_row = _li(parcel="R55555-005-005-005", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001")})
    enrich_tax_owed([copy_row], today=TODAY)
    assert copy_row.raw["tax_owed"]["balance"] == 4100.01


# ---- the carry-over: a prior copy never overwrites this run's own block --------------------------

def test_keep_fresh_tax_blocks_restores_the_fresh_roll_entry():
    fresh = _li(parcel="R66666-006-006-006", raw={"nc_county_csv_delinquent_tax": _csv_block("R66666-006-006-006", 812.0)})
    prior = _li(parcel="R66666-006-006-006", raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"),
                                                 "vision": {"score": 3}})
    merged = fresh.merge(prior)
    # Listing.merge(): the prior's leaves win inside raw
    assert merged.raw["nc_county_csv_delinquent_tax"]["county_id"] == "R11111-001-001-001"
    assert tb.keep_fresh_tax_blocks(fresh, merged) == 1
    assert merged.raw["nc_county_csv_delinquent_tax"] == fresh.raw["nc_county_csv_delinquent_tax"]
    assert merged.raw["vision"] == {"score": 3}                       # other prior enrichment kept
    # the same parcel's block is merged as before (prior extra keys survive)
    prior2 = _li(parcel="R66666-006-006-006",
                 raw={"nc_county_csv_delinquent_tax": dict(_csv_block("R66666-006-006-006", 812.0), extra_key=1)})
    merged2 = fresh.merge(prior2)
    assert tb.keep_fresh_tax_blocks(fresh, merged2) == 0
    assert merged2.raw["nc_county_csv_delinquent_tax"]["extra_key"] == 1


def _write_board(docs_dir: Path, listings: list[Listing]) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "listings.json").write_text(json.dumps([li.model_dump(mode="json") for li in listings]))


def test_merge_prior_board_keeps_the_fresh_block(tmp_path):
    prior = _li(parcel="R77777-007-007-007", street="7 Sample Ln",
                raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"), **_derived(4100.01)})
    _write_board(tmp_path, [prior])
    fresh = _li(parcel="R77777-007-007-007", street="7 Sample Ln",
                raw={"nc_county_csv_delinquent_tax": _csv_block("R77777-007-007-007", 260.07)})
    out, stats = merge_prior_board([fresh], docs_dir=tmp_path, now=NOW)
    assert len(out) == 1 and stats["matched"] == 1
    assert out[0].raw["nc_county_csv_delinquent_tax"]["county_id"] == "R77777-007-007-007"
    assert stats["tax_block_fresh_kept"] == 1


def test_cleanup_after_merge_takes_old_attachments_off_carried_rows(tmp_path):
    # a prior-only row (not re-scraped) carrying another parcel's block: kept and aged by the merge,
    # then the cleanup removes the block and every tax field derived from it
    carried = _li(parcel="R88888-008-008-008", street="8 Sample Ln",
                  raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"), **_derived(4100.01)})
    owner = _li(parcel="R11111-001-001-001", street="1 Sample Ln",
                raw={"nc_county_csv_delinquent_tax": _csv_block("R11111-001-001-001"), **_derived(4100.01)})
    _write_board(tmp_path, [carried, owner])
    out, _ = merge_prior_board([], docs_dir=tmp_path, now=NOW)
    stats = tb.scrub_unbound_tax(out)
    by_pid = {li.parcel_id: li for li in out}
    assert stats["rows_scrubbed"] == 1
    assert "tax_owed" not in by_pid["R88888-008-008-008"].raw
    assert "tax_aging_surfaced" not in by_pid["R88888-008-008-008"].raw
    assert by_pid["R11111-001-001-001"].raw["tax_owed"]["balance"] == 4100.01

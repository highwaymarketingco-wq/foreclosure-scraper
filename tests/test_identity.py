"""identity.py (audit 2026-10-09, identity): duplicate properties, fused rows, owner conflicts.
Every row here is made up; parcel ids, names and addresses are fictional."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import identity as idn
from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.web_artifact import _to_dict

REPO = Path(__file__).resolve().parent.parent
FRESH = datetime(2026, 10, 8, 2)
PRIOR = datetime(2026, 9, 22, 15)
AGED = {"pulled_sale": {"consecutive_misses": 1, "presumed_withdrawn": True}}


def _li(source="counties_nc.test_roll", parcel=None, addr=None, *, county="Testcounty", state="NC",
        owner="DOE JANE", raw=None, aged=False, case=None, lt=ListingType.TAX_LIEN, url=None,
        when=None) -> Listing:
    r = dict(raw or {})
    if aged:
        r.update(AGED)
    t = when or (PRIOR if aged else FRESH)
    return Listing(source=source, source_url=url or f"https://example.test/{source}", listing_type=lt,
                   state=state, county=county, parcel_id=parcel, street_address=addr,
                   owner_name=owner, case_number=case, raw=r, first_seen=t, last_seen=t)


def _dups(rows) -> int:
    return idn.duplicate_groups([_to_dict(li) for li in rows])[1]["duplicates"]


# ------------------------------------------------------------------------------------ partition

def test_two_house_numbers_on_one_parcel_are_two_properties_not_duplicates():
    # an apartment complex's code cases at two buildings, each its own record
    rows = [_li("city_websites.test_code", "1000000001", "1020 FAKE CT", case="C-1", owner="ACME LLC"),
            _li("city_websites.test_code", "1000000001", "1022 FAKE CT", case="C-2", owner="ACME LLC")]
    assert _dups(rows) == 0
    out = list(rows)
    assert idn.collapse_twins(out)["rows_removed"] == 0 and len(out) == 2


def test_units_of_one_address_are_two_properties():
    rows = [_li("x.roll", "1000000002", "15 FAKE ST #101"), _li("x.roll", "1000000002", "15 FAKE ST #202")]
    assert _dups(rows) == 0


def test_aged_copy_and_its_rescrape_are_one_property_and_collapse_to_the_live_row():
    live = _li("x.roll", "1000000003", "40 FAKE RD", raw={"distress_stack": {"tier": "WARM"}})
    aged = _li("x.roll", "1000000003", "40 FAKE RD", aged=True,
               raw={"skip_trace": {"owner_name": "SOMEONE ELSE"}})
    rows = [aged, live]
    assert _dups(rows) == 1
    stats = idn.collapse_twins(rows)
    assert stats["rows_removed"] == 1 and len(rows) == 1
    kept = rows[0]
    assert not kept.raw.get("pulled_sale")                 # the live row is the base
    assert "skip_trace" not in kept.raw                    # the copy gives only COPY_ALLOWLIST
    assert kept.raw["twins_collapsed"] == 1
    assert _dups(rows) == 0


def test_an_aged_copy_at_the_owners_mailing_address_is_the_same_property():
    # before the source fix the roll printed the owner's mailing address as the situs
    mail = {"owner_mailing": {"mailing": "325 FAKE CREEK RD TESTTOWN NC 28000", "situs": "416 FAKE WAY",
                              "source": "test_gis"}}
    live = _li("x.elderly", "1000000004", "416 FAKE WAY", raw=mail)
    aged = _li("x.elderly", "1000000004", "325 FAKE CREEK RD", aged=True,
               raw={"owner_mailing": {"mailing": "325 FAKE CREEK RD TESTTOWN NC 28000"}})
    rows = [aged, live]
    assert _dups(rows) == 1
    idn.collapse_twins(rows)
    assert len(rows) == 1 and rows[0].street_address == "416 FAKE WAY"


def test_an_owner_occupied_house_is_not_a_mailing_address():
    # the county roll says the owner lives at the situs: both addresses are real properties
    occ = {"owner_mailing": {"mailing": "152 FAKE RD TESTTOWN NC", "situs": "152 FAKE RD",
                             "parcel_id": "1000000005", "source": "county_gis"}}
    rows = [_li("x.wildfire", "1000000005", "152 FAKE RD", raw=occ, aged=True),
            _li("liensnc", "1000000005", "297 OTHER DR", case="2600001")]
    assert _dups(rows) == 0


def test_a_live_rows_address_always_counts_even_when_it_is_a_mailing_address():
    mail = {"owner_mailing": {"mailing": "171 FAKE ISLE DR TESTTOWN NC"}}
    rows = [_li("liensnc", "1000000006", "171 FAKE ISLE DR", raw=mail, case="2600002"),
            _li("x.wildfire", "1000000006", "161 FAKE ISLE DR", raw=mail)]
    assert _dups(rows) == 0


def test_an_aged_copy_of_the_same_record_at_a_new_county_address_is_the_same_property():
    blk = {"PIN": "3500000001", "PARCELID": "22500", "NAME1": "DOE JANE"}
    rows = [_li("counties_nc.lincoln_vacant", "3500000001", "4018 FAKE TRL", aged=True,
                raw={"lincoln_vacant": dict(blk)}),
            _li("counties_nc.lincoln_vacant", "3500000001", "736 FAKE WOODS DR", raw={"lincoln_vacant": dict(blk)})]
    assert _dups(rows) == 1


def test_two_owners_of_one_source_at_one_address_are_units_not_one_property():
    # two short-term-rental permits of two owners in one building with no unit numbers
    rows = [_li("city_websites.test_str", None, "615 FAKE AVE", owner="SMITH ALICE", case="18-1"),
            _li("city_websites.test_str", None, "615 FAKE AVE", owner="JONES BOB", case="18-2")]
    assert _dups(rows) == 0


def test_two_ids_of_one_source_roll_at_one_address_are_two_properties():
    rows = [_li("counties_nc.test_tax", "358 102", "8135 FAKE RD", owner="ALPHA INC"),
            _li("counties_nc.test_tax", "358 024", "8135 FAKE RD", owner="ALPHA INC")]
    assert _dups(rows) == 0


def test_cross_source_rows_at_one_address_are_one_property():
    rows = [_li("counties_generic.state_contamination.test_ust", None, "5208 E FAKE HWY 56", owner="CORNER GROCERY"),
            _li("counties_generic.test_hazard", None, "5208 EAST FAKE HIGHWAY 56", owner="CORNER GROCERY")]
    assert _dups(rows) == 1
    out = list(rows)
    idn.collapse_twins(out)
    assert len(out) == 1
    # the absorbed live record stays readable on the row
    assert out[0].raw["merged_records"][0]["source"] in {r.source for r in rows}


def test_street_names_and_intersections_name_no_property():
    for addr in ("6th Avenue", "I-85 & FAKE RD", "0 FAKE DR", "99999 FAKE LN"):
        assert idn.situs_tag({"street_address": addr}) == ""
    assert idn.situs_tag({"street_address": "100 E MAIN ST"}) != idn.situs_tag({"street_address": "100 S MAIN ST"})
    assert idn.situs_tag({"street_address": "635 1/2 FAKE AVE"}) != idn.situs_tag({"street_address": "635 FAKE AVE"})
    assert idn.situs_tag({"street_address": "1 FAKE ST, STE 102"}) != idn.situs_tag({"street_address": "1 FAKE ST, STE 103"})
    assert idn.situs_tag({"street_address": "40 FAKE ROAD"}) == idn.situs_tag({"street_address": "40 FAKE RD"})


def test_short_account_aged_copy_and_resolved_rescrape_collapse():
    # the source's short account was nulled by validation; the name resolver gave both the PIN
    nulled = {"parcel_id_nulled": {"value": "57152", "reason": "too_short"},
              "resolved_from_name": {"queried": True, "confidence": "exact", "matched_owner": "ACRES INC"}}
    rows = [_li("counties_nc.nc_county_pdf_delinquent_tax", "372100000001", None, owner="ACRES INC",
                aged=True, raw=dict(nulled)),
            _li("counties_nc.nc_county_pdf_delinquent_tax", "372100000001", None, owner="ACRES INC",
                raw=dict(nulled))]
    assert _dups(rows) == 1
    idn.collapse_twins(rows)
    assert len(rows) == 1 and not rows[0].raw.get("pulled_sale")


def test_collapse_is_idempotent_and_never_drops_a_property():
    rows = [_li("x.roll", "1000000007", "1 FAKE ST", aged=True), _li("x.roll", "1000000007", "1 FAKE ST"),
            _li("x.roll", "1000000007", "3 FAKE ST"), _li("x.other", "1000000008", "9 FAKE ST")]
    idn.collapse_twins(rows)
    assert sorted(li.street_address for li in rows) == ["1 FAKE ST", "3 FAKE ST", "9 FAKE ST"]
    again = idn.collapse_twins(rows)
    assert again["rows_removed"] == 0 and len(rows) == 3


# ----------------------------------------------------------------------------------- fused rows

def _bill(pin, house="19", street="FAKE", typ="ST", owner_last="RIVER", owner_first="ANN"):
    return {"layer": "test_unpaid_bills", "bill": "0000000001-2025", "pin": pin, "house_num": house,
            "street_name": street, "street_type": typ, "owner1_last_name": owner_last,
            "owner1_first_name": owner_first}


def test_fused_row_is_rekeyed_to_its_own_record():
    row = _li("counties_generic.arcgis_distress.test_unpaid_bills", "0600-00-0073-00000", "86 MAIL RD",
              owner="STONE PAUL", raw={"arcgis_distress": _bill("0600-00-4200-00000")})
    row.latitude, row.longitude = 35.5, -82.5
    assert idn.fused_record(row)
    rec = idn.unfuse(row)
    assert rec["from_parcel"] == "0600-00-0073-00000" and rec["to_parcel"] == "0600-00-4200-00000"
    assert row.parcel_id == "0600-00-4200-00000"
    assert row.street_address == "19 FAKE ST" and row.latitude is None and rec["point_cleared"]
    assert row.owner_name.startswith("RIVER") and rec["from_owner"] == "STONE PAUL"
    assert row.raw["unfused"] == rec
    assert idn.fused_record(row) is None and idn.unfuse(row) is None     # idempotent


def test_not_fused_parent_pins_candidates_short_ids_and_other_layers():
    # a lien filing's PIN is the master tract
    assert idn.fused_record(_li("counties_generic.liensnc", "1000000009", "1 FAKE ST",
                                raw={"liensnc": {"pin": "1000000099"}})) is None
    # an address lookup's candidate list names candidates, not the row
    assert idn.fused_record(_li("x.parcel_from_address", "1000000010", "1 FAKE ST",
                                raw={"parcel_from_address": {"cache_ids": ["1000000011", "1000000012"]}})) is None
    # a short county account is too weak to say the record is another property
    assert idn.fused_record(_li("counties_nc.test_upset", "1000000013", "1 FAKE ST",
                                raw={"test_upset": {"parcel": "32276"}})) is None
    # another layer merged into the row is not the row's own record (block_binding's to judge)
    other = _li("counties_generic.arcgis_distress.test_flood", "4000-00-95-5012", "156 FAKE RD",
                raw={"arcgis_distress": {"layer": "test_owned", "PIN": "5000-00-02-0747"}})
    assert idn.fused_record(other) is None


def test_unfuse_rows_counts_and_keeps_every_row():
    rows = [_li("counties_generic.arcgis_distress.test_unpaid_bills", "0600-00-0073-00000", "86 MAIL RD",
                raw={"arcgis_distress": _bill("0600-00-4200-00000")}), _li("x.roll", "1000000014", "2 FAKE ST")]
    stats = idn.unfuse_rows(rows)
    assert stats["unfused"] == 1 and len(rows) == 2


# ------------------------------------------------------------------------------ owner conflicts

def test_unbound_roll_owner_loses_to_the_row_and_is_stamped():
    row = _li(owner="HARTON ERIC", parcel="1700000001", raw={"gis": {"owner": "NEIGHBOR BRYAN", "mailing": "443 OAK"}})
    assert idn.resolve_owner(row) == "row"
    assert row.owner_name == "HARTON ERIC"
    assert row.raw["owner_conflict"] == {"decision": "row", "reason": "unbound_record", "block": "gis",
                                         "loser": "NEIGHBOR BRYAN"}


def test_bound_roll_record_replaces_an_unrefreshed_owner():
    row = _li(owner="OLD OWNER", parcel="3564-64-0183",
              raw={"gis_attrs_full": {"parno": "3564-64-0183", "ownname": "NEW OWNER LLC"}})
    assert idn.resolve_owner(row) == "roll"
    assert row.owner_name == "NEW OWNER LLC" and row.raw["owner_conflict"]["loser"] == "OLD OWNER"
    assert idn.owner_verdict(row) is None          # agrees with the roll now: idempotent


def test_bound_record_against_a_refreshed_owner_is_undecided():
    row = _li(owner="BRADY TRUST", parcel="1600000002",
              raw={"owner_name_as_of": "2026-10-06",
                   "lrcpwa": {"reid": "1600000002", "owner": "LOGAN CALVIN"}})
    assert idn.resolve_owner(row) == "undecided"
    assert row.owner_name == "BRADY TRUST" and row.raw["owner_conflict"]["loser"] == "LOGAN CALVIN"


def test_historical_taxpayer_and_foreign_records_do_not_replace_the_owner():
    row = _li(owner="CURRENT BUYER", parcel="6-62-00-007.01", state="SC",
              raw={"qpaybill_roll": {"identification_no": "6-62-00-007.01", "owner": "PRIOR TAXPAYER",
                                     "years_unpaid": ["2017"]}})
    assert idn.resolve_owner(row) == "row" and row.owner_name == "CURRENT BUYER"
    foreign = _li(owner="ROW OWNER", parcel="1300752",
                  raw={"lrcpwa": {"reid": "1646560", "owner": "NEXT DOOR"}})
    assert idn.owner_verdict(foreign) is None


def test_no_conflict_when_any_roll_owner_agrees():
    row = _li(owner="SMITH JOHN", parcel="1700000003",
              raw={"gis": {"owner": "SMITH JOHN A"}, "gis_attrs_full": {"parno": "1700000003", "ownname": "OTHER"}})
    assert idn.owner_verdict(row) is None and idn.resolve_owner(row) is None


# --------------------------------------------------------------------- the audit check and pass

def _checks():
    spec = importlib.util.spec_from_file_location("identity_checks", REPO / "scripts" / "audit_checks" / "identity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _board():
    return [
        _li("x.roll", "1000000020", "1 FAKE ST", aged=True), _li("x.roll", "1000000020", "1 FAKE ST"),
        _li("city_websites.test_code", "1000000021", "1020 FAKE CT", case="C-1", owner="ACME LLC"),
        _li("city_websites.test_code", "1000000021", "1022 FAKE CT", case="C-2", owner="ACME LLC"),
        _li("counties_generic.arcgis_distress.test_unpaid_bills", "0600-00-0073-00000", "86 MAIL RD",
            raw={"arcgis_distress": _bill("0600-00-4200-00000")}),
        _li(owner="HARTON ERIC", parcel="1700000001", addr="5 FAKE ST",
            raw={"gis": {"owner": "NEIGHBOR BRYAN"}}),
    ]


def _run(mod, rows):
    checks = mod.make_checks()
    for row in rows:
        for c in checks:
            c.feed(row)
    return {r["name"]: r for r in (c.finish() for c in checks)}


def test_invariants_catch_the_defects_and_pass_after_the_identity_pass():
    mod = _checks()
    rows = _board()
    before = _run(mod, [_to_dict(li) for li in rows])
    assert before["identity-no-duplicate-properties"]["violations"] == 1
    assert before["identity-multi-address-parcels"]["violations"] == 1
    assert before["identity-fused-own-record"]["violations"] == 1
    assert before["identity-owner-conflict-stamped"]["violations"] == 1
    stats = idn.run_identity_pass(rows)
    assert stats["unfuse"]["unfused"] == 1 and stats["twins"]["rows_removed"] == 1
    after = _run(mod, [_to_dict(li) for li in rows])
    for name in ("identity-no-duplicate-properties", "identity-fused-own-record",
                 "identity-owner-conflict-stamped"):
        assert after[name]["violations"] == 0 and after[name]["ok"], after[name]
    assert after["identity-multi-address-parcels"]["violations"] == 1   # reported, not merged


def test_board_selfcheck_counts_duplicates_by_property():
    spec = importlib.util.spec_from_file_location("board_selfcheck", REPO / "scripts" / "board_selfcheck.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    rows = [_to_dict(li) for li in _board()]
    entry = {e["name"]: e for e in sc.invariants(rows)}["no duplicate identifiable properties"]
    assert entry["count"] == 1 and entry["multi_address_keys"] == 1

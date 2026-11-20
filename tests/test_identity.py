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


def test_a_lien_sweep_stamp_from_the_losing_identity_is_dropped_on_a_live_merge():
    """2026-10-17 gap-sweep wave 7, top80-lien-sweep-name-fit: two LIVE rows of the same property
    under different owner names (a tax-roll record and a court/defendant-identified record) merge
    via dedupe.merge_rows -- the base's scalar owner_name wins, but raw is deep-merged, so a
    rod_lien_sweep stamp the OTHER identity (MILLARD) correctly earned for ITSELF ends up on a
    row whose final owner_name is the base's (GARVIN) instead. The stamp's own instruments ('f'/
    'g') still carry MILLARD's name, not GARVIN's, so it must not survive the merge."""
    base = _li("x.roll", "1000000010", "50 FAKE AVE", owner="GARVIN MAURICE",
               raw={"tax_owed": {"amount": 500}, "distress_stack": {"tier": "WARM"}})
    other = _li("x.court", "1000000010", "50 FAKE AVE", owner="MILLARD MICHAEL",
                raw={"rod_lien_sweep": {"status": "found", "checked_at": "2026-10-16",
                                        "instruments": [{"f": "MILLARD, MICHAEL", "g": "SOME BANK",
                                                        "fit": "exact"}]}})
    rows = [base, other]
    assert _dups(rows) == 1
    stats = idn.collapse_twins(rows)
    assert stats["rows_removed"] == 1 and len(rows) == 1
    kept = rows[0]
    assert kept.owner_name == "GARVIN MAURICE"
    assert "rod_lien_sweep" not in kept.raw
    assert stats["lien_sweep_dropped_on_merge"] == 1


def test_a_lien_sweep_stamp_that_still_fits_the_merged_owner_survives():
    """Same merge shape as above, but the stamp's instrument DOES name the base's own owner (the
    sweep found the SAME person's record either side happened to be filed under) -- it must not
    be dropped just because a merge happened."""
    base = _li("x.roll", "1000000011", "60 FAKE AVE", owner="GARVIN MAURICE",
               raw={"tax_owed": {"amount": 500}, "distress_stack": {"tier": "WARM"}})
    other = _li("x.court", "1000000011", "60 FAKE AVE", owner="MILLARD MICHAEL",
                raw={"rod_lien_sweep": {"status": "found", "checked_at": "2026-10-16",
                                        "instruments": [{"f": "GARVIN, MAURICE", "g": "SOME BANK",
                                                        "fit": "exact"}]}})
    rows = [base, other]
    stats = idn.collapse_twins(rows)
    assert len(rows) == 1
    kept = rows[0]
    assert kept.owner_name == "GARVIN MAURICE"
    assert kept.raw["rod_lien_sweep"]["status"] == "found"
    assert stats.get("lien_sweep_dropped_on_merge", 0) == 0


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


def test_unfuse_clears_the_superseded_parcels_gis_fill_screen():
    """2026-10-18 top80-fill-screen-honest unfuse/repoint gap: gis_fill.py runs early in main.py's
    pipeline and keys its 'screened'/deed/legal verdict to li.parcel_id at the time it ran; identity's
    unfuse() runs late and re-keys parcel_id to the record's own (to_parcel). Left alone, the row
    would carry the SUPERSEDED (from_parcel)'s gis_fill/county_deed_ref/county_legal under the new
    identity, and gis_fill.needs() would skip re-screening it as already done."""
    stale_fill = {"checked_at": "2026-10-16T00:00:00+00:00", "source": "test_layer", "found": True,
                  "deed": "found", "legal": "found", "value": "skip", "acres": "skip"}
    row = _li("counties_generic.arcgis_distress.test_unpaid_bills", "0600-00-0073-00000", "86 MAIL RD",
              owner="STONE PAUL",
              raw={"arcgis_distress": _bill("0600-00-4200-00000"), "gis_fill": stale_fill,
                   "county_deed_ref": {"source": "test_layer", "parno": "0600-00-0073-00000",
                                       "book": "100", "page": "1"},
                   "county_legal": {"source": "test_layer", "parno": "0600-00-0073-00000",
                                    "text": "LOT 1 THE WRONG PARCEL'S PLAT"}})
    rec = idn.unfuse(row)
    assert rec["to_parcel"] == "0600-00-4200-00000"
    assert "gis_fill" not in row.raw and "county_deed_ref" not in row.raw and "county_legal" not in row.raw
    assert sorted(rec["superseded_fill_cleared"]) == ["county_deed_ref", "county_legal", "gis_fill"]


def test_unfuse_leaves_gis_fill_alone_when_the_row_was_never_fused():
    row = _li("x.roll", "1000000099", "2 FAKE ST", raw={"gis_fill": {"checked_at": "2026-10-16T00:00:00+00:00",
                                                                     "found": False}})
    assert idn.fused_record(row) is None
    assert idn.unfuse(row) is None
    assert row.raw["gis_fill"]["found"] is False


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


# ---------------------------------------------------------------------------
# 2026-11-19 verification follow-up: PARTY-ROLE CONFUSION. A third verification sample (18
# live-checked rows where li.owner_name and skip_trace.owner_name disagreed) found 3/18 where
# NEITHER was the real owner -- a lienholder, government body, builder-of-record, or (one real
# example) a literal job title ("Procurement Manager") read off a liensnc filing's free-text
# owner field. suspicious_owner_name() is the narrow, fail-safe net for the shapes that sample
# actually showed; it is a DIFFERENT defect from owner_verdict()/resolve_owner() above.
# ---------------------------------------------------------------------------

def test_suspicious_owner_name_flags_a_government_entity():
    v = idn.suspicious_owner_name("CLEVELAND COUNTY")
    assert v == {"reason": "government", "name": "CLEVELAND COUNTY"}
    assert idn.suspicious_owner_name("CITY OF ROCK HILL")["reason"] == "government"
    assert idn.suspicious_owner_name("SPARTANBURG COUNTY HOUSING AUTHORITY")["reason"] == "government"


def test_suspicious_owner_name_flags_the_literal_job_title_sample():
    # the real 2026-11-19 verification example: a liensnc filing's owner_text parsed as a title
    assert idn.suspicious_owner_name("Procurement Manager")["reason"] == "job_title"
    assert idn.suspicious_owner_name("Tax Collector")["reason"] == "job_title"


def test_suspicious_owner_name_does_not_flag_an_ordinary_person():
    assert idn.suspicious_owner_name("SMITH JOHN") is None
    assert idn.suspicious_owner_name("Smith, John A") is None
    assert idn.suspicious_owner_name(None) is None
    assert idn.suspicious_owner_name("") is None


def test_suspicious_owner_name_flags_an_entity_sourced_from_a_lien_filings_own_parse():
    # liensnc_handoff.py's parse_owner() reads a filing's free-text owner_text with no
    # identity check -- an entity-suffixed hit FROM THAT SOURCE is suspect.
    v = idn.suspicious_owner_name("ACME HOLDINGS LLC", source="liensnc_filing")
    assert v == {"reason": "entity_from_lien_filing", "name": "ACME HOLDINGS LLC"}
    assert idn.suspicious_owner_name("DOE JANE TRUST", source="liensnc")["reason"] == \
        "entity_from_lien_filing"


def test_suspicious_owner_name_does_not_flag_an_entity_sourced_from_the_county_roll():
    # the SAME entity-suffixed name is a perfectly ordinary owner when it came from an actual
    # county tax-roll block instead of a lien filing's unvalidated free-text parse.
    assert idn.suspicious_owner_name("ACME HOLDINGS LLC", source="county_gis") is None
    assert idn.suspicious_owner_name("ACME HOLDINGS LLC") is None       # no source at all


def test_suspicious_owner_name_does_not_flag_a_person_sourced_from_a_lien_filing():
    # the lien-filing-source rule is scoped to ENTITY-shaped names, not every name that source
    # ever touches -- an ordinary person's name from liensnc must not be flagged.
    assert idn.suspicious_owner_name("SMITH JOHN", source="liensnc_filing") is None


def test_suspicious_owner_name_flags_a_decedent_estate_or_heir_group():
    # 2026-11-20 find: classify_entity_type() already buckets these as 'estate', but
    # suspicious_owner_name() never checked that bucket, so outreach.py's _first_name()
    # positionally misread the leading phrase as a name ("ESTATE OF HERSHEL MOORE" -> "Of").
    v = idn.suspicious_owner_name("ESTATE OF HERSHEL MOORE")
    assert v == {"reason": "estate", "name": "ESTATE OF HERSHEL MOORE"}
    assert idn.suspicious_owner_name("The Estate Of William J. Mcbride")["reason"] == "estate"
    assert idn.suspicious_owner_name(
        "Any Heirs-At-Law, Or Devisees Of Rhonda L. Lewis, Deceased,")["reason"] == "estate"
    assert idn.suspicious_owner_name("SMITH JOHN HEIRS")["reason"] == "estate"
    # unconditional, unlike entity_from_lien_filing -- a county-roll source does not save it,
    # because the defect here is "no living person at a knowable position", not provenance.
    assert idn.suspicious_owner_name("ESTATE OF HERSHEL MOORE", source="county_gis")["reason"] \
        == "estate"


def test_suspicious_owner_name_does_not_flag_an_llc_whose_business_name_says_real_estate():
    # live board find: classify_entity_type() checks its ESTATE/HEIRS markers BEFORE is_entity(),
    # so an LLC/Inc-suffixed "...Real Estate..." business name also reads back 'estate' -- but
    # it is an unambiguous, well-identified entity, not a decedent's estate. Flagging it here
    # made the real board row WORSE (it fell through to an unrelated garbage li.defendant value
    # instead of using this perfectly good LLC name), so the entity-suffixed case must stay
    # unflagged regardless of source.
    assert idn.suspicious_owner_name("RAY AND SALLIE EDWARDS REAL ESTATE LLC") is None
    assert idn.suspicious_owner_name("BAKER AND BAKER REAL ESTATE DEVELOPERS LLC") is None
    assert idn.suspicious_owner_name("The Conservancy Real Estate Group, LLC") is None
    assert idn.suspicious_owner_name("RODGER C JARRELL REAL ESTATE & MORTGAGES INC") is None


def test_suspicious_owner_name_does_not_flag_a_life_estate_or_an_ordinary_trust():
    # "LIFE ESTATE" is a living person's interest, not a decedent's estate (classify_entity_type's
    # own exception); a bare TRUST is handled by the existing entity_from_lien_filing rule only,
    # never unconditionally like 'estate' -- a family trust from the county roll is an ordinary
    # current owner, not a party-role defect.
    assert idn.suspicious_owner_name("SMITH JOHN LIFE ESTATE") is None
    assert idn.suspicious_owner_name("SMITH FAMILY TRUST") is None
    assert idn.suspicious_owner_name("SMITH FAMILY TRUST", source="county_gis") is None


def test_suspicious_owner_name_flags_a_handle_like_bare_lowercase_token():
    # 2026-11-20 find: li.defendant sometimes carries a squashed contractor handle or email
    # local-part instead of a court party name -- a shape no real producer here writes a name
    # in (a county roll is all-caps, a court filing is Title Case).
    v = idn.suspicious_owner_name("chcenturycom")
    assert v == {"reason": "handle_like", "name": "chcenturycom"}
    assert idn.suspicious_owner_name("reesebuiltnc")["reason"] == "handle_like"
    assert idn.suspicious_owner_name("victorybuildersllc")["reason"] == "handle_like"
    # source-independent, same as 'government'/'estate' -- this is about shape, not provenance
    assert idn.suspicious_owner_name("izzis", source="county_gis")["reason"] == "handle_like"


def test_suspicious_owner_name_does_not_flag_an_ordinary_lowercase_or_short_name():
    # a real, ordinary name is never flagged just for being short or lower-case on its own --
    # the rule is anchored on the WHOLE string being one run-together 5+ letter lowercase word.
    assert idn.suspicious_owner_name("Smith, John A") is None     # mixed case, multi-word
    assert idn.suspicious_owner_name("izzi") is None              # under the 5-letter floor
    assert idn.suspicious_owner_name("smith john") is None        # has a space


def test_owner_identity_uncertain_reads_the_rows_own_owner_mailing_source():
    flagged = _li(owner="ACME HOLDINGS LLC",
                  raw={"owner_mailing": {"owner": "ACME HOLDINGS LLC", "source": "liensnc_filing"}})
    assert idn.owner_identity_uncertain(flagged)["reason"] == "entity_from_lien_filing"

    clean = _li(owner="ACME HOLDINGS LLC",
               raw={"owner_mailing": {"owner": "ACME HOLDINGS LLC", "source": "county_gis"}})
    assert idn.owner_identity_uncertain(clean) is None

    no_mailing = _li(owner="SMITH JOHN")
    assert idn.owner_identity_uncertain(no_mailing) is None


# ---------------------------------------------------------------------------
# rod_chain_conveyance_owner(): the residual 22% gap f5eeab0d/f8aa709c scoped out by name (a
# builder/developer entity or old grantor stuck as li.owner_name after a real, recorded sale).
# Live-checked 2026-11-20 against the real board: raw['rod_chain']['conveyed_out_since'] is
# found by NAME, not by parcel, so it can be a namesake's deed or a different lot in the same
# bulk builder purchase -- these tests mirror the real shapes found, both the ones narrow enough
# to confirm and the ones that must stay unconfirmed.
# ---------------------------------------------------------------------------

def test_rod_chain_conveyance_owner_confirms_by_book_page_against_county_deed_ref():
    # the real McDowell NC example: the chain's OWN last_deed book/page does not match the
    # county's current parcel record, but a LATER conveyed_out_since deed's book/page does --
    # proof the county's own index already has this exact instrument as the parcel's own.
    row = _li(owner="CLARK JOSHUA KEITH", parcel="172000341984",
              raw={"rod_chain": {"status": "ok", "conveyed_out_since": [
                       {"recorded": "2025-03-11", "book": "1494", "page": "797",
                        "grantors": ["CLARK JOSHUA KEITH"], "grantees": ["BLUERIDGE PROCESSING CORP."]}]},
                   "county_deed_ref": {"book": "1494", "page": "797"}})
    v = idn.rod_chain_conveyance_owner(row)
    assert v == {"name": "BLUERIDGE PROCESSING CORP.", "tie": "book_page",
                 "recorded": "2025-03-11", "book": "1494", "page": "797"}


def test_rod_chain_conveyance_owner_confirms_by_the_rows_own_parcel_id_embedded_in_the_description():
    # the real Jones County NC example: no date and no county_deed_ref book/page match, but the
    # conveyed-out deed's OWN recorded description embeds this row's exact parcel id.
    row = _li(owner="JAG DEVELOPMENT COMPANY", parcel="546830142700",
              raw={"rod_chain": {"status": "ok", "conveyed_out_since": [
                       {"recorded": "2026-01-14", "book": "446", "page": "555",
                        "description": "Parcel: 5468-30-1427-00 LOT 17 POLLOCKSVILLE TOWNSHIP",
                        "grantors": ["JAG DEVELOPMENT COMPANY"],
                        "grantees": ["COLONY CUSTOM BUILDERS LLC"]}]},
                   "county_deed_ref": {"book": "312", "page": "659"}})  # the stale bulk-buy deed
    v = idn.rod_chain_conveyance_owner(row)
    assert v["name"] == "COLONY CUSTOM BUILDERS LLC"
    assert v["tie"] == "parcel_id"


def test_rod_chain_conveyance_owner_declines_a_namesakes_or_a_different_lots_deed():
    # the real Jackson County NC example (Byers Construction & Development LLC, 611 Osprey
    # Mountain Way): county_deed_ref matches the chain's LAST deed (this parcel IS theirs), but
    # the only conveyed_out_since deed is a bigger, differently-numbered tract (0.314 AC parcel
    # vs a 3.21 AC conveyance) with no parcel id embedded in its description -- neither tie
    # holds, so this must NOT be read as proof Byers sold THIS parcel.
    row = _li(owner="BYERS CONSTRUCTION & DEVELOPMENT LLC", parcel="7640464099",
              raw={"rod_chain": {"status": "ok", "conveyed_out_since": [
                       {"recorded": "2024-06-04", "book": "2378", "page": "1236",
                        "description": "WEBSTER 3.21 AC",
                        "grantors": ["BYERS CONSTRUCTION & DEVELOPMENT, LLC"],
                        "grantees": ["ELLIS, RANDALL S.", "ELLIS, TERRI S."]}]},
                   "county_deed_ref": {"book": "2335", "page": "638"}})
    assert idn.rod_chain_conveyance_owner(row) is None


def test_rod_chain_conveyance_owner_declines_a_bulk_builder_purchases_other_lot():
    # the real RiverWILD Homes LLC example: a builder bought dozens of lots in one deed and the
    # only retrieved conveyance is a DIFFERENT, unrelated lot in a different subdivision -- must
    # not be handed back as if it were this row's own buyer.
    row = _li(owner="RiverWILD Homes, LLC", parcel=None,
              raw={"rod_chain": {"status": "ok", "conveyed_out_since": [
                       {"recorded": "2024-03-07", "book": "6628", "page": "313",
                        "description": "Subdivision: MEADOW CREST Lot: 4 PB 98/22 PB 98/435",
                        "grantors": ["RIVERWILD HOMES, LLC"],
                        "grantees": ["COTTINGHAM GEORGE DAVIS IV", "COTTINGHAM JESSICA HOFF"]}]}})
    assert idn.rod_chain_conveyance_owner(row) is None


def test_rod_chain_conveyance_owner_declines_without_rod_chain_or_a_bad_status():
    assert idn.rod_chain_conveyance_owner(_li(owner="SMITH JOHN", parcel="1234567890")) is None
    walled = _li(owner="SMITH JOHN", parcel="1234567890",
                 raw={"rod_chain": {"status": "walled", "conveyed_out_since": [
                          {"book": "1", "page": "2", "grantees": ["DOE JANE"]}]},
                      "county_deed_ref": {"book": "1", "page": "2"}})
    assert idn.rod_chain_conveyance_owner(walled) is None


def test_rod_chain_conveyance_owner_ignores_a_short_parcel_id_as_a_coincidental_match():
    # a short parcel id could appear inside an unrelated description's digits by chance;
    # _CONVEYANCE_MIN_PARCEL_DIGITS guards against treating that as proof.
    row = _li(owner="SMITH JOHN", parcel="12",
              raw={"rod_chain": {"status": "ok", "conveyed_out_since": [
                       {"recorded": "2025-01-01", "book": "9", "page": "9",
                        "description": "LOT 12 SOME SUBDIVISION",
                        "grantors": ["SMITH JOHN"], "grantees": ["DOE JANE"]}]}})
    assert idn.rod_chain_conveyance_owner(row) is None

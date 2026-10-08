"""A raw block binds only to the row whose property, owner or case it describes (block_binding.py,
audit 2026-10-09). Every parcel, owner, phone and address here is made up."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import block_binding as bb
from foreclosure_scraper.board_persist import merge_prior_board
from foreclosure_scraper.enrichment_geocode import COUNTY_SEAT_CENTROIDS
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

NOW = datetime(2026, 10, 9)
SRC = "counties_generic.arcgis_distress.sample_unpaid_bills"


def _li(parcel="1357-24-6801", county="Sample", state="NC", street="11 Test Rd", owner="ALPHA ANN",
        raw=None, source=SRC, lat=None, lng=None, url="https://x.invalid/a"):
    return Listing(source=source, source_url=url, listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county, parcel_id=parcel,
                   street_address=street, owner_name=owner, latitude=lat, longitude=lng,
                   first_seen=NOW, last_seen=NOW, raw=raw or {})


def _roll(owner="ALPHA ANN"):
    return {"gis": {"owner": owner, "mailing": "PO BOX 1 SAMPLETOWN NC"}}


# ------------------------------------------------------------------ probe and per-row verdicts

def test_probe_reads_property_fields_and_skips_mailing_state():
    p = bb.probe("owner_mailing", {"owner": "BETA BOB", "mailing": "9 Far Rd", "state": "GA",
                                   "situs": "22 Test Rd", "parcel_id": "2468-13-5790"})
    assert p["ids"] == ["2468-13-5790"] and p["addrs"] == ["22 Test Rd"]
    assert p["state"] == []                       # the owner's mailing state is not the property's
    assert "BETA BOB" in p["owners"]
    lv = bb.probe("lincoln_vacant", {"PIN": "3141592653", "STATE": "SC", "NAME1": "GAMMA GUS"})
    assert lv["state"] == [] and lv["ids"] == ["3141592653"]


def test_foreign_county_block_is_unbound_but_own_source_is_kept():
    code = {"county": "Othercounty", "open_violations": 2, "source": "othercounty_code_archive",
            "violations": [{"case_id": "CE 2016-100"}]}
    li = _li(raw={"code_enforcement": code, **_roll()})
    assert bb.block_verdict(li, "code_enforcement", code)[0] == "foreign_county"
    # the row's own source record is never removed (the row's identity is what is wrong then)
    own = _li(source="counties_nc.othercounty_code_enforcement", raw={"code_enforcement": code})
    assert bb.block_verdict(own, "code_enforcement", code)[0] == "own_source"


def test_other_parcel_other_address_and_not_comparable_ids():
    om_other = {"owner": "ALPHA ANN", "mailing": "PO BOX 1", "parcel_id": "2468-13-5790",
                "situs": "22 Test Rd", "source": "county_tax_roll"}
    li = _li(raw={"owner_mailing": om_other, **_roll()})
    assert bb.block_verdict(li, "owner_mailing", om_other)[0] == "other_parcel"
    om_own = dict(om_other, parcel_id="1357-24-6801", situs="11 Test Rd")
    assert bb.block_verdict(_li(raw={"owner_mailing": om_own}), "owner_mailing", om_own)[0] == "bound"
    # a 7-digit county account against a 10-digit PIN: two numbering systems, the situs decides
    om_pin = dict(om_other, parcel_id="1234567890", situs="11 Test Rd")
    li7 = _li(parcel="1234567", raw={"owner_mailing": om_pin})
    assert bb.block_verdict(li7, "owner_mailing", om_pin)[0] == "bound"
    # no id on the row: a different situs is another property's record
    noid = _li(parcel=None, raw={"owner_mailing": dict(om_other, parcel_id=None)})
    assert bb.block_verdict(noid, "owner_mailing", noid.raw["owner_mailing"])[0] == "other_address"


def test_other_person_is_roll_aware():
    lien = {"owner": "DELTA MOVING LLC", "balance": 262.53, "source": "sc_dew_lien_registry"}
    li = _li(raw={"sc_state_tax_lien": lien, **_roll()})
    assert bb.row_owner_strength(li) == "roll"
    assert bb.block_verdict(li, "sc_state_tax_lien", lien)[0] == "other_person"
    # the lien registry's own row keeps its lien
    own = _li(source="counties_sc.sc_dew_lien_registry", owner="DELTA MOVING LLC",
              raw={"sc_state_tax_lien": lien})
    assert bb.block_verdict(own, "sc_state_tax_lien", lien)[0] not in bb.UNBOUND
    # the row's owner is stale (the roll names a newer owner): a block naming the roll's owner stays
    st = {"provider": "tax_records_only", "owner_name": "EPSILON EVE", "parcel_id": None}
    stale = _li(owner="ALPHA ANN", raw={"skip_trace": st, **_roll("EPSILON EVE")})
    assert bb.row_owner_strength(stale) == "contradicted"
    assert bb.block_verdict(stale, "skip_trace", st)[0] != "other_person"


# ------------------------------------------------------------------ the scrub

def test_scrub_removes_a_copied_mailing_where_the_owner_differs():
    copied = {"owner": "LAMBDA LEE", "mailing": "2 Copy Rd SAMPLETOWN NC", "situs": None,
              "source": "nc_onemap"}
    rows = [_li(parcel=f"{n}482-00-73{n}1", street=f"{n} Test Rd", owner=o,
                raw={"owner_mailing": dict(copied), **_roll(o)})
            for n, o in ((1, "ALPHA ANN"), (2, "BETA BOB"), (3, "LAMBDA LEE"))]
    stats = bb.scrub_unbound_blocks(rows)
    kept = [r.owner_name for r in rows if "owner_mailing" in r.raw]
    assert kept == ["LAMBDA LEE"]
    assert stats["rows_scrubbed"] == 2


def test_multi_parcel_deed_of_one_owner_stays_but_a_copied_deed_goes():
    deed = {"transfers": [{"date": "2015-05-28", "price": 50000.0, "book": "4321", "page": "0099",
                           "source": "gis.last_sale"}], "summary": {"chain_length": 1}}
    same = [_li(parcel=f"5150-00-73{n}2", street=f"{n} Lot Rd", owner="OMEGA LLC",
                raw={"deed_chain": copy.deepcopy(deed)}) for n in (1, 2, 3)]
    bb.scrub_unbound_blocks(same)
    assert all("deed_chain" in r.raw for r in same)
    mixed = [_li(parcel=f"6160-00-84{n}3", street=f"{n} Mix Rd", owner=o, raw={"deed_chain": copy.deepcopy(deed)})
             for n, o in ((1, "ALPHA ANN"), (2, "BETA BOB"), (3, "GAMMA GUS"))]
    stats = bb.scrub_unbound_blocks(mixed)
    assert not any("deed_chain" in r.raw for r in mixed)
    assert stats["by_reason"]["shared_copy"] == 3


def test_a_shared_mailing_address_alone_is_not_a_copy():
    # one property manager's office is the mailing address of many owners' parcels
    office = {"mailing": "5 Office Park Ste 210 SAMPLETOWN NC", "absentee": True,
              "source": "sample_tax_parcel_layer"}
    rows = [_li(parcel=f"7170-00-95{n}4", street=f"{n} Rent Rd", owner=o, raw={"owner_mailing": dict(office)})
            for n, o in ((1, "ALPHA ANN"), (2, "BETA BOB"), (3, "GAMMA GUS"))]
    bb.scrub_unbound_blocks(rows)
    assert all("owner_mailing" in r.raw for r in rows)


def test_fallback_point_blocks_go_from_rows_with_no_location_of_their_own():
    lat, lng = next(iter(COUNTY_SEAT_CENTROIDS.values()))
    bag = {"PIN": "9081726354", "OWNER": "CHURCH OF SAMPLE"}
    fp = {"footprint_sqft": 1200, "est_living_sqft": 1200, "source": "ms_footprints"}
    nowhere = _li(parcel=None, street=None, owner="ALPHA ANN", lat=lat, lng=lng,
                  raw={"gis_attrs_full": dict(bag), "footprint": dict(fp)})
    nowhere.living_sqft, nowhere.living_sqft_estimated = 1200, True
    somewhere = _li(parcel="9081726354", street=None, owner="CHURCH OF SAMPLE", lat=lat, lng=lng,
                    raw={"gis_attrs_full": dict(bag)})
    stats = bb.scrub_unbound_blocks([nowhere, somewhere])
    assert "gis_attrs_full" not in nowhere.raw and "footprint" not in nowhere.raw
    assert nowhere.living_sqft is None and nowhere.living_sqft_estimated is False
    assert "gis_attrs_full" in somewhere.raw
    assert stats["by_reason"]["fallback_point"] == 2


def test_removed_filing_takes_its_contacts_and_bulk_ocr_takes_its_phone():
    filing = {"entry_number": "1234567", "address": "31 Other Rd", "owner_text": "ZETA BUILDERS",
              "source": "liensnc"}
    li = _li(street="86 Test Rd", raw={
        "liensnc": filing, **_roll(),
        "owner_mailing": {"owner": "ZETA BUILDERS", "mailing": "1 Builder Way", "source": "liensnc_filing"},
        "owner_phone": {"phone": "(555) 010-0000", "source": "liensnc_filing"}})
    bb.scrub_unbound_blocks([li])
    assert not any(k in li.raw for k in ("liensnc", "owner_mailing", "owner_phone"))
    ocr = {"raw_text_preview": "1 LIST OF 900 PARCELS 961895417300000", "phones": ["5550100001"],
           "source_pdf": "https://x.invalid/list.pdf"}
    rows = [_li(parcel=f"8180-00-16{n}5", street=f"{n} List Rd", owner=o,
                raw={"ocr_extraction": dict(ocr),
                     "owner_phone": {"phone": "(555) 010-0001", "source": "ocr_legal_notice", "role": "agent"}})
            for n, o in ((1, "ALPHA ANN"), (2, "BETA BOB"))]
    bb.scrub_unbound_blocks(rows)
    assert not any(k in r.raw for r in rows for k in ("ocr_extraction", "owner_phone"))


def test_scrub_is_idempotent_and_tolerates_odd_rows():
    rows = [_li(raw={"owner_mailing": {"owner": "BETA BOB", "parcel_id": "2468-13-5790"}, **_roll()}),
            {"state": "NC", "county": "Sample", "raw": {"gis": "not a dict", "owner_mailing": None}},
            {"raw": None}]
    first = bb.scrub_unbound_blocks(rows)
    second = bb.scrub_unbound_blocks(rows)
    assert first["blocks_removed"] == 1 and second["blocks_removed"] == 0


# ------------------------------------------------------------------ merge precedence

def test_keep_fresh_blocks_lets_the_fresh_record_win():
    fresh = _li(raw={"qpb_like": {"balance": 10.0, "statuses": ["Paid"]},
                     "nc_ecourts": {"case_number": "26CV000111", "county": "Sample", "status": "Open"}})
    prior = _li(raw={"qpb_like": {"balance": 99.0, "statuses": ["Unpaid"], "detail": {"x": 1}},
                     "nc_ecourts": {"case_number": "26CV000111", "county": "Othercounty", "status": "Old"},
                     "vision": {"score": 3}, "first_seen_run": "2026-01-01"})
    merged = fresh.merge(prior)
    assert merged.raw["qpb_like"]["balance"] == 99.0            # Listing.merge(): the prior leaf won
    out = bb.keep_fresh_blocks(fresh, merged)
    assert merged.raw["qpb_like"] == {"balance": 10.0, "statuses": ["Paid"], "detail": {"x": 1}}
    assert merged.raw["nc_ecourts"] == fresh.raw["nc_ecourts"]  # another county's record: fresh whole
    assert merged.raw["vision"] == {"score": 3}                 # enrichment the fresh row lacks: carried
    assert merged.raw["first_seen_run"] == "2026-01-01"
    assert out == {"fresh_block_kept": 2, "fresh_block_whole": 1}


def _write_board(docs_dir: Path, listings: list[Listing]) -> None:
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "listings.json").write_text(json.dumps([li.model_dump(mode="json") for li in listings]))


def test_merge_prior_board_keeps_the_fresh_scraper_block(tmp_path):
    prior = _li(raw={"sample_roll": {"owner": "ALPHA ANN", "balance": 500.0, "status": "Unpaid"},
                     "vision": {"score": 2}})
    _write_board(tmp_path, [prior])
    fresh = _li(raw={"sample_roll": {"owner": "ALPHA ANN", "balance": 0.0, "status": "Paid"}})
    out, stats = merge_prior_board([fresh], docs_dir=tmp_path, now=NOW)
    assert len(out) == 1 and stats["matched"] == 1
    assert out[0].raw["sample_roll"]["status"] == "Paid" and out[0].raw["sample_roll"]["balance"] == 0.0
    assert out[0].raw["vision"] == {"score": 2}
    assert stats["fresh_block_kept"] == 1


# ------------------------------------------------------------------ source guards

def test_images_do_not_frame_a_fallback_point():
    from foreclosure_scraper.enrichment_images import _has_precise_point
    ok = _li(lat=35.123456, lng=-81.654321)
    assert _has_precise_point(ok)
    flagged = _li(lat=35.123456, lng=-81.654321, raw={"geo_imprecise": "centroid_snap"})
    assert not _has_precise_point(flagged)
    assert not _has_precise_point(ok, {(35.12346, -81.65432)})   # 8+ leads share this point


def test_gis_attrs_bag_of_another_parcel_does_not_bind():
    from foreclosure_scraper.enrichment_gis_attrs import _bag_binds
    li = _li(parcel="1357246801")
    assert _bag_binds(li, {"PIN": "1357246801", "OWNER": "ALPHA ANN"})
    assert not _bag_binds(li, {"PIN": "1357246899", "OWNER": "NEXT DOOR"})
    assert _bag_binds(_li(parcel=None), {"PIN": "1357246899"})      # nothing to compare


def test_ocr_skips_a_document_many_rows_share():
    from foreclosure_scraper.enrichment_ocr import enrich_ocr_extraction, shared_documents
    rows = [_li(parcel=f"4{n}82-00-7351", url="https://x.invalid/roster.pdf?t=1") for n in range(5)]
    assert shared_documents(rows) == {"https://x.invalid/roster.pdf"}   # cache buster dropped
    stats = enrich_ocr_extraction(rows)          # no download is attempted for a shared roster
    assert stats["shared_document_rows"] == 5 and stats["processed"] == 0
    assert not any("ocr_extraction" in r.raw or "owner_phone" in r.raw for r in rows)


def test_a_filers_contact_on_its_own_filing_row_goes_only_when_the_roll_names_another_owner():
    filing = {"entry_number": "7654321", "address": "11 Test Rd", "source": "liensnc"}
    om = {"owner": "ZETA BUILDERS", "mailing": "1 Builder Way", "situs": "11 Test Rd", "source": "liensnc_filing"}
    rolled = _li(source="counties_generic.liensnc", raw={"liensnc": filing, "owner_mailing": dict(om), **_roll()})
    assert bb.block_verdict(rolled, "liensnc", filing)[0] == "own_source"
    assert bb.block_verdict(rolled, "owner_mailing", rolled.raw["owner_mailing"])[0] == "other_person"
    bare = _li(source="counties_generic.liensnc", raw={"liensnc": filing, "owner_mailing": dict(om)})
    assert bb.block_verdict(bare, "owner_mailing", bare.raw["owner_mailing"])[0] == "own_source"


# ------------------------------------------------------------------ the audit invariants

def _checks():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "audit_checks" / "block_binding.py"
    spec = importlib.util.spec_from_file_location("audit_block_binding", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {c.name: c for c in mod.make_checks()}


def test_audit_checks_count_what_the_scrub_removes_and_pass_after_it():
    copied = {"owner": "LAMBDA LEE", "mailing": "2 Copy Rd SAMPLETOWN NC", "source": "nc_onemap"}
    code = {"county": "Othercounty", "violations": [{"case_id": "CE 2016-100"}], "source": "x_code"}
    rows = [_li(parcel=f"{n}482-00-73{n}1", street=f"{n} Test Rd", owner=o,
                raw={"owner_mailing": dict(copied), **_roll(o)})
            for n, o in ((1, "ALPHA ANN"), (2, "BETA BOB"), (3, "LAMBDA LEE"))]
    rows[0].raw["code_enforcement"] = code
    dicts = [li.model_dump(mode="json") for li in rows]
    checks = _checks()
    for d in dicts:
        for c in checks.values():
            c.feed(d)
    res = {n: c.finish() for n, c in checks.items()}
    assert set(res["block-binding-a-shared-copy"]) == {"name", "checked", "violations", "max_violations", "ok", "detail"}
    assert res["block-binding-a-shared-copy"]["violations"] == 2
    assert res["block-binding-b-foreign-county"]["violations"] == 1
    assert res["block-binding-d-other-person"]["violations"] == 2     # the copied owner is not theirs
    # after the scrub every check passes
    bb.scrub_unbound_blocks(dicts)
    checks = _checks()
    for d in dicts:
        for c in checks.values():
            c.feed(d)
    assert all(c.finish()["ok"] for c in checks.values())

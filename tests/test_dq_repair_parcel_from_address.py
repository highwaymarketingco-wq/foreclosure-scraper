"""repair_parcel_from_address: which parcels are eligible, what counts as a clear disagreement, when a replacement is made,
what it clears (only what provably came from the old parcel), the backup, and the corrupt-and-repair hold-out.
Offline: synthetic caches in a temp dir, no board, no network."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _dq_common as C  # noqa: E402
import repair_parcel_from_address as X  # noqa: E402
import resolve_parcel_from_address as R  # noqa: E402
from foreclosure_scraper import parcel_cache as pc  # noqa: E402
from foreclosure_scraper.models import Listing, ListingType  # noqa: E402

COLS = "id TEXT, owner TEXT, address TEXT, owner_mailing TEXT, market_value REAL, tax_value REAL, acreage REAL, " \
       "living_sqft REAL, land_use TEXT, sale_price REAL, sale_date TEXT"


# ------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture
def caches(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(pc, "_CONN", {})

    def make(county, parcels, state=None):
        """parcels: [(ids, owner, address, mailing, market_value[, extras dict])]."""
        con = sqlite3.connect(pc._db_path(county, state))
        con.execute(f"CREATE TABLE parcels({COLS})")
        for p in parcels:
            ids, owner, address, mailing, mv = p[:5]
            ex = p[5] if len(p) > 5 else {}
            for i in ids:
                con.execute("INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (i, owner, address, mailing, mv, ex.get("tax_value", 400000.0), ex.get("acreage", 0.3),
                             ex.get("sqft", 1800.0), ex.get("land_use"), ex.get("sale_price"), None))
        con.execute("CREATE INDEX idx_id ON parcels(id)")
        con.commit()
        con.close()
    return make


@pytest.fixture
def registered(monkeypatch):
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: [])


def _li(**kw):
    base = dict(source="national.liensnc", source_url="https://example.invalid/1", listing_type=ListingType.TAX_LIEN,
                state="NC", county="Wake", raw={})
    base.update(kw)
    return Listing(**base)


def _wake(caches):
    """4028 (the neighbour the lead wrongly carries), 4116 (the lead's real parcel), and filler for the board id length."""
    caches("Wake", [(("1000000001", "0000001"), "ORNDORFF PAUL E", "4028 BALSAM DR", "4028 BALSAM DR CARY NC 27511", 300000.0),
                    (("1000000002", "0000002"), "CHILDREN OF JULIE LLC", "4116 BALSAM DR", "PO BOX 9 CARY NC 27511", 640000.0,
                     {"tax_value": 610000.0, "acreage": 0.41, "sqft": 2900.0}),
                    (("1000000003",), "SMITH JOHN", "12 OAK HILL RD", "12 OAK HILL RD CARY NC 27511", 250000.0),
                    (("1000000004",), "BUILDER HOMES LLC", "7 ELM CT", "PO BOX 5 CARY NC 27511", 100000.0),
                    (("1000000005",), "BUILDER HOMES LLC", "9 ELM CT", "PO BOX 5 CARY NC 27511", 100000.0)])


def _neighbour_lead(**kw):
    """A liensnc lead at 4116 Balsam Drive that carries the parcel of 4028, with what the join copied from it."""
    raw = {"gis": {"mailing": "4028 BALSAM DR CARY NC 27511", "queried": True},
           "owner_mailing": {"owner": "Revolution Homes", "mailing": "1 FILING WAY RALEIGH NC 27601", "source": "liensnc_filing"}}
    base = dict(street_address="4116 Balsam Drive", city="Cary", owner_name="Revolution Homes", parcel_id="1000000001",
                market_value=300000.0, tax_value=400000.0, acreage=0.3, living_sqft=1800.0, raw=raw)
    base.update(kw)
    return _li(**base)


# ------------------------------------------------------------------------------------------ situs_verdict
@pytest.mark.parametrize("lead,cache,verdict", [
    ("4116 Balsam Drive", "4028 BALSAM DR", "disagrees"),                    # same street, other number
    ("200 Draymont Drive", "200 SPARTANBURG HWY LYMAN", "disagrees"),        # same number, another street
    ("1513 Rodanthe Ave", "100  RALEIGH ST", "disagrees"),
    ("12 Oak St", "12 OAK CT", "agrees"),                                    # a suffix alone is not a disagreement
    ("341 Allen St.", "341 ALLEN CT SPARTANBURG", "agrees"),
    ("141 Levi Dr", "000141 LEVI DR", "agrees"),                             # leading zeros
    ("9002 Palmetto Drive", "9002 316 PALMETTO DR", "agrees"),               # unit in front of the street: shares number and word
    ("133 Laverne Ave", "133 LAVERNE AVE, Unit A", "agrees"),
    ("15 McLeod St", "15 W MCLEOD ST", "agrees"),
    ("4116 Balsam Drive", "", "unknown"),                                    # no cache situs
    ("4116 Balsam Drive", "SPLIT FROM 116-00-01-048", "unknown"),            # legal text
    ("4116 Balsam Drive", "OFF SR 1151 EXT", "unknown"),
    ("4116 Balsam Drive", "0 BALSAM DR", "unknown"),                         # sentinel house number
    ("MEADOW RD", "4028 BALSAM DR", "unknown"),                              # the lead has no numbered street
    ("831/833 N Oak St", "4028 BALSAM DR", "unknown"),                       # a range
    ("4116 Balsam Drive", "4028 BALSAM DR;LOT 5 THE PINES", "unknown"),      # one part of the situs is not a street
    ("4116 Balsam Drive", "2215 E LYNCHES RIVER RD;4116 BALSAM DR", "agrees"),
    ("4116 Balsam Drive", "2215 E LYNCHES RIVER RD;4028 BALSAM DR", "disagrees"),
])
def test_situs_verdict(lead, cache, verdict):
    assert X.situs_verdict(lead, cache) == verdict


# ------------------------------------------------------------------------------------------ eligibility
def _status(raw=None, **kw):
    li = _neighbour_lead(**kw) if raw is None else _neighbour_lead(raw=raw, **kw)
    ld = R.lead_from_listing(0, li)
    return X.existing_status(ld, li.raw)[0]


def test_only_a_disagreeing_parcel_in_a_repairable_source_goes_on_to_resolution(caches):
    _wake(caches)
    assert _status() == "disagrees"
    assert _status(street_address="4028 Balsam Drive") == "agrees"
    assert _status(street_address="4028 Balsam Ct") == "agrees"                       # a suffix difference is not enough
    assert _status(parcel_id="9999999999") == "existing_id_not_in_cache"              # left as it is
    assert _status(street_address="MEADOW RD") == "situs_not_comparable"
    assert _status(street_address="") == "skip_no_address"
    assert _status(parcel_id="") == "skip_no_parcel"
    assert _status(county=None) == "skip_no_county"
    assert _status(county="Buncombe") == "no_cache"
    assert _status(state="SC") == "skip_county_not_in_state"
    assert _status(listing_type=ListingType.TAX_SALE_OVERAGE) == "skip_tax_sale_overage"


def test_a_sources_own_parcel_is_never_repaired_however_it_disagrees(caches):
    """A tax roll's parcel_id is what the bill is for: when its street differs, the street is the mailing address."""
    _wake(caches)
    assert _status(source="counties_nc.qpaybill_delinquent_roll") == "skip_parcel_is_the_sources_own"
    assert _status(source="counties_nc.buncombe_elderly") == "skip_parcel_is_the_sources_own"
    assert _status(source="counties_nc.nc_county_pdf_delinquent_tax") == "skip_source_street_is_not_situs"   # denied
    assert _status(source="counties_generic.nc_ust_incidents") == "disagrees"                                # a repairable one


def test_provenance_gates_leave_a_parcel_that_did_not_come_from_coordinates(caches):
    _wake(caches)
    assert _status(raw={"resolved_from_name": {"a": 1}}) == "skip_parcel_not_from_coordinates"
    assert _status(raw={"parcel_from_geo": {"source": "ptscloud_pts_to_pin"}}) == "skip_parcel_not_from_coordinates"
    assert _status(raw={"parcel_from_geo": {"source": "county_gis"}}) == "disagrees"
    assert _status(raw={"situs_address_source": "parcel_cache:exact"}) == "skip_street_came_from_a_parcel_layer"
    assert _status(raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}}) == "skip_parcel_from_the_address_resolver"


def test_a_parcel_the_address_resolver_wrote_is_not_hold_out_truth(caches):
    _wake(caches)
    base = {"source": "national.liensnc", "state": "NC", "county": "Wake", "parcel_id": "1000000002", "street_address": "4116 Balsam Dr"}
    assert len(R.collect_dicts([base]).holdout) == 1
    assert R.collect_dicts([dict(base, raw={"parcel_from_address": {"source": "parcel_cache_situs_address"}})]).holdout == []


def test_a_cache_row_with_no_situs_or_unparseable_situs_is_not_a_disagreement(caches):
    caches("Wake", [(("1000000001",), "OWNER", None, None, 1.0), (("1000000002",), "OWNER", "OFF SR 1151 EXT", None, 1.0)])
    assert _status() == "existing_situs_missing"
    assert _status(parcel_id="1000000002") == "situs_not_comparable"


# ------------------------------------------------------------------------------------------ replacement
def test_replacement_backup_provenance_and_clearing(caches, registered):
    _wake(caches)
    rows = [_neighbour_lead(), _li(street_address="12 Oak Hill Road", parcel_id="1000000003", owner_name="John Smith", raw={})]
    before = [r.model_dump(mode="json") for r in rows]
    dry = X.apply_rows(rows, dry_run=True)
    assert [r.model_dump(mode="json") for r in rows] == before and "_backup" not in dry
    assert dry["replaced"] == 1 and dry["agrees"] == 1 and dry["replaced: new owner agrees False"] == 1

    res = X.apply_rows(rows)
    assert len(rows) == 2 and res["replaced"] == 1
    li = rows[0]
    assert li.parcel_id in ("1000000002", "0000002")                                # a spelling of the 4116 parcel
    assert rows[1].parcel_id == "1000000003" and "parcel_from_address" not in rows[1].raw      # the agreeing lead is untouched
    blk = li.raw["parcel_from_address"]
    assert blk["replaced_parcel"] == "1000000001" and blk["replaced_situs"] == "4028 BALSAM DR"
    assert blk["matched_situs"] == "4116 BALSAM DR" and blk["owner_agrees"] is False and blk["replaced_owner_agrees"] is False
    assert blk["verified"] == "address_exact_unique_replaced_disagreeing_parcel"
    # what came from the old parcel is gone (so the next join refills it) ...
    assert li.market_value is None and li.tax_value is None and li.acreage is None and li.living_sqft is None
    assert "mailing" not in li.raw["gis"] and li.raw["gis"]["queried"] is True
    # ... and the lead's own filing is not
    assert li.owner_name == "Revolution Homes"
    assert li.raw["owner_mailing"] == {"owner": "Revolution Homes", "mailing": "1 FILING WAY RALEIGH NC 27601", "source": "liensnc_filing"}
    bk = res["_backup"]["0"]
    assert bk["old_parcel_id"] == "1000000001" and bk["new_parcel_id"] == li.parcel_id and bk["street"] == "4116 Balsam Drive"
    assert bk["old_situs"] == "4028 BALSAM DR" and bk["source_url"] == "https://example.invalid/1"
    kinds = {(c["kind"], c["key"]) for c in bk["cleared"]}
    assert ("top", "market_value") in kinds and ("gis", "mailing") in kinds
    assert set(res["_backup"]) == {"0"}


def test_the_replaced_lead_is_stable_a_second_run_finds_nothing_to_do(caches, registered):
    _wake(caches)
    rows = [_neighbour_lead()]
    X.apply_rows(rows)
    again = X.apply_rows(rows)
    assert "replaced" not in again and "_backup" not in again and again["agrees"] == 1


def test_values_that_are_not_the_old_parcels_are_never_cleared(caches, registered):
    _wake(caches)
    lead = _neighbour_lead(market_value=725000.0, tax_value=None, acreage=0.5, living_sqft=None)   # the lead's own values
    X.apply_rows([lead])
    assert lead.market_value == 725000.0 and lead.acreage == 0.5
    assert lead.parcel_id in ("1000000002", "0000002")


def test_parcel_layer_blocks_that_name_the_old_parcel_are_cleared_and_the_filing_is_not(caches, registered):
    _wake(caches)
    raw = {"owner_mailing": {"mailing": "4028 BALSAM DR CARY NC 27511", "absentee": False, "mail_state": "NC"},   # written by the join
           "gis": {"mailing": "4028 BALSAM DR CARY NC 27511", "owner": "ORNDORFF PAUL E", "market_value": 300000.0,
                   "last_sale": {"amount": 250000.0, "date": "2011-01-01"}},
           "gis_attrs_full": {"PIN": "1000000001", "OWNER": "ORNDORFF PAUL E"}, "zillow": {"zestimate": 1}}
    lead = _neighbour_lead(raw=raw)
    caches_row = sqlite3.connect(pc._db_path("Wake")).execute("UPDATE parcels SET sale_price=250000.0 WHERE id='1000000001'")
    caches_row.connection.commit()
    res = X.apply_rows([lead])
    assert res["replaced"] == 1
    assert "owner_mailing" not in lead.raw and "gis" not in lead.raw and "gis_attrs_full" not in lead.raw
    assert lead.raw["zillow"] == {"zestimate": 1}                                   # unrelated raw keys stay
    kinds = {(c["kind"], c["key"]) for c in res["_backup"]["0"]["cleared"]}
    assert {("owner_mailing", "owner_mailing"), ("gis", "owner"), ("gis", "market_value"), ("gis_last_sale", "last_sale"),
            ("gis_attrs_full", "gis_attrs_full")} <= kinds


def test_an_nc_onemap_bag_is_attributed_by_its_parcel_number_or_by_its_site_and_owner(caches, registered):
    _wake(caches)
    by_id = _neighbour_lead(raw={"gis_attrs_full": {"parno": "1000000001", "siteadd": "4028 BALSAM DR", "ownname": "ORNDORFF PAUL E", "parval": 1.0}})
    by_site = _neighbour_lead(raw={"gis_attrs_full": {"parno": "999", "siteadd": "4028 Balsam Dr", "ownname": "Orndorff Paul E"}})
    other = _neighbour_lead(raw={"gis_attrs_full": {"parno": "999", "siteadd": "77 ELSEWHERE ST", "ownname": "SOMEONE"}})
    X.apply_rows([by_id, by_site, other])
    assert "gis_attrs_full" not in by_id.raw and "gis_attrs_full" not in by_site.raw
    assert other.raw["gis_attrs_full"]["siteadd"] == "77 ELSEWHERE ST"


def test_a_block_from_a_parcel_layer_that_is_not_the_old_parcels_is_kept(caches, registered):
    _wake(caches)
    lead = _neighbour_lead(raw={"owner_mailing": {"mailing": "PO BOX 77 SOMEWHERE NC 28000", "source": "county_gis"},
                                "gis_attrs_full": {"PIN": "0999999999"}})
    X.apply_rows([lead])
    assert lead.raw["owner_mailing"]["mailing"] == "PO BOX 77 SOMEWHERE NC 28000" and lead.raw["gis_attrs_full"] == {"PIN": "0999999999"}


def test_owner_name_is_cleared_only_when_it_is_the_old_parcels_verbatim_owner(caches, registered):
    _wake(caches)
    a = _neighbour_lead(owner_name="ORNDORFF PAUL E", raw={})                # the join copied it from the old parcel
    b = _neighbour_lead(owner_name="Orndorff Paul E", raw={})                # the source's own spelling
    res = X.apply_rows([a, b])
    # a's owner is the old parcel's, copied: it is not evidence for the old parcel, so the guard does not hold it back
    assert res["replaced"] == 1 and res["left_owner_favours_existing"] == 1
    assert a.owner_name is None and a.parcel_id in ("1000000002", "0000002")
    assert a.raw["parcel_from_address"]["owner_agrees"] is None and a.raw["parcel_from_address"]["replaced_owner_agrees"] is None
    assert b.owner_name == "Orndorff Paul E" and b.parcel_id == "1000000001"      # b's own spelling agrees with the old owner: it stays


def test_owner_evidence():
    assert X.owner_evidence("Meritage Homes", "MERITAGE HOMES LLC", "SOMEONE ELSE") == (True, False)
    assert X.owner_evidence("MERITAGE HOMES LLC", "MERITAGE HOMES LLC", "SOMEONE ELSE") == (None, None)     # copied from the old parcel
    assert X.owner_evidence("", "A B", "C D") == (None, None)


# ------------------------------------------------------------------------------------------ what it will not replace
def test_not_replaced_when_the_address_does_not_resolve_uniquely(caches, registered):
    caches("Wake", [(("1000000001",), "ORNDORFF PAUL E", "4028 BALSAM DR", None, 1.0),
                    (("1000000002",), "A", "4116 BALSAM DR", None, 1.0), (("1000000009",), "B", "4116 BALSAM DR", None, 2.0),
                    (("1000000003",), "C", "55 PINE ST", None, 1.0)])
    amb = _neighbour_lead()
    none = _neighbour_lead(street_address="777 Nowhere Lane")
    res = X.apply_rows([amb, none], withdraw=False)                           # replacement only: nothing else is touched
    assert res["left_ambiguous"] == 1 and res["left_no_match"] == 1 and "replaced" not in res and "withdrawn" not in res
    assert amb.parcel_id == "1000000001" and none.parcel_id == "1000000001"
    assert amb.market_value == 300000.0                                       # and nothing was cleared


def test_a_unit_or_a_zip_conflict_or_a_placeholder_id_blocks_the_replacement(caches, registered):
    caches("Wake", [(("1000000001",), "ORNDORFF PAUL E", "4028 BALSAM DR", None, 1.0),
                    (("1000000002",), "A", "4116 BALSAM DR", "4116 BALSAM DR CARY NC 27511", 1.0),
                    (("1000000003",), "B", "30 MAPLE CT, 1 CITY NC", None, 1.0), (("1000000004",), "C", "30 MAPLE CT, 2 CITY NC", None, 1.0),
                    (("1000000007",), "E", "40 IVY ST", None, 1.0)])
    zip_lead = _neighbour_lead(zip_code="27502")
    unit_lead = _neighbour_lead(street_address="30 Maple Ct")
    res = X.apply_rows([zip_lead, unit_lead], withdraw=False)
    assert res["left_zip_conflict"] == 1 and res["left_unit_rejected"] == 1
    assert zip_lead.parcel_id == "1000000001" and unit_lead.parcel_id == "1000000001"


def test_the_owner_guard_keeps_a_parcel_whose_owner_matches_when_the_new_one_does_not(caches, registered):
    """The lead's owner is the OLD parcel's owner and not the new one's: a mistyped address, so the parcel stays. When both
    match (a builder with adjacent lots) the address decides."""
    caches("Wake", [(("1000000001",), "SMITH JOHN A", "7 ELM CT", None, 1.0), (("1000000002",), "JONES MARY", "9 ELM CT", None, 1.0),
                    (("1000000003",), "SMITH JOHN A", "11 ELM CT", None, 1.0)])
    typo = _neighbour_lead(street_address="9 Elm Court", owner_name="John Smith", parcel_id="1000000001")
    both = _neighbour_lead(street_address="11 Elm Court", owner_name="John Smith", parcel_id="1000000001")
    res = X.apply_rows([typo, both])
    assert res["left_owner_favours_existing"] == 1 and res["replaced"] == 1
    assert typo.parcel_id == "1000000001" and both.parcel_id == "1000000003"
    assert both.raw["parcel_from_address"]["replaced_owner_agrees"] is True and both.raw["parcel_from_address"]["owner_agrees"] is True


def test_agreeing_native_and_unreadable_parcels_are_never_touched(caches, registered):
    _wake(caches)
    rows = [_neighbour_lead(street_address="4028 Balsam Drive"),                                    # agrees
            _neighbour_lead(source="counties_nc.qpaybill_delinquent_roll"),                        # the source's own parcel
            _neighbour_lead(parcel_id="9999999999"),                                                # id not in the cache
            _neighbour_lead(street_address="4116 Balsam Ct", parcel_id="1000000002")]             # suffix only
    before = [(r.parcel_id, r.market_value, dict(r.raw)) for r in rows]
    res = X.apply_rows(rows)
    assert "replaced" not in res and [(r.parcel_id, r.market_value, dict(r.raw)) for r in rows] == before


# ------------------------------------------------------------------------------------------------ withdrawal
def _wake_without_4116(caches):
    """The cache does not have the lead's own street (new construction): the neighbour's parcel is all it can offer."""
    caches("Wake", [(("1000000001", "0000001"), "ORNDORFF PAUL E", "4028 BALSAM DR", "4028 BALSAM DR CARY NC 27511", 300000.0),
                    (("1000000003",), "SMITH JOHN", "12 OAK HILL RD", "12 OAK HILL RD CARY NC 27511", 250000.0)])


def test_a_neighbours_parcel_with_no_unique_replacement_is_withdrawn(caches, registered):
    _wake_without_4116(caches)
    lead = _neighbour_lead()
    other = _li(street_address="12 Oak Hill Road", parcel_id="1000000003", owner_name="John Smith", raw={})
    before_other = other.model_dump(mode="json")
    dry = X.apply_rows([lead], dry_run=True)
    assert dry["withdrawn"] == 1 and dry["withdrawn: no_match"] == 1 and lead.parcel_id == "1000000001" and lead.market_value == 300000.0

    res = X.apply_rows([lead, other])
    assert res["withdrawn"] == 1 and "replaced" not in res
    assert lead.parcel_id is None and lead.street_address == "4116 Balsam Drive"            # the street stays: it is what the resolver will use
    assert lead.market_value is None and lead.tax_value is None and lead.acreage is None and lead.living_sqft is None
    assert "mailing" not in lead.raw["gis"] and lead.raw["owner_mailing"]["source"] == "liensnc_filing"      # the filing's own mailing stays
    assert lead.owner_name == "Revolution Homes"
    blk = lead.raw["parcel_from_address"]
    assert blk["withdrawn_parcel"] == "1000000001" and blk["reason"] == "street_disagrees_no_unique_match"
    assert blk["match_status"] == "left_no_match" and blk["withdrawn_situs"] == "4028 BALSAM DR" and "owner_agrees" not in blk
    bk = res["_backup"]["0"]
    assert bk["action"] == "withdrawn" and bk["old_parcel_id"] == "1000000001" and bk["new_parcel_id"] is None
    assert bk["withdraw_reason"] == "street_disagrees_no_unique_match"
    assert ("top", "market_value") in {(c["kind"], c["key"]) for c in bk["cleared"]}
    assert set(res["_backup"]) == {"0"} and other.model_dump(mode="json") == before_other      # the agreeing lead is untouched


@pytest.mark.parametrize("why", ["ambiguous", "unit_rejected", "zip_conflict", "no_specific_id"])
def test_every_resolution_that_yields_no_replacement_withdraws(caches, registered, why):
    """The old parcel is at another address whatever the reason the street has no unique parcel."""
    rows = {"ambiguous": [(("1000000002",), "A", "4116 BALSAM DR", None, 1.0), (("1000000009",), "B", "4116 BALSAM DR", None, 2.0)],
            "unit_rejected": [(("1000000003",), "A", "4116 BALSAM DR, 1 CITY NC", None, 1.0), (("1000000004",), "B", "4116 BALSAM DR, 2 CITY NC", None, 1.0)],
            "zip_conflict": [(("1000000002",), "A", "4116 BALSAM DR", "4116 BALSAM DR CARY NC 27511", 1.0)],
            "no_specific_id": [(("37051",), "A", "4116 BALSAM DR", None, 1.0)] + [(("37051",), f"O{i}", f"{i + 500} JUNK ST", None, 1.0) for i in range(4)]}[why]
    caches("Wake", [(("1000000001",), "ORNDORFF PAUL E", "4028 BALSAM DR", None, 300000.0)] + rows)
    lead = _neighbour_lead(zip_code="27502" if why == "zip_conflict" else None)
    res = X.apply_rows([lead])
    assert res["withdrawn"] == 1 and res[f"withdrawn: {why}"] == 1 and lead.parcel_id is None
    assert lead.raw["parcel_from_address"]["match_status"] == f"left_{why}"


def test_the_guards_that_protect_a_parcel_also_protect_it_from_withdrawal(caches, registered):
    _wake_without_4116(caches)
    rows = [_neighbour_lead(owner_name="Paul Orndorff"),                                # the lead's owner agrees with the old parcel: a typo, keep
            _neighbour_lead(parcel_id="9999999999"),                                    # id not in the cache
            _neighbour_lead(street_address="MEADOW RD"),                                # no numbered street
            _neighbour_lead(street_address="4028 Balsam Drive"),                        # agrees
            _neighbour_lead(street_address="4028 Balsam Ct"),                           # a suffix only
            _neighbour_lead(source="counties_nc.qpaybill_delinquent_roll"),             # the source's own parcel
            _neighbour_lead(source="counties_nc.nc_county_pdf_delinquent_tax"),         # street is not a situs
            _neighbour_lead(raw={"resolved_from_name": {"a": 1}}),                      # not from coordinates
            _neighbour_lead(listing_type=ListingType.TAX_SALE_OVERAGE)]
    before = [(r.parcel_id, r.market_value, r.tax_value, r.acreage, dict(r.raw)) for r in rows]
    res = X.apply_rows(rows)
    assert "withdrawn" not in res and "replaced" not in res and "_backup" not in res
    assert res["left_owner_agrees_with_existing"] == 1
    assert [(r.parcel_id, r.market_value, r.tax_value, r.acreage, dict(r.raw)) for r in rows] == before


def test_a_lead_with_a_copied_owner_is_withdrawn_not_protected(caches, registered):
    """owner_name equal to the old parcel's cache string was copied by the join: it is no evidence for the old parcel."""
    _wake_without_4116(caches)
    lead = _neighbour_lead(owner_name="ORNDORFF PAUL E", raw={})
    res = X.apply_rows([lead])
    assert res["withdrawn"] == 1 and lead.parcel_id is None and lead.owner_name is None


def test_the_join_cannot_refill_a_withdrawn_lead_and_a_rerun_is_stable(caches, registered):
    import join_parcel_cache_to_board as J
    _wake_without_4116(caches)
    lead = _neighbour_lead()
    X.apply_rows([lead])
    snapshot = lead.model_dump(mode="json")
    for _ in range(2):
        counts = J.apply_rows([lead])
        assert counts["no parcel_id"] == 1 and "cache HIT" not in counts
    assert lead.model_dump(mode="json") == snapshot and lead.market_value is None and "mailing" not in (lead.raw.get("gis") or {})
    again = X.apply_rows([lead])
    assert not again                                                                # a lead with no parcel_id is not looked at again


def test_the_resolver_resolves_a_withdrawn_lead_once_the_cache_gains_its_street(caches, registered):
    _wake_without_4116(caches)
    lead = _neighbour_lead()
    X.apply_rows([lead])
    assert lead.parcel_id is None
    still = R.apply_rows([lead])
    assert "resolved" not in still and lead.parcel_id is None                        # the cache still has no 4116
    con = sqlite3.connect(pc._db_path("Wake"))
    for i in ("1000000002", "0000002"):
        con.execute("INSERT INTO parcels VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (i, "CHILDREN OF JULIE LLC", "4116 BALSAM DR", "PO BOX 9 CARY NC 27511", 640000.0, 610000.0, 0.41, 2900.0, None, None, None))
    con.commit()
    con.close()
    res = R.apply_rows([lead])
    assert res["resolved"] == 1 and lead.parcel_id in ("1000000002", "0000002")
    blk = lead.raw["parcel_from_address"]
    assert blk["matched_situs"] == "4116 BALSAM DR" and blk["withdrawn_parcel"] == "1000000001"      # the withdrawal stays on the record
    assert blk["withdrawn_reason"] == "street_disagrees_no_unique_match" and blk["withdrawn_situs"] == "4028 BALSAM DR"
    assert X.apply_rows([lead])["skip_parcel_from_the_address_resolver"] == 1                          # and the repair does not touch it


def test_replaced_and_withdrawn_leads_share_one_run_and_one_backup(caches, registered):
    _wake(caches)
    lead_a = _neighbour_lead()                                                     # 4116 exists: replaced
    lead_b = _neighbour_lead(street_address="777 Nowhere Lane")                    # not in the cache: withdrawn
    res = X.apply_rows([lead_a, lead_b])
    assert res["replaced"] == 1 and res["withdrawn"] == 1
    assert res["_backup"]["0"]["action"] == "replaced" and res["_backup"]["1"]["action"] == "withdrawn"
    assert lead_a.parcel_id and lead_b.parcel_id is None


def test_the_driver_step_withdraws_and_the_next_steps_do_not_refill(caches, registered, monkeypatch, tmp_path):
    import apply_board_fixes as D
    monkeypatch.setattr(C, "BACKUPS", tmp_path / "backups")
    _wake_without_4116(caches)
    rows = [_neighbour_lead()]
    out = D.run_steps(rows, {"parcel_repair", "address", "join"}, dry_run=False, log=lambda m: None)
    assert out["parcel_repair"]["withdrawn"] == 1 and rows[0].parcel_id is None and rows[0].market_value is None
    assert "filled market value" not in out["join"] and "cache HIT" not in out["join"]
    files = list((tmp_path / "backups").glob("repair_parcel_from_address_replaced_*.json"))
    assert len(files) == 1 and '"action": "withdrawn"' in files[0].read_text()


def test_a_real_run_refuses_before_touching_a_row_when_the_raw_key_is_unregistered(caches, monkeypatch):
    _wake(caches)
    monkeypatch.setattr(C, "missing_raw_keep", lambda keys: list(keys))
    rows = [_neighbour_lead()]
    with pytest.raises(RuntimeError, match="parcel_from_address"):
        X.apply_rows(rows)
    assert rows[0].parcel_id == "1000000001"
    assert X.apply_rows(rows, dry_run=True)["replaced"] == 1


def test_the_module_follows_the_apply_rows_contract():
    assert callable(X.apply_rows) and X.repair_rows is X.apply_rows and X.REQUIRED_RAW_KEYS == ["parcel_from_address"]
    assert X.BACKUP_NAME


# ------------------------------------------------------------------------------------ policy is checked against the scrapers
def test_every_repairable_source_has_a_scraper_that_never_sets_a_parcel_id():
    """REPAIRABLE_SOURCES is the safety rule: a source whose scraper sets parcel_id owns that parcel, and a differing
    street on it is a mailing address. If a scraper starts setting parcel_id this fails and the source must come off the list."""
    scrapers = ROOT / "src" / "foreclosure_scraper" / "scrapers"
    for tail in sorted(X.REPAIRABLE_SOURCES):
        rel = X.SCRAPER_FILE.get(tail)
        files = [scrapers / rel] if rel else list(scrapers.rglob(f"{tail}.py"))
        assert files and files[0].exists(), f"no scraper file found for {tail}"
        text = files[0].read_text(encoding="utf-8")
        assert not re.search(r"parcel_id|parcel_number|parcelid", text, re.I), f"{files[0].name} sets a parcel id: {tail} is not repairable"


def test_the_deny_list_and_the_repairable_list_do_not_overlap():
    assert not (X.REPAIRABLE_SOURCES & R.DENY_SOURCES)


# ---------------------------------------------------------------------------------------- corrupt-and-repair hold-out
def test_corrupt_and_repair_restores_the_true_parcel_and_reports_precision(caches):
    caches("Wake", [(("2000000001",), "A A", "10 ASH LN", None, 1.0), (("2000000002",), "B B", "12 ASH LN", None, 1.0),
                    (("2000000003",), "C C", "14 ASH LN", None, 1.0), (("2000000004",), "D D", "22 BIRCH DR", None, 1.0),
                    (("2000000005",), "E E", "30 CEDAR CT", None, 1.0), (("2000000006",), "F F", "30 CEDAR CT", None, 2.0)])   # 30 CEDAR CT is ambiguous
    rows = [{"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": f"200000000{i}", "street_address": s,
             "city": "Cary", "owner_name": ""}
            for i, s in ((1, "10 Ash Lane"), (2, "12 Ash Lane"), (3, "14 Ash Lane"), (4, "22 Birch Drive"), (5, "30 Cedar Court"))]
    hold = X.evaluate_repair_holdout(R.collect_dicts(rows))
    nb, ot = hold["neighbour"], hold["other_street"]
    assert dict(hold["agree"]) == {"checked": 5, "agrees": 5}                       # every hold-out lead's own parcel agrees: none is touched
    assert nb["corrupted"] == 3 and nb["restored"] == 3 and nb["WRONG"] == 0        # the three Ash Lane leads, each given a neighbour's parcel
    assert ot["corrupted"] == 5 and ot["restored"] == 4 and ot["WRONG"] == 0
    assert ot["withdrawn"] == 1 and ot["left_ambiguous"] == 0                        # 30 Cedar Ct has two parcels: nothing is guessed, the decoy is withdrawn


def test_the_hold_out_counts_a_wrong_replacement_as_wrong(caches):
    """The lead's own parcel sits at 50 CEDAR LN ANGIER; another parcel at 50 CEDAR LN has no town. A lead in Erwin rejects the first
    and matches the second uniquely: a replacement, and not the true parcel."""
    caches("Wake", [(("3000000001",), "A", "50 CEDAR LN ANGIER", None, 1.0), (("3000000002",), "B", "50 CEDAR LN", None, 1.0),
                    (("3000000003",), "C", "8 OTHER RD", None, 1.0)])
    rows = [{"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "3000000001", "street_address": "50 Cedar Ln",
             "city": "Erwin"},
            {"source": "counties_nc.tax_roll", "state": "NC", "county": "Wake", "parcel_id": "3000000003", "street_address": "8 Other Rd",
             "city": ""}]
    hold = X.evaluate_repair_holdout(R.collect_dicts(rows))
    ot = hold["other_street"]
    assert ot["corrupted"] == 2 and ot["restored"] == 1 and ot["WRONG"] == 1
    assert hold["wrong_samples"][0][3] == "50 Cedar Ln" and hold["wrong_samples"][0][4] == "50 CEDAR LN"


# ---------------------------------------------------------------------------------------- the single-load driver
def test_the_driver_runs_the_step_and_writes_the_backup(caches, registered, monkeypatch, tmp_path):
    import apply_board_fixes as D
    monkeypatch.setattr(C, "BACKUPS", tmp_path / "backups")
    _wake(caches)
    rows = [_neighbour_lead(), _li(street_address="12 Oak Hill Road", parcel_id="1000000003", owner_name="John Smith", raw={})]
    out = D.run_steps(rows, {"parcel_repair"}, dry_run=False, log=lambda m: None)
    assert out["parcel_repair"]["replaced"] == 1 and "_backup" not in out["parcel_repair"]
    files = list((tmp_path / "backups").glob("repair_parcel_from_address_replaced_*.json"))
    assert len(files) == 1 and "1000000001" in files[0].read_text()
    assert rows[0].parcel_id != "1000000001" and rows[1].parcel_id == "1000000003"
    dry = D.run_steps([_neighbour_lead()], {"parcel_repair"}, dry_run=True, log=lambda m: None)
    assert dry["parcel_repair"]["replaced"] == 1


# --------------------------------------------------------------------------------------------------- the dry run
def test_the_dry_run_reads_a_board_extract_and_reports_without_writing(caches, tmp_path, capsys):
    import json
    _wake(caches)
    rows = [{"source": "national.liensnc", "state": "NC", "county": "Wake", "parcel_id": "1000000001", "street_address": "4116 Balsam Drive",
             "city": "Cary", "owner_name": "Revolution Homes", "market_value": 300000.0, "raw": {"gis": {"mailing": "4028 BALSAM DR CARY NC 27511"}}},
            {"source": "national.liensnc", "state": "NC", "county": "Wake", "parcel_id": "1000000003", "street_address": "12 Oak Hill Road",
             "owner_name": "John Smith"},
            {"source": "counties_nc.qpaybill_delinquent_roll", "state": "NC", "county": "Wake", "parcel_id": "1000000001",
             "street_address": "4116 Balsam Drive"},
            {"source": "national.liensnc", "state": "NC", "county": "Wake", "parcel_id": "1000000001", "street_address": "777 Nowhere Lane",
             "latitude": 35.7, "longitude": -78.6, "market_value": 300000.0, "raw": {}}]
    f = tmp_path / "rows.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows))
    before = f.read_text()
    assert X._dry_run(str(f), holdout=False) == 0
    out = capsys.readouterr().out
    assert "REPLACED 1" in out and "WITHDRAWN 1" in out and "liensnc 1" in out and "GUARD CHECK" in out and "(must be 0)" in out
    assert "withdrawn leads that carry coordinates: 1" in out and "by why there is no replacement: no_match 1" in out
    assert "gis.mailing 1" in out and "market_value" in out
    assert f.read_text() == before


def test_geo_enricher_never_reattaches_a_withdrawn_parcel():
    # doc section 12.4: coordinates attached the neighbour's parcel in the first place
    from foreclosure_scraper import enrichment_parcel_from_geo as G
    from foreclosure_scraper.models import Listing, ListingType
    li = Listing(source="counties_generic.liensnc", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC",
                 county="Wake", raw={"parcel_from_address": {"withdrawn_parcel": "0123456789",
                                                             "reason": "street_disagrees_no_unique_match"}})
    assert G._withdrawn(li) is True
    li2 = Listing(source="x", source_url="u", listing_type=ListingType.TAX_LIEN, state="NC", county="Wake", raw={})
    assert G._withdrawn(li2) is False

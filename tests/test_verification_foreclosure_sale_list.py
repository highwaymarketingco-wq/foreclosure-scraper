"""foreclosure_sale_list: a firm's sale re-read on the firm's own current list (made-up lists)."""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from foreclosure_scraper.verification import registry
from foreclosure_scraper.verification.verifiers import foreclosure_sale_list as F

TODAY = date(2026, 10, 9)


def _li(case, addr, county="Burke", sale="2026-11-04"):
    return {"case_number": case, "street_address": addr, "county": county, "sale_date": sale}


LIST = [_li("26SP000216-110", "8551 Example Drive"), _li("26SP000300-110", "12 Sample St"),
        _li("26SP000301-110", "14 Sample St"), _li("26SP000302-110", "16 Sample St"),
        _li("26SP000303-110", "18 Sample St", sale="2026-12-01")]
TAX = [_li("26CV000871-220", "336 Example Cir", "Cleveland", "2026-10-06"),
       _li("26CV000871-220", "319 Example Cir", "Cleveland", "2026-10-06"),
       _li("26CV000001-220", "1 A St", "Cleveland"), _li("26CV000002-220", "2 A St", "Cleveland"),
       _li("26CV000003-220", "3 A St", "Cleveland")]
# No case_number of its own (the firm's catalog carries parcel ids, not court cases), matching
# the real terry_howe_flc.py Listing shape: some rows have a numbered street_address, some are
# "Off <street>" locator parcels with none -- the same split this file's own applies() already
# handles for every other firm via address-only matching.
FLC = [_li(None, "817 Saxon Ave", "Spartanburg", None), _li(None, "123 Elm St", "Chester", None),
       _li(None, "Off Dodd St", "Spartanburg", None), _li(None, "2 Elm St", "Chester", None),
       _li(None, "4 Elm St", "Chester", None), _li(None, "6 Elm St", "Chester", None)]


@pytest.fixture(autouse=True)
def _lists(monkeypatch):
    F.reset_caches()

    async def nc():
        return LIST

    async def kania():
        return TAX

    async def flc():
        return FLC

    async def broken():
        raise TimeoutError("no answer")

    monkeypatch.setattr(F, "PROVIDERS",
                         {"hutchens_NC": nc, "kania": kania, "shapiro": broken, "terry_howe_flc": flc})
    yield
    F.reset_caches()


def _row(**kw):
    r = {"state": "NC", "county": "Burke", "source": "law_firms.hutchens",
         "listing_type": "foreclosure_sale", "case_number": "26SP000216-110",
         "street_address": "8551 Example Drive", "sale_date": "2026-11-04T00:00:00"}
    r.update(kw)
    return r


def _run(row):
    return asyncio.run(F.verify(row, None, today=TODAY))


def test_registered():
    v = {x.name: x for x in registry.discover()}["foreclosure_sale_list"]
    assert v.identity == "case" and v.ttl_days == 7 and "list_unreadable" in v.transient_reasons
    assert F.applies(_row())
    assert not F.applies(_row(source="law_firms.brock_scott"))     # WAF: not read
    assert not F.applies(_row(state="GA"))


def test_listed_is_confirmed():
    r = _run(_row())
    assert r.verdict == "confirmed" and r.evidence["reason"] == "listed"


def test_postponed_shows_its_new_date():
    r = _run(_row(case_number="26SP000303-110", street_address="18 Sample St"))
    assert r.verdict == "confirmed" and r.evidence["reason"] == "listed_new_date"
    assert r.evidence["sale_date_now"] == "2026-12-01"


def test_removed_before_the_sale_is_stale_and_governs_the_sale():
    r = _run(_row(case_number="26SP000999-110"))
    assert r.verdict == "stale" and r.evidence["reason"] == "removed_before_sale"
    assert F.governs_for(r.to_dict()) == ("foreclosure_sale", "upset_bid", "court_sale")


def test_not_listed_after_the_sale_date_is_unconfirmed():
    r = _run(_row(case_number="26SP000999-110", sale_date="2026-10-01"))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "sale_held_or_cancelled"


def test_case_for_another_house_is_refuted():
    r = _run(_row(street_address="77 Other Rd"))
    assert r.verdict == "refuted" and r.evidence["reason"] == "case_address_conflict"


def test_a_multi_parcel_tax_case_matches_the_rows_own_parcel():
    row = _row(source="law_firms.kania", county="Cleveland", case_number="26CV000871-220",
               street_address="319 Example Cir", sale_date="2026-10-06")
    r = _run(row)
    assert r.verdict == "confirmed" and r.evidence["address_relation"] == "match"
    assert F.governs_for(r.to_dict()) == ("tax_sale", "upset_bid")


def test_nc_upset_bids_rows_from_the_kania_page_use_its_list():
    row = _row(source="national.nc_upset_bids", county="Cleveland", case_number="26CV000001-220",
               street_address="1 A St", source_url="https://kanialawfirm.com/tax-foreclosures/x/")
    assert F.applies(row)
    assert _run(row).verdict == "confirmed"


def test_unreadable_list_is_transient():
    r = _run(_row(source="law_firms.shapiro_ingle_powerbi"))
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "list_unreadable"
    v = {x.name: x for x in registry.discover()}["foreclosure_sale_list"]
    assert v.is_transient(r.to_dict())


def test_row_with_no_case_matches_by_address_in_the_county():
    r = _run(_row(case_number=None, street_address="12 Sample Street"))
    assert r.verdict == "confirmed" and r.evidence["match_basis"] == "address"


def test_terry_howe_flc_row_with_numbered_address_matches_by_address():
    row = _row(source="counties_sc.terry_howe_flc", county="Spartanburg", case_number=None,
               street_address="817 Saxon Ave", sale_date=None)
    assert F.applies(row)
    r = _run(row)
    assert r.verdict == "confirmed" and r.evidence["match_basis"] == "address"
    assert F.governs_for(r.to_dict()) == ("tax_sale", "upset_bid")


def test_terry_howe_flc_locator_only_row_is_out_of_scope():
    # "Off Dodd St" carries no house number and no case number -- the same scope limit every
    # other firm's address-only matching already has, not a new gap this entry introduces.
    row = _row(source="counties_sc.terry_howe_flc", county="Spartanburg", case_number=None,
               street_address="Off Dodd St", sale_date=None)
    assert not F.applies(row)


def test_terry_howe_flc_ignores_a_foreign_case_number_and_matches_by_address():
    # Live-confirmed 2026-11-20: some real Spartanburg terry_howe_flc board rows carry a
    # "trulia-<id>_ZPID" case_number from cross-source enrichment, never the firm's own (an FLC
    # auction has no court case). Matching that against the firm's case-less catalog must not
    # block the address fallback that would otherwise find the row.
    row = _row(source="counties_sc.terry_howe_flc", county="Spartanburg",
               case_number="trulia-11805212_ZPID", street_address="817 Saxon Ave", sale_date=None)
    assert F.applies(row)
    r = _run(row)
    assert r.verdict == "confirmed" and r.evidence["match_basis"] == "address"


def test_terry_howe_flc_row_for_a_different_county_is_unconfirmed():
    row = _row(source="counties_sc.terry_howe_flc", county="Laurens", case_number=None,
               street_address="817 Saxon Ave", sale_date=None)
    r = _run(row)
    assert r.verdict == "unconfirmed" and r.evidence["reason"] == "not_listed_no_date"

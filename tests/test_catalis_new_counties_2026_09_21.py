"""Catalis delinquent roll: Chester, Hampton, Fairfield and Aiken (added 2026-09-21).

The research note said the four new counties share Pickens' schema and need no parser
change. One live request each showed otherwise, and these tests pin what was measured:

  Chester / Hampton   RecordType "Delinquent" + RealPropertyType True (Pickens' shape).
                      Chester adds AssessorData with the CURRENT owner.
  Fairfield           RecordType "Real", RealPropertyType null, delinquency = DelqSw True,
                      situs in Description.
  Aiken               RealPropertyType null everywhere. Real delinquents are RecordType
                      "Delinquent" WITH a parcel and DelqSw True; business personal property
                      is "Delinquent" with no parcel and a BillingID starting "M"/"P".

Every record below is hand-built from those shapes. Names and addresses are invented; no
personal data from the live responses is stored in the repository.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

import foreclosure_scraper.scrapers.counties_sc.sc_catalis_delinquent_roll as m
from foreclosure_scraper.models import ListingType, PropertyKind


def _rec(**kw):
    base = {
        "ParcelNumber": "061-02-00-021-000", "BillingID": "061-02-00-021-000", "Year": 2025,
        "RecordType": "Delinquent", "RealPropertyType": True, "DelqSw": None,
        "isDelinquent": False, "DueDate": "2026-01-15T00:00:00",
        "TaxSaleRedemptionDate": None, "Description": "LOT # 21 = 2.00 AC AD#26-00121",
        "District": "02", "Acres": 2.0, "LastUpdated": "2026-09-02T04:03:09.0286938Z",
        "OwnerName1": "DOE JOHN Q", "OwnerName2": None,
        "OwnerAddress": {"Line1": "c/o JANE ROE", "Line2": "PO BOX 10", "Line3": None,
                         "City": "MATTHEWS                NC", "State": None, "Zip": "28106"},
        "SitusAddress": {"Line1": "LOT # 21 = 2.00 AC AD#26-00121", "Line2": None,
                         "Line3": None, "City": None, "State": None, "Zip": None},
        "Values": {"Appraised": 44000, "Assessed": 2640, "BaseTax": 1261.39, "Penalty": 175.51,
                   "Interest": 0.0, "Costs": 65.0, "OriginalAmountDue": 1170.09,
                   "AmountDue": 1410.6, "BuildingAppraisal_4Pct": 0, "BuildingAppraisal_6Pct": 0,
                   "LandAppraisal_4Pct": 0, "LandAppraisal_6Pct": 44000},
        "CountyValues": {"GrossTax": 1261.39, "Mills": 477.8, "HomesteadExemption": 0.0,
                         "LegalResidenceExemption": 0.0},
        "AssessorData": {"OwnerName": "ROE JANE TTE", "StreetNumber911": "", "StreetName911": ""},
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------- config

def test_county_codes_and_hosts_are_pinned():
    """The exact data ids and hosts verified live on 2026-09-21."""
    want = {
        "Chester": ("61020303-8d26-4a16-b995-6deb1def7d97", "https://chestercountysctax.com"),
        "Hampton": ("38077f99-bf3d-48df-8d9a-467eb4de0d64", "https://hamptoncountytax.org"),
        "Fairfield": ("89835e71-6978-4dc5-a0a8-17306a76b81f", "https://fairfieldsctax.com"),
        "Aiken": ("27a11acb-7de9-43e7-a078-f98cfb4fc397", "https://aikencountysctax.com"),
        "Pickens": ("c9ab58ea-c187-4c02-ad9d-b18dd6167431", "https://pickenscountysctax.us"),
    }
    for county, pair in want.items():
        assert m.CATALIS_COUNTIES[county] == pair


def test_sweep_order_puts_the_3mb_county_last():
    assert m.SWEEP_ORDER[-1] == "Aiken"
    assert set(m.SWEEP_ORDER) == set(m.CATALIS_COUNTIES)


def test_aiken_is_depth_and_budget_limited_and_the_rest_are_not():
    assert m.rule_for("Aiken").max_depth == 2
    assert m.rule_for("Aiken").budget == 400
    assert m.rule_for("Chester").max_depth is None


# --------------------------------------------------------------------------- filters

def test_chester_and_hampton_use_the_pickens_shape():
    for county in ("Chester", "Hampton", "Pickens"):
        assert m.is_delinquent_real_property(_rec(), m.rule_for(county)) is True
    # A vehicle-shaped row, and the mobile-home row Chester marks RealPropertyType False.
    assert m.is_delinquent_real_property(_rec(RecordType="Vehicle", RealPropertyType=False),
                                         m.rule_for("Chester")) is False
    assert m.is_delinquent_real_property(_rec(RealPropertyType=False),
                                         m.rule_for("Chester")) is False


def test_fairfield_says_real_and_marks_delinquency_with_delqsw():
    ok = _rec(RecordType="Real", RealPropertyType=None, DelqSw=True, isDelinquent=True,
              ParcelNumber="187-00-00-012-000", BillingID="1870000012000")
    rule = m.rule_for("Fairfield")
    assert m.is_delinquent_real_property(ok, rule) is True
    # Not delinquent (current-year bill): DelqSw False or null.
    assert m.is_delinquent_real_property({**ok, "DelqSw": False}, rule) is False
    assert m.is_delinquent_real_property({**ok, "DelqSw": None}, rule) is False
    # The same row under Pickens' rule is invisible, which is why a config-only add failed.
    assert m.is_delinquent_real_property(ok, m.RULE_DEFAULT) is False
    # A vehicle is never real property.
    assert m.is_delinquent_real_property({**ok, "RecordType": "Vehicle"}, rule) is False


def test_aiken_real_delinquents_need_a_parcel_and_delqsw():
    rule = m.rule_for("Aiken")
    real = _rec(RecordType="Delinquent", RealPropertyType=None, DelqSw=True,
                ParcelNumber="049-19-01-002", BillingID="049-19-01-002")
    assert m.is_delinquent_real_property(real, rule) is True
    # Business personal property: RecordType "Delinquent", DelqSw True, but no parcel
    # and a BillingID starting "M". 19 of 47 "Delinquent" rows in one live prefix.
    biz = _rec(RecordType="Delinquent", RealPropertyType=None, DelqSw=True,
               ParcelNumber="", BillingID="M2025101179")
    assert m.is_delinquent_real_property(biz, rule) is False
    # Aiken "Real" rows with DelqSw False are current-year bills, not delinquent.
    cur = _rec(RecordType="Real", RealPropertyType=None, DelqSw=False,
               ParcelNumber="074-20-01-006")
    assert m.is_delinquent_real_property(cur, rule) is False
    # A parcel-shaped id is required to be digit-led.
    assert m.is_delinquent_real_property({**real, "ParcelNumber": "M-123"}, rule) is False


def test_aiken_mobile_homes_are_opt_in(monkeypatch):
    rule = m.rule_for("Aiken")
    mh = _rec(RecordType="Mobile Home", RealPropertyType=None, DelqSw=True,
              ParcelNumber="777-00-13-949", BillingID="777-00-13-949")
    monkeypatch.delenv("CATALIS_ROLL_MOBILE_HOMES", raising=False)
    assert m.is_delinquent_real_property(mh, rule) is False
    monkeypatch.setenv("CATALIS_ROLL_MOBILE_HOMES", "1")
    assert m.is_delinquent_real_property(mh, rule) is True
    li = m.to_listing("Aiken", mh)
    assert li.property_kind == PropertyKind.MOBILE
    # Chester has no such rule: the flag does not widen it.
    assert m.is_delinquent_real_property(mh, m.rule_for("Chester")) is False


# --------------------------------------------------------------------------- mapping

def test_chester_row_maps_owner_amount_mailing_and_type():
    li = m.to_listing("Chester", _rec())
    assert li.state == "SC" and li.county == "Chester"
    assert li.parcel_id == "061-02-00-021-000"
    assert li.listing_type == ListingType.TAX_LIEN         # a standing roll, no sale date
    assert li.sale_date is None
    # The current owner leads; the billed name is kept beside it.
    assert li.owner_name == "ROE JANE TTE" and li.defendant == "ROE JANE TTE"
    c = li.raw["catalis_roll"]
    assert c["billed_owner"] == "DOE JOHN Q" and c["assessor_owner"] == "ROE JANE TTE"
    assert c["owner_mailing"] == "c/o JANE ROE PO BOX 10 MATTHEWS NC 28106"
    assert c["total_due"] == 1410.6 and c["base_tax"] == 1261.39 and c["penalty"] == 175.51
    # The balance reaches the field the scorer's recorded_debt signal reads.
    assert li.raw["tax_owed"]["balance"] == 1410.6
    assert li.raw["tax_owed"]["basis"] == "own_record"
    assert li.raw["tax_owed"]["year"] == 2025
    assert li.acreage == 2.0
    assert "$1,410.60 due" in li.description


def test_a_legal_fragment_is_not_a_street_address():
    li = m.to_listing("Chester", _rec())
    assert li.street_address is None
    assert li.legal_description == "LOT # 21 = 2.00 AC AD#26-00121"


def test_a_mobile_home_description_is_not_a_street_address():
    rec = _rec(Description="1994 FLEETWOOD",
               SitusAddress={"Line1": "1994 FLEETWOOD"}, AssessorData=None)
    li = m.to_listing("Hampton", rec)
    assert li.street_address is None and li.legal_description == "1994 FLEETWOOD"
    assert li.owner_name == "DOE JOHN Q"                   # no assessor block: billed name


def test_fairfield_situs_comes_from_description():
    rec = _rec(RecordType="Real", RealPropertyType=None, DelqSw=True,
               ParcelNumber="187-00-00-012-000", BillingID="1870000012000",
               Description="1333 MOOD HARRISON RD", SitusAddress={}, AssessorData=None,
               Values={"Appraised": 36516, "Assessed": 1461, "BaseTax": 0.0, "Penalty": 42.41,
                       "OriginalAmountDue": 0.0, "AmountDue": 386.12})
    li = m.to_listing("Fairfield", rec)
    assert li.street_address == "1333 MOOD HARRISON RD"
    assert li.legal_description is None
    assert li.raw["tax_owed"]["balance"] == 386.12        # AmountDue, not the zero original
    assert li.listing_type == ListingType.TAX_LIEN


def test_amount_falls_back_to_the_original_when_amountdue_is_missing():
    rec = _rec(Values={"OriginalAmountDue": 301.17, "Appraised": 25500})
    assert m.to_listing("Hampton", rec).raw["catalis_roll"]["total_due"] == 301.17
    assert "tax_owed" not in m.to_listing("Hampton", _rec(Values={"Appraised": 1})).raw


def test_a_recorded_tax_sale_is_a_tax_sale_and_a_roll_is_not():
    sold = m.to_listing("Chester", _rec(TaxSaleRedemptionDate="2027-01-04T00:00:00"))
    assert sold.listing_type == ListingType.TAX_SALE
    assert m.to_listing("Chester", _rec()).listing_type == ListingType.TAX_LIEN


def test_pickens_keeps_its_original_type():
    """Pickens' rows are already on the board as TAX_SALE; that must not drift."""
    assert m.to_listing("Pickens", _rec(AssessorData=None)).listing_type == ListingType.TAX_SALE


def test_a_row_with_no_parcel_is_still_not_a_lead():
    assert m.to_listing("Aiken", _rec(ParcelNumber="")) is None


@pytest.mark.parametrize("text,ok", [
    ("1306 SEIVERN RD", True), ("198 OLD CHEROKEE INDIAN RD", True),
    ("14 FOLLY CIRCLE", True), ("1521 SUMNER AVE Lot 5", True),
    ("1994 FLEETWOOD", False), ("EU WILLIEMAE LN", False),
    ("LOT # 21 = 2.00 AC", False), ("N OF SILVER BLUFF ROAD", False), ("", False), (None, False),
])
def test_street_address_shape(text, ok):
    assert m.looks_like_street_address(text) is ok


# --------------------------------------------------------------------------- the sweep

def _patch_client(monkeypatch, handler):
    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    monkeypatch.setattr(m, "_PACE_S", 0.0)
    monkeypatch.setattr(m, "_BACKOFF_S", 0.0)


def test_a_sample_prefix_is_one_request_and_keeps_partial(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json=[_rec(), _rec(RecordType="Vehicle", RealPropertyType=False,
                                                       ParcelNumber="", BillingID="V1")])

    _patch_client(monkeypatch, handler)
    monkeypatch.setenv("CATALIS_ROLL_COUNTIES", "Chester")
    s = m.SCCatalisDelinquentRoll()
    s.sample_prefixes = {"Chester": "BROWN"}
    out = asyncio.run(s.fetch())
    assert len(seen) == 1 and seen[0].endswith("/61020303-8d26-4a16-b995-6deb1def7d97/Records")
    assert [li.county for li in out] == ["Chester"]
    assert len(s.partial) == 1                              # kept for a soft-timeout salvage


def test_a_403_stops_the_sweep_and_every_later_county(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(403, text="Access Denied")

    _patch_client(monkeypatch, handler)
    monkeypatch.delenv("CATALIS_ROLL_COUNTIES", raising=False)
    s = m.SCCatalisDelinquentRoll()
    out = asyncio.run(s.fetch())
    assert out == []
    # ONE request in total: not five retries, not 36 first-level prefixes, not the next county.
    assert len(seen) == 1, seen


def test_sweep_county_raises_on_403_and_does_not_retry(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(1)
        return httpx.Response(403)

    _patch_client(monkeypatch, handler)
    guid, site = m.CATALIS_COUNTIES["Chester"]
    with pytest.raises(m.CatalisBlocked):
        asyncio.run(m.sweep_county("Chester", guid, site, m._Budget(50)))
    assert len(seen) == 1


def test_sweep_deepens_a_capped_prefix_and_honours_the_aiken_depth_limit(monkeypatch):
    calls = []

    def handler(req: httpx.Request):
        import json as _j
        val = _j.loads(req.content)["value"]
        calls.append(val)
        # Every prefix is "full": forces deepening until max depth.
        return httpx.Response(200, json=[_rec(BillingID=f"{val}-{i}", ParcelNumber=f"049-19-01-{i:03d}",
                                              RealPropertyType=None, DelqSw=True)
                                         for i in range(m.PAGE_CAP)][:m.PAGE_CAP])

    _patch_client(monkeypatch, handler)
    guid, site = m.CATALIS_COUNTIES["Aiken"]
    recs, stats = asyncio.run(m.sweep_county("Aiken", guid, site, m._Budget(10_000),
                                             prefixes=["Z"]))
    # depth 1: "Z"; depth 2: "Z"+36 chars; depth 3 is refused for Aiken.
    assert len(calls) == 1 + 36
    assert stats["truncated_prefixes"] == 36          # every depth-2 prefix is still full
    assert max(len(c) for c in calls) == 2


# --------------------------------------------------------------------------- years and parcels

def test_bills_sharing_a_billing_id_across_years_are_all_read(monkeypatch):
    """Chester and Hampton use the parcel number as the BillingID of every year's bill. Keyed
    on BillingID alone a parcel delinquent since 2016 collapsed to ONE bill: prefix BROWN
    returned 71 delinquent rows and the sweep kept 18."""
    bills = [_rec(Year=y, Values={**_rec()["Values"], "AmountDue": 100.0 * (2026 - y)})
             for y in (2025, 2024, 2016)]

    def handler(req: httpx.Request):
        return httpx.Response(200, json=bills)

    _patch_client(monkeypatch, handler)
    guid, site = m.CATALIS_COUNTIES["Chester"]
    recs, _ = asyncio.run(m.sweep_county("Chester", guid, site, m._Budget(5), prefixes=["BROWN"]))
    assert sorted(r["Year"] for r in recs) == [2016, 2024, 2025]


def test_a_delinquent_parcel_becomes_one_lead_with_the_years_summed():
    bills = [_rec(Year=y, BillingID="061-02-00-021-000",
                  Values={**_rec()["Values"], "AmountDue": amt})
             for y, amt in ((2025, 1410.6), (2024, 1300.0), (2016, 500.4))]
    out = m.to_listings("Chester", bills + [_rec(ParcelNumber="061-02-00-022-000",
                                                 BillingID="061-02-00-022-000")])
    assert len(out) == 2
    li = next(x for x in out if x.parcel_id == "061-02-00-021-000")
    c = li.raw["catalis_roll"]
    assert c["years"] == [2016, 2024, 2025] and c["years_delinquent"] == 3
    assert c["oldest_year"] == 2016 and c["is_two_year_plus"] is True
    assert c["total_due"] == 3211.0
    assert li.raw["tax_owed"]["balance"] == 3211.0
    assert li.raw["tax_owed"]["year"] == 2025                 # the latest bill leads
    assert len(c["bills"]) == 3
    assert li.raw["two_year_delinquent"] == {"is_two_year_plus": True, "years": 3, "oldest_year": 2016,
                                             "source": m.SLUG}
    assert "2016-2025" in li.description and "3 bills" in li.description
    single = next(x for x in out if x.parcel_id == "061-02-00-022-000")
    assert single.raw["catalis_roll"]["is_two_year_plus"] is False


def test_pickens_stays_one_row_per_bill():
    bills = [_rec(Year=2025, BillingID="4192-00-96-21060001763", AssessorData=None),
             _rec(Year=2024, BillingID="4192-00-96-21060001764", AssessorData=None)]
    assert len(m.to_listings("Pickens", bills)) == 2

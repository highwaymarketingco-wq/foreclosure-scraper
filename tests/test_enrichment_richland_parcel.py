"""Richland County SC map-viewer API reader (enrichment_richland_parcel). Offline: the JSON
shapes are the live API's (2026-10-07); every name, street and number is made up."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from foreclosure_scraper import enrichment_richland_parcel as R
from foreclosure_scraper.models import Listing, ListingType

NOW = datetime(2026, 10, 7, 12, 0)

SEARCH = {"d": [
    {"confidence": "low", "uniqstring": "1200 PRETEND ST, 29201", "centerWKT": "POINT(-81.1 34.1)"},
    {"confidence": "high", "uniqstring": "1200 SAMPLE AVE, 29201", "centerWKT": "POINT(-81.0001 34.0002)"},
]}
PARCEL = {"d": [
    {"Parcel": {"TMS": "R09999-01-02", "Address": "1202 SAMPLE AVE", "Owner_Name": "OTHER PARCEL"}},
    {"Parcel": {"TMS": "R09999-01-01", "Address": "1200 SAMPLE AVE", "Owner_Name": "DOE JANE Q",
                "Owner_Addr": "PO BOX 77", "Owner_Ad_1": "", "Owner_City": "ATLANTA",
                "Owner_Stat": "GA", "Owner_Zip": "303010000", "Market_Val": "123,400",
                "Heated_SQF": "1,350 ft&sup2;", "Bldg1_Beds": "3", "Bldg1_Bath": "2",
                "Bldg1_YrBu": "1958", "Acreage": "0.25", "Last_Sale_": "March 3, 2004",
                "Last_Sale1": "$61,000", "OptedOut": "0", "WKT_Geom": "POLYGON((...))",
                "OWNER_SSN": "000-00-0000"}},
]}


def L(street="1200 SAMPLE AVE", **kw):
    return Listing(source="t", source_url="https://example.invalid/x", state="SC", county="Richland",
                   street_address=street, **kw)


class FakeHttp:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        body = SEARCH if url == R.SEARCH else PARCEL

        class Resp:
            status_code = 200

            def json(self_inner):
                return body
        return Resp()


def test_choose_point_needs_high_confidence_same_number_and_street():
    assert R.choose_point(SEARCH["d"], "1200 SAMPLE AVE") == (34.0002, -81.0001)
    assert R.choose_point(SEARCH["d"], "1200 PRETEND ST") is None      # only a low-confidence hit
    assert R.choose_point(SEARCH["d"], "1201 SAMPLE AVE") is None


def test_choose_parcel_matches_the_house_number_and_drops_sensitive_fields():
    p = R.choose_parcel(PARCEL["d"], "1200 SAMPLE AVE")
    assert p["TMS"] == "R09999-01-01" and "OWNER_SSN" not in p


def test_apply_fills_mailing_facts_and_provenance():
    li = L()
    filled = R.apply_parcel(li, R.choose_parcel(PARCEL["d"], "1200 SAMPLE AVE"), NOW)
    assert li.parcel_id == "R09999-01-01" and li.owner_name == "DOE JANE Q"
    om = li.raw["owner_mailing"]
    assert om["mailing"] == "PO BOX 77 ATLANTA GA 30301" and om["out_of_state"] is True
    assert (li.market_value, li.living_sqft, li.bedrooms, li.bathrooms, li.year_built) == \
        (123400.0, 1350.0, 3.0, 2.0, 1958)
    assert li.raw["gis"]["last_sale"] == {"amount": 61000.0, "date": "2004-03-03"}
    assert li.raw["richland_parcel"]["matched"] is True and "WKT_Geom" not in str(li.raw)
    assert {"mailing", "parcel_id", "year_built"} <= set(filled)


def test_opted_out_owner_keeps_name_and_mailing_off():
    p = dict(R.choose_parcel(PARCEL["d"], "1200 SAMPLE AVE"), OptedOut="1")
    li = L()
    R.apply_parcel(li, p, NOW)
    assert li.owner_name is None and "owner_mailing" not in li.raw
    assert li.market_value == 123400.0


def test_a_different_owner_withholds_the_mailing():
    li = L(owner_name="SMITH ROBERT")
    R.apply_parcel(li, R.choose_parcel(PARCEL["d"], "1200 SAMPLE AVE"), NOW)
    assert "owner_mailing" not in li.raw and li.raw["richland_parcel"]["owner_agrees"] is False
    assert li.owner_name == "SMITH ROBERT"


def test_wants_only_richland_rows_that_need_it_and_respects_the_retry_window():
    assert R.wants(L(), NOW)
    assert not R.wants(L(street="SAMPLE AVE"), NOW)
    assert not R.wants(Listing(source="t", source_url="https://e.invalid", state="SC",
                               county="Lexington", street_address="1 A ST"), NOW)
    assert not R.wants(L(listing_type=ListingType.TAX_SALE_OVERAGE), NOW)
    li = L()
    li.raw = {"richland_parcel": {"attempted": (NOW - timedelta(days=3)).isoformat()}}
    assert not R.wants(li, NOW)
    li.raw = {"richland_parcel": {"attempted": (NOW - timedelta(days=40)).isoformat()}}
    assert R.wants(li, NOW)


def test_enrich_runs_two_calls_per_row_and_caps_lookups():
    http = FakeHttp()
    rows = [L(), L(street="1200 SAMPLE AVE"), L(street="5 NOWHERE RD")]
    stats = asyncio.run(R.enrich_richland_parcel(rows, max_lookups=2, delay_s=0, http=http))
    assert stats["candidates"] == 2 and stats["matched"] == 2 and stats["filled_mailing"] == 2
    assert [u for u, _p in http.calls] == [R.SEARCH, R.AT_POINT, R.SEARCH, R.AT_POINT]
    assert http.calls[0][1]["searchTerm"] == "1200 SAMPLE AVE"
    assert "richland_parcel" not in (rows[2].raw or {})


def test_env_gate(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_RICHLAND_PARCEL", "0")
    assert asyncio.run(R.enrich_richland_parcel([L()], http=FakeHttp())) == {"skipped": "env"}

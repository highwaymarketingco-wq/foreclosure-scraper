"""NC OneMap statewide resolution for bankruptcy debtors — recovers an in-scope
NC property (+ parval value) for a debtor name, filtered to our footprint."""
from __future__ import annotations

import asyncio

import foreclosure_scraper.enrichment_bankruptcy_property as bkp
from foreclosure_scraper.models import Listing, ListingType


def _bk(name):
    return Listing(source="national.courtlistener_bankruptcy", source_url="u",
                   listing_type=ListingType.BANKRUPTCY, defendant=name, raw={})


def _patch(monkeypatch, results):
    async def fake(c, base, field, name):
        return results
    monkeypatch.setattr(bkp, "_query_by_owner", fake)


def test_distinctive_tokens():
    t = bkp._distinctive_tokens("Smith Holdings LLC")
    assert "smith" in t and "holdings" in t and "llc" not in t
    assert bkp._distinctive_tokens("J D Co") == set()  # all too short / stopwords


def test_footprint_only_single_match(monkeypatch):
    _patch(monkeypatch, [
        {"ownname": "SMITH, JOHN", "cntyname": "Wake", "parno": "1", "parval": 100000},      # out of scope
        {"ownname": "SMITH, JOHN", "cntyname": "Buncombe", "parno": "2", "parval": 200000},  # in scope
    ])
    m = asyncio.run(bkp._try_nc_onemap(None, "John Smith"))
    assert m and m["cntyname"] == "Buncombe"  # out-of-footprint dropped -> one left


def test_out_of_footprint_returns_none(monkeypatch):
    _patch(monkeypatch, [{"ownname": "SMITH, JOHN", "cntyname": "Wake", "parno": "1"}])
    assert asyncio.run(bkp._try_nc_onemap(None, "John Smith")) is None


def test_ambiguous_single_token_no_match(monkeypatch):
    _patch(monkeypatch, [
        {"ownname": "SMITH, JOHN", "cntyname": "Buncombe", "parno": "1"},
        {"ownname": "SMITH, JANE", "cntyname": "Gaston", "parno": "2"},
    ])
    # only one distinctive token ('smith') across 2 results -> gate needs >=2
    assert asyncio.run(bkp._try_nc_onemap(None, "Smith")) is None


def test_all_tokens_disambiguate(monkeypatch):
    _patch(monkeypatch, [
        {"ownname": "SMITH, JOHN A", "cntyname": "Buncombe", "parno": "1"},
        {"ownname": "DOE, JANE", "cntyname": "Gaston", "parno": "2"},
    ])
    m = asyncio.run(bkp._try_nc_onemap(None, "John Smith"))
    assert m and m["cntyname"] == "Buncombe"


def test_apply_match_fills_value_and_county():
    li = _bk("John Smith")
    attrs = {"ownname": "SMITH, JOHN", "siteadd": "123 MAIN ST",
             "parno": "9-99-99", "parval": 215000, "cntyname": "Buncombe"}
    counts = {"matched": 0, "kind_inferred": 0, "fields_filled": 0}
    bkp._apply_match(li, attrs, "Buncombe", counts)
    assert li.county == "Buncombe"
    assert (li.tax_value or li.market_value or li.assessed_value) == 215000
    assert counts["matched"] == 1 and counts["fields_filled"] > 0


def test_mecklenburg_denied_not_in_footprint():
    # the in-scope filter must exclude denied Mecklenburg/Madison
    assert "MECKLENBURG" not in bkp._ALLOWED_NC_UPPER
    assert "BUNCOMBE" in bkp._ALLOWED_NC_UPPER

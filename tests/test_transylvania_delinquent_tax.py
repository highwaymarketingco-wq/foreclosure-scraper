"""counties_nc.transylvania_delinquent_tax — multi-year widening (2026-10-14).

Date-coverage audit fix (docs/date_coverage_audit_2026-10-14.md, target #4): this file used
to query a single hardcoded `FORECLOSURE_TRANSYLVANIA_TAX_YEAR` (default "2025") and stop,
on the SAME ITSPublic/bitek vendor platform as the sibling `nc_its_public_tax.py`, whose
multi-year loop already proves the portal answers any `TaxYear` asked. Live-verified
2026-10-14: real unpaid-bill data exists for every year 2014-2025 (12 years); 2013 and
earlier all answer 0. A live dry run (no code change, just reading all 12 years and grouping
by parcel) found 909 real-estate bill-rows collapsing to 308 distinct parcels, 135 of them
(44%) delinquent in 2+ separate years -- several delinquent EVERY year since 2014. The fixed
module confirms this exactly: a full live `fetch()` returns 308 listings (up from 235 with
`FORECLOSURE_TRANSYLVANIA_TAX_YEAR=2025` reproducing the old single-year behavior), 134 of
them multi-year, the deepest three delinquent all 12 years 2014-2025 with real accumulated
balances ($1,166.41 / $1,738.97 / $1,319.97).
"""
from __future__ import annotations

import asyncio
import json as _json

import httpx
import pytest

import foreclosure_scraper.scrapers.counties_nc.transylvania_delinquent_tax as m


def _grid_row(year, bill, account, owner, desc, orig, bal):
    return {"id": f"{year}/{bill}",
            "cell": [str(year), str(bill), account, owner, desc, orig, bal]}


# Real-shaped description cells, live 2026-10-14: "PARCEL<br/>MAP MS<br/><br/>ACREAGE LT".
REAL_ESTATE_DESC = "8586223397000<br/>T001A00001  01 MS.01<br /><br />1.270 AC"
PERSONAL_PROPERTY_DESC = "Personal Property<br /><br />"


# --------------------------------------------------------------------------- tax_years

def test_years_back_default_is_15_and_the_loop_goes_back_that_far(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", raising=False)
    assert m.YEARS_BACK == 15
    years = m.tax_years(latest=2025)
    assert years[0] == 2025 and years[-1] == 2011 and len(years) == 15


def test_a_single_year_override_still_works_unchanged(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", "2025")
    assert m.tax_years(latest=2019) == [2025]      # override wins regardless of `latest`


# --------------------------------------------------------------------------- parse_grid_row / grouping

def test_parse_grid_row_extracts_parcel_map_acreage_and_drops_personal_property():
    real = m.parse_grid_row(_grid_row(2025, 101, "70000001", "ROE JANE", REAL_ESTATE_DESC,
                                      "100.00", "50.00"))
    assert real["grid_parcel"] == "8586223397000" and real["acreage"] == 1.27
    assert real["year"] == 2025 and real["balance"] == 50.0
    pp = m.parse_grid_row(_grid_row(2025, 102, "70000002", "ROE JOHN", PERSONAL_PROPERTY_DESC,
                                    "10.00", "10.00"))
    assert pp is None


def test_group_by_parcel_merges_the_same_parcel_across_many_years():
    bills = [m.parse_grid_row(_grid_row(y, 100 + y, "70000001", "ROE JANE", REAL_ESTATE_DESC,
                                        "100.00", "50.00"))
             for y in range(2014, 2026)]           # 12 straight years, same parcel
    other = m.parse_grid_row(_grid_row(2025, 999, "70000099", "DOE ANN",
                                       "9500000099000<br/>T099A00001  01 MS.01<br /><br />0.500 AC",
                                       "20.00", "15.00"))
    groups = m.group_by_parcel(bills + [other])
    assert len(groups) == 2
    assert len(groups["8586223397000"]) == 12
    assert len(groups["9500000099000"]) == 1


def test_group_by_parcel_falls_back_to_account_when_the_grid_has_no_parcel():
    """Transylvania's grid prints no situs at all, so a bill with a completely empty
    description (no parcel, no map, no acreage line at all) groups by account instead of
    being dropped."""
    no_parcel = m.parse_grid_row(_grid_row(2025, 5, "70000005", "ROE SAM", "<br /><br /><br />",
                                           "10.00", "5.00"))
    assert no_parcel is not None and no_parcel["grid_parcel"] is None
    groups = m.group_by_parcel([no_parcel])
    assert list(groups.keys()) == ["acct:70000005"]


# --------------------------------------------------------------------------- build_listing

def test_build_listing_sums_balance_and_levy_across_every_year_in_the_group():
    """The actual business fix: a parcel delinquent 12 STRAIGHT years aggregates its full
    accumulated balance and reports the true years_delinquent depth, not just whichever
    single year the old code happened to read."""
    bills = [m.parse_grid_row(_grid_row(y, 100 + (y - 2014), "70000001", "ROE JANE",
                                        REAL_ESTATE_DESC, "100.00", "50.00"))
             for y in range(2014, 2026)]
    li = m.build_listing(bills, {}, __import__("datetime").datetime(2026, 10, 14))
    t = li.raw["transylvania_tax"]
    assert t["years"] == list(range(2014, 2026)) and t["years_delinquent"] == 12
    assert t["oldest_year"] == 2014 and t["is_two_year_plus"] is True
    assert t["balance_owed"] == 600.0 and t["original_levy"] == 1200.0     # 12 x $50 / $100
    assert li.raw["two_year_delinquent"] == {"is_two_year_plus": True, "years": 12,
                                             "oldest_year": 2014, "source": m.SLUG}
    assert li.raw["tax_owed"]["balance"] == 600.0
    assert "2014-2025" in li.description and "12 bills" in li.description


def test_build_listing_with_a_single_year_bill_matches_the_old_single_year_shape():
    bills = [m.parse_grid_row(_grid_row(2025, 101, "70000001", "ROE JANE", REAL_ESTATE_DESC,
                                        "100.00", "50.00"))]
    li = m.build_listing(bills, {}, __import__("datetime").datetime(2026, 10, 14))
    t = li.raw["transylvania_tax"]
    assert t["years_delinquent"] == 1 and t["is_two_year_plus"] is False
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is False


def test_build_listing_uses_the_detail_fetch_for_mailing_and_value_not_the_grid():
    bills = [m.parse_grid_row(_grid_row(2025, 101, "70000001", "ROE JANE", REAL_ESTATE_DESC,
                                        "100.00", "50.00"))]
    det = {"parcel_number": "8586223397000", "mailing_full": "17 Example Ct, Sampleton, NV 89000",
          "mailing_state": "NV", "building_value": 50000.0, "land_value": 10000.0,
          "parcel_value_total": 60000.0}
    li = m.build_listing(bills, det, __import__("datetime").datetime(2026, 10, 14))
    assert li.raw["owner_mailing"]["mail_state"] == "NV"
    assert li.raw["owner_mailing"]["out_of_state"] is True
    assert li.assessed_value == 60000.0


# --------------------------------------------------------------------------- full fetch() integration

def _years_transport(rows_by_year: dict[str, list[dict]], detail_html: str = ""):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/TaxBillSearch":
            return httpx.Response(200, text="<html>search</html>",
                                  headers={"set-cookie": "ASP.NET_SessionId=abc; path=/"})
        body = _json.loads(request.content or b"{}")
        if path.endswith("GetSearchTablePartial/"):
            handler.year = body["TaxYear"]
            return httpx.Response(200, text="<div>fragment</div>")
        if path.endswith("GetSearchTableData"):
            rows = rows_by_year.get(handler.year, [])
            return httpx.Response(200, json={"total": 1, "numRecords": len(rows), "rows": rows})
        if path.endswith("ViewTaxBill"):
            return httpx.Response(200, text=detail_html)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def _fast_env(monkeypatch):
    monkeypatch.delenv("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", raising=False)
    monkeypatch.setenv("FORECLOSURE_TRANSYLVANIA_TAX_CONCURRENCY", "2")


def test_fetch_aggregates_a_decade_deep_parcel_across_many_years(monkeypatch, _fast_env):
    """End-to-end: 12 years of the SAME parcel, one bill each, plus a lone 2025-only parcel
    for contrast. With the multi-year fix, fetch() must return exactly 2 listings -- the
    long-delinquent parcel with years_delinquent == 12, and the other with 1."""
    monkeypatch.setattr(m, "tax_years", lambda latest=None, back=None: list(range(2025, 2013, -1)))
    rows_by_year = {}
    for y in range(2014, 2026):
        rows_by_year[str(y)] = [_grid_row(y, 100 + (y - 2014), "70000001", "ROE JANE",
                                          REAL_ESTATE_DESC, "100.00", "50.00")]
    rows_by_year["2025"].append(_grid_row(2025, 999, "70000099", "DOE ANN",
                                          "9500000099000<br/>T099A00001  01 MS.01<br /><br />0.500 AC",
                                          "20.00", "15.00"))

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = _years_transport(rows_by_year)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    out = asyncio.run(m.TransylvaniaDelinquentTax().fetch())
    by_parcel = {li.parcel_id: li for li in out}
    assert len(out) == 2
    assert by_parcel["8586223397000"].raw["transylvania_tax"]["years_delinquent"] == 12
    assert by_parcel["8586223397000"].raw["transylvania_tax"]["balance_owed"] == 600.0
    assert by_parcel["9500000099000"].raw["transylvania_tax"]["years_delinquent"] == 1


def test_fetch_with_the_single_year_override_reproduces_the_old_behavior(monkeypatch, _fast_env):
    """Setting FORECLOSURE_TRANSYLVANIA_TAX_YEAR must reproduce the PRE-fix shape exactly:
    one year read, no multi-year aggregation, even though the SAME parcel has older bills
    sitting in rows_by_year that a multi-year read would have picked up."""
    monkeypatch.setenv("FORECLOSURE_TRANSYLVANIA_TAX_YEAR", "2025")
    rows_by_year = {str(y): [_grid_row(y, 100 + (y - 2014), "70000001", "ROE JANE",
                                       REAL_ESTATE_DESC, "100.00", "50.00")]
                    for y in range(2014, 2026)}

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = _years_transport(rows_by_year)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    out = asyncio.run(m.TransylvaniaDelinquentTax().fetch())
    assert len(out) == 1
    assert out[0].raw["transylvania_tax"]["years_delinquent"] == 1
    assert out[0].raw["transylvania_tax"]["balance_owed"] == 50.0    # not the 12-year sum


def test_fetch_stops_after_two_consecutive_empty_years_but_not_one(monkeypatch, _fast_env):
    """Mirrors the real Onslow-style blip this codebase already handles elsewhere: a lone
    empty year must not cut the crawl short, but two in a row does."""
    monkeypatch.setattr(m, "YEARS_BACK", 6)
    latest = 2025
    years_seq = [latest - i for i in range(6)]      # [2025, 2024, 2023, 2022, 2021, 2020]
    rows_by_year = {
        str(years_seq[0]): [_grid_row(years_seq[0], 1, "1", "A", REAL_ESTATE_DESC, "1", "1")],
        str(years_seq[1]): [_grid_row(years_seq[1], 2, "1", "A", REAL_ESTATE_DESC, "1", "1")],
        str(years_seq[2]): [],                                                    # lone blip
        str(years_seq[3]): [_grid_row(years_seq[3], 3, "1", "A", REAL_ESTATE_DESC, "1", "1")],
        str(years_seq[4]): [],
        str(years_seq[5]): [],                                                    # 2 in a row -> stop
    }
    seen_years: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/TaxBillSearch":
            return httpx.Response(200, text="ok")
        body = _json.loads(request.content or b"{}")
        if path.endswith("GetSearchTablePartial/"):
            seen_years.append(body["TaxYear"])
            handler.year = body["TaxYear"]
            return httpx.Response(200, text="ok")
        rows = rows_by_year.get(handler.year, [])
        return httpx.Response(200, json={"total": 1, "numRecords": len(rows), "rows": rows})

    real = httpx.AsyncClient

    class Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", Fake)
    monkeypatch.setattr(m, "tax_years", lambda latest=None, back=None: years_seq)
    out = asyncio.run(m.TransylvaniaDelinquentTax().fetch())
    assert seen_years == [str(y) for y in years_seq]     # all 6 years asked for
    assert len(out) == 1 and out[0].raw["transylvania_tax"]["years_delinquent"] == 3

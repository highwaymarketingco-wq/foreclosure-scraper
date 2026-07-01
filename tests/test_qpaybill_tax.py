"""qPayBill delinquent-tax enrichment — grid parse, surname, TMS match, gating."""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_qpaybill_tax as q
from foreclosure_scraper.models import Listing, ListingType

_ROW = ('<tr><td>175401253</td><td>SMITH X 148 COBB RD</td><td>2025</td><td>148 COBB RD</td>'
        '<td>2-37-00-035.53</td><td>RealEstate</td><td>{status}</td><td></td><td>${amt}</td><td>View</td></tr>')


def test_parse_grid_row():
    rows = q._parse_rows(_ROW.format(status="Unpaid", amt="508.70"))
    assert rows == [{"tms": "2-37-00-035.53", "year": "2025", "status": "Unpaid", "amount": 508.70}]


def test_parse_skips_sentinel_and_junk():
    assert q._parse_rows(_ROW.format(status="Unpaid", amt="99,999.00")) == []  # $99,999 sentinel
    assert q._parse_rows("<tr><td>no</td><td>cells</td></tr>") == []


def test_surname_extraction():
    assert q._surname("MEADOWS ALFRED AAA WOFTMAN LLC") == "MEADOWS"
    assert q._surname("ADDIS PATRICIA CUDD TIFFANY (CS)") == "ADDIS"
    assert q._surname("  123 ") is None


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr(q, "_ENABLED", False)
    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="2-37-00-035.53", owner_name="SMITH X")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out == {"targets": 0, "queries": 0, "filled": 0, "misses": 0}


def test_match_by_tms_and_sum_years(monkeypatch):
    monkeypatch.setattr(q, "_ENABLED", True)

    async def fake_search(client, sub, vs, surname):
        # two years owed on the target parcel + one unrelated parcel + one paid row
        return [
            {"tms": "2-37-00-035.53", "year": "2025", "status": "Unpaid", "amount": 500.0},
            {"tms": "2-37-00-035.53", "year": "2024", "status": "Unpaid", "amount": 300.0},
            {"tms": "9-99-99-999.99", "year": "2025", "status": "Unpaid", "amount": 111.0},
        ]

    async def fake_get(url):
        class R:  # minimal stub
            text = '<input id="__VIEWSTATE" value="v"><input id="__VIEWSTATEGENERATOR" value="g"><input id="__EVENTVALIDATION" value="e">'
        return R()

    monkeypatch.setattr(q, "_search_surname", fake_search)
    # patch the client GET via monkeypatching httpx is heavier; instead pre-seed vs by patching get_vs path:
    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "get", lambda self, url: fake_get(url))

    li = Listing(source="counties_sc.spartanburg_delinquent_tax", source_url="u",
                 listing_type=ListingType.TAX_SALE, state="SC", county="Spartanburg",
                 parcel_id="2-37-00-035.53", owner_name="ADDIS PATRICIA")
    out = asyncio.run(q.enrich_qpaybill_tax([li]))
    assert out["filled"] == 1
    t = li.raw["tax_owed"]
    assert t["balance"] == 800.0                 # summed across 2025 + 2024
    assert t["kind"] == "delinquent_tax" and t["years"] == ["2024", "2025"]
    assert t["source"] == "qpaybill:spartanburgcountytax"

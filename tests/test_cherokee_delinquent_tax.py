"""Tests for Cherokee SC delinquent tax sale PDF parser."""
import asyncio
import json

from foreclosure_scraper.scrapers.counties_sc import cherokee_delinquent_tax as mod
from foreclosure_scraper.scrapers.counties_sc.cherokee_delinquent_tax import (
    CherokeeDelinquentTaxScraper,
    _parse_pdf_text,
)


SAMPLE_TEXT = """DELINQUENT TAX SALE
Legal Notice of Delinquent Tax Sale
State of South Carolina, Cherokee County
NOTICE: THE DELINQUENT TAX SALE OF CHEROKEE COUNTY WILL BE HELD ON MONDAY NOVEMBER 4, 2024

Item Number Owner Name Map Number Description
1 A AND R PROPERTY MANAGEMENT 099-01-00-022.000 946 N LOGAN ST
2 A.T.O. 21 LLC 081-12-00-025.000 W FAIRVIEW AVE//800 1/2
3 A.T.O. 21 LLC 081-14-00-031.000 417 MARION AVE
4 A.T.O. 21 LLC 099-06-00-133.000 604 RAILROAD AVE LT#6 B
6 A.T.O. 21 LLC 118-05-00-028.000 730 MARIETTA ST
106-00-00-018.002 ADAMS ZAVIAH 4701 UNION HWY
032-00-00-112.102 ALEJO PABLE ANTONIO 121 C B LN
"""


def test_parses_standard_rows():
    """Standard rows: <item#> <owner> <TMS> <description>"""
    rows = _parse_pdf_text(SAMPLE_TEXT)
    # Should parse rows that start with item number
    tms_values = [r["tms"] for r in rows]
    assert "099-01-00-022.000" in tms_values
    assert "081-12-00-025.000" in tms_values


def test_extracts_owner():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    owners = {r["tms"]: r["owner"] for r in rows}
    assert owners.get("099-01-00-022.000") == "A AND R PROPERTY MANAGEMENT"
    assert owners.get("081-12-00-025.000") == "A.T.O. 21 LLC"


def test_extracts_description():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    descs = {r["tms"]: r["description"] for r in rows}
    assert "946 N LOGAN ST" in descs.get("099-01-00-022.000", "")


def test_skips_header_lines():
    rows = _parse_pdf_text(SAMPLE_TEXT)
    # No row should have "Item Number" as owner
    for r in rows:
        assert "Item Number" not in r["owner"]
        assert "DELINQUENT" not in r["owner"].upper()


def test_empty_text():
    assert _parse_pdf_text("") == []
    assert _parse_pdf_text("No data here\njust text") == []


def test_tms_format():
    """TMS should match NNN-NN-NN-NNN.NNN format"""
    rows = _parse_pdf_text(SAMPLE_TEXT)
    import re
    tms_re = re.compile(r"^\d{3}-\d{2}-\d{2}-\d{3}\.\d{3}$")
    for r in rows:
        assert tms_re.match(r["tms"]), f"Bad TMS: {r['tms']}"


# --------------------------------------------------------------------------
# fetch() -> Listing construction. Audited 2026-10-01: owner and the parsed
# situs ("description") were both correctly extracted by _parse_pdf_text but
# never reached the Listing's owner_name/street_address fields -- owner only
# reached `defendant`, and description was kept in raw only. Live-verified
# before the fix: 0/528 real rows had owner_name or street_address. These
# tests cover the fetch()-level wiring with the network fully mocked.
# --------------------------------------------------------------------------

_FAKE_MEDIA = [{"source_url": "https://example.test/Tax-Sale-List-2024.pdf",
                "title": {"rendered": "Tax Sale List 2024"}}]


def _run_fetch(monkeypatch):
    async def fake_get_text(url, timeout=20, headers=None):
        return json.dumps(_FAKE_MEDIA)

    async def fake_get_bytes(url, timeout=60):
        return b"%PDF-fake"

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    monkeypatch.setattr(mod, "get_bytes", fake_get_bytes)
    monkeypatch.setattr(mod, "_extract_pdf_text", lambda data: SAMPLE_TEXT)

    async def collect():
        return [li async for li in CherokeeDelinquentTaxScraper().fetch()]

    return asyncio.run(collect())


def test_fetch_sets_owner_name_not_just_defendant(monkeypatch):
    out = _run_fetch(monkeypatch)
    by_tms = {li.parcel_id: li for li in out}
    row = by_tms["099-01-00-022.000"]
    assert row.owner_name == "A AND R PROPERTY MANAGEMENT"
    assert row.owner_name == row.defendant


def test_fetch_sets_street_address_from_parsed_description(monkeypatch):
    out = _run_fetch(monkeypatch)
    by_tms = {li.parcel_id: li for li in out}
    assert by_tms["099-01-00-022.000"].street_address == "946 N LOGAN ST"
    assert by_tms["081-14-00-031.000"].street_address == "417 MARION AVE"


def test_fetch_keeps_no_house_number_situs_too(monkeypatch):
    """Not every description is house-number-led (e.g. a bare lot) -- those
    are still real, usable situs text and must not be dropped."""
    out = _run_fetch(monkeypatch)
    by_tms = {li.parcel_id: li for li in out}
    assert by_tms["081-12-00-025.000"].street_address == "W FAIRVIEW AVE//800 1/2"

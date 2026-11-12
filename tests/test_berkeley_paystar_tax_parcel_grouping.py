"""Berkeley paystar: one lead per parcel with every unpaid year, and a retry for failed details.

The portal bills each tax year as its own invoice. The scraper used to emit one row per
invoice; dedupe() merged a parcel's rows on the parcel key and kept one invoice's block, so
the other years' balances and the multi-year fact were lost. Made-up names and parcels.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc import berkeley_paystar_tax as mod
from foreclosure_scraper.scrapers.counties_sc.berkeley_paystar_tax import BerkeleyPaystarTax


def _detail(inv: str, parcel: str, year: int, cents: int, owner: str = "SAMPLE OWNER A") -> dict:
    return {
        "invoiceNumber": inv,
        "taxYear": year,
        "invoiceAmountMinor": cents,
        "delinquent": True,
        "invoiceeName": owner,
        "invoiceStreetAddress1": "10 EXAMPLE LN",
        "invoiceCity": "SAMPLETOWN",
        "invoiceState": "SC",
        "invoicePostalCode": "29400",
        "assetIdentifierDisplay": parcel,
        "assetMetaJson": None,
    }


DETAILS = {
    "h1": _detail("2025-0000001", "111-00-00-001", 2025, 150000),
    "h2": _detail("2024-0000002", "111-00-00-001", 2024, 120050),
    "h3": _detail("2022-0000003", "111-00-00-001", 2022, 9900),
    "h4": _detail("2025-0000004", "222-00-00-002", 2025, 50000, owner="SAMPLE OWNER B"),
}


def _patch(monkeypatch, details, fail_first=()):
    async def fake_list_all(client):
        return [{"invoiceNumberHash": h, "taxYear": details[h]["taxYear"]} for h in details]

    calls: dict[str, int] = {}

    async def fake_detail(client, sem, h):
        calls[h] = calls.get(h, 0) + 1
        if h in fail_first and calls[h] == 1:
            return h, None
        return h, details[h]

    monkeypatch.setattr(mod, "_list_all", fake_list_all)
    monkeypatch.setattr(mod, "_fetch_detail", fake_detail)
    return calls


def test_a_parcels_invoices_become_one_row_with_every_year(monkeypatch):
    _patch(monkeypatch, DETAILS)
    rows = asyncio.run(BerkeleyPaystarTax().fetch())
    by_parcel = {r.parcel_id: r for r in rows}
    assert sorted(by_parcel) == ["111-00-00-001", "222-00-00-002"]

    multi = by_parcel["111-00-00-001"]
    blk = multi.raw["berkeley_paystar_tax"]
    assert blk["tax_year"] == 2025                       # the newest invoice is the row
    assert multi.case_number == "2025-0000001"
    assert blk["latest_invoice_total_due"] == 1500.00
    assert blk["total_due"] == 1500.00 + 1200.50 + 99.00
    assert blk["years_unpaid"] == ["2022", "2024", "2025"]
    assert blk["oldest_year"] == 2022
    assert blk["invoice_count"] == 3
    assert [b["tax_year"] for b in blk["bills"]] == [2022, 2024, 2025]
    assert [b["total_due"] for b in blk["bills"]] == [99.00, 1200.50, 1500.00]

    single = by_parcel["222-00-00-002"].raw["berkeley_paystar_tax"]
    assert single["total_due"] == 500.00 and single["years_unpaid"] == ["2025"]


def test_salvage_list_holds_the_grouped_rows_not_one_per_invoice(monkeypatch):
    _patch(monkeypatch, DETAILS)
    s = BerkeleyPaystarTax()
    rows = asyncio.run(s.fetch())
    assert len(s.partial) == len(rows) == 2
    assert {r.parcel_id: r.raw["berkeley_paystar_tax"]["total_due"] for r in s.partial} == \
        {r.parcel_id: r.raw["berkeley_paystar_tax"]["total_due"] for r in rows}


def test_tax_owed_reads_every_year_off_the_grouped_block(monkeypatch):
    from foreclosure_scraper import enrichment_tax_owed as eto
    _patch(monkeypatch, DETAILS)
    rows = asyncio.run(BerkeleyPaystarTax().fetch())
    multi = next(r for r in rows if r.parcel_id == "111-00-00-001")
    assert eto.unpaid_levy_years(multi.raw) == [2022, 2024, 2025]
    assert eto._amounts_by_year(multi.raw) == {2022: 99.0, 2024: 1200.5, 2025: 1500.0}


def test_a_failed_detail_is_tried_once_more(monkeypatch):
    calls = _patch(monkeypatch, DETAILS, fail_first=("h3", "h4"))
    rows = asyncio.run(BerkeleyPaystarTax().fetch())
    assert calls["h3"] == 2 and calls["h4"] == 2 and calls["h1"] == 1
    assert sorted(r.parcel_id for r in rows) == ["111-00-00-001", "222-00-00-002"]
    assert next(r for r in rows if r.parcel_id == "111-00-00-001") \
        .raw["berkeley_paystar_tax"]["oldest_year"] == 2022

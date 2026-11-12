"""enrichment_ptscloud_two_year_delinquent: pure, no-network restatement of
raw['nc_ptscloud_delinquent_tax']['by_year'] into the shared raw['two_year_delinquent']
contract. by_year fixtures use the exact dict shape nc_ptscloud_delinquent_tax._bill_entry
produces (tax_year/bill_amount/bill_due_amt/interest_due/total_due/bill_status/bill_due_date).
"""
from __future__ import annotations

from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_ptscloud_two_year_delinquent import (
    build_two_year_block, enrich_ptscloud_two_year_delinquent,
)

# nc_ptscloud_delinquent_tax uses tax_calendar's default (no county override) for NC levy
# delinquency, which is late on January 6 of the following year -- matches the sibling
# multiyear test's own TODAY.
TODAY = date(2026, 10, 18)


def _bill(year: str, total_due: float) -> dict:
    return {"tax_year": year, "bill_number": f"B-{year}", "bill_amount": total_due,
            "bill_due_amt": total_due, "interest_due": 0.0, "total_due": total_due,
            "bill_status": "DELINQUENT", "bill_due_date": f"{year}-01-05"}


def _li(parcel="6869430725", county="Guilford", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_ptscloud_delinquent_tax", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


# ---------------------------------------------------------------------------
# build_two_year_block
# ---------------------------------------------------------------------------

def test_build_two_year_block_matured_multi_year():
    by_year = [_bill("2026", 50.0), _bill("2025", 48.0), _bill("2024", 45.0)]
    block = build_two_year_block({"by_year": by_year}, "Guilford")
    assert block == {"is_two_year_plus": True, "years": 2, "oldest_year": 2024,
                      "source": "counties_nc.nc_ptscloud_delinquent_tax"}


def test_build_two_year_block_single_year_still_written_as_false():
    block = build_two_year_block({"by_year": [_bill("2026", 50.0)]}, "Guilford")
    assert block["is_two_year_plus"] is False
    assert block["years"] == 0          # 2026 is not yet late relative to "today" in real runs
    assert block["oldest_year"] == 2026


def test_build_two_year_block_missing_by_year_shape_returns_none():
    assert build_two_year_block({"parcel": "p1", "tax_year": "2026"}, "Guilford") is None


def test_build_two_year_block_empty_by_year_list():
    block = build_two_year_block({"by_year": []}, "Guilford")
    assert block == {"is_two_year_plus": False, "years": 0, "oldest_year": None,
                      "source": "counties_nc.nc_ptscloud_delinquent_tax"}


def test_build_two_year_block_ignores_unparseable_year_rows():
    by_year = [_bill("2023", 10.0), {"tax_year": None, "total_due": 5.0}, _bill("2022", 12.0)]
    block = build_two_year_block({"by_year": by_year}, "Guilford")
    assert block["oldest_year"] == 2022


# ---------------------------------------------------------------------------
# enrich_ptscloud_two_year_delinquent: walks Listing objects
# ---------------------------------------------------------------------------

def test_enrich_skips_rows_without_the_source_block():
    li = _li(raw={})
    stats = enrich_ptscloud_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert "two_year_delinquent" not in li.raw


def test_enrich_writes_for_real_shaped_row():
    li = _li(raw={"nc_ptscloud_delinquent_tax": {
        "tenant": "Guilford", "parcel": "6910782033",
        "by_year": [_bill("2024", 30.0), _bill("2023", 28.0), _bill("2022", 25.0)],
    }})
    stats = enrich_ptscloud_two_year_delinquent([li])
    assert stats["eligible"] == 1
    assert stats["written"] == 1
    assert li.raw["two_year_delinquent"]["is_two_year_plus"] is True
    assert li.raw["two_year_delinquent"]["years"] == 3


def test_enrich_older_shape_without_by_year_counted_not_written():
    li = _li(raw={"nc_ptscloud_delinquent_tax": {
        "tenant": "Madison", "parcel": "p1", "tax_year": "2025",
    }})
    stats = enrich_ptscloud_two_year_delinquent([li])
    assert stats["eligible"] == 1
    assert stats["no_by_year_shape"] == 1
    assert "two_year_delinquent" not in li.raw


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"is_two_year_plus": True, "years": 99, "manual": True}
    li = _li(raw={
        "nc_ptscloud_delinquent_tax": {"tenant": "Guilford", "by_year": [_bill("2024", 30.0)]},
        "two_year_delinquent": sentinel,
    })
    stats = enrich_ptscloud_two_year_delinquent([li])
    assert stats["eligible"] == 0
    assert li.raw["two_year_delinquent"] is sentinel


def test_enrich_disabled_by_env(monkeypatch):
    monkeypatch.setenv("FORECLOSURE_PTSCLOUD_TYD", "0")
    import importlib
    import foreclosure_scraper.enrichment_ptscloud_two_year_delinquent as mod
    importlib.reload(mod)
    try:
        li = _li(raw={"nc_ptscloud_delinquent_tax": {"by_year": [_bill("2024", 30.0)]}})
        stats = mod.enrich_ptscloud_two_year_delinquent([li])
        assert stats == {"eligible": 0, "written": 0, "no_by_year_shape": 0}
        assert "two_year_delinquent" not in li.raw
    finally:
        monkeypatch.delenv("FORECLOSURE_PTSCLOUD_TYD", raising=False)
        importlib.reload(mod)

"""Pin skip-trace provider dispatch + free tax-records lookup.

Dad's note #7 — investors want homeowner contact info to attempt
short-sale outreach BEFORE the foreclosure sale. The module is
provider-pluggable; these tests verify:
  - 'none' default (no API calls, no cost)
  - 'tax_records_only' free path (reads GIS mailing-address)
  - SKIP_TRACE_PROVIDER env routing
  - max_per_run cap + sale-date priority
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from foreclosure_scraper.enrichment_skip_trace import (
    NoopProvider,
    TaxRecordsOnlyProvider,
    _priority,
    _resolve_provider,
    enrich_with_skip_trace,
)
from foreclosure_scraper.models import Listing, ListingType


def _li(**kw) -> Listing:
    base = dict(
        source="law_firms.brock_scott",
        source_url="https://example.com/x",
        listing_type=ListingType.FORECLOSURE_SALE,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    return Listing(**base)


# ---- provider resolution ----

def test_default_provider_is_none(monkeypatch):
    monkeypatch.delenv("SKIP_TRACE_PROVIDER", raising=False)
    p = _resolve_provider()
    assert isinstance(p, NoopProvider)


def test_explicit_none(monkeypatch):
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "none")
    p = _resolve_provider()
    assert isinstance(p, NoopProvider)


def test_tax_records_only(monkeypatch):
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "tax_records_only")
    p = _resolve_provider()
    assert isinstance(p, TaxRecordsOnlyProvider)


def test_batchskiptracing_falls_back_to_noop_without_key(monkeypatch):
    """Paid provider without API key → silent noop, no charges."""
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "batchskiptracing")
    monkeypatch.delenv("SKIP_TRACE_API_KEY", raising=False)
    p = _resolve_provider()
    assert isinstance(p, NoopProvider)


def test_unknown_provider_falls_back_to_noop(monkeypatch):
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "imaginary_service")
    p = _resolve_provider()
    assert isinstance(p, NoopProvider)


# ---- tax_records_only path ----

@pytest.mark.asyncio
async def test_tax_records_diff_mailing_flagged():
    """Mailing address differs from property → absentee owner flag."""
    provider = TaxRecordsOnlyProvider()
    li = _li(
        street_address="123 Main St",
        city="Asheville",
        state="NC",
        raw={"gis": {"owner_mailing_address": "456 Beach Rd, Wilmington NC"}},
    )
    out = await provider.lookup(li)
    assert out is not None
    assert out["provider"] == "tax_records_only"
    assert out["owner_mailing_diff_from_property"] is True
    assert out["confidence"] == "medium"


@pytest.mark.asyncio
async def test_tax_records_same_mailing_no_diff():
    """Owner-occupied (mailing == property) → no diff flag."""
    provider = TaxRecordsOnlyProvider()
    li = _li(
        street_address="123 Main St",
        raw={"gis": {"owner_mailing_address": "123 Main St"}},
    )
    out = await provider.lookup(li)
    assert out is not None
    assert out["owner_mailing_diff_from_property"] is False
    assert out["confidence"] == "low"


@pytest.mark.asyncio
async def test_tax_records_no_mailing_returns_none():
    """No GIS data → no skip-trace result (don't fabricate)."""
    provider = TaxRecordsOnlyProvider()
    li = _li(street_address="123 Main St")  # no raw['gis']
    out = await provider.lookup(li)
    assert out is None


# ---- dispatch behavior ----

@pytest.mark.asyncio
async def test_enrich_skipped_when_provider_is_noop(monkeypatch):
    """Default behavior: no provider, no API calls, no listing mutations."""
    monkeypatch.delenv("SKIP_TRACE_PROVIDER", raising=False)
    li = _li(street_address="123 Main St")
    stats = await enrich_with_skip_trace([li])
    assert stats["provider"] == "none"
    assert stats["attempted"] == 0
    assert "skip_trace" not in (li.raw or {})


@pytest.mark.asyncio
async def test_enrich_with_tax_records_populates_raw(monkeypatch):
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "tax_records_only")
    li = _li(
        street_address="123 Main St",
        raw={"gis": {"owner_mailing_address": "999 Elsewhere Ln"}},
    )
    stats = await enrich_with_skip_trace([li])
    assert stats["provider"] == "tax_records_only"
    assert stats["attempted"] == 1
    assert stats["succeeded"] == 1
    assert stats["absentee_owners_found"] == 1
    assert li.raw["skip_trace"]["owner_mailing_diff_from_property"] is True


@pytest.mark.asyncio
async def test_enrich_respects_max_per_run(monkeypatch):
    """Cap the number of API calls per run, prioritized by sale_date."""
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "tax_records_only")
    listings = [
        _li(
            street_address=f"{i} Main St",
            raw={"gis": {"owner_mailing_address": f"{i*100} Other St"}},
        )
        for i in range(10)
    ]
    stats = await enrich_with_skip_trace(listings, max_per_run=3)
    assert stats["attempted"] == 3
    assert stats["skipped"] == 7  # 10 eligible, 3 capped → 7 skipped


@pytest.mark.asyncio
async def test_enrich_skips_listings_already_traced(monkeypatch):
    """Don't re-trace listings that already have skip_trace data —
    idempotent across runs."""
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "tax_records_only")
    fresh = _li(
        street_address="1 Main St",
        raw={"gis": {"owner_mailing_address": "999 Diff"}},
    )
    already = _li(
        street_address="2 Main St",
        raw={
            "gis": {"owner_mailing_address": "999 Diff"},
            "skip_trace": {"provider": "tax_records_only", "owner_mailing_address": "999 Diff"},
        },
    )
    stats = await enrich_with_skip_trace([fresh, already])
    assert stats["attempted"] == 1  # only fresh


# ---- priority ordering ----

def test_priority_imminent_first():
    now = datetime.utcnow()
    imminent = _li(sale_date=now + timedelta(days=2))
    future = _li(sale_date=now + timedelta(days=30))
    past = _li(sale_date=now - timedelta(days=5))
    no_date = _li()
    items = [no_date, future, past, imminent]
    items.sort(key=_priority)
    assert items[0] is imminent
    assert items[-1] is no_date  # least urgent

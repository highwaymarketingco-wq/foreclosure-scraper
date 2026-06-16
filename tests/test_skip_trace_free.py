"""Free skip tracing — owner + mailing address from county GIS (reliable),
plus best-effort people-search phone (stealth).

Owner ask: replicate the paid tools' skip tracing for free. The reliable
core is the tax-assessor owner name + mailing address we already pull via
GIS; absentee owners (mailing != property) are the motivated-seller signal.
A field-name mismatch had this returning 0 — this pins the fix.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.enrichment_skip_trace import (
    FreeProvider,
    TaxRecordsOnlyProvider,
    _resolve_provider,
)
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _li(gis=None, **kw):
    base = dict(
        source="t", source_url="x", listing_type=ListingType.FORECLOSURE_SALE,
        property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Burke",
        street_address="123 Main St", first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
    )
    base.update(kw)
    li = Listing(**base)
    if gis is not None:
        li.raw = {"gis": gis}
    return li


def test_reads_gis_mailing_and_owner_keys():
    """Regression: provider must read gis['mailing']/gis['owner'] (the keys
    enrichment_arcgis actually writes), not the old *_address aliases."""
    li = _li(gis={"owner": "SMITH JOHN", "mailing": "999 Far Away Rd"})
    r = asyncio.run(TaxRecordsOnlyProvider().lookup(li))
    assert r is not None
    assert r["owner_name"] == "SMITH JOHN"
    assert r["owner_mailing_address"] == "999 Far Away Rd"


def test_absentee_owner_flagged_when_mailing_differs():
    li = _li(gis={"owner": "SMITH JOHN", "mailing": "999 Far Away Rd"},
             street_address="123 Main St")
    r = asyncio.run(TaxRecordsOnlyProvider().lookup(li))
    assert r["absentee_owner"] is True
    assert r["confidence"] == "medium"


def test_owner_occupant_not_flagged_absentee():
    li = _li(gis={"owner": "SMITH JOHN", "mailing": "123 Main St"},
             street_address="123 Main St")
    r = asyncio.run(TaxRecordsOnlyProvider().lookup(li))
    assert r["absentee_owner"] is False


def test_returns_none_without_gis_owner():
    li = _li(gis={})
    li.defendant = None
    assert asyncio.run(TaxRecordsOnlyProvider().lookup(li)) is None


def test_free_provider_selected_by_env(monkeypatch):
    monkeypatch.setenv("SKIP_TRACE_PROVIDER", "free")
    assert _resolve_provider().name == "free"


def test_free_provider_returns_tax_record_without_phone_attempt():
    """With no defendant/city, FreeProvider still returns the reliable
    tax-records owner data and skips the phone lookup."""
    li = _li(gis={"owner": "SMITH JOHN", "mailing": "999 Far Away Rd"})
    li.defendant = None
    r = asyncio.run(FreeProvider().lookup(li))
    assert r is not None and r["owner_name"] == "SMITH JOHN"
    assert r["phone_numbers"] == []

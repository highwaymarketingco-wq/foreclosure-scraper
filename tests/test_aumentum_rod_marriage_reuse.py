"""Buncombe marriage-license reuse (gap-sweep wave 3, 2026-10-16).

enrichment_marriage_license.py (retired 2026-10-09) documented that Buncombe's Aumentum
grid carries marriage records as a plain doc_type ("MARRIED") right alongside deeds and
liens in the SAME name-search enrichment_aumentum_rod.py already runs for raw['rod'] --
but that module silently discarded them. This reuses the retired module's own pure
helpers (_is_marriage_doc/_spouse_from_doc) against the fetch aumentum_rod.py already
makes, at zero extra network cost.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from foreclosure_scraper import enrichment_aumentum_rod as AR
from foreclosure_scraper.models import Listing
from foreclosure_scraper.rod.models import RodDoc


def _li(owner="SMITH, JOHN", county="Buncombe", raw=None):
    return Listing(source="test", source_url="https://x.test/1", state="NC", county=county,
                   owner_name=owner, raw=raw or {})


def _doc(doc_type, grantor, grantee, book="100", page="1", recorded=None):
    return RodDoc(county="Buncombe", state="NC", doc_type=doc_type,
                  recorded_date=recorded or datetime(2026, 5, 1, tzinfo=timezone.utc),
                  book=book, page=page, grantor=grantor, grantee=grantee)


def test_a_marriage_record_among_the_owners_own_rows_is_extracted(monkeypatch):
    docs = [
        _doc("DEED OF TRUST", "SMITH, JOHN", "BANK OF AMERICA"),
        _doc("MARRIED", "SMITH, JOHN", "DOE, JANE"),
    ]
    monkeypatch.setattr(AR.aumentum, "search_by_name", lambda *a, **kw: _fut(docs))

    li = _li()
    asyncio.run(AR.enrich_aumentum_rod([li]))

    ml = li.raw["marriage_license"]
    assert ml["spouse_name"] == "Doe, Jane"
    assert ml["source"] == "aumentum_rod"
    assert ml["book"] == "100" and ml["page"] == "1"


def test_no_marriage_record_writes_a_confirmed_no_match_not_silence(monkeypatch):
    docs = [_doc("DEED OF TRUST", "SMITH, JOHN", "BANK OF AMERICA")]
    monkeypatch.setattr(AR.aumentum, "search_by_name", lambda *a, **kw: _fut(docs))

    li = _li()
    asyncio.run(AR.enrich_aumentum_rod([li]))

    assert li.raw["marriage_license"] == {
        "status": "no_match",
        "checked_at": li.raw["marriage_license"]["checked_at"],
    }


def test_a_failed_fetch_leaves_marriage_license_unstamped_for_retry(monkeypatch):
    monkeypatch.setattr(AR.aumentum, "search_by_name", lambda *a, **kw: _fut([]))

    li = _li()
    asyncio.run(AR.enrich_aumentum_rod([li]))

    assert "marriage_license" not in li.raw
    assert "rod" not in li.raw   # the existing fetch-failed path also leaves raw['rod'] untouched


def test_an_existing_marriage_license_value_is_never_overwritten(monkeypatch):
    docs = [_doc("MARRIED", "SMITH, JOHN", "DOE, JANE")]
    monkeypatch.setattr(AR.aumentum, "search_by_name", lambda *a, **kw: _fut(docs))

    existing = {"status": "no_match", "checked_at": "2020-01-01T00:00:00+00:00"}
    li = _li(raw={"marriage_license": dict(existing)})
    asyncio.run(AR.enrich_aumentum_rod([li]))

    assert li.raw["marriage_license"] == existing


def test_a_marriage_record_for_someone_else_in_the_grid_is_not_mistaken_for_the_owners(monkeypatch):
    """The search is surname-broad: a marriage doc naming a DIFFERENT SMITH must not be
    picked up for this owner just because it shares the doc_type."""
    docs = [_doc("MARRIED", "SMITH, ROBERT", "JONES, AMY")]
    monkeypatch.setattr(AR.aumentum, "search_by_name", lambda *a, **kw: _fut(docs))

    li = _li(owner="SMITH, JOHN")
    asyncio.run(AR.enrich_aumentum_rod([li]))

    # ROBERT's marriage doesn't name JOHN at all, so _owner_doc already filters it out of
    # `mine` -- confirmed no-match, not a false positive borrowed from a namesake.
    assert li.raw["marriage_license"]["status"] == "no_match"


async def _fut(value):
    return value

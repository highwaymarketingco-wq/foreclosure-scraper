"""A generic (non-pinned) NC county layer's owner query must use the REAL
detected field name, not the None placeholder _endpoint_cfg seeds it with.

REGRESSION, found live 2026-10-16 (py-spy + log grep on the Oracle VM's overnight
run, phase name_resolve): Mecklenburg/Brunswick/Onslow/Lincoln (and, structurally,
every other non-pinned NC county) were being sent the literal query
`UPPER(None) LIKE '%SURNAME%'` against their own ArcGIS layer -- a guaranteed
zero-row no-op on every single lead, silently, since this resolver chain was
built. enrich_resolve_name_to_property's loop resolves the real owner_field /
situs_field into LOCAL variables and correctly gates on them (`if not
owner_field: continue`), but then passed the untouched `cfg` dict (still
carrying owner_field=None from _endpoint_cfg) into _candidate_rows ->
_query_owner_scoped, which reads the field name straight back off `cfg`, not the
resolved locals. The fix: rebind `cfg` with the resolved fields before using it
for anything else in the loop body.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import foreclosure_scraper.enrichment_resolve_name_to_property as resolver
from foreclosure_scraper.models import Listing, ListingType


def _lead(**kw: Any) -> Listing:
    base = dict(
        source="ecourts", listing_type=ListingType.FORECLOSURE_SALE,
        source_url="https://example.invalid/case/1",
        state="NC", county="Mecklenburg", owner_name="Jane Q Smith",
    )
    base.update(kw)
    return Listing(**base)


class _Resp:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttp:
    """Answers every GET with empty features (and a clean health check) by
    default, and records every request so the test can inspect what was
    actually sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None,
                  timeout: float | None = None) -> _Resp:
        params = dict(params or {})
        self.calls.append((url, params))
        if params.get("f") == "json" and "where" not in params:
            return _Resp({"fields": [{"name": "irrelevant"}]})   # health check
        return _Resp({"features": []})


def _patch_client(monkeypatch, http: "_FakeHttp") -> None:
    @asynccontextmanager
    async def fake_client(*a, **kw):
        yield http
    monkeypatch.setattr(resolver, "client", fake_client)


def test_the_live_query_names_the_real_field_not_the_literal_none(monkeypatch):
    http = _FakeHttp()
    _patch_client(monkeypatch, http)

    async def fake_resolve_fields(c, base):
        return "OwnerName", "SiteAddress"
    monkeypatch.setattr(resolver, "_resolve_fields", fake_resolve_fields)

    lead = _lead()
    mecklenburg_url = ("https://meckgis.mecklenburgcountync.gov/server/rest/services/"
                        "TaxParcel_Camaownershipvalues/FeatureServer/0/query")
    assert any(c["base"] == mecklenburg_url for c in resolver._endpoint_plan(lead)), (
        "test fixture drifted from the real NC_GIS entry for Mecklenburg")

    asyncio.run(resolver.enrich_resolve_name_to_property([lead]))

    owner_queries = [p for u, p in http.calls if u == mecklenburg_url and "where" in p]
    assert owner_queries, "the Mecklenburg layer's own owner-search was never queried"
    for params in owner_queries:
        assert "None" not in params["where"], (
            f"query used the unresolved placeholder field: {params['where']!r}")
        assert "OwnerName" in params["where"]


def test_a_county_where_detection_itself_fails_still_bails_cleanly(monkeypatch):
    """The companion case: _resolve_fields finding nothing must still skip the
    query (no_owner_field), never fall through to a None-named query either."""
    http = _FakeHttp()
    _patch_client(monkeypatch, http)

    async def fake_resolve_fields(c, base):
        return None, None
    monkeypatch.setattr(resolver, "_resolve_fields", fake_resolve_fields)

    lead = _lead()
    stats = asyncio.run(resolver.enrich_resolve_name_to_property([lead]))

    mecklenburg_url = ("https://meckgis.mecklenburgcountync.gov/server/rest/services/"
                        "TaxParcel_Camaownershipvalues/FeatureServer/0/query")
    assert not any(u == mecklenburg_url and "where" in p for u, p in http.calls)
    assert stats["no_owner_field"] >= 1

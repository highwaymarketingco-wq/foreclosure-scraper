"""A broken tenant and an empty tenant must not look the same.

nc_ptscloud_delinquent_tax is the largest source on the board (21,463 rows).
_download_delinquent_csv had five bare `return None` exits and the caller did
`if not text: continue` with no log, so nine of the seventeen declared tenants
produced no trace at all and there was no way to tell "this county published no
delinquent export this week" from "this county's endpoint broke".

Live probe 2026-08-04 of all 17: 8 producing, 9 empty, 0 broken. So the data was
in fact intact — which is exactly the situation in which a silent hole is most
dangerous, because nothing looks wrong until the week one of the eight dies.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from foreclosure_scraper.scrapers.counties_nc.nc_ptscloud_delinquent_tax import (
    TENANTS,
    TenantExportBroken,
    _download_delinquent_csv,
)


def _resp(status=200, json_body=None, content=b""):
    r = MagicMock()
    r.status_code = status
    r.content = content
    if json_body is None:
        r.json = MagicMock(side_effect=ValueError("not json"))
    else:
        r.json = MagicMock(return_value=json_body)
    return r


def test_no_delinquent_blob_is_an_empty_answer_not_a_failure():
    """Verified live for Burke, Rutherford, Mecklenburg and six others: HTTP 200
    with a blob list that has no delinquent file. That is a real answer."""
    c = AsyncMock()
    c.get = AsyncMock(return_value=_resp(200, json_body=[{"blobName": "Bills_2026.csv"}]))
    assert asyncio.run(_download_delinquent_csv(c, "Burke")) is None


def test_list_endpoint_http_error_raises():
    c = AsyncMock()
    c.get = AsyncMock(return_value=_resp(500, json_body=[]))
    with pytest.raises(TenantExportBroken, match="list HTTP 500"):
        asyncio.run(_download_delinquent_csv(c, "Madison"))


def test_list_endpoint_non_json_raises():
    c = AsyncMock()
    c.get = AsyncMock(return_value=_resp(200, json_body=None))
    with pytest.raises(TenantExportBroken, match="not JSON"):
        asyncio.run(_download_delinquent_csv(c, "Madison"))


def test_transport_failure_raises_rather_than_reading_as_empty():
    c = AsyncMock()
    c.get = AsyncMock(side_effect=OSError("connection reset"))
    with pytest.raises(TenantExportBroken, match="list request failed"):
        asyncio.run(_download_delinquent_csv(c, "Madison"))


def test_blob_without_download_url_raises():
    """A delinquent blob that exists but yields no SAS URL is a break: the county
    IS publishing, we just failed to fetch it. Silently returning None here
    would erase a producing county."""
    calls = []

    async def get(url, **kw):
        calls.append(url)
        if "GetTaxpayerDownloadList" in url:
            return _resp(200, json_body=[{"blobName": "Delinquent_2026.csv"}])
        return _resp(200, json_body={})          # no downloadUrl

    c = AsyncMock()
    c.get = get
    with pytest.raises(TenantExportBroken, match="no downloadUrl"):
        asyncio.run(_download_delinquent_csv(c, "Madison"))


def test_download_http_error_raises():
    async def get(url, **kw):
        if "GetTaxpayerDownloadList" in url:
            return _resp(200, json_body=[{"blobName": "Delinquent_2026.csv"}])
        if "DownloadTaxpayerDownloadBlob" in url:
            return _resp(200, json_body={"downloadUrl": "https://blob.example/x y.csv?sig=a"})
        return _resp(403)

    c = AsyncMock()
    c.get = get
    with pytest.raises(TenantExportBroken, match="download HTTP 403"):
        asyncio.run(_download_delinquent_csv(c, "Madison"))


def test_happy_path_returns_decoded_csv_and_preserves_the_sas_query():
    """The SAS signature breaks if the query is re-encoded; only the path may
    be quoted. Pin that, it has bitten before."""
    seen = {}

    async def get(url, **kw):
        if "GetTaxpayerDownloadList" in url:
            return _resp(200, json_body=[{"blobName": "Delinquent_2026.csv"}])
        if "DownloadTaxpayerDownloadBlob" in url:
            return _resp(200, json_body={
                "downloadUrl": "https://blob.example/a b/Delinquent 2026.csv?sig=abc%2Fdef&se=2026"})
        seen["download"] = url
        return _resp(200, content="﻿PARCEL,OWNER\n1,SMITH\n".encode())

    c = AsyncMock()
    c.get = get
    text = asyncio.run(_download_delinquent_csv(c, "Madison"))
    assert text.startswith("PARCEL,OWNER"), "BOM not stripped"
    assert "sig=abc%2Fdef&se=2026" in seen["download"], "SAS query was re-encoded"
    assert "%20" in seen["download"], "spaces in the blob path were not quoted"


def test_every_declared_tenant_is_guarded():
    """The guard's declared set must be the tenant list itself — a tenant that
    silently stops being harvested is the failure this closes."""
    assert len(TENANTS) == 17
    assert len(set(TENANTS)) == len(TENANTS), "duplicate tenant keys"


# ---------------------------------------------------------------------------
# fetch() itself. The helper tests above all passed while fetch() raised
# TypeError on its first line: LayerHarvest is a SYNC context manager and it had
# been put in the `async with` header. Testing only the helpers of a scraper is
# how you ship a source that cannot run at all.
# ---------------------------------------------------------------------------

def _fake_client(handler):
    """Patch http_client.client with an async CM yielding a stub with .get."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _cm(*a, **kw):
        stub = MagicMock()
        stub.get = handler
        yield stub
    return _cm


def test_fetch_runs_and_harvests_every_tenant(monkeypatch):
    import foreclosure_scraper.scrapers.counties_nc.nc_ptscloud_delinquent_tax as M

    async def get(url, **kw):
        if "GetTaxpayerDownloadList" in url:
            return _resp(200, json_body=[{"blobName": "Bills.csv"}])   # empty everywhere
        raise AssertionError("should not reach download for an empty tenant")

    monkeypatch.setattr(M, "client", _fake_client(get))
    rows = asyncio.run(M.NCPtsCloudDelinquentTax().fetch())
    assert list(rows) == [], "no tenant publishes a delinquent blob in this fixture"


def test_fetch_hard_fails_when_a_declared_tenant_breaks(monkeypatch):
    """The whole point of the guard: one broken tenant must raise, not shrink
    the number quietly."""
    import foreclosure_scraper.scrapers.counties_nc.nc_ptscloud_delinquent_tax as M
    from foreclosure_scraper.layer_guard import PartialHarvest

    async def get(url, **kw):
        if "GetTaxpayerDownloadList" in url:
            if kw.get("headers", {}).get("X-Tenant") == "Guilford":
                return _resp(503, json_body=[])
            return _resp(200, json_body=[{"blobName": "Bills.csv"}])
        raise AssertionError("unexpected download")

    monkeypatch.setattr(M, "client", _fake_client(get))
    with pytest.raises(PartialHarvest):
        asyncio.run(M.NCPtsCloudDelinquentTax().fetch())

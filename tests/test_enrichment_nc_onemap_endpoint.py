"""enrichment_nc_onemap: the parcel point query goes to the live statewide layer (the old
NC_Parcels MapServer answers 404), asks for named fields only (no legal description, never *), and
drops identifier columns. Canned responses, made-up values; no network."""
import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper import enrichment_nc_onemap as om
from foreclosure_scraper.models import Listing


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Client:
    def __init__(self, calls):
        self.calls = calls

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if url == om.PARCEL_URL:
            return _Resp(200, {"features": [{"attributes": {
                "parno": "0000-11-2222", "cntyname": "Testcounty", "ownname": "TESTER ANNA",
                "siteadd": "12 EXAMPLE RIDGE RD", "parval": 52000.0, "TCSSN1": "000-00-0000"}}]})
        return _Resp(404, {})


def test_parcel_url_is_the_live_feature_service():
    assert om.PARCEL_URL == ("https://services.nconemap.gov/secure/rest/services/"
                             "NC1Map_Parcels/FeatureServer/1/query")
    assert "NC_Parcels/MapServer" not in om.PARCEL_URL


def test_point_query_names_its_fields_and_drops_identifiers(monkeypatch):
    calls = []

    @asynccontextmanager
    async def fake_client(timeout=30.0, **kw):
        yield _Client(calls)

    monkeypatch.setattr(om, "client", fake_client)
    li = Listing(source="test", source_url="https://example.invalid/1", state="NC", county="Testcounty",
                 latitude=35.5, longitude=-82.5)
    out = asyncio.run(om.enrich_nc_onemap(li))
    parcel_call = [c for c in calls if c[0] == om.PARCEL_URL][0][1]
    fields = parcel_call["outFields"].split(",")
    assert "*" not in fields and "legdecfull" not in fields and "sourceref" not in fields
    assert {"parno", "ownname", "siteadd", "parval"} <= set(fields)
    assert parcel_call["geometry"] == "-82.5,35.5" and parcel_call["inSR"] == "4326"
    parcel = out.raw["nc_onemap"]["parcel"]
    assert parcel["parno"] == "0000-11-2222" and "TCSSN1" not in parcel
    assert "floodplain" not in out.raw["nc_onemap"] and "zoning" not in out.raw["nc_onemap"]

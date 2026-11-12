"""GIS-attrs persistent parcel cache: a cache hit reuses attrs with NO network."""
import asyncio
from datetime import datetime

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper import enrichment_gis_attrs as g


def _li(parcel=None, lat=None, lng=None, county="Spartanburg", state="SC"):
    now = datetime.utcnow()
    return Listing(source="s", source_url="https://x/1", listing_type=ListingType.TAX_LIEN,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, latitude=lat, longitude=lng,
                   first_seen=now, last_seen=now, raw={})


def test_cache_key_parcel_and_point():
    assert g._cache_key(_li(parcel="1-23-45")) == "SC|Spartanburg|P:12345"
    k = g._cache_key(_li(lat=34.949, lng=-81.932))
    assert k.startswith("SC|Spartanburg|G:34.949")


def test_cache_hit_applies_attrs_without_network(monkeypatch):
    # Prime the cache; then enrich must NOT hit the network for that parcel.
    g._ATTR_CACHE.clear()
    g._CACHE_LOADED = True  # skip disk load
    monkeypatch.setattr(g, "_CACHE_ON", False)  # don't persist during test
    key = "SC|Spartanburg|P:99999"
    g._ATTR_CACHE[key] = {"MARKET_VALUE": 250000, "OWNER": "DOE JANE"}

    async def _boom(*a, **k):
        raise AssertionError("network GIS query called despite cache hit")
    monkeypatch.setattr(g, "_query_point", _boom)
    monkeypatch.setattr(g, "_query_parcel", _boom)

    li = _li(parcel="99999", lat=34.9, lng=-81.9)
    stats = asyncio.run(g.enrich_gis_attrs([li]))
    assert stats["cache_hit"] == 1
    assert (li.raw.get("gis") or {}).get("queried") is True

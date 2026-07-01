import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match, _load
import foreclosure_scraper.enrichment_buyer_match as _bm


@pytest.fixture(autouse=True)
def _enable_buyer_match(monkeypatch):
    # Production gates the server-side tagger OFF (the dashboard matches
    # client-side); enable it here to exercise the matching logic directly.
    monkeypatch.setattr(_bm, "_ENABLED", True)


def _li(**kw):
    base=dict(source="s",source_url="x",listing_type=ListingType.TAX_LIEN,state="NC",county="Polk")
    base.update(kw); return Listing(**base)

def test_registry_loads():
    assert len(_load()) > 100  # 188 buyers

def test_land_gets_many_types():
    li=_li(property_kind=PropertyKind.LAND)
    enrich_buyer_match([li])
    bm=li.raw["buyer_match"]
    assert bm["category"]=="land"
    # land pulls developers, builders, timber, solar, conservation, flippers...
    assert len(bm["by_type"]) >= 5
    assert "land_flippers" in bm["by_type"]
    assert bm["count"] >= 10

def test_region_gate_upstate_vs_wnc():
    li=_li(state="SC", county="Greenville", property_kind=PropertyKind.LAND)
    enrich_buyer_match([li])
    assert li.raw["buyer_match"]["count"] >= 10

def test_out_of_footprint_skipped():
    li=_li(county="Wake")  # not in footprint
    enrich_buyer_match([li])
    assert "buyer_match" not in (li.raw or {})

def test_i85_land_gets_industrial():
    li=_li(state="SC", county="Spartanburg", property_kind=PropertyKind.LAND)
    enrich_buyer_match([li])
    assert "industrial_logistics" in li.raw["buyer_match"]["by_type"]

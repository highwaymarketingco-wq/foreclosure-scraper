from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_buyer_match import enrich_buyer_match

def _li(**kw):
    base=dict(source="s",source_url="x",listing_type=ListingType.TAX_LIEN,state="NC",county="Polk")
    base.update(kw); return Listing(**base)

def test_land_gets_blanket_buyers():
    li=_li(property_kind=PropertyKind.LAND)
    enrich_buyer_match([li])
    bm=li.raw["buyer_match"]; names=[x["name"] for x in bm["land"]]
    assert "Bubba Land Company" in names and "Value Land Buyers" in names

def test_bubba_respects_3ac_min():
    li=_li(property_kind=PropertyKind.LAND); li.raw={"lrcpwa":{"acreage":1.0}}
    enrich_buyer_match([li])
    names=[x["name"] for x in li.raw["buyer_match"]["land"]]
    assert "Bubba Land Company" not in names  # 1 acre < 3 min
    assert "Value Land Buyers" in names       # no min

def test_upstate_regional_and_builders_by_county():
    li=_li(state="SC", county="Greenville", property_kind=PropertyKind.LAND)
    enrich_buyer_match([li])
    bm=li.raw["buyer_match"]
    assert any("Greenville Home Solutions" in x["name"] for x in bm["land"])
    assert bm.get("builders")

def test_distressed_house_gets_cash_buyers():
    li=_li(county="Buncombe"); li.raw={"distress_stack":{"tier":"HOT"}}
    enrich_buyer_match([li])
    assert li.raw["buyer_match"].get("houses")

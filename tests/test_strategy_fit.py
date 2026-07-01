from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit

def _li(**kw):
    base=dict(source="s",source_url="x",listing_type=ListingType.TAX_LIEN,state="NC",county="Polk")
    base.update(kw); return Listing(**base)

def test_land_wholesale():
    li=_li(property_kind=PropertyKind.LAND); li.raw={"tax_owed":{"balance":5000}}
    enrich_strategy_fit([li])
    assert "LAND_WHOLESALE" in li.raw["strategy_fit"]["tags"]
    assert "GATOR" in li.raw["strategy_fit"]["tags"]

def test_wholesale_needs_equity_not_blank():
    # residential + distress but NO equity/tenure -> should NOT tag wholesale
    li=_li(); li.raw={"distress_stack":{"tier":"HOT"}}
    enrich_strategy_fit([li])
    assert "strategy_fit" not in li.raw or "WHOLESALE" not in li.raw.get("strategy_fit",{}).get("tags",[])

def test_wholesale_with_long_tenure_proxy():
    li=_li(); li.raw={"distress_stack":{"tier":"WARM","signals":["auction"]},"tenure":{"long_tenure":True}}
    enrich_strategy_fit([li])
    assert "WHOLESALE" in li.raw["strategy_fit"]["tags"]

def test_subject_to_low_equity_foreclosure():
    li=_li(listing_type=ListingType.LIS_PENDENS); li.raw={"equity":{"pct":0.10},"distress_stack":{"tier":"HOT"}}
    enrich_strategy_fit([li])
    assert "SUBJECT_TO" in li.raw["strategy_fit"]["tags"]

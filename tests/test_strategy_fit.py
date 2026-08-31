from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit

def _li(**kw):
    base=dict(source="s",source_url="x",listing_type=ListingType.TAX_LIEN,state="NC",county="Polk")
    base.update(kw); return Listing(**base)

def test_land_wholesale():
    li=_li(property_kind=PropertyKind.LAND); li.raw={"tax_owed":{"balance":5000}}
    enrich_strategy_fit([li])
    tags=li.raw["strategy_fit"]["tags"]
    assert "LAND_WHOLESALE" in tags
    # GATOR was retired product-wide (commit 0cff20d); the emitter must not re-add it.
    assert "GATOR" not in tags

def test_wholesale_needs_equity_not_blank():
    # residential + distress but NO equity/tenure -> should NOT tag wholesale
    li=_li(); li.raw={"distress_stack":{"tier":"HOT"}}
    enrich_strategy_fit([li])
    assert "strategy_fit" not in li.raw or "WHOLESALE" not in li.raw.get("strategy_fit",{}).get("tags",[])

def test_long_tenure_proxy_drives_fix_flip():
    # WHOLESALE was retired (commit 0cff20d). Long tenure still stands in for equity,
    # so a rough-condition residential lead with no computed equity % should now fit
    # FIX_FLIP via the tenure proxy — and must NOT carry the retired WHOLESALE tag.
    li=_li(); li.raw={"condition_tier":"gut","distress_stack":{"tier":"WARM","signals":["auction"]},"tenure":{"long_tenure":True}}
    enrich_strategy_fit([li])
    tags=li.raw["strategy_fit"]["tags"]
    assert "FIX_FLIP" in tags
    assert "WHOLESALE" not in tags

def test_low_equity_foreclosure_no_subject_to():
    # SUBJECT_TO was retired (commit 0cff20d). A low-equity residential foreclosure
    # no longer matches any current strategy (not land, not rough condition), so it
    # should get no strategy_fit at all — and definitely no SUBJECT_TO tag.
    li=_li(listing_type=ListingType.LIS_PENDENS); li.raw={"equity":{"pct":0.10},"distress_stack":{"tier":"HOT"}}
    enrich_strategy_fit([li])
    assert "strategy_fit" not in li.raw or "SUBJECT_TO" not in li.raw["strategy_fit"]["tags"]

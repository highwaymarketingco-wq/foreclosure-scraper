"""national.fannie_homepath: RAW_KEEP parity fix, batch 18 (2026-10-04).

Batch 17 found and fixed this exact bug on the sibling
national.homepath_json (commit c81124b6): bedrooms/bathrooms/sqft/
year_built/mls_id/property_uuid/retail_status/online_offer_only/first_look
were all flat top-level keys in `raw`, and none of them were registered in
web_artifact.RAW_KEEP -- a direct _slim_raw() round-trip confirmed only
`reo_id`/`images` survived publish. fannie_homepath.py's raw dict was
line-for-line the identical shape (minus property_uuid, added here for
completeness) with the identical gap, confirmed by reading the module and
by a live fetch of the real API 2026-10-04 (a real current Waynesville, NC
/ Haywood County row carries bedrooms=3.0, bathrooms=5.0, sqft=3531,
yearBuilt=2005 -- all genuinely populated, all previously dropped).

Fixed with the exact same pattern: promote bedrooms/bathrooms/sqft/
year_built to first-class Listing kwargs (always serialized, sidesteps
RAW_KEEP entirely); namespace the rest under a new registered
"fannie_homepath" RAW_KEEP key.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national import fannie_homepath as m
from foreclosure_scraper.web_artifact import RAW_KEEP, _slim_raw


def _rich_prop(uuid: str = "rich-1") -> dict:
    return {
        "propertyUuid": uuid,
        "reoId": "R999",
        "mlsId": "M888",
        "addressLine1": "1 Test St",
        "city": "Weaverville",
        "state": "NC",
        "zipCode": "28787",
        "county": "BUNCOMBE COUNTY",
        "propertyType": "Single Family",
        "bedrooms": 3,
        "bathrooms": 2,
        "sqft": 1800,
        "yearBuilt": 2001,
        "price": 250000,
        "retailStatus": "Price Reduced",
        "onlineOfferOnly": True,
        "firstLookProgramIndicator": True,
        "primHiResImageUrl": "https://homepath.fanniemae.com/images/x.jpg",
    }


def test_bedrooms_bathrooms_sqft_year_built_are_first_class_listing_fields():
    """Real Listing-model fields (see web_artifact._SLIM_TOP) must be set
    directly, not buried in `raw` where they'd need a RAW_KEEP entry that
    never existed for this scraper."""
    li = m._to_listing(_rich_prop(), m.FannieHomePath.slug)
    assert li is not None
    assert li.bedrooms == 3.0
    assert li.bathrooms == 2.0
    assert li.living_sqft == 1800.0
    assert li.year_built == 2001


def test_remaining_fields_namespaced_under_registered_fannie_homepath_key():
    li = m._to_listing(_rich_prop(), m.FannieHomePath.slug)
    fh = li.raw["fannie_homepath"]
    assert fh["mls_id"] == "M888"
    assert fh["property_uuid"] == "rich-1"
    assert fh["retail_status"] == "Price Reduced"
    assert fh["online_offer_only"] is True
    assert fh["first_look"] is True
    # reo_id/images stay flat (pre-existing, already-registered convention).
    assert li.raw["reo_id"] == "R999"


def test_fannie_homepath_key_registered_in_raw_keep():
    assert "fannie_homepath" in RAW_KEEP


def test_raw_fields_survive_slim_raw_round_trip():
    """Direct regression pin for the silent-drop bug this batch found --
    every field _to_listing stuffs into raw must still be present after
    web_artifact._slim_raw() (the real publish-time filter)."""
    li = m._to_listing(_rich_prop(), m.FannieHomePath.slug)
    slim = _slim_raw(li.raw)
    assert slim.get("fannie_homepath") == li.raw["fannie_homepath"]
    assert slim.get("reo_id") == "R999"


def test_missing_year_built_does_not_crash():
    p = _rich_prop()
    p["yearBuilt"] = None
    li = m._to_listing(p, m.FannieHomePath.slug)
    assert li is not None
    assert li.year_built is None


def test_zero_bedrooms_bathrooms_sqft_normalize_to_none():
    """_safe_float treats 0 as missing (matches homepath_json's convention),
    not a real zero-bedroom/zero-sqft property."""
    p = _rich_prop()
    p["bedrooms"] = 0
    p["bathrooms"] = 0
    p["sqft"] = 0
    li = m._to_listing(p, m.FannieHomePath.slug)
    assert li is not None
    assert li.bedrooms is None
    assert li.bathrooms is None
    assert li.living_sqft is None

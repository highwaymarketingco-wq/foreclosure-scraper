"""auction_dot_com.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4) after finding the JSON-LD `address.addressLocality` field is
actually the COUNTY name, not the city -- verified live against every row
on both NC/SC state pages (e.g. `addressLocality: "Gaston"` for a Bessemer
City, NC property). `city` was silently wrong on every enriched row, and
`county` (a real Listing field) was never populated at all. The node's
`name` field carries the correct full line instead:
"<street> <City>, <ST> <ZIP>, <County> County"."""
from foreclosure_scraper.scrapers.national.auction_dot_com import (
    _node_listing,
    _parse_name_city_county,
    _split_slug_address,
)

# Live-captured JSON-LD node (2026-10-01).
_NODE_MIXED_CASE_STREET = {
    "name": "2003 Plain Field Dr Bessemer City, NC 28016, Gaston County",
    "description": "Unavailable",
    "numberOfBedrooms": 4,
    "numberOfBathroomsTotal": 3,
    "yearBuilt": 2026,
    "floorSize": {"value": 2, "unitCode": "FTK"},
    "address": {
        "addressCountry": "US",
        "addressLocality": "Gaston",
        "addressRegion": "NC",
        "postalCode": "28016",
        "streetAddress": "2003 Plain Field Dr",
    },
    "url": "https://www.auction.com/details/2003-plain-field-dr-bessemer-city-nc-2197585",
    "geo": {"latitude": 35.3298387, "longitude": -81.2897935},
}

# Live-captured node where address.streetAddress is ALL CAPS but name's
# street portion is title-case -- the prefix-strip must be case-insensitive.
_NODE_CAPS_STREET = {
    "name": "135 Connie Lane Beaufort, NC 28516, Carteret County",
    "address": {
        "addressLocality": "Carteret",
        "addressRegion": "NC",
        "postalCode": "28516",
        "streetAddress": "135 CONNIE LANE",
    },
}


def test_parse_name_city_county_recovers_both_from_name():
    city, county = _parse_name_city_county(
        "2003 Plain Field Dr Bessemer City, NC 28016, Gaston County",
        "2003 Plain Field Dr",
    )
    assert city == "Bessemer City"
    assert county == "Gaston"


def test_parse_name_city_county_is_case_insensitive_on_street_prefix():
    city, county = _parse_name_city_county(
        "135 Connie Lane Beaufort, NC 28516, Carteret County",
        "135 CONNIE LANE",
    )
    assert city == "Beaufort"
    assert county == "Carteret"


def test_parse_name_city_county_returns_none_on_unmatched_shape():
    assert _parse_name_city_county("not a real address line", "123 Main St") == (None, None)
    assert _parse_name_city_county(None, "123 Main St") == (None, None)


def test_node_listing_uses_real_city_not_addresslocality_county():
    li = _node_listing("2197585", "2003-plain-field-dr-bessemer-city", "NC", _NODE_MIXED_CASE_STREET)
    assert li is not None
    # The bug: addressLocality says "Gaston" (the county) -- city must NOT be that.
    assert li.city == "Bessemer City"
    assert li.county == "Gaston"
    assert li.street_address == "2003 Plain Field Dr"
    assert li.zip_code == "28016"


def test_node_listing_caps_street_still_resolves_city_and_county():
    li = _node_listing("2148364", "135-connie-ln-beaufort", "NC", _NODE_CAPS_STREET)
    assert li is not None
    assert li.city == "Beaufort"
    assert li.county == "Carteret"


def test_node_listing_falls_back_to_slug_when_node_absent():
    li = _node_listing("2045737", "1402-tom-pepper-rd-creswell", "NC", None)
    assert li is not None
    assert li.county is None  # Creswell isn't in the in-footprint/metro gazetteer
    assert li.city == "Creswell"


# ---------------------------------------------------------------------------
# FIX 2026-10-04: multi-word city names in the slug fallback path (the
# MAJORITY case -- only ~50 of ~510 statewide rows get a JSON-LD node per
# the module's own 2026-06-24 capture-model note). Live-verified real
# in-footprint example: "165-fernwood-dr-forest-city" is a real current NC
# listing in Forest City, Rutherford County -- the old last-token-only split
# produced city="City".
# ---------------------------------------------------------------------------

def test_split_slug_address_recognizes_known_multiword_city():
    street, city = _split_slug_address("165-fernwood-dr-forest-city")
    assert street == "165 Fernwood Dr"
    assert city == "Forest City"


def test_split_slug_address_recognizes_another_known_multiword_city():
    street, city = _split_slug_address("152-scotland-ridge-dr-winston-salem")
    assert street == "152 Scotland Ridge Dr"
    assert city == "Winston Salem"


def test_split_slug_address_falls_back_to_last_token_for_unknown_city():
    """A multi-word city NOT in the gazetteer (out-of-footprint, uncommon)
    still falls back to the old last-token heuristic -- best-effort, not a
    regression, since these rows get filtered out by county scope anyway."""
    street, city = _split_slug_address("305-woodpecker-pkwy-rocky-point")
    assert city == "Point"
    assert street == "305 Woodpecker Pkwy Rocky"


def test_split_slug_address_single_word_city_unaffected():
    street, city = _split_slug_address("1402-tom-pepper-rd-creswell")
    assert street == "1402 Tom Pepper Rd"
    assert city == "Creswell"


def test_node_listing_backfills_county_from_known_city_in_fallback_path():
    """Fallback rows (no JSON-LD) never got a county at all before -- now
    that the slug-derived city is accurate, back it with the same
    gazetteer scrapers.national.crexi_multifamily uses."""
    li = _node_listing("2159527", "165-fernwood-dr-forest-city", "NC", None)
    assert li is not None
    assert li.city == "Forest City"
    assert li.county == "Rutherford"

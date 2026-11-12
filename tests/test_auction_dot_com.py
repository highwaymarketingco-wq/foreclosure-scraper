"""auction_dot_com.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4) after finding the JSON-LD `address.addressLocality` field is
actually the COUNTY name, not the city -- verified live against every row
on both NC/SC state pages (e.g. `addressLocality: "Gaston"` for a Bessemer
City, NC property). `city` was silently wrong on every enriched row, and
`county` (a real Listing field) was never populated at all. The node's
`name` field carries the correct full line instead:
"<street> <City>, <ST> <ZIP>, <County> County"."""
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.national.auction_dot_com import (
    REO_URL_SUFFIX,
    REO_URLS,
    URLS,
    _extract_page,
    _ltype_from_status,
    _node_listing,
    _parse_name_city_county,
    _split_slug_address,
    _status_index,
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


# ---------------------------------------------------------------------------
# FIX 2026-10-04 (REO-liveness audit): every row was hardcoded
# ListingType.AUCTION -- `_ltype_from_status` existed but was never called.
# Live-verified (real browser render against auction.com, 2026-10-04) that
# each rendered card carries its own status in a
# `data-elm-id="asset-info-asset_<id>"` block whose child `<img alt="...">`
# reads "Bank Owned" or "Foreclosure Sale" verbatim. The HTML fragments below
# are real captured markup from https://www.auction.com/residential/nc/
# (ids 2185639 "Bank Owned" / 2139335 "Foreclosure Sale") -- the `<img>`'s
# `src` data-URI (a multi-KB base64 SVG in the live page) is elided since
# it's irrelevant to the parsing logic; everything else, including tag
# order and attribute names, is the real captured shape.
# ---------------------------------------------------------------------------

_CARD_HTML_BANK_OWNED = (
    '<div data-elm-id="asset_2185639_root" data-position="0" class="q__asset-root--VmozO">'
    '<div class="styles__root--k0hIz">'
    '<a href="/details/181-booth-ln-richlands-nc-2185639" class="styles__card-link--pHDnC" '
    'target="_blank" rel="noopener noreferrer">'
    '<div class="styles__base-card--aZR7x" data-elm-id="property_card_asset_2185639">'
    '<h3 data-elm-id="address_line_asset_2185639" '
    'class="styles__text--YqNdS cardPartsStyles__property-address-line--SHW3X">'
    '181 Booth Lane, Richlands, NC 28574</h3>'
    '<div class="cardPartsStyles__listing-indicator-row--vyfs8">'
    '<div data-elm-id="asset-info-asset_2185639" '
    'class="styles__asset-info--AQgpK cardPartsStyles__asset-info--i04ie listing-card-asset-info">'
    '<img src="data:image/svg+xml;base64,ELIDED" class="styles__info-dot--qtzr4" alt="Bank Owned">'
    '<div>Bank Owned</div></div></div></div></a></div></div>'
)

_CARD_HTML_FORECLOSURE_SALE = (
    '<div data-elm-id="asset_2139335_root" data-position="3" class="q__asset-root--VmozO">'
    '<div class="styles__root--k0hIz">'
    '<a href="/details/1442-carnsmore-dr-fayetteville-nc-2139335" class="styles__card-link--pHDnC" '
    'target="_blank" rel="noopener noreferrer">'
    '<div class="styles__base-card--aZR7x" data-elm-id="property_card_asset_2139335">'
    '<h3 data-elm-id="address_line_asset_2139335" '
    'class="styles__text--YqNdS cardPartsStyles__property-address-line--SHW3X">'
    '1442 Carnsmore Drive, Fayetteville, NC 28304</h3>'
    '<div class="cardPartsStyles__listing-indicator-row--vyfs8">'
    '<div data-elm-id="asset-info-asset_2139335" '
    'class="styles__asset-info--AQgpK cardPartsStyles__asset-info--i04ie listing-card-asset-info">'
    '<img src="data:image/svg+xml;base64,ELIDED" class="styles__info-dot--qtzr4" alt="Foreclosure Sale">'
    '<div>Foreclosure Sale</div></div></div></div></a></div></div>'
)

# A plain detail-link with NO asset-info badge block at all -- the realistic
# "off-screen, not yet hydrated" case (auction.com virtualizes the card
# list; see module docstring). _status_index must simply omit it rather
# than mis-tagging it, and _extract_page must default it to AUCTION.
_SLUG_ONLY_HTML = '<a href="/details/1402-tom-pepper-rd-creswell-nc-2045737">1402 Tom Pepper Rd</a>'


def test_status_index_recovers_real_badge_text_by_id():
    html = _CARD_HTML_BANK_OWNED + _CARD_HTML_FORECLOSURE_SALE + _SLUG_ONLY_HTML
    idx = _status_index(html)
    assert idx == {"2185639": "Bank Owned", "2139335": "Foreclosure Sale"}
    assert "2045737" not in idx  # no badge block -> not in the index at all


def test_ltype_from_status_classifies_real_badge_text():
    assert _ltype_from_status("Bank Owned") == ListingType.REO
    assert _ltype_from_status("Foreclosure Sale") == ListingType.FORECLOSURE_SALE
    assert _ltype_from_status("") == ListingType.AUCTION
    assert _ltype_from_status(None) == ListingType.AUCTION


def test_extract_page_tags_reo_and_foreclosure_sale_from_real_badges():
    """End-to-end: _extract_page must pick up _status_index's classification
    for cards that carry the badge, and fall back to the old AUCTION default
    for the slug-only card that doesn't (partial/best-effort, matching the
    JSON-LD index's existing "enrich where available" shape)."""
    html = _CARD_HTML_BANK_OWNED + _CARD_HTML_FORECLOSURE_SALE + _SLUG_ONLY_HTML
    rows = _extract_page(html, "NC")
    assert rows["2185639"].listing_type == ListingType.REO
    assert rows["2139335"].listing_type == ListingType.FORECLOSURE_SALE
    assert rows["2045737"].listing_type == ListingType.AUCTION


def test_node_listing_default_listing_type_is_still_auction():
    """Backward-compat: callers (and the dedicated REO-crossref path in
    fetch(), which only forces REO on an id match) that don't pass
    listing_type explicitly must keep getting the old hardcoded AUCTION."""
    li = _node_listing("2045737", "1402-tom-pepper-rd-creswell", "NC", None)
    assert li is not None
    assert li.listing_type == ListingType.AUCTION


# ---------------------------------------------------------------------------
# REO_URLS: live-verified 2026-10-04 by selecting auction.com's own
# "Listing Type" -> "REO Bank Owned" filter checkbox through the UI (NOT
# guessed) and reading the resulting URL. See module docstring for the full
# verification detail (result counts + sampled-card badge confirmation on
# both NC and SC).
# ---------------------------------------------------------------------------

def test_reo_urls_match_the_live_verified_pattern():
    assert REO_URL_SUFFIX == (
        "active_lt/resi_sort_v2_st/y_nbs/bank-owned,newly-foreclosed_at"
    )
    reo = dict(REO_URLS)
    assert reo["NC"] == (
        "https://www.auction.com/residential/nc/"
        "active_lt/resi_sort_v2_st/y_nbs/bank-owned,newly-foreclosed_at"
    )
    assert reo["SC"] == (
        "https://www.auction.com/residential/sc/"
        "active_lt/resi_sort_v2_st/y_nbs/bank-owned,newly-foreclosed_at"
    )
    # Every state in the regular URLS list must have a matching REO URL.
    assert set(dict(REO_URLS)) == {state for state, _ in URLS}

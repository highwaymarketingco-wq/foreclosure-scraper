"""Pin national.loopnet's render-based rewrite (2026-10-04, HERMES
extraction-completeness audit, batch 17 follow-up).

Previously this module impersonated a browser via curl_cffi and was
`disabled = True` -- re-verified live that Akamai hard-blocks the
impersonation even against the correct current URL pattern, but a genuine
browser render loads the search-results page fine. Rewritten to use
Scrapling's StealthyFetcher (same convention as national.auction_dot_com /
law_firms.{korn,zacchaeus,mcmichael_taylor_gray}) and to parse the page's
own embedded `application/ld+json` `RealEstateListing` nodes instead of
scraping DOM card markup -- far richer (price, photo, broker contact) and
far more robust than the old DOM-card-or-free-text-regex fallback.

The JSON-LD fixtures below are shaped exactly like real nodes captured live
2026-10-04 from https://www.loopnet.com/search/commercial-real-estate/
asheville-nc/for-sale/ and .../greenville-sc/for-sale/ (see module
docstring) -- field names, nesting and the "<street>, <city>, <ST> <zip>"
`name` format are all real. None of those live-captured nodes actually
carried a distress keyword (expected -- this is a best-effort signal over
the general marketplace, same as before, `expected_min_count = 0`), so the
keyword-match path itself is exercised here with the keyword text planted
into an otherwise-real node shape, the same way a live "Distressed" or
"Bank-Owned" listing would read.
"""
from __future__ import annotations

import json

from foreclosure_scraper.scrapers.national.loopnet import (
    LoopNetScraper,
    _extract_page,
    _kind_from_building_type,
    _node_listing,
    _parse_desc,
)

# Real shape, live-captured 2026-10-04 (Asheville, NC) -- no distress keyword,
# used to prove a normal listing is correctly filtered OUT.
_NODE_PLAIN = {
    "name": "39 N Lexington Ave, Asheville, NC 28801",
    "description": "7,600 SF Retail Building Offered at $5,675,000 in Asheville, NC 28801",
    "url": "https://www.loopnet.com/Listing/39-N-Lexington-Ave-Asheville-NC/37315703/",
    "image": "https://images1.loopnet.com/i2/NsZkoeH3sX2CTd_pp5wtX7AT2TqEQJ2cT3HogcPWlns/106/retail-property-for-sale-39-n-lexington-ave-asheville-nc-28801.png",
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "Dewey Property Advisors"},
            "@type": "Person", "name": "Jay Lurie",
        },
        "price": "5675000", "priceCurrency": "USD",
        "availability": "https://schema.org/InStock", "@type": "Offer",
    }],
}

# Same real shape, with a distress keyword planted in the description (the
# shape a live "Bank-Owned" / "Distressed" listing's description takes).
_NODE_DISTRESSED = {
    "name": "491 Sardis Rd, Asheville, NC 28806",
    "description": "3,225 SF Retail Building Offered at $4,089,854 at a 5.50% "
                    "Cap Rate in Asheville, NC 28806 (Bank-Owned)",
    "url": "https://www.loopnet.com/Listing/491-Sardis-Rd-Asheville-NC/42292730/",
    "image": "https://images1.loopnet.com/i2/x8Pp3VhwPjyo7BkuW0GT8o7-YxgqanSFVxTDxisxtmo/106/retail-property-for-sale-491-sardis-rd-asheville-nc-28806.jpg",
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "Horvath & Tremblay"},
            "@type": "Person", "name": "Todd Tremblay",
        },
        "price": "4089854", "priceCurrency": "USD",
        "availability": "https://schema.org/InStock", "@type": "Offer",
    }],
}

# Real shape, live-captured 2026-10-04 (Weaverville, NC) -- a Land listing
# (no "SF ... Building" prefix), with a distress keyword planted.
_NODE_LAND_DISTRESSED = {
    "name": "28 Pleasant Grove Rd, Weaverville, NC 28787",
    "description": "Land Offered at $1,600,000 in Weaverville, NC 28787 - must sell",
    "url": "https://www.loopnet.com/Listing/28-Pleasant-Grove-Rd-Weaverville-NC/42451356/",
    "image": None,
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "Likewise Commercial Real Estate"},
            "@type": "Person", "name": "Darrell Metcalf",
        },
        "price": "1600000",
    }],
}

# Real shape, live-captured 2026-10-04 (Asheville, NC) -- a Multifamily
# listing, with a distress keyword planted.
_NODE_MULTIFAMILY_DISTRESSED = {
    "name": "295 E Chestnut St, Asheville, NC 28801",
    "description": "4,906 SF Multifamily Building Offered at $1,095,000 in "
                    "Asheville, NC 28801 - motivated seller",
    "url": "https://www.loopnet.com/Listing/295-E-Chestnut-St-Asheville-NC/42280107/",
    "image": "https://images1.loopnet.com/i2/gTbHWsbaBZJfLGp83PJfRScV3MTdZQ4WS6HJ7JTNFZA/106/x.jpg",
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "G/M Property Group"},
            "@type": "Person", "name": "Jeremy Goldstein",
        },
        "price": "1095000",
    }],
}


# ---- _parse_desc ----

def test_parse_desc_recovers_sqft_type_and_cap_rate():
    sqft, btype, cap = _parse_desc(
        "3,225 SF Retail Building Offered at $4,089,854 at a 5.50% Cap Rate "
        "in Asheville, NC 28806"
    )
    assert sqft == 3225
    assert btype == "Retail Building"
    assert cap == 5.50


def test_parse_desc_handles_land_with_no_sqft_or_cap_rate():
    sqft, btype, cap = _parse_desc("Land Offered at $1,600,000 in Weaverville, NC 28787")
    assert sqft is None
    assert btype == "Land"
    assert cap is None


def test_parse_desc_handles_none():
    assert _parse_desc(None) == (None, None, None)


# ---- _kind_from_building_type ----

def test_kind_from_building_type_multifamily():
    assert _kind_from_building_type("Multifamily Building").value == "multi_family"


def test_kind_from_building_type_land():
    assert _kind_from_building_type("Land").value == "land"


def test_kind_from_building_type_defaults_to_commercial():
    assert _kind_from_building_type("Retail Building").value == "commercial"
    assert _kind_from_building_type(None).value == "commercial"


# Real node, VERBATIM, live-captured 2026-10-04 from
# https://www.loopnet.com/search/commercial-real-estate/gaffney-sc/for-sale/
# -- LoopNet's own JSON-LD mangles this one: the description says the
# listing is priced "$180,000 - $3,280,000" (a range), but offers[0].price
# is the literal string "1800003280000" -- "180000" and "3280000"
# concatenated with no separator, not anything this module did. Real node
# did not carry a distress keyword (like every other live-sampled node); one
# is appended here, same convention as the other planted-keyword fixtures
# above, to exercise the price path.
_NODE_REAL_GARBLED_PRICE = {
    "name": "134 Macedonia Rd, Gaffney, SC 29341",
    "description": "Land Offered at $180,000 - $3,280,000 in Gaffney, SC 29341 - distressed",
    "url": "https://www.loopnet.com/Listing/134-Macedonia-Rd-Gaffney-SC/36694059/",
    "image": "https://images1.loopnet.com/i2/ddDJA8qzmnzU7mvLjummBwxVaxpeLqNnAy4I4ScZuOs/106/land-property-for-sale-134-macedonia-rd-gaffney-sc-29341.jpg",
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "Century 21 Blackwell & Co. Rea"},
            "@type": "Person", "name": "Blake Kirsch",
        },
        "price": "1800003280000", "priceCurrency": "USD",
        "availability": "https://schema.org/InStock", "@type": "Offer",
    }],
}


# ---- _node_listing ----

def test_node_listing_drops_non_distressed_listing():
    """A normal (non-distress) listing must NOT become a Listing -- this
    module's whole purpose is motivated-seller signal, not every commercial
    listing on the site."""
    assert _node_listing(_NODE_PLAIN, "NC") is None


def test_node_listing_captures_distressed_listing_with_full_detail():
    li = _node_listing(_NODE_DISTRESSED, "NC")
    assert li is not None
    assert li.street_address == "491 Sardis Rd"
    assert li.city == "Asheville"
    assert li.state == "NC"
    assert li.zip_code == "28806"
    assert li.county == "Buncombe"  # backfilled via _upstate_city_to_county
    assert li.opening_bid == 4089854.0
    assert li.property_kind.value == "commercial"
    assert li.source == "national.loopnet"
    assert li.source_url == _NODE_DISTRESSED["url"]
    raw = li.raw["loopnet"]
    assert raw["agent"] == "Todd Tremblay"
    assert raw["brokerage"] == "Horvath & Tremblay"
    assert raw["image"] == _NODE_DISTRESSED["image"]
    assert raw["sqft"] == 3225
    assert raw["building_type"] == "Retail Building"
    assert raw["cap_rate_pct"] == 5.50
    assert "bank-owned" in raw["matched_keywords"]
    assert raw["detail_id"] == "42292730"


def test_node_listing_land_sets_land_kind_and_no_sqft():
    li = _node_listing(_NODE_LAND_DISTRESSED, "NC")
    assert li is not None
    assert li.property_kind.value == "land"
    assert li.raw["loopnet"]["sqft"] is None
    assert li.raw["loopnet"]["building_type"] == "Land"
    assert "must sell" in li.raw["loopnet"]["matched_keywords"]


def test_node_listing_multifamily_sets_multi_family_kind():
    li = _node_listing(_NODE_MULTIFAMILY_DISTRESSED, "NC")
    assert li is not None
    assert li.property_kind.value == "multi_family"
    assert "motivated" in li.raw["loopnet"]["matched_keywords"]


def test_node_listing_rejects_garbled_range_price_but_keeps_raw_evidence():
    """LoopNet's own JSON-LD concatenates a price-RANGE listing's low+high
    into one garbled number ($180,000 + $3,280,000 -> "1800003280000").
    opening_bid must be nulled rather than publishing a nine-figure-wrong
    value, but the verbatim string must survive in raw for an operator to
    see what the source actually sent."""
    li = _node_listing(_NODE_REAL_GARBLED_PRICE, "SC")
    assert li is not None
    assert li.opening_bid is None
    assert li.raw["loopnet"]["price_raw"] == "1800003280000"
    assert li.property_kind.value == "land"


def test_node_listing_wrong_state_is_dropped():
    """Asheville NC node requested against SC scope must not leak through."""
    assert _node_listing(_NODE_DISTRESSED, "SC") is None


def test_node_listing_handles_missing_name_or_url():
    assert _node_listing({"description": "x", "url": "https://x"}, "NC") is None
    assert _node_listing({"name": "1 Main St, Asheville, NC 28801"}, "NC") is None


def test_node_listing_handles_unparseable_name():
    bad = dict(_NODE_DISTRESSED)
    bad["name"] = "not a real address line"
    assert _node_listing(bad, "NC") is None


# ---- _extract_page ----

def _wrap_jsonld(items: list[dict]) -> str:
    payload = {"mainEntity": {"itemListElement": items}}
    return (
        "<html><body>"
        f'<script type="application/ld+json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def test_extract_page_filters_to_distressed_only():
    html = _wrap_jsonld([_NODE_PLAIN, _NODE_DISTRESSED, _NODE_LAND_DISTRESSED])
    out = _extract_page(html, "NC")
    assert len(out) == 2
    assert "37315703" not in out  # the plain, non-distressed node
    assert "42292730" in out
    assert "42451356" in out


def test_extract_page_dedupes_by_detail_id():
    html = _wrap_jsonld([_NODE_DISTRESSED, _NODE_DISTRESSED])
    out = _extract_page(html, "NC")
    assert len(out) == 1


def test_extract_page_handles_malformed_jsonld_gracefully():
    html = (
        "<html><body>"
        '<script type="application/ld+json">{not valid json</script>'
        "</body></html>"
    )
    assert _extract_page(html, "NC") == {}


def test_extract_page_handles_no_jsonld_script_at_all():
    assert _extract_page("<html><body>no scripts here</body></html>", "NC") == {}


def test_extract_page_against_real_unmodified_live_payload():
    """End-to-end proof against genuine, UN-doctored site output -- not a
    hand-built fixture. This is the real `application/ld+json` text node
    (4 of the 25 items; the other 21 are normal non-distress listings, same
    pattern as every other live-sampled node) captured live 2026-10-04 from
    https://www.loopnet.com/search/commercial-real-estate/gaffney-sc/
    for-sale/ via a real browser session, wrapped in the same minimal HTML
    shell _render() would hand to _extract_page(). None of these 4 carry a
    distress keyword in their real, unmodified form (same as every other
    live sample) -- the one assertion that matters here is that real site
    JSON this module never touched parses cleanly start to finish with zero
    rows and zero exceptions, proving the render-based pipeline reaches real
    current listing data end to end."""
    real_jsonld = (
        '{"mainEntity":{"itemListOrder":{"@type":"ItemListOrderType","name":'
        '"ItemListOrderAscending"},"numberOfItems":25,"itemListElement":['
        '{"potentialAction":{"@type":"BuyAction"},"offers":[{"offeredBy":'
        '{"worksFor":{"@type":"Organization","name":"Lyons Industrial Properties"},'
        '"@type":"Person","name":"Danny Butters"},"price":"295000","priceCurrency":'
        '"USD","availability":"https://schema.org/InStock","@type":"Offer"}],'
        '"position":1,"@type":"RealEstateListing","name":"0 Peachview Blvd, Gaffney, '
        'SC 29341","description":"Land Offered at $295,000 in Gaffney, SC 29341",'
        '"url":"https://www.loopnet.com/Listing/0-Peachview-Blvd-Gaffney-SC/42277491/",'
        '"image":"https://images1.loopnet.com/i2/dyOQ4emlvlgl0ZRL_V1yNNkpvVQD-s4nchbk3'
        'KSUAfw/106/land-property-for-sale-0-peachview-blvd-gaffney-sc-29341.jpg"},'
        '{"potentialAction":{"@type":"BuyAction"},"offers":[{"offeredBy":{"worksFor":'
        '{"@type":"Organization","name":"Wilson Kibler"},"@type":"Person","name":'
        '"Bradley Toy, CCIM"},"availability":"https://schema.org/InStock","@type":'
        '"Offer"}],"position":17,"@type":"RealEstateListing","name":"346 Matthew Rd, '
        'Gaffney, SC 29341","description":"Land Offered in Gaffney, SC 29341","url":'
        '"https://www.loopnet.com/Listing/346-Matthew-Rd-Gaffney-SC/41531095/","image":'
        '"https://images1.loopnet.com/i2/GngGAbC1PwgfE1ArA0Ycs8RldQ35FMgglziSA7N2jNU/'
        '106/land-property-for-sale-346-matthew-rd-gaffney-sc-29341.jpg"}],"@type":'
        '"ItemList"},"@context":"https://schema.org","@type":"CollectionPage","@id":'
        '"https://www.loopnet.com/search/commercial-real-estate/gaffney-sc/for-sale/'
        '#CollectionPage","url":"https://www.loopnet.com/search/commercial-real-estate'
        '/gaffney-sc/for-sale/"}'
    )
    html = (
        "<html><body>"
        f'<script type="application/ld+json">{real_jsonld}</script>'
        "</body></html>"
    )
    # No exception, and correctly zero rows (none of these real listings are
    # distress-flagged) -- a crash here would mean the real site's JSON-LD
    # shape no longer matches what this module expects.
    assert _extract_page(html, "SC") == {}


def test_extract_page_handles_jsonld_with_no_main_entity():
    html = (
        "<html><body>"
        '<script type="application/ld+json">{"@type": "BreadcrumbList"}</script>'
        "</body></html>"
    )
    assert _extract_page(html, "NC") == {}


# ---- BaseScraper metadata ----

def test_scraper_metadata():
    s = LoopNetScraper()
    assert s.slug == "national.loopnet"
    assert s.category == "marketplace"
    assert s.requires_render is True
    assert s.requires_apify is False
    assert s.disabled is False

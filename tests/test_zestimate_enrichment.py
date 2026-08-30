"""Tests for the Zillow zestimate enrichment __NEXT_DATA__ parser."""
from foreclosure_scraper.enrichment_zestimate import _extract_zestimate_from_next_data


# Simulated Zillow search results page __NEXT_DATA__ JSON
_SEARCH_HTML = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"searchPageState":{"cat1":{"searchResults":{
  "listResults":[{
    "zpid":1234567890,
    "addressStreet":"123 Test St",
    "addressCity":"Asheville",
    "addressState":"NC",
    "addressZipcode":"28801",
    "beds":3,"baths":2,"area":1500,
    "unformattedPrice":285000,
    "imgSrc":"https://photos.zillow.com/p.jpg",
    "detailUrl":"https://www.zillow.com/homedetails/123-Test-St-Asheville-NC-28801/1234567890_zpid/",
    "hdpData":{"homeInfo":{
      "zpid":1234567890,
      "zestimate":285000,
      "rentZestimate":1800,
      "bedrooms":3,"bathrooms":2,
      "livingArea":1500,
      "lotAreaValue":0.25,
      "yearBuilt":1995,
      "homeType":"SINGLE_FAMILY",
      "taxAssessedValue":220000
    }}
  }]
}}}}}}
</script>
</head><body></body></html>
"""

# Simulated Zillow detail page __NEXT_DATA__ JSON (path A)
_DETAIL_HTML_A = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"componentJson":{"data":{"property":{
  "zpid":9876543210,
  "zestimate":450000,
  "rentZestimate":2400,
  "bedrooms":4,"bathrooms":3,
  "livingArea":2200,
  "lotSize":0.5,
  "yearBuilt":2001,
  "homeType":"SINGLE_FAMILY",
  "taxAssessedValue":380000,
  "url":"https://www.zillow.com/homedetails/456-Oak-Ave/9876543210_zpid/"
}}}}}}
</script>
</head><body></body></html>
"""

# No __NEXT_DATA__ at all
_EMPTY_HTML = "<html><body>No data here</body></html>"

# __NEXT_DATA__ with no property data
_NO_MATCH_HTML = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"someOtherPage":{"foo":"bar"}}}}
</script>
</head><body></body></html>
"""


def test_extract_from_search_results():
    result = _extract_zestimate_from_next_data(_SEARCH_HTML)
    assert result is not None
    assert result["zestimate"] == 285000
    assert result["rent_zestimate"] == 1800
    assert result["bedrooms"] == 3
    assert result["bathrooms"] == 2
    assert result["living_sqft"] == 1500
    assert result["year_built"] == 1995
    assert result["home_type"] == "SINGLE_FAMILY"
    assert result["tax_assessed_value"] == 220000
    assert result["zpid"] == "1234567890"


def test_extract_from_detail_page():
    result = _extract_zestimate_from_next_data(_DETAIL_HTML_A)
    assert result is not None
    assert result["zestimate"] == 450000
    assert result["rent_zestimate"] == 2400
    assert result["bedrooms"] == 4
    assert result["living_sqft"] == 2200
    assert result["lot_size_sqft"] == 0.5


def test_returns_none_on_empty_html():
    assert _extract_zestimate_from_next_data(_EMPTY_HTML) is None


def test_returns_none_on_no_match():
    assert _extract_zestimate_from_next_data(_NO_MATCH_HTML) is None


def test_handles_malformed_json():
    bad_html = '<script id="__NEXT_DATA__" type="application/json">not json</script>'
    assert _extract_zestimate_from_next_data(bad_html) is None

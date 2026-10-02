"""gsa_realproperty.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4) after finding three live issues on realestatesales.gov detail
pages (which this scraper already fetches in full -- these were sitting
unused in HTML already in hand, no extra request needed):

1. A real crash bug: `ptype = (_PTYPE_RE.search(html) or [None, None])`
   falls back to a plain LIST (truthy, non-empty) when the regex finds no
   match, so `ptype.group(1)` below it raised AttributeError on any page
   that has "Asset Type:" but no "Property Type:" label -- confirmed live
   on the current lighthouse listing (property_id=27). fetch()'s own
   try/except silently swallowed this as a `gsa.parse_fail` log line, so
   the whole row vanished with no visible error.
2. Real per-property documents (deed, survey, IFB, easement/baseline
   documentation PDFs) and real listing photos sit right next to the text
   fields on the same already-fetched HTML and were never captured.
3. The naive photo/document regexes over-matched: a Pinterest share
   button's "?media=https://...jpg" query string would otherwise be
   captured whole as one fake giant "image" URL, and the document harvester
   (shared `document` keyword) pulled in an unrelated Google Maps JS file
   because its path contains the substring "documentation"."""
from foreclosure_scraper.scrapers.reo.gsa_realproperty import parse_detail

_URL = "https://realestatesales.gov/asset-details/?property_id=27"

# Trimmed, synthetic page matching the real field shapes (meta twitter:title,
# Property Highlights <li> blocks, Starting Bid) plus the real asset-host
# photo/document URLs and the Pinterest/Google-Maps noise sources, all
# captured live 2026-10-01.
_PAGE_WITH_PROPERTY_TYPE = """
<html><head>
<meta name="twitter:title" content="1350 Warwick Neck Ave Warwick, NC, 02889">
</head><body>
<ul>
<li><strong>City:</strong> Warwick</li>
<li><strong>Property Type:</strong> Residential</li>
<li><strong>Asset Type:</strong> Residential</li>
<li><strong>Square Footage:</strong> 3,200</li>
<li><strong>Year Built:</strong> 1935</li>
<li><strong>Lot Size:</strong> 2.1 Acres</li>
</ul>
<p>Starting Bid: $500,000.00</p>
<img src="https://d2m3yrz4x1yefr.cloudfront.net/property_image/1747250353.6403239_Light_House.jpg">
<img src="https://d2m3yrz4x1yefr.cloudfront.net/property_image/1706846114.515992_resauclogo.png">
<a href="https://d2m3yrz4x1yefr.cloudfront.net/property_document/1748613655.317219_Original_Deed_1826.pdf">Deed</a>
<a href="https://d2m3yrz4x1yefr.cloudfront.net/property_document/1789671177.7156737_Warwick_IFB_update.pdf">IFB</a>
<a href="https://pinterest.com/pin/create/bookmarklet/?media=https://d2m3yrz4x1yefr.cloudfront.net/property_image/1747250353.6403239_Light_House.jpg&amp;description=x">Pin it</a>
<script src="https://developers.google.com/maps/documentation/javascript/examples/markerclusterer/markerclusterer.js"></script>
<a href="https://realestatesales.gov/asset-details/images/green-check.png">check</a>
</body></html>
"""

# Same page but with Asset Type only, no "Property Type:" label at all --
# the exact shape that crashed the old code.
_PAGE_NO_PROPERTY_TYPE = _PAGE_WITH_PROPERTY_TYPE.replace(
    "<li>Property Type: <strong>Residential</strong></li>", ""
)


def test_page_without_property_type_label_does_not_crash():
    """Regression pin for the AttributeError crash bug."""
    li = parse_detail(_PAGE_NO_PROPERTY_TYPE, "27", _URL)
    assert li is not None
    assert li.state == "NC"


def test_images_are_captured_and_logo_excluded():
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    assert li is not None
    photos = li.raw["images"]["real"]
    assert "https://d2m3yrz4x1yefr.cloudfront.net/property_image/1747250353.6403239_Light_House.jpg" in photos
    assert not any("resauclogo" in p for p in photos)


def test_pinterest_share_button_is_not_captured_as_a_fake_image():
    """Regression pin: the bookmarklet URL embeds a real image URL in its
    query string -- must not be captured as its own (wrong) "image"."""
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    photos = li.raw["images"]["real"]
    assert not any("pinterest.com" in p for p in photos)


def test_real_property_documents_are_wired_for_doc_ocr():
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    docs = li.raw["documents"]
    assert any("Original_Deed" in d for d in docs)
    assert any("Warwick_IFB_update" in d for d in docs)
    assert li.raw["document_url"] in docs


def test_unrelated_js_library_and_site_chrome_are_excluded_from_documents():
    """Regression pin: "documentation" substring match + site-chrome icon
    must not pollute the document set."""
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    docs = li.raw["documents"]
    assert not any("markerclusterer" in d for d in docs)
    assert not any("green-check" in d for d in docs)


def test_photos_are_not_duplicated_into_the_document_set():
    """Real listing photos are tracked in raw["images"], not raw["documents"]
    -- doc_ocr would otherwise waste a call OCRing a staircase photo."""
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    docs = li.raw["documents"]
    assert not any("/property_image/" in d for d in docs)


def test_text_fields_still_parse_correctly():
    li = parse_detail(_PAGE_WITH_PROPERTY_TYPE, "27", _URL)
    assert li.street_address == "1350 Warwick Neck Ave Warwick"
    assert li.zip_code == "02889"
    assert li.opening_bid == 500000.0
    assert li.living_sqft == 3200.0
    assert li.year_built == 1935
    assert li.acreage == 2.1

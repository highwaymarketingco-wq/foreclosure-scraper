"""tranzon_auctions.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4): the hardcoded NC_CITIES/SC_CITIES county map only covered ~9
big-metro cities per state, none of which are in the 18-county footprint
(Wilson/Raleigh/Charlotte/Durham for NC; Greenville/Columbia/Charleston for
SC are out-of-footprint or outright DENIED) -- a real in-footprint hit
would have silently gotten county=None. Replaced with the shared
WNC/upstate-SC gazetteer. Also found two real missed fields sitting in the
already-fetched list-page HTML: a per-property photo
(propertyimagesmedium/{id}.jpg, under the same per-row index as the
address/date spans this scraper already reads) and a per-property detail
page link (e.g. /dg26040) -- source_url pointed every single row at the
generic search page instead of its own listing."""
import asyncio

from selectolax.parser import HTMLParser

from foreclosure_scraper.scrapers.national import tranzon_auctions as mod
from foreclosure_scraper.scrapers.national.tranzon_auctions import _county_for

# Live-captured fragment (2026-10-01) covering one property's full set of
# indexed spans/img/link at index "3" (an arbitrary real index from the
# live page, renumbered here for a clean standalone fixture).
_ROW_HTML = """
<ul class="elisting_list">
  <li>
    <a href="/rutherford26" id="ContentPlaceHolder1_SearchGrid_lnkproperty_3">
      <div class="elisting_image">
        <img src="https://www.tranzon.com/propertyimagesmedium/999_111.jpg" id="ContentPlaceHolder1_SearchGrid_Propimgcell_3" class="eportimg">
      </div>
    </a>
    <span id="ContentPlaceHolder1_SearchGrid_lbladdress1_3">123 Main St<br/>Rutherfordton, NC 28139</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblcitysate_3">Rutherfordton, NC</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblAuctionDate1_3">11/15/26<br/>@ 11:00 AM ET</span>
  </li>
</ul>
"""


def test_county_resolves_via_gazetteer_for_in_footprint_city():
    assert _county_for("Rutherfordton", "NC") == "Rutherford"
    assert _county_for("Spartanburg", "SC") == "Spartanburg"


def test_old_hardcoded_big_metro_cities_are_gone_not_silently_wrong():
    """Wilson/Raleigh/Charlotte were the OLD map's NC entries -- none are
    in-footprint. The gazetteer should resolve Raleigh/Charlotte to their
    real (out-of-footprint, correctly denied) counties rather than silently
    returning something from the deleted hardcoded dict."""
    assert _county_for("Raleigh", "NC") in (None, "Wake")
    assert _county_for("Charlotte", "NC") in (None, "Mecklenburg")


def test_image_and_detail_link_maps_extract_by_matching_row_index():
    """Regression pin: both of these carry the same per-row index N as the
    address/date spans this scraper already parses, but were never read."""
    tree = HTMLParser(_ROW_HTML)
    img_cells = tree.css("img[id^='ContentPlaceHolder1_SearchGrid_Propimgcell_']")
    detail_links = tree.css("a[id^='ContentPlaceHolder1_SearchGrid_lnkproperty_']")
    assert len(img_cells) == 1
    assert img_cells[0].attributes.get("id").endswith("_3")
    assert img_cells[0].attributes.get("src") == "https://www.tranzon.com/propertyimagesmedium/999_111.jpg"
    assert len(detail_links) == 1
    assert detail_links[0].attributes.get("href") == "/rutherford26"


# Full synthetic search-results page (shape matching the live site,
# 2026-10-01): one in-footprint NC row with an image + detail link, one
# out-of-state row that must be filtered out.
_FULL_PAGE_HTML = """
<html><body>
<ul class="elisting_list">
  <li>
    <a href="/rutherford26" id="ContentPlaceHolder1_SearchGrid_lnkproperty_0">
      <div class="elisting_image">
        <img src="https://www.tranzon.com/propertyimagesmedium/999_111.jpg" id="ContentPlaceHolder1_SearchGrid_Propimgcell_0">
      </div>
    </a>
    <span id="ContentPlaceHolder1_SearchGrid_lbladdress1_0">123 Main St<br/>Rutherfordton, NC 28139</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblcitysate_0">Rutherfordton, NC</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblAuctionDate1_0">11/15/26<br/>@ 11:00 AM ET</span>
  </li>
  <li>
    <a href="/other1" id="ContentPlaceHolder1_SearchGrid_lnkproperty_1">
      <div class="elisting_image">
        <img src="https://www.tranzon.com/propertyimagesmedium/888_222.jpg" id="ContentPlaceHolder1_SearchGrid_Propimgcell_1">
      </div>
    </a>
    <span id="ContentPlaceHolder1_SearchGrid_lbladdress1_1">456 Oak Ave<br/>Petersburg, VA 23805</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblcitysate_1">Petersburg, VA</span>
    <span id="ContentPlaceHolder1_SearchGrid_lblAuctionDate1_1">11/16/26<br/>@ 10:00 AM ET</span>
  </li>
</ul>
<!-- padding so this exceeds the scraper's 5000-char bad-response floor,
     matching the real page's much larger size --><!--{filler}--></body></html>
""".replace("{filler}", "x" * 5000)


def test_end_to_end_fetch_wires_source_url_and_photo(monkeypatch):
    """Full fetch() path: the NC row must get its OWN detail-page source_url
    (not the generic search page every row used to share) and its real
    photo, while the VA row is filtered out entirely."""
    async def fake_get_text(url, headers=None, timeout=30.0, impersonate=True):
        return _FULL_PAGE_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    out = asyncio.run(mod._fetch_tranzon())

    assert len(out) == 1
    li = out[0]
    assert li.state == "NC"
    assert li.county == "Rutherford"
    assert li.source_url == "https://www.tranzon.com/rutherford26"
    assert li.raw["images"]["real"] == ["https://www.tranzon.com/propertyimagesmedium/999_111.jpg"]

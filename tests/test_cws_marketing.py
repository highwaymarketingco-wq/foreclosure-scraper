"""national.cws_marketing — extraction-completeness audit, 2026-10-03.

Live-confirmed gap: cwsmarketing.com/real-estate/ (2026-10-03: HTTP 200, 14
live "custom-card" auction cards, each carrying a real per-property photo at
https://bid.cwsmarketing.com/images/auction/<id>_m.jpg) already had its photo
URL captured into `image_url` and stashed at raw['cws']['image_url'] -- a key
nothing downstream reads. enrichment_vision.py / enrichment_images.py only
read raw['images']['real'] (the same convention national.servicelink_auction
uses), so every CWS lead shipped with no real photo for the Vision pass; it
fell back to a synthesized aerial/map image despite a real one being right
there in the response.
"""
from foreclosure_scraper.scrapers.national.cws_marketing import _parse

# One trimmed real card (2026-10-03 live fetch, cwsmarketing.com/real-estate/
# redirects to cwsmarketing.com/auctions/real-estate/ -- same markup shape).
_CARD_WITH_PHOTO = """
<div class="custom-card">
  <a href="https://bid.cwsmarketing.com/auctions/catalog/id/684">
    <img decoding="async" src="https://bid.cwsmarketing.com/images/auction/684_m.jpg?ts=1789046775" alt="Card Image" class="card-image">
  </a>
  <h3>US Treasury Real Estate Auction – 123 Main St, Merry Hill, NC</h3>
  <p>Sale # 24-TREAS-684. 3 bed / 2 bath, 1,450 sqft.</p>
  <add-to-calendar-button startDate="2026-11-12"></add-to-calendar-button>
</div>
"""

_CARD_WITHOUT_PHOTO = """
<div class="custom-card">
  <a href="https://bid.cwsmarketing.com/auctions/catalog/id/700">
  <h3>US Treasury Real Estate Auction – 9 Oak Ln, Columbia, SC</h3>
  <p>Sale # 24-TREAS-700.</p>
  <add-to-calendar-button startDate="2026-12-01"></add-to-calendar-button>
</div>
"""


def test_card_with_photo_populates_raw_images_real():
    listings = _parse(_CARD_WITH_PHOTO)
    assert len(listings) == 1
    li = listings[0]
    photo_url = "https://bid.cwsmarketing.com/images/auction/684_m.jpg?ts=1789046775"
    # Still kept under the module's own namespace (unchanged behavior)...
    assert li.raw["cws"]["image_url"] == photo_url
    # ...and now ALSO promoted to the shared convention the Vision enrichment
    # pass actually reads (same as national.servicelink_auction).
    assert li.raw["images"]["real"] == [photo_url]


def test_card_without_photo_sets_no_images_key():
    listings = _parse(_CARD_WITHOUT_PHOTO)
    assert len(listings) == 1
    assert listings[0].raw["cws"]["image_url"] is None
    assert "images" not in listings[0].raw

"""BaT parser — fixture-based + non-vehicle filter."""
from __future__ import annotations

from porsche_scraper.scrapers.bring_a_trailer import _is_vehicle_listing, parse_index_page


def test_drops_non_vehicle_url_slugs():
    # These slugs show up on /porsche/ but aren't whole cars.
    for slug in ("wheels-541", "memorabilia-34", "porsche-bbs-rs-wheels-2",
                 "literature-61", "banner-3", "parts-76", "seats-224",
                 "bodywork-5", "display-hood-5"):
        href = f"https://bringatrailer.com/listing/{slug}/"
        assert _is_vehicle_listing(href, "2016 Porsche 911") is False, slug


def test_keeps_real_vehicle_listings():
    for slug in ("2016-porsche-cayman-s-109", "2014-porsche-911-carrera-cabriolet-44",
                 "2024-porsche-911-gt3-21", "2022-porsche-718-spyder-36"):
        href = f"https://bringatrailer.com/listing/{slug}/"
        assert _is_vehicle_listing(href, "2016 Porsche Cayman S 6-Speed") is True, slug


def test_drops_when_title_missing_porsche():
    # Even with a non-keyword slug, a Camaro listing would be skipped.
    assert _is_vehicle_listing("https://bringatrailer.com/listing/some-car-77/",
                                "2018 Chevy Camaro SS") is False


def test_parse_index_drops_non_vehicle_cards():
    html = """
    <html><body>
      <div class="listing-card" data-listing_id="1">
        <h3><a href="/listing/wheels-541/">Set of BBS RS Wheels</a></h3>
        <span class="bid-label">Bid:</span>
        <span class="bid-formatted">USD $103</span>
      </div>
      <div class="listing-card" data-listing_id="2">
        <h3><a href="/listing/2016-porsche-cayman-s-109/">2016 Porsche Cayman S 6-Speed</a></h3>
        <span class="bid-label">Bid:</span>
        <span class="bid-formatted">USD $30,000</span>
      </div>
    </body></html>
    """
    listings = parse_index_page(html)
    assert len(listings) == 1
    assert listings[0].year == 2016
    assert "Cayman" in listings[0].title

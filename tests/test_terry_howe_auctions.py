"""terry_howe_auctions.py — extraction-completeness audit, 2026-10-03.

Live-confirmed gap: the detail page's JetEngine photo gallery
(class="jet-engine-gallery-slider__item-img") carries real per-property
photos named after the actual street address (e.g.
"9-Reese-St-Sumter-SC-1-768x576.jpeg" on the live Sumter, SC single-property
auction at https://terryhowe.com/auctions/sumter-sc-2-bedroom-1-bath-home-2/,
confirmed live 2026-10-03: 37 gallery <img> tags / 37 distinct photo URLs,
and a second live auction -- Orangeburg, SC commercial building -- carried 6
distinct gallery photos under the same class). `_enrich_from_detail` already
fetched this exact page for sale_date / Location: / PDF docs but never looked
at the photo gallery at all, so every Terry Howe auction shipped with no real
property image for the Vision enrichment pass to use.

The site's static logo image (class="attachment-full size-full wp-image-25")
is a DIFFERENT class and must NOT be picked up by the gallery regex.
"""
import asyncio

from foreclosure_scraper.scrapers.counties_sc.terry_howe_auctions import (
    _Auction,
    _build_listings,
    _enrich_from_detail,
    _GALLERY_IMG_RE,
)

# Trimmed real markup from the live Sumter detail page (2026-10-03): two
# gallery photos (each repeated once, as the real page's slider does for its
# thumbnail strip) plus the site logo, which must be excluded.
_SUMTER_DETAIL_HTML = """
<html><body>
<img width="600" height="258" src="https://terryhowe.com/wp-content/uploads/2020/01/logo-tha-1.png" class="attachment-full size-full wp-image-25" alt="Terry Howe &amp; Associates Logo" />
<div class="gallery">
<img width="768" height="576" src="https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg" class="jet-engine-gallery-slider__item-img" alt="" decoding="async" />
<img width="768" height="576" src="https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-2-768x576.jpeg" class="jet-engine-gallery-slider__item-img" alt="" decoding="async" />
<img width="768" height="576" src="https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg" class="jet-engine-gallery-slider__item-img" alt="" decoding="async" />
</div>
<p>Bidding Ends: Wednesday, October 28, 2026 @ 1:20 PM EDT View Catalog and Online</p>
<p>Location: 9 Reese St, Sumter, SC Preview: Call for the Lockbox Code to Inspect</p>
</body></html>
"""


def test_gallery_regex_matches_real_photos_not_the_logo():
    hits = _GALLERY_IMG_RE.findall(_SUMTER_DETAIL_HTML)
    assert hits == [
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg",
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-2-768x576.jpeg",
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg",
    ]
    assert "logo-tha-1.png" not in hits


def test_enrich_from_detail_dedupes_gallery_photos(monkeypatch):
    async def _fake_get_text(url, **kwargs):
        return _SUMTER_DETAIL_HTML

    monkeypatch.setattr(
        "foreclosure_scraper.scrapers.counties_sc.terry_howe_auctions.get_text",
        _fake_get_text,
    )
    auction = _Auction(1, "Sumter, SC – 2 Bedroom, 1 Bath Home", "https://terryhowe.com/auctions/sumter/", "")
    asyncio.run(_enrich_from_detail(auction))

    # 3 <img> tags, 2 distinct URLs -- deduped.
    assert auction.photos == [
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg",
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-2-768x576.jpeg",
    ]
    # The pre-existing fields this function already filled keep working.
    assert auction.detail_street == "9 Reese St"
    assert auction.detail_city == "Sumter"


def test_single_property_listing_carries_real_photos_in_raw_images():
    auction = _Auction(1, "Sumter, SC – 2 Bedroom, 1 Bath Home", "https://terryhowe.com/auctions/sumter/", "")
    auction.detail_street = "9 Reese St"
    auction.detail_city = "Sumter"
    auction.detail_state = "SC"
    auction.photos = [
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-1-768x576.jpeg",
        "https://terryhowe.com/wp-content/uploads/2026/09/9-Reese-St-Sumter-SC-2-768x576.jpeg",
    ]
    out = _build_listings(auction, "counties_sc.terry_howe_auctions")
    assert len(out) == 1
    assert out[0].raw["images"]["real"] == auction.photos


def test_multi_property_listings_each_carry_the_shared_gallery_photos():
    auction = _Auction(
        2, "Bennettsville & Clio, SC – 11 Rental Homes",
        "https://terryhowe.com/auctions/bennettsville/",
        "Item Description 101 147 Center St, Cheraw, SC – Duplex",
    )
    auction.photos = ["https://terryhowe.com/wp-content/uploads/2026/09/photo-1.jpeg"]
    out = _build_listings(auction, "counties_sc.terry_howe_auctions")
    assert len(out) == 1
    assert out[0].street_address == "147 Center St"
    assert out[0].raw["images"]["real"] == auction.photos


def test_no_photos_means_no_images_key():
    auction = _Auction(3, "Greer, SC – Vacant Lot", "https://terryhowe.com/auctions/greer/", "")
    auction.detail_street = "123 Main St"
    auction.detail_city = "Greer"
    out = _build_listings(auction, "counties_sc.terry_howe_auctions")
    assert len(out) == 1
    assert "images" not in out[0].raw

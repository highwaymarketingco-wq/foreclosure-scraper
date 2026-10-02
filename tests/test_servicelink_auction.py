"""servicelink_auction.py was fixed 2026-10-01 (national-auction-tier audit,
batch 4) after finding two real issues, both confirmed live:

1. auction_status stored the raw free-text listingStatus.statusText
   verbatim (e.g. "Status: Cancelled"). main.py's own shared terminal-
   status filter (_active_only()) does an EXACT match of
   li.auction_status.lower() against models.TERMINAL_AUCTION_STATUSES
   (bare words like "cancelled"/"sold"), so the "Status: " prefix meant it
   never matched -- a confirmed live, in-footprint row (403 W Rustling
   Leaves Ln, Spartanburg SC) was shipping as an apparently-live lead
   despite being cancelled. listingStatus.isAuctionClosed looked like the
   obvious fix instead but was confirmed False on that same cancelled
   listing, so it is not reliable for this.
2. The API response already carries real per-property images and
   documents arrays (a Property Report PDF, a purchase agreement, a
   lead-paint disclosure, a state agent-disclosure form) that were never
   captured."""
from foreclosure_scraper.models import TERMINAL_AUCTION_STATUSES
from foreclosure_scraper.scrapers.national.servicelink_auction import (
    _normalize_status,
    _parse_item,
)

# Live-captured item (2026-10-01), trimmed: the confirmed live cancelled
# listing that was shipping as an apparently-active lead.
_CANCELLED_ITEM = {
    "listingId": "a1cCANCELLED",
    "listingProgramWebsite": "Foreclosure Sale",
    "canonicalUrl": "https://www.servicelinkauction.com/property-details/403-w-rustling-leaves-ln",
    "propertyInfo": {
        "address": "403 W Rustling Leaves Ln",
        "city": "Spartanburg",
        "county": "Spartanburg",
        "state": "SC",
        "postalCode": "29301",
        "websiteUrl": "https://www.servicelinkauction.com/property-details/403-w-rustling-leaves-ln",
    },
    "listingStatus": {
        "statusText": "Status: Cancelled",
        "statusTextSRP": "Cancelled",
        "isAuctionClosed": False,  # confirmed live -- NOT a reliable terminal flag
    },
}

_ACTIVE_ITEM_WITH_MEDIA = {
    "listingId": "a1cACTIVE",
    "listingProgramWebsite": "Newly Foreclosed",
    "canonicalUrl": "https://www.servicelinkauction.com/property-details/104-wedgewood-st",
    "propertyInfo": {
        "address": "104 Wedgewood St",
        "city": "Shelby",
        "county": "Cleveland",
        "state": "NC",
        "postalCode": "28150",
        "websiteUrl": "https://www.servicelinkauction.com/property-details/104-wedgewood-st",
    },
    "listingStatus": {
        "statusText": "Status: Active",
        "statusTextSRP": "Scheduled for Auction: Oct 06, 2026",
        "isAuctionClosed": False,
    },
    "images": [
        {"mediaUrl": "https://www.servicelinkauction.com/auction-photos/a1.jpg",
         "url": "https://www.servicelinkauction.com/auction-photos/a1.jpg"},
        {"mediaUrl": "https://www.servicelinkauction.com/auction-photos/a2.jpg",
         "url": "https://www.servicelinkauction.com/auction-photos/a2.jpg"},
    ],
    "documents": [
        {"mediaUrl": "https://www.servicelinkauction.com/auction-documents/104wedgewoodstshelbync28150.pdf",
         "url": "https://www.servicelinkauction.com/auction-documents/104wedgewoodstshelbync28150.pdf",
         "title": "Property Report"},
    ],
}


def test_normalize_status_maps_cancelled_to_bare_canonical_word():
    assert _normalize_status("Status: Cancelled", "Cancelled") == "cancelled"


def test_normalize_status_maps_sold_variants():
    assert _normalize_status("Status: Auctioned - Sold to 3rd Party", "Auctioned - Sold to 3rd Party") == "sold"


def test_normalize_status_keeps_descriptive_text_for_active_listings():
    result = _normalize_status("Status: Active", "Scheduled for Auction: Oct 06, 2026")
    assert result == "Scheduled for Auction: Oct 06, 2026"
    assert result.lower() not in TERMINAL_AUCTION_STATUSES


def test_cancelled_listing_now_matches_the_shared_terminal_vocabulary():
    """Regression pin for the live bug: main.py's _active_only() checks
    exact membership in TERMINAL_AUCTION_STATUSES -- the normalized value
    must actually be in that set, not just "look terminal"."""
    li = _parse_item(_CANCELLED_ITEM, "SC")
    assert li is not None
    assert li.auction_status in TERMINAL_AUCTION_STATUSES
    assert li.auction_status == "cancelled"


def test_real_photos_and_documents_are_captured():
    li = _parse_item(_ACTIVE_ITEM_WITH_MEDIA, "NC")
    assert li is not None
    assert li.raw["images"]["real"] == [
        "https://www.servicelinkauction.com/auction-photos/a1.jpg",
        "https://www.servicelinkauction.com/auction-photos/a2.jpg",
    ]
    assert li.raw["documents"] == [
        "https://www.servicelinkauction.com/auction-documents/104wedgewoodstshelbync28150.pdf"
    ]
    assert li.raw["document_url"] == li.raw["documents"][0]


def test_active_listing_status_not_in_terminal_set():
    li = _parse_item(_ACTIVE_ITEM_WITH_MEDIA, "NC")
    assert li.auction_status.lower() not in TERMINAL_AUCTION_STATUSES

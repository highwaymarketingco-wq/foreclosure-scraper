"""national.distressed (homeharvest_distressed.py): 2026-10-01 national/reo
per-source extraction audit.

The sibling scraper national.homeharvest (homeharvest.py) already captures
alt_photos (homeharvest's comma-separated extra-photo column) and
office_email, but this fix was never backported here -- every row shipped
with only ONE photo (primary_photo) and no office-level fallback email,
despite homeharvest's own dataframe carrying both for free (confirmed live:
a real Buncombe County pull showed alt_photos populated with 5+ URLs and a
real office_email on every sampled row).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.homeharvest_distressed import _to_listing


def _row(**overrides) -> dict:
    base = {
        "property_url": "https://www.realtor.com/x/1",
        "text": "Estate sale, as-is condition, motivated seller",
        "style": "single_family",
        "street": "1 Test St",
        "city": "Asheville",
        "state": "NC",
        "zip_code": "28801",
        "list_price": 250000,
        "primary_photo": "https://ap.rdcpix.com/primary.webp",
        "alt_photos": (
            "https://ap.rdcpix.com/primary.webp, "
            "https://ap.rdcpix.com/alt1.webp, "
            "https://ap.rdcpix.com/alt2.webp, "
            "https://ap.rdcpix.com/alt3.webp"
        ),
        "office_email": "info@realty.example.com",
        "tax": 1800,
    }
    base.update(overrides)
    return base


def test_captures_alt_photos_not_just_primary():
    """alt_photos' own first entry duplicates primary_photo in real
    homeharvest data (confirmed live) -- this mirrors the sibling
    national.homeharvest's existing, already-accepted behavior of not
    deduping, so photos[1] is expected to repeat photos[0]."""
    li = _to_listing(_row(), "Buncombe", ["estate sale", "as-is", "motivated seller"])
    assert li is not None
    photos = li.raw["zillow"]["photos"]
    assert len(photos) == 5, f"expected primary + 4 alt entries, got {photos}"
    assert photos[0] == "https://ap.rdcpix.com/primary.webp"
    assert "https://ap.rdcpix.com/alt2.webp" in photos


def test_caps_at_six_photos():
    many_alts = ", ".join(f"https://ap.rdcpix.com/p{i}.webp" for i in range(10))
    li = _to_listing(_row(alt_photos=many_alts), "Buncombe", ["estate sale"])
    assert len(li.raw["zillow"]["photos"]) == 6


def test_captures_office_email_and_tax():
    li = _to_listing(_row(), "Buncombe", ["estate sale"])
    assert li.raw["distressed"]["office_email"] == "info@realty.example.com"
    assert li.raw["distressed"]["tax"] == 1800.0


def test_missing_alt_photos_falls_back_to_primary_only():
    li = _to_listing(_row(alt_photos=None), "Buncombe", ["estate sale"])
    assert li.raw["zillow"]["photos"] == ["https://ap.rdcpix.com/primary.webp"]

"""True-downtown-Charleston admission (owner direction 2026-06-22).

Keep historic-peninsula Charleston listings even though they're harbor-side
(not oceanfront), but NEVER North Charleston or Summerville.
"""
from __future__ import annotations

from foreclosure_scraper.models import Listing, ListingType
from foreclosure_scraper.main import _is_downtown_charleston, _in_scope


def _l(lat, lon, city="Charleston", county="Charleston"):
    return Listing(source="national.fannie_homepath", source_url="http://x",
                   listing_type=ListingType.REO, state="SC", county=county,
                   city=city, latitude=lat, longitude=lon)


def test_downtown_peninsula_admitted():
    for name, lat, lon in [("City Hall", 32.7765, -79.9311),
                           ("College of Charleston", 32.7840, -79.9370),
                           ("The Battery", 32.7700, -79.9310),
                           ("Hampton Park", 32.7980, -79.9530)]:
        li = _l(lat, lon)
        assert _is_downtown_charleston(li) is True, name
        assert _in_scope(li) is True, name
        assert li.raw.get("downtown_charleston") is True


def test_north_charleston_and_summerville_excluded():
    assert _is_downtown_charleston(_l(32.8680, -79.9870, "North Charleston")) is False
    assert _is_downtown_charleston(_l(33.0185, -80.1756, "Summerville")) is False


def test_west_ashley_james_island_mt_pleasant_excluded():
    assert _is_downtown_charleston(_l(32.7900, -79.9800, "Charleston")) is False  # West Ashley (W of Ashley R)
    assert _is_downtown_charleston(_l(32.7300, -79.9500, "Charleston")) is False  # James Island (S)
    assert _is_downtown_charleston(_l(32.7900, -79.8600, "Mount Pleasant")) is False  # E of Cooper R


def test_city_name_guard_beats_coords():
    # Even if coords land in the box, an explicit North Charleston city is rejected.
    assert _is_downtown_charleston(_l(32.7800, -79.9350, "North Charleston")) is False


def test_requires_coords_and_charleston_county():
    assert _is_downtown_charleston(_l(None, None)) is False
    assert _is_downtown_charleston(_l(32.7765, -79.9311, county="Berkeley")) is False

"""national.foreclosure_dot_com -- source-completeness audit, Pattern B
(2026-10-13): confirmed, not fixed.

Both row-parse paths (`_parse_search_row` off the search-view HTML,
`_parse_jsonld_node` off the city/zip JSON-LD) build `source_url` for every
row but keep only the ONE photo present on the LIST page -- the same
"detail URL built, never fetched" shape as the other Pattern B sources.

Live-reverified before touching anything (see the module docstring and
`ForeclosureDotCom`'s class-level comment for the full account): this
host's whole-site AWS-ELB block ("VPN or proxy", first seen 2026-09-23)
still answers the identical 403 to a live `/address/.../_lid` DETAIL page
directly via `get_text_impersonate()` -- not just the search/city list
URLs already known blocked. Re-checked again from a second, independent
network (the Oracle VM) against `https://www.foreclosure.com/` itself:
same 403. A detail-page gallery fetch has nothing to recover right now, so
none was wired -- these tests pin the current, intentional single-photo
behavior of both parse paths rather than silently leaving it untested.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.foreclosure_dot_com import (
    _extract_jsonld_listings,
    _parse_jsonld_node,
    _parse_search_row,
)

# Real row shape (invented address, same convention as
# test_foreclosure_dot_com_block_stop.py's SEARCH_NC fixture).
_SEARCH_ROW_CHUNK = (
    '<a href="/address/Testa-Placeholder-Rd-Shelby-NC-28150/123456_lid">'
    '<img alt="View this home at Testa Placeholder Rd, Shelby, NC 28150" '
    'src="//img.example/listingphoto/1.jpg"></a> $123,000 Single-Family'
)

_SEARCH_ROW_CHUNK_NO_PHOTO = (
    '<a href="/address/Testa-Placeholder-Rd-Shelby-NC-28150/654321_lid">'
    '<img alt="View this home at Testa Placeholder Rd, Shelby, NC 28150"></a> '
    "$99,000 Single-Family"
)


def test_search_row_keeps_exactly_one_photo():
    """The list page's own single `listingphoto` match -- the detail page
    that would carry the rest of the gallery is unreachable (whole-site
    block, re-confirmed 2026-10-13), so this is the correct ceiling right
    now, not an oversight."""
    li = _parse_search_row(_SEARCH_ROW_CHUNK, "NC", "national.foreclosure_dot_com")
    assert li is not None
    assert li.raw["images"]["real"] == ["https://img.example/listingphoto/1.jpg"]
    assert li.source_url == (
        "https://www.foreclosure.com/address/"
        "Testa-Placeholder-Rd-Shelby-NC-28150/123456_lid"
    )


def test_search_row_without_photo_markup_has_no_images_key():
    li = _parse_search_row(_SEARCH_ROW_CHUNK_NO_PHOTO, "NC", "national.foreclosure_dot_com")
    assert li is not None
    assert li.raw["images"] == {}


def _jsonld_item(image: str | None) -> dict:
    item = {
        "@type": "RealEstateListing",
        "url": "https://www.foreclosure.com/address/Moore-Dr-Spartanburg-SC-29302/12345_lid",
        "name": "Foreclosure on Moore Dr",
        "offers": {
            "itemOffered": {
                "@type": "SingleFamilyResidence",
                "address": {
                    "streetAddress": "Moore Dr",
                    "addressLocality": "Spartanburg",
                    "addressRegion": "SC",
                    "postalCode": "29302",
                },
            }
        },
    }
    if image is not None:
        item["image"] = image
    return item


def test_jsonld_node_keeps_exactly_one_photo():
    """Same ceiling on the city/zip JSON-LD path: one photo off `item.image`,
    not the gallery that would live on the (unreachable) detail page at
    `item.url` == this row's own `source_url`."""
    li = _parse_jsonld_node({"item": _jsonld_item("//img.foreclosure.com/listingphoto/abc.jpg")}, "SC", "national.foreclosure_dot_com")
    assert li is not None
    assert li.raw["images"]["real"] == ["https://img.foreclosure.com/listingphoto/abc.jpg"]
    # source_url is the detail page a gallery fetch would target -- confirmed
    # unreachable (whole-site block), which is WHY only the one photo above
    # is captured instead of a real gallery.
    assert li.source_url == _jsonld_item(None)["url"]


def test_jsonld_node_without_image_has_no_images_key():
    li = _parse_jsonld_node({"item": _jsonld_item(None)}, "SC", "national.foreclosure_dot_com")
    assert li is not None
    assert li.raw["images"] == {}


def test_extract_jsonld_listings_end_to_end_single_photo_per_row():
    """Full page-level extraction (@graph -> CollectionPage -> itemListElement)
    still surfaces exactly the one photo per row end to end."""
    import json

    doc = {
        "@graph": [
            {
                "@type": "CollectionPage",
                "mainEntity": {"itemListElement": [{"item": _jsonld_item("//img.foreclosure.com/listingphoto/xyz.jpg")}]},
            }
        ]
    }
    html = f'<script type="application/ld+json">{json.dumps(doc)}</script>'
    out = _extract_jsonld_listings(html, "SC", "national.foreclosure_dot_com")
    assert len(out) == 1
    assert out[0].raw["images"]["real"] == ["https://img.foreclosure.com/listingphoto/xyz.jpg"]

"""national.loopnet -- source-completeness audit, Pattern B follow-up
(2026-10-13): re-verified, not fixed, and a more urgent finding surfaced.

The audit flagged this module for the same "detail URL built, gallery/
contact never fetched" shape as the other Pattern B sources (the module's
own 2026-10-04 docstring already self-admits the per-listing detail page
carries a full narrative description, the broker's phone/email, and the
additional photo gallery that this scraper never fetches).

Live-reverifying that gap turned up something upstream of it: the exact
`_render()` StealthyFetcher config that loaded the search-results page
cleanly on 2026-10-04 (no CAPTCHA, no block, confirmed on 3 real cities)
now gets a hard 403 on that SAME search-results page -- reproduced from
two independent networks (this Mac, and the Oracle VM which had made zero
prior requests to loopnet.com today), with and without `real_chrome=True`.
`curl_cffi` impersonation (already known-blocked) still 403s too. See the
module docstring's 2026-10-13 note for the full account.

Net effect: there is no live listing-detail URL to safely fetch right now
-- the search page this scraper depends on for candidate URLs may itself
be walled in production. Per the owner's "don't fight a wall" rule, no
code was changed and no detail-page fetch was wired. This test file pins
the CURRENT behavior (one photo + no broker phone/email captured from the
search-results JSON-LD alone) so a future fix attempt has a clean baseline
to diff against, and documents the finding in a form `pytest` surfaces
rather than only in a docstring.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.loopnet import _node_listing

# Real shape, live-captured 2026-10-04 (Asheville, NC) -- same fixture
# convention as test_loopnet.py's _NODE_DISTRESSED.
_NODE_DISTRESSED = {
    "name": "491 Sardis Rd, Asheville, NC 28806",
    "description": "3,225 SF Retail Building Offered at $4,089,854 at a 5.50% "
                    "Cap Rate in Asheville, NC 28806 (Bank-Owned)",
    "url": "https://www.loopnet.com/Listing/491-Sardis-Rd-Asheville-NC/42292730/",
    "image": "https://images1.loopnet.com/i2/x8Pp3VhwPjyo7BkuW0GT8o7-YxgqanSFVxTDxisxtmo/106/retail-property-for-sale-491-sardis-rd-asheville-nc-28806.jpg",
    "offers": [{
        "offeredBy": {
            "worksFor": {"@type": "Organization", "name": "Horvath & Tremblay"},
            "@type": "Person", "name": "Todd Tremblay",
        },
        "price": "4089854", "priceCurrency": "USD",
        "availability": "https://schema.org/InStock", "@type": "Offer",
    }],
}


def test_search_page_node_has_no_broker_phone_or_email_field():
    """The search-results JSON-LD this module actually reaches never carries
    a phone/email at all (only agent name + brokerage name) -- confirmed by
    this module's own 2026-10-04 docstring and unchanged today. `raw["loopnet"]`
    must not claim fields this source cannot currently supply."""
    li = _node_listing(_NODE_DISTRESSED, "NC")
    assert li is not None
    raw = li.raw["loopnet"]
    assert "phone" not in raw
    assert "email" not in raw
    assert set(raw) == {
        "detail_id", "agent", "brokerage", "image", "sqft", "building_type",
        "cap_rate_pct", "matched_keywords", "name_raw", "price_raw",
    }


def test_search_page_node_image_is_a_single_url_not_a_gallery_list():
    """`raw["loopnet"]["image"]` is one URL (the search card's cover photo),
    not a list -- the real gallery lives only on the per-listing detail
    page, which is unreachable right now (see module docstring)."""
    li = _node_listing(_NODE_DISTRESSED, "NC")
    assert li is not None
    assert isinstance(li.raw["loopnet"]["image"], str)
    assert li.raw["loopnet"]["image"] == _NODE_DISTRESSED["image"]


def test_module_docstring_records_the_2026_10_13_wall_reverification():
    """Guard against the finding quietly disappearing on a future edit --
    whoever next touches this module should see why detail-page enrichment
    was not wired this pass."""
    import foreclosure_scraper.scrapers.national.loopnet as mod
    doc = mod.__doc__ or ""
    assert "2026-10-13" in doc
    assert "403" in doc

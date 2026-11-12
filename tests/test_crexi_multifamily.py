"""national.crexi_multifamily: photo-gallery fix, 2026-10-13 source-completeness
audit (Pattern B).

Before this fix the scraper never looked at a photo at all -- not even one
from a card/JSON-LD teaser, because the search-grid response it parses is
slug-only and the detail page was never fetched. Live-confirmed 2026-10-13
against 3 real NC multifamily detail pages (ids 2346159 / 2734804 / 2198267,
fetched with the scraper's own StealthyFetcher-backed `_render()`) that each
one's rendered detail page carries a real multi-photo gallery (39 / 100 / 43
unique images respectively) at
``https://crexi.com/images/format=auto,width=W,height=H/assets/<id>/<hash>.
<ext>`` -- and that the SAME page also serves a dozen or so *other* numeric
asset ids (the "similar properties" sidebar) off the identical CDN path
shape, which any un-scoped match would wrongly attribute to this listing.

The HTML fragments below are trimmed-but-real excerpts of the live
2346159/2734804 pages captured during that verification pass (same style as
the real-fixture approach in test_freddie_homesteps.py), not an invented
schema.
"""
from __future__ import annotations

import asyncio

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.national import crexi_multifamily as cx

# ---------------------------------------------------------------------------
# _extract_gallery_photos — pure parsing, real captured srcset shape.
# ---------------------------------------------------------------------------

# Real srcset block, pid 2346159, captured live 2026-10-13 against
# https://www.crexi.com/properties/2346159/north-carolina-1801-us-highway-421-n
# (one <img>/<source> worth of crop-size variants for a single real photo).
_REAL_SRCSET_PHOTO_1 = (
    'srcset="https://crexi.com/images/format=auto,width=300,height=200/assets/'
    '2346159/031c23124a194c0e9e5f9dafa4ffcdc6.JPG 300w, '
    'https://crexi.com/images/format=auto,width=900,height=600/assets/'
    '2346159/031c23124a194c0e9e5f9dafa4ffcdc6.JPG 900w, '
    'https://crexi.com/images/format=auto,width=1200,height=800/assets/'
    '2346159/031c23124a194c0e9e5f9dafa4ffcdc6.JPG 1200w, '
    'https://crexi.com/images/format=auto,width=1500,height=1000/assets/'
    '2346159/031c23124a194c0e9e5f9dafa4ffcdc6.JPG 1500w, '
    'https://crexi.com/images/format=auto,width=3000,height=2000/assets/'
    '2346159/031c23124a194c0e9e5f9dafa4ffcdc6.JPG 3000w"'
)
# A second, third, fourth real photo on the same page (different hash, same
# listing id) -- srcset trimmed to just one width each for brevity; the dedup
# logic is already exercised in full by _REAL_SRCSET_PHOTO_1 above.
_REAL_OTHER_PHOTOS_SAME_LISTING = (
    '<img src="https://crexi.com/images/format=auto,width=900,height=600/assets/'
    '2346159/6c1f6f0620da4afa977e99e87b3f0f86.JPG">'
    '<img src="https://crexi.com/images/format=auto,width=900,height=600/assets/'
    '2346159/d507f4d9b24a40f2b3933ba62b58c27d.JPG">'
    '<img src="https://crexi.com/images/format=auto,width=1200,height=800/assets/'
    '2346159/b925fd26c4244ba98b62e7e3c333f83c.JPG">'
)
# The real og:image single-photo teaser meta tag from the same live page --
# included to show the fix captures the FULL gallery, not just this one tag.
_REAL_OG_IMAGE_TEASER = (
    '<meta content="https://crexi.com/images/format=auto,width=716,height=444,'
    'fit=cover/assets/2346159/608f5d9fa63e45cd98c983deee1a143c.JPG" property="og:image">'
)
# Real "similar properties" sidebar thumbnails under OTHER listings' ids,
# captured on the same live 2346159 page -- must never be attributed to
# 2346159.
_REAL_SIDEBAR_OTHER_LISTINGS = (
    '<img src="https://crexi.com/images/format=auto,width=370,height=205/assets/'
    '2673560/6dd4eaffc08d48ec848408a6f4de4d7c.PNG">'
    '<img src="https://crexi.com/images/format=auto,width=300,height=166/assets/'
    '2192818/f940f8dc40134908b6512ef455877f81.JPG">'
)
# Real agent/user-account avatar from the same page -- different CDN path
# shape (/user-accounts/<id>/, not /assets/<id>/) so the gallery regex must
# not match it at all.
_REAL_USER_ACCOUNT_AVATAR = (
    '<img src="https://crexi.com/images/format=auto,width=828,height=828/'
    'user-accounts/140920/3b95ab6e8f4d4b5fa7a30eb338b77d80.png">'
)

_REAL_DETAIL_PAGE_EXCERPT = (
    "<html><body>"
    + _REAL_OG_IMAGE_TEASER
    + "<img " + _REAL_SRCSET_PHOTO_1 + ">"
    + _REAL_OTHER_PHOTOS_SAME_LISTING
    + _REAL_SIDEBAR_OTHER_LISTINGS
    + _REAL_USER_ACCOUNT_AVATAR
    + "</body></html>"
)


def test_extract_gallery_photos_captures_the_full_gallery_not_just_the_teaser():
    """The og:image teaser is ITSELF one real photo of this listing (also
    under /assets/2346159/, just a smaller crop) -- the fix must capture it
    PLUS the other real photos on the page, not stop at that single tag the
    way a card/JSON-LD-teaser-only scraper would."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "2346159")
    assert len(photos) == 5  # the 5 distinct /assets/2346159/ hashes above
    hashes = {p.rsplit("/", 1)[-1].split(".")[0] for p in photos}
    assert hashes == {
        "031c23124a194c0e9e5f9dafa4ffcdc6",
        "6c1f6f0620da4afa977e99e87b3f0f86",
        "d507f4d9b24a40f2b3933ba62b58c27d",
        "b925fd26c4244ba98b62e7e3c333f83c",
        "608f5d9fa63e45cd98c983deee1a143c",  # the og:image teaser's own hash
    }


def test_extract_gallery_photos_dedupes_crop_size_variants_keeping_widest():
    """031c231... appears 5 times in the real srcset (300/900/1200/1500/3000w)
    -- must collapse to ONE entry, the 3000w (widest) variant."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "2346159")
    match = [p for p in photos if "031c23124a194c0e9e5f9dafa4ffcdc6" in p]
    assert len(match) == 1
    assert "width=3000,height=2000" in match[0]


def test_extract_gallery_photos_excludes_other_listings_sidebar_images():
    """2673560 and 2192818 are real OTHER listings' thumbnails present on
    2346159's own page (the "similar properties" sidebar) -- must never leak
    into 2346159's gallery."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "2346159")
    assert all("/assets/2346159/" in p for p in photos)
    assert not any("2673560" in p or "2192818" in p for p in photos)


def test_extract_gallery_photos_excludes_user_account_avatar():
    """/user-accounts/<id>/ is a different CDN path shape than /assets/<id>/
    -- the agent headshot must not show up as a listing photo."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "2346159")
    assert not any("user-accounts" in p or "140920" in p for p in photos)


def test_extract_gallery_photos_scoped_to_a_different_pid_finds_nothing_here():
    """Asking for a pid that owns none of the images on this page returns
    empty, not a cross-attributed photo -- the id filter must be an exact
    match, not "any /assets/ hit anywhere on the page"."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "9999999999")
    assert photos == []


def test_extract_gallery_photos_sidebar_listing_only_gets_its_own_photo():
    """2673560 DOES own one real image on 2346159's page (its "similar
    properties" sidebar thumbnail) -- querying for 2673560 must return
    exactly that one, not 2346159's gallery too."""
    photos = cx._extract_gallery_photos(_REAL_DETAIL_PAGE_EXCERPT, "2673560")
    assert len(photos) == 1
    assert "/assets/2673560/" in photos[0]


def test_extract_gallery_photos_caps_at_gallery_cap():
    html = "<html><body>"
    for i in range(12):
        h = f"{i:032x}"
        html += (
            f'<img src="https://crexi.com/images/format=auto,width=900,'
            f'height=600/assets/999/{h}.JPG">'
        )
    html += "</body></html>"
    photos = cx._extract_gallery_photos(html, "999")
    assert len(photos) == cx.GALLERY_CAP == 8


@pytest.mark.parametrize("bad_html", ["", "<html></html>", "not html at all", None])
def test_extract_gallery_photos_degrades_gracefully_on_empty_or_garbage_html(bad_html):
    photos = cx._extract_gallery_photos(bad_html or "", "2346159")
    assert photos == []


# ---------------------------------------------------------------------------
# _fetch_detail_photos — the render-and-extract wrapper; a failed render must
# never raise, only ever degrade to [] so the caller's listing survives.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_detail_photos_happy_path(monkeypatch):
    async def fake_render(url):
        return _REAL_DETAIL_PAGE_EXCERPT, url

    monkeypatch.setattr(cx, "_render", fake_render)
    photos = await cx._fetch_detail_photos(
        "2346159", "https://www.crexi.com/properties/2346159/north-carolina-x"
    )
    assert len(photos) == 5


@pytest.mark.asyncio
async def test_fetch_detail_photos_empty_render_degrades_to_empty_list(monkeypatch):
    async def fake_render(url):
        return "", url

    monkeypatch.setattr(cx, "_render", fake_render)
    photos = await cx._fetch_detail_photos("2346159", "https://www.crexi.com/x")
    assert photos == []


@pytest.mark.asyncio
async def test_fetch_detail_photos_search_redirect_treated_as_failure(monkeypatch):
    """Crexi's intermittent redirect to a /search/ SEO page (no real detail
    content) must not be mistaken for a successful detail-page render."""
    async def fake_render(url):
        return _REAL_DETAIL_PAGE_EXCERPT, "https://www.crexi.com/search/foo"

    monkeypatch.setattr(cx, "_render", fake_render)
    photos = await cx._fetch_detail_photos("2346159", "https://www.crexi.com/x")
    assert photos == []


@pytest.mark.asyncio
async def test_fetch_detail_photos_render_exception_degrades_to_empty_list(monkeypatch):
    async def raising_render(url):
        raise RuntimeError("stealth browser crashed")

    monkeypatch.setattr(cx, "_render", raising_render)
    photos = await cx._fetch_detail_photos("2346159", "https://www.crexi.com/x")
    assert photos == []


# ---------------------------------------------------------------------------
# Integration: fetch() end-to-end with the network mocked out. A failed
# detail-page fetch for one listing must never drop that listing, and must
# never break the rest of the run.
# ---------------------------------------------------------------------------


def _make_listing(pid: str, state: str = "NC") -> Listing:
    return Listing(
        source="national.crexi_multifamily",
        source_url=f"https://www.crexi.com/properties/{pid}/north-carolina-test",
        listing_type=ListingType.DISTRESSED,
        property_kind=PropertyKind.MULTI_FAMILY,
        street_address="123 Test St",
        city="Asheville",
        county="Buncombe",
        state=state,
        case_number=f"crexi-{pid}",
        description="Crexi multifamily for-sale (CRE investment/value-add)",
        raw={"loopnet": {
            "crexi_id": pid, "units": None, "name": "Test Listing",
            "channel": "for_sale", "address_is_name": False,
        }},
    )


@pytest.mark.asyncio
async def test_fetch_photo_enrichment_failure_never_drops_a_listing(monkeypatch):
    """One listing's detail-page fetch raises, the other succeeds -- both
    listings must still be in the final output; the raising one simply keeps
    the pre-fix behavior (no "images" key)."""
    listings = {"1111": _make_listing("1111"), "2222": _make_listing("2222")}

    async def fake_fetch_state(state, prefix, pages_cap):
        return listings if state == "NC" else {}

    async def fake_fetch_detail_photos(pid, url):
        if pid == "1111":
            raise RuntimeError("simulated stealth-browser crash")
        return ["https://crexi.com/images/format=auto,width=3000,height=2000/"
                f"assets/{pid}/deadbeefdeadbeefdeadbeefdeadbeef.JPG"]

    monkeypatch.setattr(cx, "_fetch_state", fake_fetch_state)
    # fetch() calls the module-level _fetch_detail_photos name directly, so
    # patch it there (not just the class), mirroring how fetch() resolves it.
    monkeypatch.setattr(cx, "_fetch_detail_photos", fake_fetch_detail_photos)

    scraper = cx.CrexiMultifamily()
    out = list(await scraper.fetch())

    assert {li.case_number for li in out} == {"crexi-1111", "crexi-2222"}
    by_pid = {li.raw["loopnet"]["crexi_id"]: li for li in out}
    assert "images" not in by_pid["1111"].raw
    assert by_pid["2222"].raw["images"]["real"][0].endswith("deadbeefdeadbeefdeadbeefdeadbeef.JPG")


@pytest.mark.asyncio
async def test_fetch_photo_enrichment_respects_the_cap_not_every_listing(monkeypatch):
    """DETAIL_PHOTO_CAP bounds how many listings per state get a detail-page
    fetch at all -- confirms the cost-tradeoff documented in the module
    docstring is actually enforced, not just aspirational."""
    many = {str(i): _make_listing(str(i)) for i in range(cx.DETAIL_PHOTO_CAP + 5)}
    calls = []

    async def fake_fetch_state(state, prefix, pages_cap):
        return many if state == "NC" else {}

    async def counting_fetch_detail_photos(pid, url):
        calls.append(pid)
        return ["https://crexi.com/images/format=auto,width=3000,height=2000/"
                f"assets/{pid}/deadbeefdeadbeefdeadbeefdeadbeef.JPG"]

    monkeypatch.setattr(cx, "_fetch_state", fake_fetch_state)
    monkeypatch.setattr(cx, "_fetch_detail_photos", counting_fetch_detail_photos)

    scraper = cx.CrexiMultifamily()
    out = list(await scraper.fetch())

    assert len(out) == len(many)  # no listing dropped
    assert len(calls) == cx.DETAIL_PHOTO_CAP  # but only the capped handful enriched


@pytest.mark.asyncio
async def test_fetch_photo_enrichment_time_budget_stops_early(monkeypatch):
    """Even under DETAIL_PHOTO_CAP, a blown time budget must stop the
    enrichment loop rather than keep rendering."""
    many = {str(i): _make_listing(str(i)) for i in range(cx.DETAIL_PHOTO_CAP)}
    calls = []

    async def fake_fetch_state(state, prefix, pages_cap):
        return many if state == "NC" else {}

    async def slow_fetch_detail_photos(pid, url):
        calls.append(pid)
        return []

    monkeypatch.setattr(cx, "_fetch_state", fake_fetch_state)
    monkeypatch.setattr(cx, "_fetch_detail_photos", slow_fetch_detail_photos)
    # Force the budget to already be spent before the loop starts.
    monkeypatch.setattr(cx, "DETAIL_PHOTO_BUDGET_S", -1.0)

    scraper = cx.CrexiMultifamily()
    out = list(await scraper.fetch())

    assert len(out) == len(many)  # still nothing dropped
    assert len(calls) == 0  # but no enrichment calls were made at all

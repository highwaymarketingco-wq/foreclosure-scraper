"""national.estate_sales: 2026-10-13 source-completeness audit, Pattern B.

Before this fix the scraper captured ZERO photos -- not "kept one, dropped
the rest" like the other Pattern-B scrapers (freddie_homesteps, govdeals,
hud_homestore), genuinely none at all, even though the schema.org SaleEvent
JSON-LD on the search card already carries a single-photo "image" field the
code never read.

Live-verified 2026-10-13 against 3 real, currently-active estatesales.net
listings (fetched with a plain unauthenticated GET, no login/CAPTCHA/WAF
bypass involved):

  * A radius-search bleed listing (Johnson City, TN, sale id 5095113) --
    148 real photos.
  * An in-footprint listing (Gastonia, NC, sale id 5104050) -- 90 real
    photos.
  * A brand-new listing (Knoxville, TN, sale id 5117652) with 0 photos --
    items not yet photographed; must degrade to no gallery, not an error.

Each listing's own detail page -- already captured as source_url, never
fetched -- server-renders the full gallery into a plain (non-escaped) JSON
blob: <script id="estatesales-net-state" type="application/json">, an
Angular NGRX state-transfer dump. The sale's own entity inside it carries
`pictures` (a list of {pictureOrder, url, thumbnailUrl, ...}), `mainPicture`
(== pictures[0]) and `pictureCount`. The fixtures below reproduce that exact
real shape (trimmed to a few picture dicts instead of 90-148) rather than
inventing a different one.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.national import estate_sales as m
from foreclosure_scraper.scrapers.national.estate_sales import (
    EstateSales,
    _enrich_estatesales_net_gallery,
    _find_picture_entity,
    _is_estatesales_net_detail_url,
    _parse_detail_gallery,
)


def _picture(order: int, uuid: str, sale_id: int = 5095113) -> dict:
    """One entry in the real `pictures` list -- same keys confirmed live on
    https://www.estatesales.net/TN/Johnson-City/37601/5095113."""
    return {
        "id": 235946191 + order,
        "saleId": sale_id,
        "pictureOrder": order,
        "width": 960,
        "height": 1200,
        "thumbnailWidth": 325,
        "thumbnailHeight": 260,
        "url": f"https://picturescdn.estatesales.net/{sale_id}/1-1/{uuid}.jpg",
        "thumbnailUrl": f"https://picturescdn.estatesales.net/{sale_id}/1-2/{uuid}-thumb.jpg",
        "description": "",
        "isFeatured": False,
        "isFavorited": False,
        "utcDatePending": None,
        "utcDateSold": None,
        "lotUrl": "",
        "shouldUseContain": False,
    }


def _detail_html(sale_id: int, pictures: list[dict]) -> str:
    """A trimmed but schema-accurate estatesales-net-state blob -- same
    nesting path confirmed live: NGRX_STATE.feature.traditionalSaleViewState
    .entitiesById.<sale_id>.{pictures, mainPicture, pictureCount}."""
    entity = {
        "id": sale_id,
        "saleId": sale_id,
        "pictureCount": len(pictures),
        "pictures": pictures,
        "mainPicture": pictures[0] if pictures else None,
        "name": "Test Estate Sale",
    }
    state = {
        "NGRX_STATE": {
            "feature.traditionalSaleViewState": {
                "entitiesById": {str(sale_id): entity},
            },
        },
    }
    return (
        "<html><body>"
        f'<script id="estatesales-net-state" type="application/json">'
        f"{json.dumps(state)}</script>"
        "</body></html>"
    )


def _search_page_html(sale_id: int) -> str:
    """Shape confirmed live for the SEARCH-results page: the same
    estatesales-net-state script and the same `pictureCount` per card, but
    never the full `pictures` list (only the detail page loads that) --
    _find_picture_entity must not match this and must not mistake a
    different sale's teaser data for a gallery."""
    entity = {"id": sale_id, "saleId": sale_id, "pictureCount": 20, "name": "Teaser only"}
    state = {
        "NGRX_STATE": {
            "feature.saleRowsViewState": {
                "entitiesById": {str(sale_id): entity},
            },
        },
    }
    return (
        "<html><body>"
        f'<script id="estatesales-net-state" type="application/json">'
        f"{json.dumps(state)}</script>"
        "</body></html>"
    )


# --- _parse_detail_gallery --------------------------------------------------

# Real UUIDs confirmed live on https://www.estatesales.net/TN/Johnson-City/
# 37601/5095113 (first 3 of its real 148, in the site's own pictureOrder).
_REAL_UUIDS = [
    "0a6709c5-f7c1-4158-98cc-d7015709f2fe",
    "6976a0dc-d4da-4352-ab40-38f4f7dc33ad",
    "4f0bccfc-01d1-41c3-a50b-e3ee0b19a120",
]


def test_real_detail_page_shape_captures_multiple_photos_not_just_one():
    pictures = [_picture(i, uuid) for i, uuid in enumerate(_REAL_UUIDS)]
    html = _detail_html(5095113, pictures)
    photos = _parse_detail_gallery(html)
    assert len(photos) == 3
    assert photos == [
        "https://picturescdn.estatesales.net/5095113/1-1/0a6709c5-f7c1-4158-98cc-d7015709f2fe.jpg",
        "https://picturescdn.estatesales.net/5095113/1-1/6976a0dc-d4da-4352-ab40-38f4f7dc33ad.jpg",
        "https://picturescdn.estatesales.net/5095113/1-1/4f0bccfc-01d1-41c3-a50b-e3ee0b19a120.jpg",
    ]


def test_gallery_is_capped_at_eight_even_when_the_real_total_is_much_larger():
    # Real totals measured live were 148 and 90 -- build 12 here to prove the
    # cap engages without needing a 148-entry fixture.
    pictures = [_picture(i, f"uuid-{i:03d}") for i in range(12)]
    photos = _parse_detail_gallery(_detail_html(5104050, pictures))
    assert len(photos) == 8
    assert photos[0].endswith("uuid-000.jpg")
    assert photos[-1].endswith("uuid-007.jpg")


def test_gallery_is_ordered_by_the_sites_own_pictureOrder_not_list_order():
    # Shuffle the list order but keep real pictureOrder values -- the organizer's
    # chosen lead/cover photo (mainPicture, pictureOrder 0) must come first
    # regardless of where it sits in the raw JSON array.
    p0, p1, p2 = (_picture(0, "zzz-first", sale_id=1), _picture(1, "mid", sale_id=1),
                  _picture(2, "last", sale_id=1))
    shuffled = [p2, p0, p1]
    photos = _parse_detail_gallery(_detail_html(1, shuffled))
    assert photos == [
        "https://picturescdn.estatesales.net/1/1-1/zzz-first.jpg",
        "https://picturescdn.estatesales.net/1/1-1/mid.jpg",
        "https://picturescdn.estatesales.net/1/1-1/last.jpg",
    ]


def test_duplicate_photo_urls_are_deduped():
    dup = _picture(0, "same-uuid", sale_id=1)
    photos = _parse_detail_gallery(_detail_html(1, [dup, dict(dup, pictureOrder=1)]))
    assert photos == ["https://picturescdn.estatesales.net/1/1-1/same-uuid.jpg"]


def test_brand_new_listing_with_zero_photos_yet_returns_empty_not_an_error():
    """Live-confirmed on https://www.estatesales.net/TN/Knoxville/37909/
    5117652 -- items not yet photographed. pictureCount is 0 and `pictures`
    is an empty list (key present), not missing."""
    photos = _parse_detail_gallery(_detail_html(5117652, []))
    assert photos == []


def test_search_page_shape_never_yields_a_wrong_gallery():
    """The search-results page has the same script id and the same
    `pictureCount` field per card, but never the full `pictures` list.
    _find_picture_entity must not match it and must not fabricate a gallery
    out of unrelated teaser data."""
    assert _parse_detail_gallery(_search_page_html(5095113)) == []
    search_state = {
        "NGRX_STATE": {
            "feature.saleRowsViewState": {
                "entitiesById": {"5095113": {"id": 5095113, "pictureCount": 20}},
            },
        },
    }
    assert _find_picture_entity(search_state) is None


@pytest.mark.parametrize("bad_html", [
    "",
    "<html><body>nothing here at all</body></html>",
    '<html><body><script id="estatesales-net-state" type="application/json">{not valid json</script></body></html>',
    '<html><body><script id="estatesales-net-state" type="application/json">null</script></body></html>',
])
def test_malformed_or_missing_state_blob_degrades_to_empty_list(bad_html):
    assert _parse_detail_gallery(bad_html) == []


# --- _is_estatesales_net_detail_url -----------------------------------------

def test_detail_url_shape_is_recognized():
    assert _is_estatesales_net_detail_url(
        "https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    assert _is_estatesales_net_detail_url(
        "https://www.estatesales.net/NC/Gastonia/28054/5104050")


def test_bare_search_page_url_is_not_treated_as_a_detail_url():
    """_saleevent_to_listing can fall back to the SEARCH page's own URL when
    a SaleEvent node has no "url" field -- re-fetching that would waste a
    request for a gallery fetch that could never match anyway."""
    assert not _is_estatesales_net_detail_url("https://www.estatesales.net/NC/Asheville/")
    assert not _is_estatesales_net_detail_url("https://www.estatesales.net/NC/Asheville")
    assert not _is_estatesales_net_detail_url(None)
    assert not _is_estatesales_net_detail_url("")


# --- _enrich_estatesales_net_gallery -----------------------------------------

def _listing(source_url: str, source_site: str = "estatesales.net") -> Listing:
    return Listing(
        source="national.estate_sales",
        source_url=source_url,
        listing_type=ListingType.ESTATE_LEAD,
        property_kind=PropertyKind.UNKNOWN,
        raw={"estate_sales": {"source_site": source_site, "title": "Test Sale"}},
    )


def test_enrich_attaches_real_images_on_success(monkeypatch):
    html = _detail_html(5095113, [_picture(0, _REAL_UUIDS[0])])
    monkeypatch.setattr(m, "_fetch_text", lambda *a, **kw: _async_return(html))
    li = _listing("https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    asyncio.run(_enrich_estatesales_net_gallery(li))
    assert li.raw["images"] == {
        "real": ["https://picturescdn.estatesales.net/5095113/1-1/"
                 "0a6709c5-f7c1-4158-98cc-d7015709f2fe.jpg"]
    }


def test_enrich_never_raises_on_a_failed_fetch_and_leaves_listing_untouched(monkeypatch):
    async def _boom(*a, **kw):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(m, "_fetch_text", _boom)
    li = _listing("https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    asyncio.run(_enrich_estatesales_net_gallery(li))  # must not raise
    assert "images" not in li.raw


def test_enrich_never_raises_on_garbage_html(monkeypatch):
    monkeypatch.setattr(m, "_fetch_text", lambda *a, **kw: _async_return("<html>garbage</html>"))
    li = _listing("https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    asyncio.run(_enrich_estatesales_net_gallery(li))  # must not raise
    assert "images" not in li.raw


def test_enrich_skips_non_detail_urls_without_a_network_call(monkeypatch):
    def _must_not_be_called(*a, **kw):
        raise AssertionError("_fetch_text should not be called for a non-detail URL")

    monkeypatch.setattr(m, "_fetch_text", _must_not_be_called)
    li = _listing("https://www.estatesales.net/NC/Asheville/")
    asyncio.run(_enrich_estatesales_net_gallery(li))  # must not raise / not fetch
    assert "images" not in li.raw


async def _async_return(value):
    return value


# --- EstateSales.fetch() wiring ---------------------------------------------

def test_fetch_attaches_galleries_and_survives_one_failed_detail_fetch(monkeypatch):
    """End-to-end: two estatesales.net rows (one gallery succeeds, one
    detail fetch fails) plus one estatesale.com row (must be skipped, no
    network call attempted for it) -- all three still ship."""
    good = _listing("https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    bad = _listing("https://www.estatesales.net/NC/Gastonia/28054/5104050")
    other_site = _listing(
        "https://www.estatesale.com/sales/view/999", source_site="estatesale.com")

    async def _fake_net(zip_code, city, state, county):
        if zip_code == "28801":
            return [good, bad]
        if zip_code == "28792":
            return [other_site]
        return []

    async def _fake_com(zip_code, city, state, county):
        return []

    fetch_calls: list[str] = []

    async def _fake_fetch_text(url, timeout=20.0, headers=None):
        fetch_calls.append(url)
        if url == good.source_url:
            return _detail_html(5095113, [_picture(0, _REAL_UUIDS[0])])
        raise ConnectionError("simulated failure for the 'bad' listing")

    monkeypatch.setattr(m, "_fetch_estatesales_net", _fake_net)
    monkeypatch.setattr(m, "_fetch_estatesale_com", _fake_com)
    monkeypatch.setattr(m, "_fetch_text", _fake_fetch_text)
    monkeypatch.setattr(m, "SEARCH_ZIPS", (
        ("28801", "Asheville", "NC", "Buncombe"),
        ("28792", "Hendersonville", "NC", "Henderson"),
    ))

    s = EstateSales()
    out = asyncio.run(asyncio.wait_for(s.fetch(), timeout=5.0))

    # All three rows ship regardless of gallery outcome.
    assert len(out) == 3
    by_url = {li.source_url: li for li in out}
    assert by_url[good.source_url].raw["images"]["real"] == [
        "https://picturescdn.estatesales.net/5095113/1-1/"
        "0a6709c5-f7c1-4158-98cc-d7015709f2fe.jpg"
    ]
    assert "images" not in by_url[bad.source_url].raw
    assert "images" not in by_url[other_site.source_url].raw

    # The estatesale.com row must never trigger a detail-page fetch at all.
    assert other_site.source_url not in fetch_calls
    assert set(fetch_calls) == {good.source_url, bad.source_url}


def test_fetch_sets_partial_to_list_rows_before_gallery_enrichment(monkeypatch):
    """self.partial must hold the list-page rows BEFORE any detail-page
    gallery fetch runs, so a soft-timeout mid-enrichment still salvages
    every row already found (base_scraper.safe_run's partial path)."""
    row = _listing("https://www.estatesales.net/TN/Johnson-City/37601/5095113")
    partial_snapshot: list = []

    async def _fake_net(zip_code, city, state, county):
        return [row] if zip_code == "28801" else []

    async def _fake_com(zip_code, city, state, county):
        return []

    async def _fake_fetch_text(url, timeout=20.0, headers=None):
        # Capture what self.partial looked like at the moment the FIRST
        # detail-page fetch fires -- must already equal the deduped list.
        partial_snapshot.append(list(s.partial))
        return _detail_html(5095113, [_picture(0, _REAL_UUIDS[0])])

    monkeypatch.setattr(m, "_fetch_estatesales_net", _fake_net)
    monkeypatch.setattr(m, "_fetch_estatesale_com", _fake_com)
    monkeypatch.setattr(m, "_fetch_text", _fake_fetch_text)
    monkeypatch.setattr(m, "SEARCH_ZIPS", (("28801", "Asheville", "NC", "Buncombe"),))

    s = EstateSales()
    out = asyncio.run(asyncio.wait_for(s.fetch(), timeout=5.0))

    assert len(partial_snapshot) == 1
    assert partial_snapshot[0] == out
    assert [li.source_url for li in partial_snapshot[0]] == [row.source_url]

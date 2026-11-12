"""Cott RecordRoom adapter (Union SC) — HTML cleaning, distress filter, classify."""
from __future__ import annotations

import pytest

from foreclosure_scraper.rod import cott_recordroom as cr
from foreclosure_scraper.scrapers.counties_sc.sc_rod_cott import _classify, _to_listing
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.rod.models import RodDoc


def test_clean_strips_html():
    assert cr._clean("<div>DENKERS, TIMOTHY</div>") == "DENKERS, TIMOTHY"
    assert cr._clean("DEE<br/>DIS STMT") == "DEE DIS STMT"
    assert cr._clean(None) == ""


def test_is_distress():
    assert cr.is_distress("DEE<br/>DOD") is True            # deed of distribution
    assert cr.is_distress("<div>DEATH/C</div>") is True
    assert cr.is_distress("TAX LIEN") is True
    assert cr.is_distress("DEED") is False
    assert cr.is_distress("SAT TAX LIEN") is False          # resolution excluded
    # 2026-10-04 (batch 13): "DIS STMT" is NOT a probate signal. Live-pulled
    # every "DEE DIS STMT" row Union has recorded in the last 90 days (37 of
    # them, 74% of this adapter's live output) -- all 37 are "HOMEOWNERS
    # DISCLOSURE STATEMENT" filings with the Dept of Building Safety / City
    # Planning Dept as the counterparty, never an estate distribution
    # statement. Was a 100% false-positive match; removed from _DISTRESS.
    assert cr.is_distress("DEE<br/>DIS STMT") is False


def test_classify():
    assert _classify("DEED OF DISTRIBUTION")[0] is ListingType.PROBATE_NOTICE
    assert _classify("DEATH/C")[0] is ListingType.PROBATE_NOTICE
    assert _classify("TAX LIEN")[0] is ListingType.TAX_LIEN
    assert _classify("SAT LIEN") is None
    assert _classify("DEED") is None
    # Same false-positive fix as test_is_distress, on the scraper-side classifier.
    assert _classify("DIS STMT") is None


def test_property_block_extraction():
    """Parcel #, situs address, remarks and $ consideration embedded inside the
    vendor's own HTML cells (not plain text) -- live-shaped sample from a real
    Union "DEE DOD" deed-of-distribution row (2026-10-04 audit)."""
    prop_html = (
        '<div><div data-propertyid="16734651"><div class="indexdetail_primary">'
        '<strong>City Name:</strong> <span class="indexdetail_data">UNION COUNTY</span> '
        '<strong>Parcel #:</strong> <span class="indexdetail_data">'
        '<a class="gpinActive" href="../../Search?parcelNumber=074-10-02-003">074-10-02-003</a>'
        '</span> <strong>Remarks:</strong> <span class="indexdetail_data">LOT OF LAND W/IMP '
        'FRONTING ON PERRIN AVENUE. SEE INSTRUMENT</span></div>'
        '<div class="indexdetail_address"><strong>Address: </strong>'
        '<span class="indexdetail_data">709 PERRIN AVENUE  UNION, SC 29379</span></div>'
        '</div></div>'
    )
    assert cr._extract_parcel(prop_html) == "074-10-02-003"
    assert cr._extract_block_address(prop_html) == "709 PERRIN AVENUE UNION, SC 29379"
    assert cr._extract_remarks(prop_html) == "LOT OF LAND W/IMP FRONTING ON PERRIN AVENUE. SEE INSTRUMENT"
    assert cr._extract_amount(prop_html) is None  # deed of distribution: no consideration

    deed_html = (
        '<span class="amtDesc"> <strong>Amount:</strong> $500.00</span>'
        '<div><div data-propertyid="1"><div class="indexdetail_primary">'
        '<strong>Parcel #:</strong> <span class="indexdetail_data">'
        '<a href="#">074-07-13-001.000</a></span></div></div></div>'
    )
    assert cr._extract_amount(deed_html) == 500.00

    party_html = (
        '<div>KNOX, BARBARA DOVER<div class="indexdetail_address">'
        '<span class="indexdetail_label">Address: </span>'
        '<span class="indexdetail_data">522 T BISHOP ROAD JONESVILLE, SC 29353</span>'
        '</div></div>'
    )
    assert cr._extract_block_address(party_html) == "522 T BISHOP ROAD JONESVILLE, SC 29353"
    assert cr._extract_parcel(party_html) is None


def test_to_listing_wires_parcel_and_address():
    """sc_rod_cott._to_listing must carry parcel_id/street_address through from
    the RodDoc, matching the sibling sc_rod_acclaim.py convention (previously
    missing entirely on this adapter -- see test_property_block_extraction)."""
    d = RodDoc(county="Union", state="SC", doc_type="DEED OF DISTRIBUTION",
               grantor="ALLEN, FLOYD", instrument_no="2026000123", notes="LOT 5",
               parcel_id="074-10-02-003", property_address="709 PERRIN AVENUE UNION, SC 29379",
               raw={"cott_recordroom": {"grantee_address": "522 T BISHOP ROAD JONESVILLE, SC 29353",
                                        "consideration_amount": 500.0}})
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.parcel_id == "074-10-02-003"
    assert li.street_address == "709 PERRIN AVENUE UNION, SC 29379"
    assert li.raw["rod"]["grantee_address"] == "522 T BISHOP ROAD JONESVILLE, SC 29353"
    assert li.raw["rod"]["consideration_amount"] == 500.0


def test_to_listing_probate_tags_signal():
    d = RodDoc(county="Union", state="SC", doc_type="DEED OF DISTRIBUTION",
               grantor="ALLEN, FLOYD", instrument_no="2026000123", notes="LOT 5")
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.listing_type is ListingType.PROBATE_NOTICE
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.defendant == "ALLEN, FLOYD" and li.county == "Union"


def test_union_wired():
    assert ("SC", "Union") in cr.COTT_RR_COUNTIES


# --- document images (added 2026-10-14) --------------------------------------
# The docstring contradiction the 2026-10-13 source-completeness audit flagged:
# this module used to claim "document images are pay-per-view" while
# rod/doc_images.py's COUNTY_IMAGE_STATUS registered Union as confirmed "free",
# and owner_dot_documents() had no vendor=="cott" branch at all. Live-checked
# 2026-10-14 against 3 real Union documents (death certificate, $540k deed,
# $42k mortgage) -- genuinely free, no login, no payment, no browser -- see
# this module's own docstring for the full evidence. The UI's own "View
# Document" route (Imaging/Document/KeyFromImage) IS login-walled; it is NOT
# what the fixes below use.
_BASE = "https://recordroom.cottsystems.com/unionsc"

# Real (trimmed) `Imaging/Document/Thumbnails?indexId=51371162` response,
# page 1 of a live 15-page MTG (Founders Federal Credit Union, $42,000 note),
# captured 2026-10-14. The `Serialized` string is the exact live value --
# everything else in this one-page document had no redaction rectangles, so
# nothing was trimmed out of it.
_LIVE_THUMBNAILS_PAGE1 = {
    "PageId": 539135, "OrganizationId": 185, "Version": 2, "Book": "340",
    "Page": "243", "ScanPages": 15, "RecordingDate": "2026-10-13T12:04:28",
    "IndexType": "MTG", "IndexTypeName": "MORTGAGES", "KindCode": "MTG",
    "KindCodeDescription": "MORTGAGES", "TotalPages": 15, "FirstPageId": 539135,
    "IndexId": 51371162, "DocumentId": 132690, "VolumeId": 3,
    "Name": "83450158-1.tif", "PageNumber": 1, "Status": 3,
    "Serialized": (
        '{"objects":[{"type":"image","originX":"left","originY":"top","left":0,'
        '"top":0,"width":2550,"height":3300,"fill":"rgb(0,0,0)","stroke":null,'
        '"strokeWidth":0,"strokeDashArray":null,"strokeLineCap":"butt",'
        '"strokeLineJoin":"miter","strokeMiterLimit":10,"scaleX":1,"scaleY":1,'
        '"angle":0,"flipX":false,"flipY":false,"opacity":1,"shadow":null,'
        '"visible":true,"clipTo":null,"backgroundColor":"","fillRule":"nonzero",'
        '"globalCompositeOperation":"source-over","transformMatrix":null,'
        '"skewX":0,"skewY":0,"crossOrigin":"use-credentials","alignX":"none",'
        '"alignY":"none","meetOrSlice":"meet",'
        '"src":"https://recordroom.cottsystems.com/unionsc/Imaging/Document/'
        'Image?PageId=539135&imageAction=eRecordingTransaction&DocumentId='
        '132690&Version=1&VolumeId=3&Name=83450158-1.tif&'
        'r=0.0028293278716251535","filters":[],"resizeFilters":[]}]}'
    ),
}
_LIVE_IMAGE_URL = (
    f"{_BASE}/Imaging/Document/Image?PageId=539135&imageAction="
    "eRecordingTransaction&DocumentId=132690&Version=1&VolumeId=3&"
    "Name=83450158-1.tif&r=0.0028293278716251535"
)


def test_image_fetch_recipe():
    r = cr.image_fetch_recipe(_BASE, 51371162)
    assert r == {
        "method": "GET",
        "thumbnails_url": f"{_BASE}/Imaging/Document/Thumbnails?indexId=51371162&indexAction=Search",
        "details_referer": f"{_BASE}/Guest/Search/Records/Details?IndexId=51371162",
        "index_id": 51371162,
    }
    # trailing slash on base is tolerated
    assert cr.image_fetch_recipe(_BASE + "/", 51371162)["index_id"] == 51371162
    # the grid's own float-encoded id shape
    assert cr.image_fetch_recipe(_BASE, 51371162.0)["index_id"] == 51371162
    assert cr.image_fetch_recipe(_BASE, "51371162")["index_id"] == 51371162


def test_image_fetch_recipe_rejects_bad_ids():
    for bad in (None, "", "  ", "not-a-number", 0, -5):
        assert cr.image_fetch_recipe(_BASE, bad) is None


def test_document_image_url_from_real_thumbnails_response():
    """The exact live 2026-10-14 Thumbnails payload for IndexId 51371162 --
    live-refetched the same URL this extracts and confirmed 200 image/png,
    415571 bytes, matching this adapter's own equity-engine use case (the
    $42,000 principal is on page 1 of this note)."""
    assert cr.document_image_url([_LIVE_THUMBNAILS_PAGE1], page_number=1) == _LIVE_IMAGE_URL


def test_document_image_url_page_not_found_or_bad_input():
    assert cr.document_image_url([_LIVE_THUMBNAILS_PAGE1], page_number=2) is None
    assert cr.document_image_url(None) is None
    assert cr.document_image_url([]) is None
    assert cr.document_image_url("not-a-list") is None
    assert cr.document_image_url([{"PageNumber": "not-a-number"}]) is None
    assert cr.document_image_url([{"PageNumber": 1}]) is None  # no Serialized at all


def test_document_image_url_unescapes_amp():
    url = f"{_BASE}/Imaging/Document/Image?PageId=1&amp;DocumentId=2"
    page = {"PageNumber": 1, "Serialized": f'{{"objects":[{{"src":"{url}","type":"image"}}]}}'}
    assert (cr.document_image_url([page], page_number=1)
            == f"{_BASE}/Imaging/Document/Image?PageId=1&DocumentId=2")


class _FakeResponse:
    def __init__(self, status_code=200, content=b"", content_type="image/png", json_data=None):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("no json configured")
        return self._json_data


class _FakeClient:
    """Stands in for the project's shared httpx client -- records every call
    (url, headers) and returns the next canned _FakeResponse."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url, headers=None, **kw):
        self.calls.append((url, dict(headers or {})))
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_fetch_document_image_sends_referer_on_both_requests():
    """Live-caught 2026-10-14: the Thumbnails call ALSO needs the Referer (not
    just the Image call) -- an otherwise-identical request without it IIS-401s
    even with valid session cookies. This test pins that regression."""
    import json as _json
    c = _FakeClient([
        _FakeResponse(200, json_data=[_LIVE_THUMBNAILS_PAGE1]),
        _FakeResponse(200, content=b"\x89PNG...", content_type="image/png"),
    ])
    got = await cr.fetch_document_image(c, _BASE, 51371162)
    assert got == (b"\x89PNG...", "image/png")
    assert len(c.calls) == 2
    thumb_url, thumb_headers = c.calls[0]
    img_url, img_headers = c.calls[1]
    assert thumb_url == f"{_BASE}/Imaging/Document/Thumbnails?indexId=51371162&indexAction=Search"
    assert img_url == _LIVE_IMAGE_URL
    expected_referer = f"{_BASE}/Guest/Search/Records/Details?IndexId=51371162"
    assert thumb_headers["Referer"] == expected_referer
    assert img_headers["Referer"] == expected_referer


@pytest.mark.asyncio
async def test_fetch_document_image_rejects_non_image_response():
    """A wrong/missing Referer 302s to the login route, which client()'s
    default follow_redirects turns into a 200 text/html page -- must not be
    mistaken for a real image."""
    c = _FakeClient([
        _FakeResponse(200, json_data=[_LIVE_THUMBNAILS_PAGE1]),
        _FakeResponse(200, content=b"<html>login</html>", content_type="text/html"),
    ])
    assert await cr.fetch_document_image(c, _BASE, 51371162) is None


@pytest.mark.asyncio
async def test_fetch_document_image_bad_index_id_makes_no_requests():
    c = _FakeClient([])
    assert await cr.fetch_document_image(c, _BASE, None) is None
    assert await cr.fetch_document_image(c, _BASE, 0) is None
    assert c.calls == []


@pytest.mark.asyncio
async def test_fetch_document_image_thumbnails_failure_returns_none():
    c = _FakeClient([_FakeResponse(401, content=b"Access is denied")])
    assert await cr.fetch_document_image(c, _BASE, 51371162) is None


def test_discover_recent_nods_row_captures_index_id_and_image_fetch():
    """The grid row's IndexId/HasFiledImage/ScanPages ride along on every
    search result (confirmed live 2026-10-14) but were previously captured
    nowhere on this adapter. A document with HasFiledImage must get a
    resolvable image_fetch recipe; one without must not."""
    import asyncio
    import httpx

    live_row_with_image = {
        "IndexId": 51372174, "ScanPages": 1, "RecordingDate": "10/13/2026",
        "Type": "DEE<br/>DEATH/C", "PartyOne": "<div>MURPHY, MARY S.</div>",
        "PartyTwo": "<div>MURPHY, MARY S.</div>", "Property": None,
        "FileNumber": "202600001", "BookPage": "  333 /   799", "HasFiledImage": 1,
    }
    live_row_no_image = dict(live_row_with_image, IndexId=51372175,
                             FileNumber="202600002", ScanPages=0, HasFiledImage=0)

    async def _fake_transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/guest/Search/records"):
            return httpx.Response(200, text="<html></html>")
        if request.url.path.endswith("/search/Records"):
            return httpx.Response(200, text="ok")
        if request.url.path.endswith("/Search/Records/Result/"):
            return httpx.Response(200, json={"recordsTotal": 2,
                                              "data": [live_row_with_image, live_row_no_image]})
        return httpx.Response(404)

    orig_client = cr.client

    def _patched_client(**kw):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm():
            async with httpx.AsyncClient(transport=httpx.MockTransport(_fake_transport)) as c:
                yield c
        return _cm()

    cr.client = _patched_client
    try:
        docs = asyncio.run(cr.discover_recent_nods("SC", "Union", days_back=5, max_docs=10))
    finally:
        cr.client = orig_client

    assert len(docs) == 2
    by_inst = {d.instrument_no: d for d in docs}

    with_image = by_inst["202600001"].raw["cott_recordroom"]
    assert with_image["index_id"] == 51372174
    assert with_image["has_filed_image"] is True
    assert with_image["scan_pages"] == 1
    assert with_image["image_fetch"] == cr.image_fetch_recipe(
        "https://recordroom.cottsystems.com/unionsc", 51372174)

    no_image = by_inst["202600002"].raw["cott_recordroom"]
    assert no_image["index_id"] == 51372175
    assert no_image["has_filed_image"] is False
    assert "image_fetch" not in no_image


# --- sc_rod_cott.py surfaces the recipe into Listing.raw ----------------------
def test_to_listing_stamps_cott_image_fetch_into_raw():
    """_to_listing surfaces rod/cott_recordroom.py's free image-fetch recipe
    into its own dedicated raw key -- NOT document_links.stamp_documents's
    raw['document_url']/raw['documents'], because resolving it needs a
    Referer-bearing Thumbnails request first that the generic, GET-only
    enrich_doc_ocr.py pass can't do (same reasoning as
    raw['beaufort_pdf_fetch']/raw['clarendon_pdf_fetch'] in sc_rod_walled.py)."""
    recipe = cr.image_fetch_recipe(cr.COTT_RR_HOST + "/unionsc", 51372174)
    d = RodDoc(county="Union", state="SC", doc_type="DEATH/C",
               grantor="MURPHY, MARY S.", instrument_no="202600001", notes="",
               raw={"cott_recordroom": {"index_id": 51372174, "has_filed_image": True,
                                        "scan_pages": 1, "image_fetch": recipe}})
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert li.raw["cott_image_fetch"] == recipe
    assert "document_url" not in li.raw
    assert "documents" not in li.raw


def test_to_listing_no_image_fetch_block_without_recipe():
    d = RodDoc(county="Union", state="SC", doc_type="LIEN", grantor="DOE, JANE",
               instrument_no="202600002",
               raw={"cott_recordroom": {"index_id": 51372176, "has_filed_image": False}})
    li = _to_listing(d, "counties_sc.sc_rod_cott", "http://x")
    assert "cott_image_fetch" not in li.raw

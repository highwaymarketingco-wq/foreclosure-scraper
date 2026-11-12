"""Pin the 2026-10-13 fix in national/auction_dot_com.py (source-completeness
audit, Pattern D): the module docstring's "AUDITED, NOT FIXED" note found
real, per-property PURCHASE_AGREEMENT / LOCAL_DISCLOSURE PDFs on the detail
page (under .../propertyDocuments/{id}/...) that this scraper never fetched
-- flagged and left, reasoning the fix would need "~100+ individual detail
pages per run through Scrapling's full stealth browser".

Live-verified 2026-10-13 that framing was the wrong cost model (see the
module docstring's FIXED 2026-10-13 section for the full detail):
  - The detail page is server-rendered (embeds a plain
    ``<script>window.INITIAL_STATE = {...}</script>`` JS object literal) --
    no browser/JS execution needed to read it, just a GET.
  - It sits behind the same Incapsula WAF as the list pages, but a plain
    curl-cffi (Chrome TLS/JA3 impersonation, no browser) session that has
    ever gotten ONE clean response stays good for every request after it in
    that same session (live-verified 5/5 across 3 distinct real detail IDs,
    repeated warm-up+fetch runs: 2197585, 2148364, 2045737).
  - Real detail id 2197585 (2003 Plain Field Dr, Bessemer City NC) carried
    two real per-property documents (property id 1491107): a
    PURCHASE_AGREEMENT and a LOCAL_DISCLOSURE, each a bare
    ``adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/...`` URL
    that itself 200'd ``application/pdf`` on a completely unauthenticated,
    no-session plain ``httpx`` GET.
  - Real detail id 2045737 (1402 Tom Pepper Rd, Creswell NC) had an EMPTY
    per-property ``documents: []`` but a populated sibling
    ``applicable_global_documents`` (11 entries) -- the boilerplate PSA/
    disclosure template every listing ships with, not property-specific,
    including some non-``propertyDocuments/`` URLs (``globalDocuments/``
    *and* a totally different host, ``auction.box.com``) -- confirming
    the real per-property array must be told apart from this sibling, which
    the ``/propertyDocuments/`` URL-path filter below does.

These fixtures are synthetic markup (no network calls) but schema-accurate:
the real JSON shapes captured live above (minus unrelated noise) are reused
verbatim.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.scrapers.national import auction_dot_com as adc

# --- real captured shapes ---------------------------------------------------

# Live-captured 2026-10-13, detail id 2197585, property id 1491107: the
# per-property `documents` array sitting at shellState.listing.documents in
# the detail page's embedded window.INITIAL_STATE blob, verbatim.
_REAL_TWO_DOC_HTML = """
<html><body><script>
window.INITIAL_STATE = {"shellState":{"listing":{"applicable_global_documents":[{"__typename":"GlobalMedia","media_purpose_type_code":"PURCHASE_AGREEMENT","media_download_uri":"https://adc-tenbox-prod.imgix.net/resi/globalDocuments/PSA%20Residential%20PSA%2010.1.2023.v1.pdf"}],"documents":[{"document_external_title":"02FD30B5195649C4817AC4A149D10B66.v1","updated_date":"2026-09-30T12:28:26.148362Z","metadata":{"document_purpose_type_code":"PURCHASE_AGREEMENT"},"file_descriptor":{"urls":{"cdn":"https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/PURCHASE_AGREEMENT/026202711AFF4809A003F82ABCA3BDE3.v1.pdf","download":"https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/PURCHASE_AGREEMENT/026202711AFF4809A003F82ABCA3BDE3.v1.pdf"}}},{"document_external_title":"MOG_2003","updated_date":"2026-09-30T22:19:20.883633Z","metadata":{"document_purpose_type_code":"LOCAL_DISCLOSURE"},"file_descriptor":{"urls":{"cdn":"https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/LOCAL_DISCLOSURE/6DED208052904A00B6C4B06E1E656A20.v1.pdf","download":"https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/LOCAL_DISCLOSURE/6DED208052904A00B6C4B06E1E656A20.v1.pdf"}}}]}}};
</script></body></html>
"""

_REAL_PURCHASE_AGREEMENT_URL = (
    "https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/"
    "PURCHASE_AGREEMENT/026202711AFF4809A003F82ABCA3BDE3.v1.pdf"
)
_REAL_LOCAL_DISCLOSURE_URL = (
    "https://adc-tenbox-prod.imgix.net/resi/propertyDocuments/1491107/"
    "LOCAL_DISCLOSURE/6DED208052904A00B6C4B06E1E656A20.v1.pdf"
)

# Live-captured 2026-10-13, detail id 2045737: empty per-property documents,
# alongside the real (trimmed to 3/11 for brevity) boilerplate
# applicable_global_documents sibling -- must NOT be swept in.
_REAL_EMPTY_DOCS_WITH_GLOBAL_HTML = """
<html><body><script>
window.INITIAL_STATE = {"shellState":{"listing":{"applicable_global_documents":[{"__typename":"GlobalMedia","media_purpose_type_code":"PURCHASE_AGREEMENT","media_download_uri":"https://adc-tenbox-prod.imgix.net/resi/globalDocuments/PSA%20Residential%20PSA%2010.1.2023.v1.pdf"},{"__typename":"GlobalMedia","media_purpose_type_code":"DISCLOSURE","media_download_uri":"https://adc-tenbox-prod.imgix.net/resi/globalDocuments/NC%20REO%20State%20Rider.v3.pdf"},{"__typename":"GlobalMedia","media_purpose_type_code":"DISCLOSURE","media_download_uri":"https://auction.box.com/shared/static/w9lw0tifms274qm8x06khdsobyy2ftcj.pdf"}],"documents":[]}}};
</script></body></html>
"""

_INCAPSULA_WALL_HTML = (
    '<html style="height:100%"><head></head><body>'
    '<iframe id="main-iframe" src="/_Incapsula_Resource?...">'
    "Request unsuccessful. Incapsula incident ID: 1007000132430754139-x"
    "</iframe></body></html>"
)


def _listing(detail_id: str, url: str) -> Listing:
    from datetime import datetime
    return Listing(
        source="national.auction_dot_com",
        source_url=url,
        listing_type=ListingType.AUCTION,
        property_kind=PropertyKind.SINGLE_FAMILY,
        street_address="2003 Plain Field Dr",
        city="Bessemer City",
        county="Gaston",
        state="NC",
        zip_code="28016",
        case_number=f"auctioncom-{detail_id}",
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        raw={"auction_dot_com": {"detail_id": detail_id}},
    )


# --- _extract_balanced_json_array / _property_document_urls ---------------

def test_property_document_urls_real_two_doc_page():
    urls = adc._property_document_urls(_REAL_TWO_DOC_HTML)
    assert urls == [_REAL_PURCHASE_AGREEMENT_URL, _REAL_LOCAL_DISCLOSURE_URL]


def test_property_document_urls_excludes_global_boilerplate_when_empty():
    """The real 2045737 shape: documents is genuinely empty, and the
    populated sibling applicable_global_documents (shared PSA template,
    not property-specific, confirmed live) must never leak through."""
    assert adc._property_document_urls(_REAL_EMPTY_DOCS_WITH_GLOBAL_HTML) == []


def test_property_document_urls_filters_non_property_document_path():
    """Defensive: even if a documents[] entry ever carried a non-
    propertyDocuments URL (e.g. the globalDocuments/ or auction.box.com
    shapes seen live in applicable_global_documents), _PROPERTY_DOC_URL_RE
    must exclude it rather than trust the array name alone."""
    html = """
    <script>window.INITIAL_STATE = {"shellState":{"listing":{"documents":[
      {"metadata":{"document_purpose_type_code":"PURCHASE_AGREEMENT"},
       "file_descriptor":{"urls":{"cdn":
         "https://adc-tenbox-prod.imgix.net/resi/globalDocuments/boilerplate.pdf"}}}
    ]}}};</script>
    """
    assert adc._property_document_urls(html) == []


def test_property_document_urls_no_documents_key_at_all():
    assert adc._property_document_urls("<html><body>no state here</body></html>") == []


def test_property_document_urls_malformed_json_does_not_raise():
    html = '<script>window.INITIAL_STATE = {"documents":[{"broken": ]};</script>'
    assert adc._property_document_urls(html) == []


# --- _capture_property_documents end-to-end (fake curl-cffi session) ------

class _FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    """Duck-types curl_cffi.requests.AsyncSession's async `.get()` just
    enough for _warm_incapsula_session / _fetch_property_doc_urls: tracks
    every call and answers from a per-URL queue (so a warm-up retry can be
    tested) or a per-URL fixed response."""

    def __init__(self, *, homepage_responses=None, by_url=None):
        self.calls: list[str] = []
        self._homepage_responses = list(homepage_responses or [])
        self._by_url = dict(by_url or {})

    async def get(self, url, *, impersonate=None, timeout=None):  # noqa: ARG002
        self.calls.append(url)
        if url == "https://www.auction.com/" and self._homepage_responses:
            return self._homepage_responses.pop(0)
        if url in self._by_url:
            return self._by_url[url]
        raise AssertionError(f"_FakeSession got an unexpected URL: {url}")


def test_warmup_succeeds_on_second_attempt_real_wall_shape():
    session = _FakeSession(homepage_responses=[
        _FakeResponse(200, _INCAPSULA_WALL_HTML),
        _FakeResponse(200, "<html>real homepage</html>"),
    ])
    ok = asyncio.run(adc._warm_incapsula_session(session))
    assert ok is True
    assert len(session.calls) == 2


def test_warmup_exhausts_retries_and_returns_false(monkeypatch):
    monkeypatch.setattr(adc, "DOC_WARMUP_RETRIES", 2)
    session = _FakeSession(homepage_responses=[
        _FakeResponse(200, _INCAPSULA_WALL_HTML),
        _FakeResponse(200, _INCAPSULA_WALL_HTML),
    ])

    async def _no_sleep(_s):
        return None
    monkeypatch.setattr(adc.asyncio, "sleep", _no_sleep)

    ok = asyncio.run(adc._warm_incapsula_session(session))
    assert ok is False
    assert len(session.calls) == 2


def test_capture_property_documents_stamps_real_doc_and_skips_empty(monkeypatch):
    """End-to-end: one listing's detail page carries the real two-document
    shape (stamped), the other's is the real empty-with-global-boilerplate
    shape (left alone) -- exactly the two live-verified cases."""
    monkeypatch.setattr(adc, "DOC_FETCH_PACE_S", 0.0)
    li_with_docs = _listing(
        "2197585",
        "https://www.auction.com/details/2003-plain-field-dr-bessemer-city-nc-2197585",
    )
    li_without_docs = _listing(
        "2045737",
        "https://www.auction.com/details/1402-tom-pepper-rd-creswell-nc-2045737",
    )
    session = _FakeSession(
        homepage_responses=[_FakeResponse(200, "<html>real homepage</html>")],
        by_url={
            li_with_docs.source_url: _FakeResponse(200, _REAL_TWO_DOC_HTML),
            li_without_docs.source_url: _FakeResponse(
                200, _REAL_EMPTY_DOCS_WITH_GLOBAL_HTML
            ),
        },
    )

    class _FakeAsyncSessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "curl_cffi.requests.AsyncSession", lambda: _FakeAsyncSessionCtx()
    )

    stamped = asyncio.run(
        adc._capture_property_documents("NC", [li_with_docs, li_without_docs])
    )

    assert stamped == 1
    assert li_with_docs.raw["documents"] == [
        _REAL_PURCHASE_AGREEMENT_URL, _REAL_LOCAL_DISCLOSURE_URL,
    ]
    assert li_with_docs.raw["document_url"] == _REAL_PURCHASE_AGREEMENT_URL
    assert "documents" not in li_without_docs.raw
    assert "document_url" not in li_without_docs.raw
    # homepage warm-up once, then exactly one GET per listing.
    assert session.calls == [
        "https://www.auction.com/",
        li_with_docs.source_url,
        li_without_docs.source_url,
    ]


def test_capture_property_documents_respects_budget_cap(monkeypatch):
    """DOC_FETCH_CAP must bound how many listings get a detail-page fetch,
    even when more listings are passed in -- the whole point of the cap is
    that a run can't silently balloon into fetching every row."""
    monkeypatch.setattr(adc, "DOC_FETCH_PACE_S", 0.0)
    monkeypatch.setattr(adc, "DOC_FETCH_CAP", 1)
    listings = [
        _listing("2197585",
                 "https://www.auction.com/details/a-nc-2197585"),
        _listing("2045737",
                 "https://www.auction.com/details/b-nc-2045737"),
    ]
    session = _FakeSession(
        homepage_responses=[_FakeResponse(200, "<html>real homepage</html>")],
        by_url={
            listings[0].source_url: _FakeResponse(200, _REAL_TWO_DOC_HTML),
            listings[1].source_url: _FakeResponse(200, _REAL_TWO_DOC_HTML),
        },
    )

    class _FakeAsyncSessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "curl_cffi.requests.AsyncSession", lambda: _FakeAsyncSessionCtx()
    )

    stamped = asyncio.run(adc._capture_property_documents("NC", listings))

    assert stamped == 1
    # homepage + exactly ONE listing fetch, never the second.
    assert session.calls == ["https://www.auction.com/", listings[0].source_url]
    assert "documents" not in listings[1].raw


def test_capture_property_documents_warmup_failure_stamps_nothing(monkeypatch):
    """If the WAF never clears (hard outage / all retries walled), the pass
    must bail cleanly -- no per-listing fetches attempted, nothing raised,
    nothing stamped -- rather than fail the whole scraper run."""
    monkeypatch.setattr(adc, "DOC_WARMUP_RETRIES", 1)

    async def _no_sleep(_s):
        return None
    monkeypatch.setattr(adc.asyncio, "sleep", _no_sleep)

    li = _listing("2197585",
                   "https://www.auction.com/details/a-nc-2197585")
    session = _FakeSession(homepage_responses=[
        _FakeResponse(200, _INCAPSULA_WALL_HTML),
    ])

    class _FakeAsyncSessionCtx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        "curl_cffi.requests.AsyncSession", lambda: _FakeAsyncSessionCtx()
    )

    stamped = asyncio.run(adc._capture_property_documents("NC", [li]))

    assert stamped == 0
    assert session.calls == ["https://www.auction.com/"]  # no listing fetch attempted
    assert "documents" not in li.raw


def test_capture_property_documents_empty_listings_is_a_noop():
    stamped = asyncio.run(adc._capture_property_documents("NC", []))
    assert stamped == 0

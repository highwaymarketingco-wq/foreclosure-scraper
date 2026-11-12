"""York County SC delinquent-tax scraper.

REWRITTEN 2026-10-13: production (commit 739cae31, 2026-10-12) replaced the old
landing-page + DocumentCenter-link + pdfplumber-PDF-table approach entirely --
the county's page started hitting Cloudflare and returning 0 rows. The scraper
now queries York County's public ArcGIS FeatureServer
(Tax_Sale_Properties_2025_View) directly and builds Listings straight from its
JSON attributes: no landing-page fetch, no PDF download, no table parser, so
there is no `get_text`/`client`/pdfplumber seam left to mock. These tests were
still exercising that dead interface (`monkeypatch.setattr(m, "get_text", ...)`)
and failed with AttributeError once the module no longer defined it.

These replacements test the same thing the old ones protected, translated to the
new shape:
  - a real ArcGIS feature with usable attributes becomes a correct Listing
    (old: "a real list PDF is downloaded and table-parsed")
  - a feature with no parcel/TMS is never shipped as a lead (old: "an
    Overage-Claim document, which has no per-parcel data, is never matched" --
    same underlying rule the shared `_sc_tax_table.is_usable_row()` gate
    enforces for this parser's HTML-table-parsing siblings: no parcel means no
    workable lead)
  - an empty/failed response yields nothing, never a fabricated placeholder
    (old: "a PDF with no matching table yields nothing")
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax import YorkDelinquentTax

# A feature with every field the scraper reads, two owners (Owner1 + Owner2)
# so the owner-name concatenation is exercised too.
_FEATURE_FULL = {
    "Owner1": "SMITH JOHN",
    "Owner2": "SMITH JANE",
    "Owner3": "",
    "ParcelID": "123-45-67-890",
    "PropertyAddress": "101 Main St",
    "AprTotVal": 150000,
    "SalePrice": 543.21,
    "LegalDescription": "LOT 4 BLK 2",
    "LandUseDesc": "Single Family",
    "URL": "https://example.com/gis/123-45-67-890",
}

# No ParcelID and no TAXMAPID -- unroutable, must never become a Listing.
_FEATURE_NO_PARCEL = {
    "Owner1": "NOBODY HOME",
    "ParcelID": None,
    "TAXMAPID": None,
    "PropertyAddress": "1 Nowhere Rd",
    "AprTotVal": 1000,
}


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeHttpxClient:
    """Sync stand-in for ``httpx.Client(timeout=...)`` used as a context manager.

    The scraper calls this synchronously (``with httpx.Client(...) as client``)
    even though ``fetch()`` itself is async, so the fake mirrors that shape
    rather than the async ``client()``/``get_text()`` helpers used elsewhere.
    """

    def __init__(self, pages):
        self._pages = list(pages)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        if self._pages:
            return self._pages.pop(0)
        return _FakeResp(200, {"features": []})


def _patch_client(monkeypatch, pages):
    import foreclosure_scraper.scrapers.counties_sc.york_delinquent_tax as m
    monkeypatch.setattr(m.httpx, "Client", lambda timeout=None: _FakeHttpxClient(pages))
    return m


def test_real_feature_is_downloaded_and_mapped_into_a_listing(monkeypatch):
    """A genuine ArcGIS feature must be fetched and mapped into a real Listing,
    not recorded as a bare/placeholder row."""
    page = _FakeResp(200, {
        "features": [{"attributes": _FEATURE_FULL}],
        "exceededTransferLimit": False,
    })
    _patch_client(monkeypatch, [page])

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert len(rows) == 1
    li = rows[0]
    assert li.defendant == "SMITH JOHN SMITH JANE"
    assert li.parcel_id == "123-45-67-890"
    assert li.street_address == "101 Main St"
    assert li.assessed_value == 150000.0
    assert li.opening_bid == 543.21
    assert li.state == "SC" and li.county == "York"


def test_feature_with_no_parcel_is_never_matched(monkeypatch):
    """A feature with no ParcelID/TAXMAPID is not a workable lead -- it must
    yield 0 rows, not a bare placeholder with no parcel to join or route on."""
    page = _FakeResp(200, {
        "features": [{"attributes": _FEATURE_NO_PARCEL}],
        "exceededTransferLimit": False,
    })
    _patch_client(monkeypatch, [page])

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert rows == []


def test_good_row_survives_alongside_a_parcel_less_row(monkeypatch):
    """One unusable row in the batch must not suppress a usable one next to it."""
    page = _FakeResp(200, {
        "features": [
            {"attributes": _FEATURE_NO_PARCEL},
            {"attributes": _FEATURE_FULL},
        ],
        "exceededTransferLimit": False,
    })
    _patch_client(monkeypatch, [page])

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert len(rows) == 1
    assert rows[0].parcel_id == "123-45-67-890"


def test_no_features_yields_nothing(monkeypatch):
    """An empty feature page must not ship a fabricated placeholder row."""
    page = _FakeResp(200, {"features": []})
    _patch_client(monkeypatch, [page])

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert rows == []


def test_http_failure_yields_nothing(monkeypatch):
    """A non-200 FeatureServer response must fail closed, not raise or fake data."""
    page = _FakeResp(503, {}, text="Service Unavailable")
    _patch_client(monkeypatch, [page])

    rows = list(asyncio.run(YorkDelinquentTax().fetch()))
    assert rows == []

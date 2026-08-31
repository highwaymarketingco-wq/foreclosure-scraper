"""Regression tests for the foreclosure.com public-preview scraper.

The scraper was rewritten from an auth-gated stub into a free public
scrape (curl-cffi browser impersonation over the search view + city/zip
JSON-LD pages). It no longer requires credentials and is NOT paywall-gated:
fetch() does a real public HTTP fetch and parses anonymized Listings.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from foreclosure_scraper.scrapers.national.foreclosure_dot_com import (
    ForeclosureDotCom,
)


def _make_jsonld_page() -> str:
    """A minimal city/zip page body carrying one RealEstateListing in JSON-LD.

    Mirrors the structure the scraper's _extract_jsonld_listings walks:
    @graph -> CollectionPage -> mainEntity.itemListElement -> item.
    """
    doc = {
        "@graph": [
            {
                "@type": "CollectionPage",
                "mainEntity": {
                    "itemListElement": [
                        {
                            "item": {
                                "@type": "RealEstateListing",
                                "url": "https://www.foreclosure.com/address/Moore-Dr-Spartanburg-SC-29302/12345_lid",
                                "name": "Foreclosure on Moore Dr",
                                "image": "//img.foreclosure.com/listingphoto/abc.jpg",
                                "offers": {
                                    "itemOffered": {
                                        "@type": "SingleFamilyResidence",
                                        "address": {
                                            "streetAddress": "Moore Dr",
                                            "addressLocality": "Spartanburg",
                                            "addressRegion": "SC",
                                            "postalCode": "29302",
                                        },
                                        "geo": {
                                            "latitude": 34.9,
                                            "longitude": -81.9,
                                        },
                                        "numberOfBedrooms": 3,
                                        "numberOfBathroomsTotal": 2,
                                        "floorSize": {
                                            "unitCode": "SQFT",
                                            "value": "1800",
                                        },
                                    }
                                },
                            }
                        }
                    ]
                },
            }
        ]
    }
    script = (
        '<script type="application/ld+json">'
        + json.dumps(doc)
        + "</script>"
    )
    # The scraper ignores pages < 5000 chars, so pad the HTML body out.
    padding = "<div>" + ("x" * 6000) + "</div>"
    # No "<N> Foreclosure Listings" title -> _get_total returns 0 -> single page,
    # so the mock does not need to model pagination.
    return f"<html><head>{script}</head><body>{padding}</body></html>"


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


def test_public_fetch_parses_listings():
    """fetch() does a public HTTP fetch (no credentials) and parses Listings.

    The http/curl_cffi layer is mocked so the test is deterministic and
    exercises the parse path rather than the live site.
    """
    page = _make_jsonld_page()

    def fake_get(url, *args, **kwargs):
        return _FakeResponse(page)

    scraper = ForeclosureDotCom()
    with patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.cf.get",
        side_effect=fake_get,
    ), patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.time.sleep",
        return_value=None,
    ):
        result = list(asyncio.run(scraper.fetch()))

    # At least the one SC listing in the mocked JSON-LD must be parsed.
    assert result, "expected the public scrape to parse at least one listing"
    li = result[0]
    assert li.state == "SC"
    assert li.city == "Spartanburg"
    assert li.zip_code == "29302"
    assert li.case_number == "fc-12345"
    assert li.raw.get("beds") == 3
    assert li.raw.get("sqft") == 1800


def test_credentials_not_required():
    """No credential env vars are consulted; the public fetch runs regardless.

    Even with only a partial credential set (the old gating condition), the
    scraper still performs a public fetch and parses listings.
    """
    page = _make_jsonld_page()

    def fake_get(url, *args, **kwargs):
        return _FakeResponse(page)

    scraper = ForeclosureDotCom()
    with patch.dict(
        "os.environ", {"FORECLOSURE_DOT_COM_USER": "x@example.com"}, clear=False
    ), patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.cf.get",
        side_effect=fake_get,
    ), patch(
        "foreclosure_scraper.scrapers.national.foreclosure_dot_com.time.sleep",
        return_value=None,
    ):
        result = list(asyncio.run(scraper.fetch()))

    assert result, "public fetch must succeed without full credentials"


def test_not_paywall_gated():
    """The scraper is a free public source, so it must NOT declare
    requires_paywall (which would classify it as PAYWALL-BLOCKED)."""
    scraper = ForeclosureDotCom()
    assert getattr(scraper, "requires_paywall", False) is False


def test_main_surfaces_paywall_blocked_status():
    """main.py's source_status logic must still support requires_paywall
    classification for the paywalled sources that do declare it."""
    import inspect
    from foreclosure_scraper import main as orchestrator
    src = inspect.getsource(orchestrator.run)
    assert "requires_paywall" in src
    assert "PAYWALL-BLOCKED" in src

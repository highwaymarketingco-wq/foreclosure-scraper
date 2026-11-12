"""national.cash_buyer_deeds -- Logan-vendor (McDowell/Transylvania/Mitchell)
free document-image wiring.

2026-10-13 source-completeness audit, Pattern C re-check: rod.logan's shared
`_parse_records` already captures each row's free `view_image.php?key=...`
image key into `raw['logan']['image_key']` (added the same session as
rod.logan's own `discover_recent_nods(fetch_images=True)`). `_logan_recent`
used to call `_parse_records` directly and return the docs as-is, closing its
httpx session before anything downstream could resolve that key -- which is
scoped to the session that rendered it (rod.logan's own module docstring) and
dies outside it, exactly like rod.logan's `view_image.php` key. All three
Logan counties this scraper covers are registered "free" in
rod/doc_images.py's COUNTY_IMAGE_STATUS, so the image was fetchable without
any login -- just never wired in. `_logan_recent` now resolves the image for
the cash-buyer subset of its own sweep (budget-capped by
`logan._MAX_IMAGES_PER_SWEEP`, same convention as
`discover_recent_nods(fetch_images=True)`) before its session closes, and
`_deed_to_listing` surfaces it as `raw['cash_buyer_deeds']['document_image']`
-- nested inside the already-RAW_KEEP'd ``"cash_buyer_deeds": "*"`` block, so
no new top-level raw key needed registering.
"""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx

from foreclosure_scraper.scrapers.national import cash_buyer_deeds as cbd

_FAKE_PDF = b"%PDF-1.4 not a real pdf, just test bytes\n%%EOF"
_IMAGE_KEY = "b1b8057d90d945b06f28a7319d59820e"

# A single warranty DEED row (McDowell shape) with no matching deed-of-trust
# anywhere else in the sweep -- a clean cash-buyer candidate -- carrying the
# real trailing XRef + Image columns rod.logan._parse_records reads (live
# shape per tests/test_logan_rod.py's _FIXTURE_WITH_DOCS).
_DEED_ROW = f"""
<a href="javascript: loadDetailsScreen('2026009999');" id="link_2026009999"> 09/01/2026&nbsp; </a></td>
<td class="summary" id="2026009999">DOC 1500  100 &nbsp; </td>
<td class="summary" id="2026009999">DEED&nbsp;</td>
<td class="summary" id="2026009999">PD:SOME LEGAL&nbsp;</td>
<td class="summary" id="2026009999">GRANTEE&nbsp;</td>
<td class="summary" id="2026009999">DOE JANE&nbsp;</td>
<td class="summary" id="2026009999">ACME BUILDERS LLC&nbsp;</td>
<td><a href="javascript:loadDetailsScreen('0');"></a></td>
<td><a id='0' onclick='linkColorChange(0)' href='view_image.php?key={_IMAGE_KEY}&type=tif' target='_blank'>TIFF</a><br><a class='imageLinkColorChange' href='view_image.php?key={_IMAGE_KEY}&type=pdf' target='_blank'>PDF</a>&nbsp;</td>
"""


def _handler(sweep_html: str, key_to_pdf: dict[str, bytes], token: str = "4242"):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/index.php") and request.method == "GET":
            return httpx.Response(200, text="<html></html>")
        if path.endswith("/index.php") and request.method == "POST":
            return httpx.Response(200, text=f"go to content.php?{token}")
        if path.endswith("/content.php"):
            return httpx.Response(200, text=sweep_html)
        if path.endswith("/view_image.php"):
            key = parse_qs(request.url.query.decode()).get("key", [""])[0]
            data = key_to_pdf.get(key)
            if data is None:
                return httpx.Response(500, content=b"")
            return httpx.Response(200, content=data, headers={"content-type": "application/pdf"})
        return httpx.Response(404)
    return handler


def _patch_logan_client(monkeypatch, handler) -> None:
    """_logan_recent resolves `client` via a LOCAL import inside the function
    body (`from ...http_client import client as _client`), matching
    _cott_recent's own convention in this file -- the real patch point is
    the attribute on the http_client module itself."""
    import foreclosure_scraper.http_client as http_client_mod

    @asynccontextmanager
    async def _fake_client(*_a, **_kw):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            yield c

    monkeypatch.setattr(http_client_mod, "client", _fake_client)


def test_logan_recent_resolves_the_free_image_for_a_cash_buyer_row(monkeypatch):
    _patch_logan_client(monkeypatch, _handler(_DEED_ROW, {_IMAGE_KEY: _FAKE_PDF}))
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert len(docs) == 1
    d = docs[0]
    assert d.doc_type == "DEED"
    assert d.grantee == "DOE JANE"
    assert d.raw["logan"]["image_key"] == _IMAGE_KEY
    img = d.raw["logan"]["image"]
    assert img["mime"] == "application/pdf"
    assert img["bytes"] == len(_FAKE_PDF)
    header, b64 = img["data_uri"].split(",", 1)
    assert base64.b64decode(b64) == _FAKE_PDF


def test_logan_recent_image_fetch_is_best_effort_on_a_dead_key(monkeypatch):
    """No key in the server's table matches (expired/wrong) -- the doc still
    comes back, just without an embedded image, same as rod.logan's own
    discover_recent_nods(fetch_images=True) behavior."""
    _patch_logan_client(monkeypatch, _handler(_DEED_ROW, {}))
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert len(docs) == 1
    assert "image" not in docs[0].raw["logan"]


def test_logan_recent_respects_the_per_sweep_image_cap(monkeypatch):
    """Two independent cash-buyer candidates, cap set to 1 -- only one image
    fetch happens; the second doc is returned without an embedded image
    rather than this scraper silently issuing unbounded extra requests."""
    monkeypatch.setattr(cbd.logan, "_MAX_IMAGES_PER_SWEEP", 1)
    key2 = "deadbeef00deadbeef00deadbeef000"
    row2 = f"""
<a href="javascript: loadDetailsScreen('2026009998');" id="link_2026009998"> 09/02/2026&nbsp; </a></td>
<td class="summary" id="2026009998">DOC 1500  101 &nbsp; </td>
<td class="summary" id="2026009998">DEED&nbsp;</td>
<td class="summary" id="2026009998">PD:OTHER LEGAL&nbsp;</td>
<td class="summary" id="2026009998">GRANTEE&nbsp;</td>
<td class="summary" id="2026009998">ROE RICHARD&nbsp;</td>
<td class="summary" id="2026009998">BETA HOMES LLC&nbsp;</td>
<td><a href="javascript:loadDetailsScreen('0');"></a></td>
<td><a id='0' onclick='linkColorChange(0)' href='view_image.php?key={key2}&type=tif' target='_blank'>TIFF</a><br><a class='imageLinkColorChange' href='view_image.php?key={key2}&type=pdf' target='_blank'>PDF</a>&nbsp;</td>
"""
    _patch_logan_client(
        monkeypatch,
        _handler(_DEED_ROW + row2, {_IMAGE_KEY: _FAKE_PDF, key2: _FAKE_PDF}),
    )
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    assert len(docs) == 2
    with_image = [d for d in docs if "image" in d.raw["logan"]]
    assert len(with_image) == 1


def test_deed_to_listing_surfaces_the_embedded_image_under_cash_buyer_deeds_block(monkeypatch):
    """The embedded image must land in raw['cash_buyer_deeds']['document_image']
    -- nested inside the already-RAW_KEEP'd block, not a new top-level key."""
    _patch_logan_client(monkeypatch, _handler(_DEED_ROW, {_IMAGE_KEY: _FAKE_PDF}))
    docs = asyncio.run(cbd._logan_recent("NC", "McDowell", 30))
    li = cbd._deed_to_listing(docs[0], "https://search.mcdowelldeeds.com/index.php")
    assert li is not None
    img = li.raw["cash_buyer_deeds"]["document_image"]
    assert img["mime"] == "application/pdf"
    header, b64 = img["data_uri"].split(",", 1)
    assert base64.b64decode(b64) == _FAKE_PDF


def test_deed_to_listing_document_image_is_none_without_logan_raw():
    """Non-Logan vendor docs (Aumentum/CCHS/Cott) carry no raw['logan'] block
    at all -- document_image must be a harmless None, never raise."""
    from foreclosure_scraper.rod.models import RodDoc
    deed = RodDoc(
        county="Henderson", state="NC", doc_type="DEED", grantor="X LLC",
        grantee="DOE JANE", book="1", page="1", raw={"cchs": True},
    )
    li = cbd._deed_to_listing(deed, "https://example.com")
    assert li is not None
    assert li.raw["cash_buyer_deeds"]["document_image"] is None

"""Vision: an image CDN that WAF-blocks plain httpx escalates to curl_cffi impersonation,
the same tier the scraper that captured the URL already used for the HTML page.

2026-10-16: confirmed live that assets.landwatch.com / assets.landandfarm.com (Land.com
network, both Akamai) 403 a plain httpx GET for the exact gallery-photo URLs
landwatch.py/landandfarm.py already extract successfully via curl_cffi impersonation for
the HTML page -- accounting for 605/1394 (43%) of the vision ledger's fetch_failed rows.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper import enrichment_vision as V

_JPEG = b"\xff\xd8\xff" + b"0" * 20
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class _Blocked:
    status_code = 403
    headers = {"content-type": "text/html"}
    content = b"<HTML>Access Denied</HTML>"


class _NetBlocked:
    async def get(self, url, **kw):
        return _Blocked()


def _real_jpeg_bytes() -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), "blue").save(buf, "JPEG")
    return buf.getvalue()


def _real_webp_bytes() -> bytes:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, "WEBP")
    return buf.getvalue()


def test_a_403_escalates_to_impersonation_and_succeeds(monkeypatch):
    jpeg = _real_jpeg_bytes()
    calls = []

    async def fake_impersonate(url, **kw):
        calls.append(url)
        return jpeg

    monkeypatch.setattr(V, "get_bytes_impersonate", fake_impersonate)
    got = asyncio.run(V._fetch_image_bytes(_NetBlocked(), "https://assets.landwatch.com/x"))
    assert calls == ["https://assets.landwatch.com/x"]
    assert got is not None and got[1] == "image/jpeg" and got[0] == jpeg


def test_a_403_escalation_normalizes_webp_to_jpeg(monkeypatch):
    webp = _real_webp_bytes()

    async def fake_impersonate(url, **kw):
        return webp

    monkeypatch.setattr(V, "get_bytes_impersonate", fake_impersonate)
    got = asyncio.run(V._fetch_image_bytes(_NetBlocked(), "https://assets.landandfarm.com/x"))
    assert got is not None and got[1] == "image/jpeg" and got[0][:2] == b"\xff\xd8"


def test_a_403_where_impersonation_also_fails_returns_none_not_a_crash(monkeypatch):
    async def fake_impersonate(url, **kw):
        raise RuntimeError("impersonate got 403 too")

    monkeypatch.setattr(V, "get_bytes_impersonate", fake_impersonate)
    assert asyncio.run(V._fetch_image_bytes(_NetBlocked(), "https://assets.landwatch.com/x")) is None


def test_a_403_where_impersonation_returns_an_unparseable_body_returns_none(monkeypatch):
    async def fake_impersonate(url, **kw):
        return b"<html>still blocked</html>"

    monkeypatch.setattr(V, "get_bytes_impersonate", fake_impersonate)
    assert asyncio.run(V._fetch_image_bytes(_NetBlocked(), "https://assets.landwatch.com/x")) is None


def test_a_real_404_is_not_escalated_to_impersonation(monkeypatch):
    class R:
        status_code = 404
        headers = {"content-type": "text/html"}
        content = b""

    class Net:
        async def get(self, url, **kw):
            return R()

    def fail_if_called(url, **kw):
        raise AssertionError("a real 404 is not a WAF block and must not escalate")

    monkeypatch.setattr(V, "get_bytes_impersonate", fail_if_called)
    assert asyncio.run(V._fetch_image_bytes(Net(), "https://assets.landwatch.com/x")) is None

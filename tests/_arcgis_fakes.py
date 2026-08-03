"""Offline stand-ins for httpx.AsyncClient against ArcGIS REST endpoints.

Shared by the arcgis_webmap walker tests and the two Henderson scraper tests so
all three drive the real code path (walk -> guard -> paginate -> map) against
saved fixtures instead of monkeypatching the logic under test out of existence.
"""
from __future__ import annotations

from typing import Any


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class FakeHttp:
    """Routes on URL substring; ``pages`` (when given) is served in order.

    Records every call as ``(verb, url, params)`` so tests can assert what was
    actually requested — which WHERE went out, whether outFields was enumerated,
    what resultOffset sequence pagination produced, and whether a guard stopped
    a request from happening at all.
    """

    def __init__(self, routes: dict[str, Any] | None = None,
                 pages: list[Any] | None = None):
        self.routes = routes or {}
        self.pages = list(pages or [])
        self.calls: list[tuple[str, str, dict]] = []

    async def _serve(self, verb: str, url: str, params: dict | None) -> FakeResponse:
        self.calls.append((verb, url, dict(params or {})))
        if self.pages:
            return FakeResponse(self.pages.pop(0))
        for frag, payload in self.routes.items():
            if frag in url:
                return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)
        return FakeResponse({"error": {"code": 400, "message": f"no route for {url}"}})

    async def get(self, url, params=None, timeout=None):
        return await self._serve("GET", url, params)

    async def post(self, url, data=None, timeout=None):
        return await self._serve("POST", url, data)

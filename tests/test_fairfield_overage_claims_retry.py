"""counties_sc.fairfield_overage_claims: a transient transport/timeout error on either of
this module's two real network calls gets retried, not treated as "no data this run."

Found 2026-11-07 (gap-sweep): neither call goes through the shared, already-must-wrap-its-
own-retries http_client.client() helper -- this file builds a raw httpx.AsyncClient itself
(fetch(), line ~178) and calls .get() directly on it, with zero retry cushioning on either
call. Same bug shape already fixed the same night in the Column legal-notice API scraper,
spartan_weekly_legals.py, the shared arcgis_webmap.query_features(), and this file's own
sibling, counties_sc.york_overage_claims.py (whose already-fixed httpx branch this fix
mirrors).

Two call sites:

  (1) _discover_doc_url(c)'s hub-page GET (secondary/lower severity). A blip here is caught
      and falls through to FALLBACK_DOC_URL -- a hardcoded, independently live-verified PDF
      URL -- so it degrades discovery rather than zeroing the scrape outright. Still worth
      retrying so a transient hiccup doesn't needlessly mask a legitimate hub-page URL
      change.

  (2) FairfieldOverageClaims.fetch()'s roster-PDF GET (primary finding). This is the one and
      only fetch of the actual overage roster -- a true single point of failure. Before this
      fix, ANY exception (including httpx.ConnectTimeout/ReadTimeout, the exact transient
      cases this targets) on the first and only attempt logged a warning and returned `out`,
      still the empty list from before the loop ran. Because this slug is registered in
      main.DATELESS_OK_SOURCES (no fallback date window), a zeroed run could not self-heal
      later -- it would just silently report an empty/healthy result until someone noticed
      by hand.

Both are plain try/except blocks that swallow every exception into a clean fallback
(FALLBACK_DOC_URL for (1), `return out` for (2)), so from the caller's side a retry-exhausted
transient failure is never a raised exception or a hang -- it is indistinguishable from
"nothing is wrong" except by counting the underlying transport's own call attempts, which is
what these tests do.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from tenacity import wait_exponential_jitter

import foreclosure_scraper.scrapers.counties_sc.fairfield_overage_claims as M

HUB_PATH = "/departments/tax-collector"
DOC_PATH_SUFFIX = "Tax_Sale_Overage_List___Public_Records_Notice.pdf"  # FALLBACK_DOC_URL's path

#: Hub page with no "Overage List" anchor -- _discover_doc_url falls through cleanly to
#: FALLBACK_DOC_URL, so group-2 tests can drive fetch()'s doc-fetch call at a known URL
#: without needing to also exercise the link-discovery HTML-parsing logic.
HUB_HTML_NO_MATCH = b"<html><body><a href=\"/other\">Something else</a></body></html>"

#: Hub page WITH a real "Overage List" anchor -- used by the group-1 "succeeds" test to
#: prove a successful (post-retry) hub fetch still does real discovery, not just a fallback.
HUB_HTML_WITH_MATCH = (
    b'<html><body>'
    b'<a href="/uploads/real-overage-list.pdf" aria-label="Overage List">Download</a>'
    b'<a href="/uploads/claim-form.pdf" aria-label="Overage Claim Form">Download</a>'
    b'</body></html>'
)
DISCOVERED_URL = "https://www.fairfieldsc.com/uploads/real-overage-list.pdf"


def _minimal_pdf(text_line: str) -> bytes:
    """A hand-rolled, byte-valid, single-page text PDF -- no reportlab dependency. Verified
    (outside this suite) that pypdf.PdfReader.extract_text() round-trips `text_line` back out
    character-for-character, so a "retry succeeds" test can assert on a REAL parsed row, not
    just a call count."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = f"BT /F1 12 Tf 50 700 Td ({text_line}) Tj ET".encode("latin-1")
    objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")

    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode()
        buf += body
        buf += b"\nendobj\n"
    xref_offset = len(buf)
    n = len(objs) + 1
    buf += f"xref\n0 {n}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += b"trailer\n"
    buf += f"<< /Size {n} /Root 1 0 R >>\n".encode()
    buf += b"startxref\n"
    buf += f"{xref_offset}\n".encode()
    buf += b"%%EOF"
    return bytes(buf)


ONE_ROW_PDF = _minimal_pdf("ADAMS, JAMES  170-00-00-058-000 $17.51")


class _FlakyTransport(httpx.AsyncBaseTransport):
    """Serves the hub page and the doc-fetch URL. Requests whose path ends with `flaky_path`
    raise `exc` for the first `fail_times` calls to that path before serving a real response
    -- models a connection that blips and then clears (or never clears, for fail_times >=
    stop_after_attempt's budget). `bad_status`, independently, makes ONE path answer with a
    fixed real (non-transport) HTTP status instead of raising -- proves that kind of failure
    is never mistaken for a transport/timeout error."""

    def __init__(self, *, hub_html: bytes = HUB_HTML_NO_MATCH, doc_bytes: bytes = ONE_ROW_PDF,
                 flaky_path: str | None = None, fail_times: int = 0, exc=None,
                 bad_status: tuple[str, int] | None = None):
        self.hub_html = hub_html
        self.doc_bytes = doc_bytes
        self.flaky_path = flaky_path
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.bad_status = bad_status  # (path_suffix, status_code)
        self.calls: dict[str, int] = {}
        self._flaky_calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] = self.calls.get(path, 0) + 1

        if self.flaky_path and path.endswith(self.flaky_path):
            self._flaky_calls += 1
            if self._flaky_calls <= self.fail_times:
                raise self.exc

        if self.bad_status and path.endswith(self.bad_status[0]):
            return httpx.Response(self.bad_status[1])

        if path == HUB_PATH:
            return httpx.Response(200, content=self.hub_html)
        return httpx.Response(200, content=self.doc_bytes)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(M, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


async def _run_discover(transport: _FlakyTransport) -> str:
    async with httpx.AsyncClient(transport=transport) as c:
        return await M._discover_doc_url(c)


def _run_fetch(monkeypatch, transport: _FlakyTransport) -> list:
    real = httpx.AsyncClient

    class _Fake(real):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _Fake)
    return asyncio.run(M.FairfieldOverageClaims().fetch())


# --------------------------------------------------------- (1) _discover_doc_url's hub GET
# Secondary/lower severity: a blip here degrades discovery (falls through to
# FALLBACK_DOC_URL) rather than zeroing the whole scrape, but is still worth retrying.

def test_hub_discover_transient_connect_timeout_is_retried_and_then_succeeds():
    transport = _FlakyTransport(hub_html=HUB_HTML_WITH_MATCH, flaky_path=HUB_PATH, fail_times=2)
    url = asyncio.run(_run_discover(transport))
    assert transport.calls[HUB_PATH] == 3     # 2 failures + the attempt that succeeded
    assert url == DISCOVERED_URL              # real discovery, not just the fallback


def test_hub_discover_connect_timeout_that_never_clears_still_falls_back_not_hangs():
    transport = _FlakyTransport(flaky_path=HUB_PATH, fail_times=99)
    url = asyncio.run(_run_discover(transport))
    assert transport.calls[HUB_PATH] == 3      # stop_after_attempt(3), then gives up
    assert url == M.FALLBACK_DOC_URL           # the pre-existing, now-reached-via-retry fallback


def test_hub_discover_real_bad_http_status_is_not_retried():
    transport = _FlakyTransport(bad_status=(HUB_PATH, 503))
    url = asyncio.run(_run_discover(transport))
    assert transport.calls[HUB_PATH] == 1      # a real bad status is not a transport/timeout error
    assert url == M.FALLBACK_DOC_URL


# ------------------------------------------------- (2) fetch()'s roster-PDF GET (primary finding)
# The true single point of failure: before this fix, fetch() swallowed this call's own
# exception into `return out`, where `out` was still the empty list from before the loop ran.

def test_doc_fetch_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _FlakyTransport(flaky_path=DOC_PATH_SUFFIX, fail_times=2)
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls[HUB_PATH] == 1                  # hub discovery untouched by this test
    assert transport.calls["/uploads/uploads/" + DOC_PATH_SUFFIX] == 3
    assert len(out) == 1
    assert out[0].parcel_id == "170-00-00-058-000"
    assert out[0].owner_name == "ADAMS, JAMES"
    assert out[0].raw["tax_sale_overage"]["amount"] == 17.51


def test_doc_fetch_read_timeout_is_also_retried(monkeypatch):
    transport = _FlakyTransport(flaky_path=DOC_PATH_SUFFIX, fail_times=1,
                                exc=httpx.ReadTimeout("slow"))
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["/uploads/uploads/" + DOC_PATH_SUFFIX] == 2
    assert len(out) == 1


def test_doc_fetch_connect_timeout_that_never_clears_still_returns_empty_not_hangs(monkeypatch):
    transport = _FlakyTransport(flaky_path=DOC_PATH_SUFFIX, fail_times=99)
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["/uploads/uploads/" + DOC_PATH_SUFFIX] == 3   # bounded, no hang
    assert out == []     # fetch()'s own pre-existing contract -- returns cleanly, never raises out


def test_doc_fetch_real_bad_http_status_is_not_retried(monkeypatch):
    transport = _FlakyTransport(bad_status=(DOC_PATH_SUFFIX, 500))
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["/uploads/uploads/" + DOC_PATH_SUFFIX] == 1   # not a transport/timeout error
    assert out == []

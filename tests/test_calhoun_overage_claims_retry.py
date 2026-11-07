"""counties_sc.calhoun_overage_claims: a transient transport/timeout error on either of
this file's two real network calls gets retried, not treated as "that source failed."

Found 2026-11-07 (gap-sweep): this module builds its own raw httpx.AsyncClient (not the
shared http_client.client() helper, which itself only works because ITS callers wrap their
own AsyncRetrying -- this file never did), so neither of its two httpx.get() calls had any
retry cushioning. Same bug shape already fixed tonight in the Column legal-notice API
scraper, spartan_weekly_legals.py and the shared arcgis_webmap.query_features().

Two real call sites:

  (1) CalhounOverageClaims.fetch()'s `for url, year in docs:` loop -- downloads each year's
      overage PDF and produces every row this scraper emits. `docs` is normally just the 3
      hardcoded KNOWN_DOCS, so losing one to a transient blip costs up to ~1/3 of the run's
      rows (a "many independent per-item requests" shape, but with an unusually small N).
      The bare `except Exception: log.warning(...); continue` around it means a transient
      httpx.TransportError/TimeoutException was *already* being swallowed into "skip this
      doc" before this fix -- the actual gap is that nothing gave the connection a second
      chance first. Worse: "counties_sc.calhoun_overage_claims" is registered in
      main.DATELESS_OK_SOURCES (no fallback date window), so a run that loses all 3 docs to
      one bad minute reports a clean OUTCOME_ZERO forever, indistinguishable from a
      legitimately-empty source, until someone notices by hand.

  (2) _discover_new_docs()'s one-shot hub-page GET, called once from fetch() to pick up a
      year Calhoun posts after this file was written. Lower blast radius -- the 3 KNOWN_DOCS
      are already queued regardless of whether this call succeeds -- but it is a real
      unprotected network call and gets the identical wrap for consistency.

Each site is covered for: (a) a transient transport/timeout error is retried and then
succeeds; (b) a transient error that never clears still gives up after stop_after_attempt(3)
-- bounded, not an infinite hang -- caught by the pre-existing (unchanged) try/except one
level up; (c) a real non-transport HTTP error status is not retried (fails on attempt 1).
"""
from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from tenacity import wait_exponential_jitter

from foreclosure_scraper.scrapers.counties_sc import calhoun_overage_claims as m


def _minimal_pdf(line: str) -> bytes:
    """Hand-built minimal single-page PDF (standard Helvetica base-14 font, no
    embedding) whose text layer is exactly `line` -- real pypdf extract_text()
    round-trips it byte-for-byte (verified), so the full fetch() pipeline (GET ->
    raise_for_status -> pypdf parse -> parse_overage_text -> Listing) runs
    completely unmocked past the retry wrap under test. No reportlab dependency."""
    content = f"BT /F1 10 Tf 20 150 Td ({line}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode())
        out.write(body)
        out.write(b"\nendobj\n")
    xref_offset = out.tell()
    n = len(objs) + 1
    out.write(f"xref\n0 {n}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {n} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode())
    out.write(b"%%EOF")
    return out.getvalue()


# One real, ASCII-hyphen row per year -- plain ordering ("$123.45"), the 2021
# reversed-dollar-sign / Unicode-hyphen / embedded-space quirks are already
# covered by test_calhoun_overage_claims.py's own parser tests and are out of
# scope here; this file is only exercising the retry wrap around the GET.
_PDF_BY_YEAR = {
    "2021": _minimal_pdf("202100004 Almonds, Romeo Jr. 074-00-02-018 $736.47"),
    "2022": _minimal_pdf("202200002 Adams, Robert Jr. 167-00-00-035 $763.10"),
    "2023": _minimal_pdf("202300005 Adams, Robert Jr. 167-00-00-039 $982.02"),
}
_SALE_BY_YEAR = {"2021": "202100004", "2022": "202200002", "2023": "202300005"}


def _doc_key(path: str) -> str:
    """Map a request path to 'HUB' or the KNOWN_DOCS filename it targets."""
    if path.rstrip("/") == "/departments/tax-collector":
        return "HUB"
    return path.rsplit("/", 1)[-1]


class _FetchTransport:
    """Serves fetch()'s real HTTP shape: the one-shot hub GET plus the three
    KNOWN_DOCS PDF GETs. Exactly one path (`flaky_path`, a KNOWN_DOCS filename)
    is made flaky -- raising `exc` for its first `fail_times` hits, or, with
    `bad_status` set, always answering a fixed real HTTP status instead of
    raising. Every other path (the hub page, and the other two years' PDFs)
    answers normally on its first and only hit, so a test on one call site
    can't be confused with a coincidental failure elsewhere."""

    def __init__(self, flaky_path=None, fail_times=0, exc=None, bad_status=None):
        self.flaky_path = flaky_path
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.bad_status = bad_status
        self.calls: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = _doc_key(request.url.path)
        self.calls[key] = self.calls.get(key, 0) + 1

        if self.flaky_path and key == self.flaky_path:
            if self.bad_status is not None:
                return httpx.Response(self.bad_status, text="server error")
            if self.calls[key] <= self.fail_times:
                raise self.exc
            # cleared -- fall through to the real terminal response below.

        if key == "HUB":
            # No overage-titled links -> _discover_new_docs finds nothing new;
            # docs stays exactly the 3 hardcoded KNOWN_DOCS.
            return httpx.Response(200, text="<html><body>nothing posted</body></html>")
        for year, filename in ((y, u.rsplit("/", 1)[-1]) for u, y in m.KNOWN_DOCS):
            if key == filename:
                return httpx.Response(200, content=_PDF_BY_YEAR[year])
        return httpx.Response(404)


class _HubTransport:
    """Serves only _discover_new_docs()'s one-shot hub-page GET."""

    def __init__(self, fail_times=0, exc=None, bad_status=None, html="<html></html>"):
        self.fail_times = fail_times
        self.exc = exc or httpx.ConnectTimeout("boom")
        self.bad_status = bad_status
        self.html = html
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.bad_status is not None:
            return httpx.Response(self.bad_status, text="server error")
        if self.calls <= self.fail_times:
            raise self.exc
        return httpx.Response(200, text=self.html)


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """The real backoff is 1-8s per attempt; make the retry tests instant."""
    monkeypatch.setattr(m, "wait_exponential_jitter",
                        lambda **kw: wait_exponential_jitter(initial=0.001, max=0.002))


def _run_fetch(monkeypatch, transport):
    """fetch() builds its own httpx.AsyncClient internally -- route it through
    `transport` the same way test_sc_overage_full_user_agent.py (which already
    covers this module) and test_transylvania_delinquent_tax_retry.py do."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(transport)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return asyncio.run(m.CalhounOverageClaims().fetch())


def _sale_numbers(out):
    return {r.raw["tax_sale_overage"]["sale_number"] for r in out}


# --------------------------------------------------------------------------------------
# (1) fetch()'s per-doc loop -- the dominant, row-producing call site.

def test_doc_fetch_transient_connect_timeout_is_retried_and_then_succeeds(monkeypatch):
    transport = _FetchTransport(flaky_path="CALHOUN-TaxColOvr_2021.pdf", fail_times=2)
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["CALHOUN-TaxColOvr_2021.pdf"] == 3   # 2 failures + the success
    assert transport.calls["CALHOUN-TaxColOvr_2022.pdf"] == 1   # unaffected, hit once
    assert transport.calls["CALHOUN-TaxColOvr_2023.pdf"] == 1   # unaffected, hit once
    # All three years' real rows landed -- the retried doc's own row included.
    assert _sale_numbers(out) == {"202100004", "202200002", "202300005"}


def test_doc_fetch_read_timeout_is_also_retried(monkeypatch):
    transport = _FetchTransport(flaky_path="CALHOUN-TaxColOvr_2022.pdf", fail_times=1,
                                exc=httpx.ReadTimeout("slow"))
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["CALHOUN-TaxColOvr_2022.pdf"] == 2
    assert "202200002" in _sale_numbers(out)


def test_doc_fetch_connect_timeout_that_never_clears_gives_up_not_hangs(monkeypatch):
    """A persistently-failing connection must cost exactly stop_after_attempt(3) raw
    HTTP attempts and then give up -- never retry forever. The exhausted-retry
    exception raises out of the AsyncRetrying block exactly as a real dead host
    would, and is caught by the pre-existing, unmodified per-doc
    `except Exception: log.warning(...); continue` -- so only the 2021 doc's own
    rows are lost; the other two independent per-item requests still succeed."""
    transport = _FetchTransport(flaky_path="CALHOUN-TaxColOvr_2021.pdf", fail_times=99)
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["CALHOUN-TaxColOvr_2021.pdf"] == 3   # bounded -- not 4, not 99
    sales = _sale_numbers(out)
    assert "202100004" not in sales          # the permanently-failing doc's row is lost
    assert sales == {"202200002", "202300005"}   # the other two docs are unaffected


def test_doc_fetch_real_bad_http_status_is_not_retried_fails_on_attempt_1(monkeypatch):
    """A real (non-transport) bad status does not match
    retry_if_exception_type((TransportError, TimeoutException, TimeoutError)), so
    raise_for_status()'s HTTPStatusError must not be retried at all -- attempt 1
    is the only attempt, exactly like the pre-existing behavior for a bad status."""
    transport = _FetchTransport(flaky_path="CALHOUN-TaxColOvr_2023.pdf", bad_status=500)
    out = _run_fetch(monkeypatch, transport)
    assert transport.calls["CALHOUN-TaxColOvr_2023.pdf"] == 1
    sales = _sale_numbers(out)
    assert "202300005" not in sales
    assert sales == {"202100004", "202200002"}


# --------------------------------------------------------------------------------------
# (2) _discover_new_docs()'s one-shot hub-page GET -- lower blast radius (the 3
# KNOWN_DOCS are already queued regardless), but a real unprotected call wrapped
# identically for consistency. Tested directly, bypassing fetch() entirely.

_NEW_DOC_HTML = (
    '<a href="/sites/calhouncounty/files/Documents/Calhoun%20County/Departments/'
    'Tax%20Collector/Overages/CALHOUN-TaxColOvr_2024.pdf" title="2024 Overages">'
    "2024 Overages</a>"
)


def _run_discover(transport, have=frozenset()):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
            return await m._discover_new_docs(c, set(have))
    return asyncio.run(run())


def test_hub_fetch_transient_connect_timeout_is_retried_and_then_succeeds():
    transport = _HubTransport(fail_times=2, html=_NEW_DOC_HTML)
    found = _run_discover(transport)
    assert transport.calls == 3   # 2 failures + the success
    assert found == [(
        "https://calhouncounty.sc.gov/sites/calhouncounty/files/Documents/"
        "Calhoun%20County/Departments/Tax%20Collector/Overages/CALHOUN-TaxColOvr_2024.pdf",
        "2024",
    )]


def test_hub_fetch_connect_timeout_that_never_clears_gives_up_not_hangs():
    """Bounded at stop_after_attempt(3), then the exhausted-retry exception is
    caught by this function's own pre-existing try/except -- it returns the
    empty `found` list cleanly rather than hanging or propagating out of fetch()."""
    transport = _HubTransport(fail_times=99, html=_NEW_DOC_HTML)
    found = _run_discover(transport)
    assert transport.calls == 3   # stop_after_attempt(3), then gives up -- not 4, not 99
    assert found == []


def test_hub_fetch_real_bad_http_status_is_not_retried_fails_on_attempt_1():
    transport = _HubTransport(bad_status=503, html=_NEW_DOC_HTML)
    found = _run_discover(transport)
    assert transport.calls == 1
    assert found == []

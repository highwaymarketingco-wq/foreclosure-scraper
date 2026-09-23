"""Spartanburg County SC delinquent real-property tax-sale list (PDF).

Covers two things:

1. The row parser (`parse_list` / `split_name_situs`) against a small
   synthetic sample shaped like the real PDF's collapsed-text layout.
2. The 2026-09-23 BLOCKED-incident fix: `fetch()`'s outer retry/backoff
   around `get_bytes()`, which rides out a transient host-level block
   (spartanburgcounty.gov / CivicPlus DocumentCenter, Cloudflare-fronted)
   that outlasts http_client's own fast internal retry. See the module
   docstring in spartanburg_delinquent_tax.py for the full incident writeup.

Network is fully mocked here — no live requests. `asyncio.sleep` is patched
to a no-op so the (tens-of-seconds) backoff doesn't slow the test suite.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx

from foreclosure_scraper.base_scraper import OUTCOME_BLOCKED, OUTCOME_OK
from foreclosure_scraper.scrapers.counties_sc import spartanburg_delinquent_tax as mod

SAMPLE_TEXT = (
    "ITEM #  MAP #            DELINQUENT TAXPAYER NAME(S)        SITUS / DESCRIPTION\n"
    "83239   2-10-00-045.00   ALSBROOKS CARLOS E (LE)           1405 COUNTRY ESTATES RD\n"
    "83101   7-16-09-062.00   MEADOWS ALFRED AAA WOFTMAN LLC     512 CRESCENT AVE\n"
    "  some disclaimer boilerplate that is not a parcel row at all\n"
)

_FAKE_PDF_BYTES = b"%PDF-1.5 fake bytes for test"


def _mk_403():
    req = httpx.Request("GET", mod.PDF_URL)
    resp = httpx.Response(403, request=req)
    return httpx.HTTPStatusError("forbidden", request=req, response=resp)


# --------------------------------------------------------------------------
# parse_list / split_name_situs
# --------------------------------------------------------------------------


def test_parses_two_parcel_rows():
    rows = mod.parse_list(SAMPLE_TEXT, "http://example/test.pdf")
    assert len(rows) == 2
    parcels = {r.parcel_id for r in rows}
    assert parcels == {"2-10-00-045.00", "7-16-09-062.00"}


def test_situs_and_owner_split_correctly():
    rows = mod.parse_list(SAMPLE_TEXT, "http://example/test.pdf")
    row = next(r for r in rows if r.parcel_id == "2-10-00-045.00")
    assert row.street_address == "1405 COUNTRY ESTATES RD"
    assert row.owner_name == "ALSBROOKS CARLOS E (LE)"
    assert row.defendant == row.owner_name


def test_non_row_lines_are_skipped():
    rows = mod.parse_list(SAMPLE_TEXT, "http://example/test.pdf")
    assert all(r.parcel_id for r in rows)
    assert len(rows) == 2  # header + disclaimer line produced nothing


def test_dedupes_repeated_item_tms_key():
    doubled = SAMPLE_TEXT + "83239   2-10-00-045.00   ALSBROOKS CARLOS E (LE)  1405 COUNTRY ESTATES RD\n"
    rows = mod.parse_list(doubled, "http://example/test.pdf")
    assert len(rows) == 2  # the exact duplicate (same item#+TMS) is not double-counted


def test_listing_type_and_process_are_tax_sale():
    rows = mod.parse_list(SAMPLE_TEXT, "http://example/test.pdf")
    for r in rows:
        assert r.foreclosure_process == "tax"
        assert r.state == "SC" and r.county == "Spartanburg"


# --------------------------------------------------------------------------
# fetch() retry/backoff around a transient block
# (regression coverage for the 2026-09-23 BLOCKED incident)
# --------------------------------------------------------------------------


def _run_fetch():
    return asyncio.run(mod.SpartanburgDelinquentTax().fetch())


def test_fetch_retries_after_transient_403_then_succeeds():
    calls = {"n": 0}

    async def fake_get_bytes(url, *, timeout=60.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _mk_403()
        return _FAKE_PDF_BYTES

    async def fake_sleep(_secs):
        return None

    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod, "_pdf_text", lambda data: SAMPLE_TEXT), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = _run_fetch()

    assert calls["n"] == 2  # first attempt blocked, second succeeded
    assert len(rows) == 2


def test_fetch_gives_up_after_max_attempts_and_returns_empty():
    calls = {"n": 0}

    async def fake_get_bytes(url, *, timeout=60.0):
        calls["n"] += 1
        raise _mk_403()

    async def fake_sleep(_secs):
        return None

    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = _run_fetch()

    assert rows == []
    assert calls["n"] == mod._MAX_FETCH_ATTEMPTS  # exactly the cap, no more


def test_fetch_backs_off_between_attempts_not_hammering():
    """The whole point of the fix: waits between waves must be real backoff
    (tens of seconds, growing), not an immediate hammering retry loop."""
    sleeps: list[float] = []

    async def fake_get_bytes(url, *, timeout=60.0):
        raise _mk_403()

    async def fake_sleep(secs):
        sleeps.append(secs)

    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        _run_fetch()

    assert len(sleeps) == mod._MAX_FETCH_ATTEMPTS - 1
    for s in sleeps:
        assert s >= mod._BACKOFF_BASE_S
    # each successive wave backs off at least as long as the previous one
    assert sleeps == sorted(sleeps)


def test_fetch_retries_on_200_non_pdf_body():
    """Some WAFs answer a soft block with HTTP 200 + an HTML challenge page
    instead of a 4xx. That must not be swallowed as a silent clean zero."""
    calls = {"n": 0}

    async def fake_get_bytes(url, *, timeout=60.0):
        calls["n"] += 1
        if calls["n"] == 1:
            return b"<html>checking your browser...</html>"
        return _FAKE_PDF_BYTES

    async def fake_sleep(_secs):
        return None

    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod, "_pdf_text", lambda data: SAMPLE_TEXT), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = _run_fetch()

    assert calls["n"] == 2
    assert len(rows) == 2


def test_fetch_success_on_first_try_makes_no_retry_calls():
    calls = {"n": 0}

    async def fake_get_bytes(url, *, timeout=60.0):
        calls["n"] += 1
        return _FAKE_PDF_BYTES

    async def fake_sleep(_secs):
        raise AssertionError("should not sleep when the first attempt succeeds")

    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod, "_pdf_text", lambda data: SAMPLE_TEXT), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = _run_fetch()

    assert calls["n"] == 1
    assert len(rows) == 2


# --------------------------------------------------------------------------
# End-to-end via safe_run(): a persistent block still classifies as BLOCKED,
# not a silent/ambiguous ZERO_RESULT — this is the behavior that actually
# surfaced the 2026-09-23 incident to the owner in the first place.
# --------------------------------------------------------------------------


def test_persistent_403_classifies_as_blocked_via_safe_run():
    """fetch() itself SWALLOWS the httpx error (same as before this fix — it
    logs and returns [] rather than raising). In production that's still
    correctly flagged BLOCKED because the real shared transport
    (http_client._ThrottledTransport) records the block signal independent of
    whether the caller catches the resulting exception — see
    test_failure_classification.py::test_swallowed_block_promoted_to_blocked
    for that mechanism in isolation. Simulate it here the same way: the fake
    get_bytes appends to the run's block holder exactly like the real
    transport would for a 403 response."""
    from foreclosure_scraper.http_client import _block_holder

    async def fake_get_bytes(url, *, timeout=60.0):
        h = _block_holder.get()
        if h is not None:
            h.append((403, "HTTP 403 (blocked/forbidden) from www.spartanburgcounty.gov"))
        raise _mk_403()

    async def fake_sleep(_secs):
        return None

    scraper = mod.SpartanburgDelinquentTax()
    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = asyncio.run(scraper.safe_run())

    assert rows == []
    assert scraper.last_outcome == OUTCOME_BLOCKED
    assert "403" in scraper.last_reason
    assert "swallowed" in scraper.last_reason


def test_recovered_block_classifies_as_ok_via_safe_run():
    """A block on wave 1 that recovers on wave 2 must NOT leave a stale
    BLOCKED verdict once real rows are shipped."""
    calls = {"n": 0}

    async def fake_get_bytes(url, *, timeout=60.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _mk_403()
        return _FAKE_PDF_BYTES

    async def fake_sleep(_secs):
        return None

    scraper = mod.SpartanburgDelinquentTax()
    with patch.object(mod, "get_bytes", fake_get_bytes), \
         patch.object(mod, "_pdf_text", lambda data: SAMPLE_TEXT), \
         patch.object(mod.asyncio, "sleep", fake_sleep):
        rows = asyncio.run(scraper.safe_run())

    assert len(rows) == 2
    assert scraper.last_outcome == OUTCOME_OK

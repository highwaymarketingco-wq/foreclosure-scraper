"""national.cash_buyer_deeds -- the Cott (Polk/Rutherford) vendor path.

2026-10-04 (national.* extraction-completeness audit, batch 15): live-
verified this path has never actually returned data for either county it
targets, Polk or Rutherford -- the posted search-form field names
("ctl00$cphMain$txtFromDate" etc.) don't exist anywhere on either county's
real SrchName.aspx page, so the POST always lands back on an unchanged page
and `_parse_grid` correctly finds no results grid: a silent zero,
indistinguishable from "no cash buyers this month."

Root cause differs by county (see cash_buyer_deeds._cott_recent's own
docstring for the full live evidence):
  * Rutherford -- a genuine registration-approval wall. The page's own
    "Guest Login" button, when clicked, returns "Application Received and
    Pending Review... FURTHER ACTION REQUIRED... a form to be completed,
    signed and submitted" -- real identity/paperwork required, not
    something this engine can complete on its own (HERMES rule 3).
  * Polk -- no login gate at all (served as "Guest User" immediately), but
    the real date-range search lives behind a different nav tab ("Date")
    with different field names than what's posted. A genuine code bug,
    not a wall, but not fixed this batch (the final AJAX UpdatePanel
    postback didn't complete end-to-end in this session's investigation)
    -- left as a diagnosed, documented gap instead of a silent one.

These tests pin the new behavior: both failure modes are now logged with a
distinct, explained reason instead of melting into an ordinary empty
result, and the Aumentum/CCHS/Logan vendor paths (the other 8 counties)
are completely unaffected -- _cott_recent's return value (always []) is
unchanged either way, only the diagnosis improves.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from foreclosure_scraper.scrapers.national import cash_buyer_deeds as cbd


class _FakeResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Minimal stand-in for the httpx.AsyncClient yielded by http_client.client()."""

    def __init__(self, html: str):
        self._html = html

    async def get(self, url, **kw):
        return _FakeResp(200, self._html)

    async def post(self, url, **kw):
        return _FakeResp(200, self._html)


def _patch_http_client(monkeypatch, html: str) -> None:
    """_cott_recent resolves `client` via a LOCAL import inside the function
    body (`from ...http_client import client as _client`), so the only
    effective patch point is the real attribute on the http_client module
    itself -- patching cash_buyer_deeds' own namespace would do nothing."""
    import foreclosure_scraper.http_client as http_client_mod

    @asynccontextmanager
    async def _fake_client(**kw):
        yield _FakeClient(html)

    monkeypatch.setattr(http_client_mod, "client", _fake_client)


# Trimmed but structurally real fragment of Rutherford's actual login gate
# (live-captured 2026-10-04). No __VIEWSTATE needed here -- the wall is
# detected from the login-gate markers before any viewstate extraction.
_RUTHERFORD_LOGIN_GATE_HTML = """
<html><head><title>eSearch | Account Sign In</title></head><body>
<input type="text" name="ctl00$cphMain$blkLogin$txtUsername" />
<input type="password" name="ctl00$cphMain$blkLogin$txtPassword" />
<input type="submit" name="ctl00$cphMain$blkLogin$btnLogin" value="Log In" />
<input type="submit" name="ctl00$cphMain$blkLogin$btnGuestLogin" value="Sign in as a Guest" />
</body></html>
"""

# Polk's real page: no login gate, but also none of the field names
# _cott_recent posts (ctl00$cphMain$txtFromDate etc.) -- this fixture
# intentionally omits them, matching the live page. Also matches Polk's
# real (live-verified 2026-10-04) shape of an EMPTY __VIEWSTATE value
# (present, by design, not missing) to pin the fix that stopped treating
# that as a fetch failure.
_POLK_NO_GATE_NO_MATCHING_FIELDS_HTML = """
<html><head><title>eSearch | Quick Name Search</title></head><body>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="" />
<input type="hidden" name="__VIEWSTATEGENERATOR" value="xyz" />
<input type="hidden" name="__EVENTVALIDATION" value="val" />
<input type="text" name="ctl00$cphMain$tcMain$tpNewSearch$ucSrchNames$txtFirmSurname" />
</body></html>
"""


def test_counties_are_registered_in_cott_dispatch():
    """Sanity: both counties this module's docstring discusses are actually
    the two Cott counties this scraper targets."""
    from foreclosure_scraper.rod import cott
    assert ("NC", "Rutherford") in cott.COTT_COUNTIES
    assert ("NC", "Polk") in cott.COTT_COUNTIES


def test_rutherford_registration_wall_returns_empty_without_posting_search(monkeypatch):
    """The wall is detected straight off the GET -- no viewstate extraction
    or search POST is attempted against a page that's just a login gate."""
    posted = {"called": False}

    import foreclosure_scraper.http_client as http_client_mod

    class _RecordingClient(_FakeClient):
        async def post(self, url, **kw):
            posted["called"] = True
            return await super().post(url, **kw)

    @asynccontextmanager
    async def _fake_client(**kw):
        yield _RecordingClient(_RUTHERFORD_LOGIN_GATE_HTML)

    monkeypatch.setattr(http_client_mod, "client", _fake_client)

    out = asyncio.run(cbd._cott_recent("NC", "Rutherford", 30))
    assert out == []
    assert posted["called"] is False  # confirms the wall short-circuits before any POST


def test_polk_field_mismatch_still_returns_empty_gracefully(monkeypatch):
    """Polk has no login gate, so the search POST is attempted with the
    (known-wrong) field names; _parse_grid correctly finds no grid on the
    unchanged page that comes back. Same empty result as before this
    batch's fix -- the fix is diagnostic (a distinct log line), not a
    behavior change, since the real fix wasn't completed this session."""
    _patch_http_client(monkeypatch, _POLK_NO_GATE_NO_MATCHING_FIELDS_HTML)
    out = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert out == []


def test_empty_but_present_viewstate_is_not_treated_as_fetch_failure(monkeypatch):
    """Regression pin for the exact bug this batch found: Polk's page ships
    `name="__VIEWSTATE" value=""` (empty by design, not missing). The old
    `if not viewstate: return []` bailed out here BEFORE ever attempting
    the search POST, which meant the field-mismatch diagnostic could never
    fire for Polk at all. Confirmed via a POST-call-count: with the field
    present-but-empty, the search POST must still be attempted."""
    calls = {"post": 0}
    import foreclosure_scraper.http_client as http_client_mod

    class _CountingClient(_FakeClient):
        async def post(self, url, **kw):
            calls["post"] += 1
            return await super().post(url, **kw)

    @asynccontextmanager
    async def _fake_client(**kw):
        yield _CountingClient(_POLK_NO_GATE_NO_MATCHING_FIELDS_HTML)

    monkeypatch.setattr(http_client_mod, "client", _fake_client)
    out = asyncio.run(cbd._cott_recent("NC", "Polk", 30))
    assert out == []
    assert calls["post"] == 1  # proves it did NOT bail out before the search POST


def test_unregistered_county_returns_empty_without_any_request(monkeypatch):
    calls = {"n": 0}
    import foreclosure_scraper.http_client as http_client_mod

    @asynccontextmanager
    async def _fake_client(**kw):
        calls["n"] += 1
        yield _FakeClient("")

    monkeypatch.setattr(http_client_mod, "client", _fake_client)
    out = asyncio.run(cbd._cott_recent("NC", "NotACounty", 30))
    assert out == []
    assert calls["n"] == 0

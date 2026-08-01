"""Per-name jail-booking SEARCH roster — Greenville SC LANSA.

Unlike the bulk rosters (fetch-all + index), this vendor has no "show all", so
the enricher runs one last-name lookup per in-scope owner: a LANSA WEBEVENT
postback where the GET seeds the session WEBEVENT action token + hidden fields
and the POST echoes them with ASC_NML + ASTDRENTST=SEARCH. The grid is current
detainees only: Name | Book Date | Race | Sex | Age | Ht | Wt.

Gaston NC used to live in this lane on the New World "Aegis"
InmateInquiry.aspx postback; that app was retired (it now 302s to
Shared/Default.aspx) and Gaston moved to the bulk Tyler InmateInquiry grid —
see tests/test_jail_bookings_new_counties.py.

All HTTP is mocked so tests never touch the live servers.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_jail_bookings import (
    _search_lansa,
    enrich_jail_bookings,
)
from foreclosure_scraper.models import Listing


# --------------------------------------------------------------------------- #
# Fake curl_cffi AsyncSession that serves canned HTML for GET (form) + POST    #
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeSession:
    """Serves `get_html` on GET and `post_html` on POST, recording POST bodies."""

    def __init__(self, get_html, post_html):
        self._get = get_html
        self._post = post_html
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None, headers=None):
        return _FakeResp(self._get)

    async def post(self, url, data=None, timeout=None, headers=None):
        self.posts.append((url, data, headers))
        return _FakeResp(self._post)


def _patch_session(monkeypatch, get_html, post_html):
    fake = _FakeSession(get_html, post_html)
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    return fake


# --------------------------------------------------------------------------- #
# LANSA (Greenville) fixtures                                                   #
# --------------------------------------------------------------------------- #
LANSA_FORM = (
    '<form action="/cgi-bin/LANSAWEB?WEBEVENT+TOKEN123+GP1+ENG" method="post" name="LANSA">'
    '<input type="hidden" name="_LW3TRCID" value="TR1" />'
    '<input type="hidden" name="_FUNCTION" value="JAW00EX" />'
    '<input type="text" name="ASC_NML" size=15 >'
    '<input type="text" name="ASC_NMF" size=15 >'
    '</form>'
)


def _lansa_row(name, book, race, sex, age):
    return (f"<tr><td>{name}</td><td>{book}</td><td>{race}</td>"
            f"<td>{sex}</td><td>{age}</td><td>5' 10&quot;</td><td>180</td></tr>")


def _lansa_results(rows):
    return ("<html><body>Records Found:&nbsp;2<table>"
            + "".join(rows) + "</table></body></html>")


@pytest.mark.asyncio
async def test_lansa_parses_name_bookdate_age(monkeypatch):
    post = _lansa_results([
        _lansa_row("SMITH, ANTHONY MARQUISE", "04/14/2026", "B", "M", "33"),
        _lansa_row("SMITH, ANTHONY JARVIS", "05/26/2026", "B", "M", "45"),
    ])
    fake = _patch_session(monkeypatch, LANSA_FORM, post)
    recs = await _search_lansa("https://host/cgi-bin/lansaweb?procfun+X", "SMITH")
    assert len(recs) == 2
    r0 = recs[0]
    assert r0["last"] == "SMITH" and r0["first"] == "ANTHONY"
    assert r0["arrest_date"] == "04/14/2026"   # Book Date
    assert r0["age"] == "33"
    assert r0["dob"] is None                   # LANSA grid has no DOB
    # POST hit the session WEBEVENT action + set last name + SEARCH, NOT first name
    url, data, _ = fake.posts[0]
    assert "WEBEVENT+TOKEN123" in url
    assert data["ASC_NML"] == "SMITH"
    assert data["ASC_NMF"] == ""               # first name deliberately skipped
    assert data["ASTDRENTST"] == "SEARCH"


@pytest.mark.asyncio
async def test_lansa_bails_without_action(monkeypatch):
    fake = _patch_session(monkeypatch, "<html>no lansa form</html>", "<html/>")
    recs = await _search_lansa("https://host/cgi-bin/lansaweb?x", "SMITH")
    assert recs == []
    assert fake.posts == []


# --------------------------------------------------------------------------- #
# End-to-end: enrich_jail_bookings drives the search lane + sets both signals  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_end_to_end_greenville_match(monkeypatch):
    post = _lansa_results([
        _lansa_row("HARRIS, MICHAEL DEAN", "03/02/2026", "W", "M", "51"),
    ])
    _patch_session(monkeypatch, LANSA_FORM, post)
    li = Listing(source="test", source_url="http://x", state="SC",
                 county="Greenville County",
                 raw={"owner_mailing": {"owner": "HARRIS MICHAEL"}})
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 1
    jbk = li.raw["jail_booking"]
    assert jbk["county"] == "Greenville" and jbk["state"] == "SC"
    assert jbk["matched_name"] == "MICHAEL HARRIS"
    assert jbk["arrest_date"] == "03/02/2026"
    assert jbk["confidence"] == "name_only_low"
    assert li.raw["incarceration"]["source"] == "Greenville County jail roster"


@pytest.mark.asyncio
async def test_end_to_end_greenville_no_match_untouched(monkeypatch):
    post = _lansa_results([
        _lansa_row("OTHERPERSON, SOMEONE", "01/01/2026", "W", "F", "50"),
    ])
    _patch_session(monkeypatch, LANSA_FORM, post)
    li = Listing(source="test", source_url="http://x", state="SC",
                 county="Greenville",
                 raw={"owner_mailing": {"owner": "NOBODY MATCHING"}})
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 0
    assert "jail_booking" not in li.raw


@pytest.mark.asyncio
async def test_search_lane_dedupes_same_surname_pair(monkeypatch):
    """Two leads with the same owner name hit the vendor once, both get flagged."""
    post = _lansa_results([
        _lansa_row("JONES, ROBERT LEE", "05/05/2026", "B", "M", "46"),
    ])
    fake = _patch_session(monkeypatch, LANSA_FORM, post)
    lis = [
        Listing(source="t", source_url="http://a", state="SC", county="Greenville",
                raw={"owner_mailing": {"owner": "JONES ROBERT"}}),
        Listing(source="t", source_url="http://b", state="SC", county="Greenville",
                raw={"owner_mailing": {"owner": "JONES ROBERT"}}),
    ]
    res = await enrich_jail_bookings(lis)
    assert res["matched"] == 2                 # both leads flagged
    assert len(fake.posts) == 1                # but only one vendor search

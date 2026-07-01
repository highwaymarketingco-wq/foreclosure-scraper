"""Per-name jail-booking SEARCH rosters — Gaston NC Aegis + Greenville SC LANSA.

Unlike the bulk rosters (fetch-all + index), these two vendors have no "show
all", so the enricher runs one last-name lookup per in-scope owner:

  * Gaston  — New World/Tyler Aegis InmateInquiry.aspx: ASP.NET WebForms postback
    (__VIEWSTATE/__EVENTVALIDATION echo). The grid is the full 3-year booking
    HISTORY, so we keep only rows whose "In Custody" cell reads "Yes". Full DOB.
  * Greenville — LANSA WEBEVENT postback: GET seeds the session WEBEVENT action
    token + hidden fields, POST echoes them with ASC_NML + ASTDRENTST=SEARCH.
    Grid is current detainees only: Name | Book Date | Race | Sex | Age | Ht | Wt.

All HTTP is mocked so tests never touch the live servers.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_jail_bookings import (
    _search_aegis,
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
# Aegis (Gaston) fixtures                                                       #
# --------------------------------------------------------------------------- #
AEGIS_FORM = (
    '<form action="InmateInquiry.aspx" method="post">'
    '<input type="hidden" name="__VIEWSTATE" value="VS123" />'
    '<input type="hidden" name="__EVENTVALIDATION" value="EV456" />'
    '<input type="text" name="ctl00$DefaultContent$uxLastName" />'
    '<input type="submit" name="ctl00$DefaultContent$uxSearch" value="Search" />'
    '</form>'
)


def _aegis_row(name, in_custody, race, sex, dob):
    return (
        "<tr>"
        '<td><img src="../GetImage.aspx" /></td>'
        f'<td><a href="InmateSummary.aspx?ID=1">{name}</a></td>'
        f"<td>{in_custody}</td>"
        f"<td>{race}</td><td>{sex}</td><td>{dob}</td>"
        "<td>6' 0&quot;</td><td>205.0 lbs</td><td>&nbsp;</td><td>&nbsp;</td>"
        "</tr>"
    )


def _aegis_results(rows):
    return "<table>" + "".join(rows) + "</table>"


@pytest.mark.asyncio
async def test_aegis_keeps_only_in_custody_and_captures_dob(monkeypatch):
    post = _aegis_results([
        _aegis_row("Smith, Christopher Michael", "Yes", "White", "Male", "7/16/1989"),
        _aegis_row("Smith, Adrian John", "&nbsp;", "Black", "Male", "7/8/1960"),  # released
        _aegis_row("Smith, Jaquis Rahmad", "Yes", "Black", "Male", "1/29/2001"),
    ])
    fake = _patch_session(monkeypatch, AEGIS_FORM, post)
    recs = await _search_aegis("https://host/InmateInquiry.aspx", "SMITH")
    # only the two "Yes" rows survive
    assert {(r["first"], r["last"]) for r in recs} == {
        ("CHRISTOPHER", "SMITH"), ("JAQUIS", "SMITH")}
    chris = next(r for r in recs if r["first"] == "CHRISTOPHER")
    assert chris["dob"] == "7/16/1989"      # full DOB captured
    # the POST echoed the ASP.NET tokens + search fields
    _, data, _ = fake.posts[0]
    assert data["__VIEWSTATE"] == "VS123"
    assert data["__EVENTVALIDATION"] == "EV456"
    assert data["ctl00$DefaultContent$uxLastName"] == "SMITH"
    assert data["ctl00$DefaultContent$uxSearch"] == "Search"


@pytest.mark.asyncio
async def test_aegis_bails_without_viewstate(monkeypatch):
    fake = _patch_session(monkeypatch, "<html>no form here</html>", "<html/>")
    recs = await _search_aegis("https://host/InmateInquiry.aspx", "SMITH")
    assert recs == []
    assert fake.posts == []  # never posts without a __VIEWSTATE token


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
async def test_end_to_end_gaston_match(monkeypatch):
    post = _aegis_results([
        _aegis_row("Harris, Michael Dean", "Yes", "White", "Male", "3/2/1975"),
    ])
    _patch_session(monkeypatch, AEGIS_FORM, post)
    li = Listing(source="test", source_url="http://x", state="NC",
                 county="Gaston County",
                 raw={"owner_mailing": {"owner": "HARRIS MICHAEL"}})
    res = await enrich_jail_bookings([li])
    assert res["matched"] == 1
    jbk = li.raw["jail_booking"]
    assert jbk["county"] == "Gaston" and jbk["state"] == "NC"
    assert jbk["matched_name"] == "MICHAEL HARRIS"
    assert jbk["roster_dob"] == "3/2/1975"     # full DOB flows through
    assert jbk["confidence"] == "name_only_low"
    assert li.raw["incarceration"]["source"] == "Gaston County jail roster"


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
    post = _aegis_results([
        _aegis_row("Jones, Robert Lee", "Yes", "Black", "Male", "5/5/1980"),
    ])
    fake = _patch_session(monkeypatch, AEGIS_FORM, post)
    lis = [
        Listing(source="t", source_url="http://a", state="NC", county="Gaston",
                raw={"owner_mailing": {"owner": "JONES ROBERT"}}),
        Listing(source="t", source_url="http://b", state="NC", county="Gaston",
                raw={"owner_mailing": {"owner": "JONES ROBERT"}}),
    ]
    res = await enrich_jail_bookings(lis)
    assert res["matched"] == 2                 # both leads flagged
    assert len(fake.posts) == 1                # but only one vendor search

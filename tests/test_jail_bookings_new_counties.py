"""Henderson NC (Citizen Connect) + Gaston NC (Tyler InmateInquiry) rosters.

Both are BULK "show all current inmates" feeds and both publish FULL DOB, which
is the whole point of the lane: a DOB lifts downstream skip-trace match rates
far more than a name-only hit.

  * Henderson — Southern Software Citizen Connect. The roster is rendered
    server-side by fetch_current_confinements.php, which answers 500 "Session
    AgencyID not set" unless a PHP session has been seeded by one GET of
    bookingsearch/index.php?AgencyID=<agency>. Page 1 posts JMSAgencyID; the
    vendor's pager then posts IDX=<1-based page>, 20 cards per page.
  * Gaston — Tyler New World InmateInquiry. The search form is a plain GET, so
    ?InCustody=True&Page=<n> walks the whole roster 100 rows at a time. The grid
    has DOB + in-custody + scheduled release; booking date and charges live on
    the per-inmate detail page and are hydrated only for matched rows.

Fixtures mirror the live markup (captured 2026-07-31); no test touches a live
server.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.enrichment_jail_bookings import enrich_jail_bookings
from foreclosure_scraper.models import Listing
from foreclosure_scraper.scrapers.national.jail_bookings import (
    _fetch_citizen_connect,
    _fetch_tyler_detail,
    _fetch_tyler_inmate_inquiry,
    _parse_date,
    _split_space_name,
    _to_listing,
)


# --------------------------------------------------------------------------- #
# Citizen Connect (Henderson) fixtures                                         #
# --------------------------------------------------------------------------- #
def _cc_card(name, dob, booked, charges, age="36 years / W / M"):
    charge_html = "".join(
        '<div class="charge-item d-flex"><span class="charge-number">1</span>'
        f'<div class="charge-details"><div>{c}'
        '<span class="charge-agency"></span></div></div></div>'
        for c in charges)
    return (
        '<div class="card booking-card"><div class="card-body">'
        '<div class="booking-header d-flex justify-content-between align-items-start">'
        f'<h5 class="mb-0">{name}</h5><span ></span></div>'
        '<div class="booking-details">'
        '<div class="detail-row"><span class="detail-label">Demographics:</span>'
        f'<span class="detail-value">{age}</span></div>'
        '<div class="detail-row"><span class="detail-label">Date of Birth:</span>'
        f'<span class="detail-value">{dob}</span></div>'
        '<div class="detail-row"><span class="detail-label">Booked:</span>'
        f'<span class="detail-value">{booked}</span></div>'
        '<div class="detail-row"><span class="detail-label">Arresting Agency:</span>'
        '<span class="detail-value">HENDERSON SO - NC0450000</span></div>'
        "</div>"
        f'<div class="charges-section">{charge_html}</div>'
        "</div></div>")


def _cc_page(cards, total, first, last):
    return (
        f'<div class="mb-3"><h5 class="text-muted">Total Inmates: '
        f'<span class="text-primary">{total}</span></h5></div>'
        + "".join(cards)
        + f'<div class="pagination-info">Showing {first}-{last} of {total} inmates</div>')


class _CCFakeSession:
    """Serves the Citizen Connect handshake GET + paged confinement POSTs."""

    def __init__(self, pages, total, page_size=20):
        self._pages = pages          # list[list[str]] of card HTML per page
        self._total = total
        self._page_size = page_size
        self.gets: list[str] = []
        self.posts: list[tuple] = []
        self.session_seeded = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None, headers=None):
        self.gets.append(url)
        self.session_seeded = True
        return _Resp("<html>booking search form</html>")

    async def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append((url, dict(data or {})))
        if not self.session_seeded:
            return _Resp("Session AgencyID not set")
        idx = int((data or {}).get("IDX", 1))
        if idx > len(self._pages):
            return _Resp("")
        cards = self._pages[idx - 1]
        start = (idx - 1) * self._page_size + 1
        return _Resp(_cc_page(cards, self._total, start, start + len(cards) - 1))


class _Resp:
    def __init__(self, text):
        self.text = text


def _patch(monkeypatch, session):
    import curl_cffi.requests as ccr
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: session)
    return session


@pytest.mark.asyncio
async def test_citizen_connect_seeds_session_then_parses(monkeypatch):
    fake = _patch(monkeypatch, _CCFakeSession(
        [[_cc_card("MICHAEL LEE ABSHER", "09/26/1989", "07/31/2025",
                   ["STAT SEX OFF WITH CHILD&lt;=15", "THIRD DEG SEX EXPLOIT MINOR"])]],
        total=1))
    recs = await _fetch_citizen_connect("HendersonCoNC|NC0450000")

    assert len(recs) == 1
    r = recs[0]
    assert (r["last"], r["first"]) == ("ABSHER", "MICHAEL")
    assert r["dob"] == "09/26/1989"          # full DOB, the point of this source
    assert r["age"] == "36"
    assert r["arrest_date"] == "07/31/2025"
    assert r["charge"] == "STAT SEX OFF WITH CHILD<=15; THIRD DEG SEX EXPLOIT MINOR"
    assert r["release_status"] == "in_custody"
    # The AJAX endpoint 500s without a seeded PHP session, so the GET comes first.
    assert fake.gets and "AgencyID=HendersonCoNC" in fake.gets[0]
    assert fake.posts[0][1]["JMSAgencyID"] == "NC0450000"


@pytest.mark.asyncio
async def test_citizen_connect_pages_by_idx(monkeypatch):
    pages = [
        [_cc_card(f"FIRST{i} MIDDLE LAST{i}", "01/01/1980", "01/02/2026", ["DWI"])
         for i in range(20)],
        [_cc_card("SOLO ONLY EXTRA", "02/02/1975", "02/03/2026", ["LARCENY"])],
    ]
    fake = _patch(monkeypatch, _CCFakeSession(pages, total=21))
    recs = await _fetch_citizen_connect("HendersonCoNC|NC0450000")

    assert len(recs) == 21
    assert [p[1].get("IDX") for p in fake.posts] == [None, 2]  # page 1 then IDX=2


@pytest.mark.asyncio
async def test_citizen_connect_bails_when_session_never_seeded(monkeypatch):
    fake = _CCFakeSession([[_cc_card("A B C", "01/01/1980", "01/02/2026", [])]],
                          total=1)

    async def _no_session(url, timeout=None, headers=None):
        fake.gets.append(url)
        return _Resp("")                       # handshake failed, no session

    fake.get = _no_session
    _patch(monkeypatch, fake)
    assert await _fetch_citizen_connect("HendersonCoNC|NC0450000") == []


def test_split_space_name_drops_generational_suffix():
    assert _split_space_name("MICHAEL LEE ABSHER") == ("ABSHER", "MICHAEL")
    assert _split_space_name("BOBBY DEAN ABEE JR") == ("ABEE", "BOBBY")
    assert _split_space_name("PLAIN") is None


# --------------------------------------------------------------------------- #
# Tyler New World InmateInquiry (Gaston) fixtures                              #
# --------------------------------------------------------------------------- #
def _tnw_row(name, dob, in_custody="Yes", sched="", detail_id="3932378"):
    link = (f'<a href="/NewWorld.InmateInquiry/GastonCounty/Inmate/Detail/{detail_id}">'
            f"{name}</a>") if detail_id else name
    return (
        "<tr>"
        '<td class="Photo"></td>'
        f'<td class="Name">{link}</td>'
        '<td class="SubjectNumber">392643</td>'
        f'<td class="InCustody">{in_custody}</td>'
        f'<td class="ScheduledReleaseDate">{sched}</td>'
        '<td class="Race">Black</td><td class="Gender">Male</td>'
        f'<td class="DateOfBirth">{dob}</td>'
        '<td class="Height">5&#39; 8&quot;</td><td class="Weight">160.0 lbs</td>'
        '<td class="MultipleBookings"></td>'
        '<td class="HousingFacility">Gaston County Jail -Main</td>'
        "</tr>")


def _tnw_page(rows, first, last, total):
    return (f'<div class="ShowingRecordCount">Showing {first} to {last} of {total}</div>'
            "<table><thead><tr><th>Name</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


TNW_DETAIL = (
    '<div id="BookingHistory">'
    '<div class="Booking"><ul class="FieldList">'
    "<li><label for=BookingDate>Booking Date</label>"
    "<span id=BookingDate>8/25/2024 12:09 PM</span></li>"
    "<li><label for=ReleaseDate>Release Date</label><span id=ReleaseDate></span></li>"
    "</ul>"
    '<div class="BookingCharges"><table><tbody>'
    '<tr><td class="SeqNumber">1</td>'
    '<td class="ChargeDescription">Break/ Enter</td></tr>'
    '<tr><td class="SeqNumber">2</td>'
    '<td class="ChargeDescription">Sex Offense, 2nd Degree</td></tr>'
    "</tbody></table></div></div></div>")

TNW_DETAIL_CLOSED_FIRST = (
    '<div id="BookingHistory">'
    '<div class="Booking"><ul class="FieldList">'
    "<span id=BookingDate>1/1/2020 9:00 AM</span>"
    "<span id=ReleaseDate>1/9/2020 4:00 PM</span></ul></div>"
    '<div class="Booking"><ul class="FieldList">'
    "<span id=BookingDate>7/14/2026 10:55 PM</span>"
    "<span id=ReleaseDate></span></ul></div></div>")


class _TNWFakeSession:
    """Serves paged grid GETs plus per-inmate detail GETs."""

    def __init__(self, pages, total, detail_html=TNW_DETAIL):
        self._pages = pages
        self._total = total
        self._detail = detail_html
        self.gets: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None, headers=None):
        self.gets.append(url)
        if "/Inmate/Detail/" in url:
            return _Resp(self._detail)
        page = int(url.rsplit("Page=", 1)[1]) if "Page=" in url else 1
        if page > len(self._pages):
            return _Resp("<html></html>")
        rows = self._pages[page - 1]
        first = (page - 1) * 100 + 1
        return _Resp(_tnw_page(rows, first, first + len(rows) - 1, self._total))


GASTON = "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"


@pytest.mark.asyncio
async def test_tyler_grid_keeps_in_custody_and_captures_dob(monkeypatch):
    fake = _patch(monkeypatch, _TNWFakeSession([[
        _tnw_row("Abdul-Wali, Khalid", "08/10/1967"),
        _tnw_row("Released, Person", "05/20/1966", in_custody=""),
        _tnw_row("Leaving, Soon", "06/05/1996", sched="09/01/2026",
                 detail_id="3221970"),
    ]], total=3))
    recs = await _fetch_tyler_inmate_inquiry(GASTON)

    assert [(r["last"], r["first"]) for r in recs] == [
        ("ABDUL-WALI", "KHALID"), ("LEAVING", "SOON")]
    assert recs[0]["dob"] == "08/10/1967"
    assert recs[0]["release_status"] == "in_custody"
    assert recs[0]["facility"] == "Gaston County Jail -Main"
    assert recs[0]["detail_id"] == "3932378"
    # A published scheduled release date is carried through as release status.
    assert recs[1]["scheduled_release"] == "09/01/2026"
    assert recs[1]["release_status"] == "scheduled_release 09/01/2026"
    # Grid-only by default: no detail page requests.
    assert not any("/Inmate/Detail/" in u for u in fake.gets)
    # The in-custody filter is pushed to the server too.
    assert "InCustody=True" in fake.gets[0]


@pytest.mark.asyncio
async def test_tyler_walks_pages_until_showing_count_satisfied(monkeypatch):
    pages = [
        [_tnw_row(f"Last{i:03d}, First{i:03d}", "01/01/1980") for i in range(100)],
        [_tnw_row("Tail, End", "02/02/1990")],
    ]
    fake = _patch(monkeypatch, _TNWFakeSession(pages, total=101))
    recs = await _fetch_tyler_inmate_inquiry(GASTON)
    assert len(recs) == 101
    assert [u.rsplit("Page=", 1)[1] for u in fake.gets] == ["1", "2"]


@pytest.mark.asyncio
async def test_tyler_detail_limit_hydrates_booking_date_and_charges(monkeypatch):
    fake = _patch(monkeypatch, _TNWFakeSession(
        [[_tnw_row("Abdul-Wali, Khalid", "08/10/1967"),
          _tnw_row("Second, Person", "01/01/1970", detail_id="999")]], total=2))
    recs = await _fetch_tyler_inmate_inquiry(GASTON, detail_limit=1)

    assert recs[0]["arrest_date"] == "8/25/2024 12:09 PM"
    assert recs[0]["charge"] == "Break/ Enter; Sex Offense, 2nd Degree"
    assert recs[1]["arrest_date"] is None      # capped at one detail fetch
    assert sum("/Inmate/Detail/" in u for u in fake.gets) == 1


@pytest.mark.asyncio
async def test_tyler_detail_picks_the_open_booking(monkeypatch):
    _patch(monkeypatch, _TNWFakeSession([[]], total=0,
                                        detail_html=TNW_DETAIL_CLOSED_FIRST))
    detail = await _fetch_tyler_detail(GASTON, "3932378")
    # The first block is a closed booking (has a Release Date); take the open one.
    assert detail["arrest_date"] == "7/14/2026 10:55 PM"


# --------------------------------------------------------------------------- #
# Listing shape + end-to-end enrichment                                        #
# --------------------------------------------------------------------------- #
def test_to_listing_carries_dob_and_release_status():
    li = _to_listing({"last": "ABSHER", "first": "MICHAEL", "dob": "09/26/1989",
                      "age": "36", "arrest_date": "07/31/2025", "charge": "DWI",
                      "release_status": "in_custody"}, "NC", "Henderson")
    jbk = li.raw["jail_booking"]
    assert jbk["dob"] == "09/26/1989"
    assert jbk["release_status"] == "in_custody"
    assert jbk["booking_date"].startswith("2025-07-31")
    assert li.county == "Henderson" and li.state == "NC"
    assert "AgencyID=HendersonCoNC" in li.source_url


def test_parse_date_handles_both_new_vendor_stamps():
    assert _parse_date("8/25/2024 12:09 PM").hour == 12
    assert _parse_date("10/21/2025 17:26").hour == 17
    assert _parse_date("07/31/2025").day == 31


@pytest.mark.asyncio
async def test_end_to_end_henderson_match_sets_dob(monkeypatch):
    _patch(monkeypatch, _CCFakeSession(
        [[_cc_card("MICHAEL DEAN HARRIS", "03/02/1975", "07/01/2026", ["DWI"])]],
        total=1))
    li = Listing(source="test", source_url="http://x", state="NC",
                 county="Henderson County",
                 raw={"owner_mailing": {"owner": "HARRIS MICHAEL"}})
    res = await enrich_jail_bookings([li])

    assert res["matched"] == 1
    jbk = li.raw["jail_booking"]
    assert jbk["county"] == "Henderson" and jbk["state"] == "NC"
    assert jbk["roster_dob"] == "03/02/1975"   # DOB reaches the lead record
    assert jbk["release_status"] == "in_custody"
    assert li.raw["incarceration"]["source"] == "Henderson County jail roster"


@pytest.mark.asyncio
async def test_end_to_end_gaston_match_hydrates_booking_detail(monkeypatch):
    _patch(monkeypatch, _TNWFakeSession(
        [[_tnw_row("Harris, Michael Dean", "03/02/1975")]], total=1))
    li = Listing(source="test", source_url="http://x", state="NC",
                 county="Gaston County",
                 raw={"owner_mailing": {"owner": "HARRIS MICHAEL"}})
    res = await enrich_jail_bookings([li])

    assert res["matched"] == 1
    assert res["hydrated"] == 1
    jbk = li.raw["jail_booking"]
    assert jbk["roster_dob"] == "03/02/1975"
    # Booking date + charges are absent from the grid and hydrated per match.
    assert jbk["arrest_date"] == "8/25/2024 12:09 PM"
    assert jbk["charge"] == "Break/ Enter; Sex Offense, 2nd Degree"


@pytest.mark.asyncio
async def test_gaston_no_match_makes_no_detail_request(monkeypatch):
    fake = _patch(monkeypatch, _TNWFakeSession(
        [[_tnw_row("Someone, Else", "03/02/1975")]], total=1))
    li = Listing(source="test", source_url="http://x", state="NC", county="Gaston",
                 raw={"owner_mailing": {"owner": "NOBODY HOME"}})
    res = await enrich_jail_bookings([li])

    assert res["matched"] == 0
    assert "jail_booking" not in li.raw
    assert not any("/Inmate/Detail/" in u for u in fake.gets)

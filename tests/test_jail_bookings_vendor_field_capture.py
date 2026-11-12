"""national.jail_bookings -- HERMES extraction-completeness audit, batch 17
(2026-10-04).

Several real gaps found and fixed, all live-verified against the current
public rosters:

1. Zuercher (Cherokee/Anderson/Laurens/Oconee SC): `mugshot` is raw base64
   JPEG bytes embedded directly in the JSON response (confirmed live --
   the `/9j/` prefix decodes to a JPEG SOI marker), not a URL. Nothing
   downstream reads or decodes it (grepped the whole repo), and storing the
   bare base64 string made it unusable to any `<img src=...>` consumer.
   Fixed to wrap as a `data:image/jpeg;base64,...` URI.
2. Zuercher's `hold_reasons` field carries literal `<br />` HTML tags
   between multiple charges on most rows (live: 200/291 Cherokee, 361/538
   Anderson) -- never stripped. Fixed with the existing `_strip_tags()`
   helper.
3. Zuercher's `is_juvenile` flag (real, rarely true but present on every
   row) was never captured.
4. CentralSquare P2C jqGrid (Cleveland NC): `middlename`/`age`/`race`/
   `sex`/`book_id`/`disp_agency` are on every live row, never read.
5. Modern CentralSquare P2C (Buncombe NC): `MiddleName`/`Race`/`Sex`/
   `Height`/`Weight`/`ScarsMarksTattoos` (87% populated live)/the full
   `Charges` list (not just PrimaryChargeDescription, 79% of live bookings
   carry a second charge)/`HoldingFacility`/`BookingAgency`/`CourtDate`/
   `TotalBondAmount`/`HomeAddress` (defensive -- 0% populated live, same
   redaction policy as DateOfBirth) were all on the row already fetched,
   never read. `ImageId` maps to a real, no-auth, directly fetchable
   mugshot at `/api/Inmates/Image/<listId>/<ImageId>` (confirmed live,
   200 OK, real PNG bytes, works from a cold session) -- never wired.
6. Buncombe's own `source_url` pointed at `/en/Inmates`, which returns
   HTTP 200 (so the scraper's own XSRF-token handshake still works) but
   whose client-side Angular router has no matching page and renders its
   own "404 - Not Found" to a human visitor (confirmed live via browser
   render). Fixed to the real working nav target, `/Inmates/Catalog`
   (confirmed live by clicking the site's own menu link).
"""
from __future__ import annotations

import asyncio
import base64

from foreclosure_scraper.scrapers.national.jail_bookings import (
    _fetch_p2c_jqgrid,
    _fetch_p2c_jqgrid_mugshot,
    _fetch_zuercher,
    _parse_citizen_connect_cards,
    _parse_tyler_rows,
    _to_listing,
)


class _FakeResp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _FakeSession:
    def __init__(self, get_data=None, post_data=None):
        self._get_data = get_data
        self._post_data = post_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None):
        return _FakeResp(self._get_data)

    async def post(self, url, json=None, data=None, timeout=None):
        return _FakeResp(self._post_data)


def _patch_session(monkeypatch, **kwargs):
    import curl_cffi.requests as ccr
    fake = _FakeSession(**kwargs)
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)
    return fake


# ---------------------------------------------------------------------------
# Zuercher: mugshot data-URI, hold_reasons HTML stripping, is_juvenile
# ---------------------------------------------------------------------------

def _zuercher_rec(**overrides) -> dict:
    base = {
        "name": "Adams, Bruce Edward",
        "race": "Black or African American", "sex": "Male",
        "cell_block": "", "arrest_date": "2026-09-21",
        "hold_reasons": (
            "Warrant Charge: Trespassing; Arrest Date 09/21/2026;<br />"
            "Warrant Charge: Larceny; Arrest Date 09/21/2026;"
        ),
        "dob": "", "is_juvenile": False, "release_date": None,
        "mugshot": "/9j/4AAQSkZJRgABAQEAYABg",
    }
    base.update(overrides)
    return base


def test_zuercher_mugshot_wrapped_as_data_uri(monkeypatch):
    _patch_session(monkeypatch, post_data={"records": [_zuercher_rec()]})
    out = asyncio.run(_fetch_zuercher("cherokee-so-sc"))
    assert len(out) == 1
    assert out[0]["mugshot"] == "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABg"


def test_zuercher_mugshot_none_when_absent(monkeypatch):
    _patch_session(monkeypatch, post_data={"records": [_zuercher_rec(mugshot=None)]})
    out = asyncio.run(_fetch_zuercher("cherokee-so-sc"))
    assert out[0]["mugshot"] is None


def test_zuercher_hold_reasons_html_stripped(monkeypatch):
    _patch_session(monkeypatch, post_data={"records": [_zuercher_rec()]})
    out = asyncio.run(_fetch_zuercher("cherokee-so-sc"))
    charge = out[0]["charge"]
    assert "<br" not in charge
    assert "Trespassing" in charge and "Larceny" in charge


def test_zuercher_captures_is_juvenile_flag(monkeypatch):
    _patch_session(monkeypatch, post_data={"records": [_zuercher_rec(is_juvenile=True)]})
    out = asyncio.run(_fetch_zuercher("cherokee-so-sc"))
    assert out[0]["is_juvenile"] is True


def test_zuercher_list_shaped_hold_reasons_still_works(monkeypatch):
    """hold_reasons can also arrive as a list (a different Zuercher tenant
    shape) -- must not regress the pre-existing list-join path."""
    _patch_session(monkeypatch, post_data={"records": [
        _zuercher_rec(hold_reasons=["Trespassing", "Larceny"])
    ]})
    out = asyncio.run(_fetch_zuercher("cherokee-so-sc"))
    assert out[0]["charge"] == "Trespassing; Larceny"


# ---------------------------------------------------------------------------
# CentralSquare P2C jqGrid (Cleveland NC)
# ---------------------------------------------------------------------------

def _jqgrid_row(**overrides) -> dict:
    base = {
        "lastname": "ADAMS", "firstname": "ANGELA", "middlename": "PATTERSON",
        "dob": "2/21/1970 12:00:00 AM", "disp_arrest_date": "08/01/2026",
        "chrgdesc": "MISD PROB VIOL", "age": "56", "race": "White",
        "sex": "Female", "book_id": "146145", "disp_agency": "Cleveland County SO",
    }
    base.update(overrides)
    return base


def test_p2c_jqgrid_captures_middle_age_race_sex_book_id(monkeypatch):
    _patch_session(monkeypatch, get_data={}, post_data={"rows": [_jqgrid_row()]})
    out = asyncio.run(_fetch_p2c_jqgrid("http://74.218.167.200/p2c"))
    assert len(out) == 1
    rec = out[0]
    assert rec["middle"] == "PATTERSON"
    assert rec["age"] == "56"
    assert rec["race"] == "White"
    assert rec["sex"] == "Female"
    assert rec["book_id"] == "146145"
    assert rec["agency"] == "Cleveland County SO"


# ---------------------------------------------------------------------------
# _to_listing: Buncombe source_url fix + new raw.jail_booking fields
# ---------------------------------------------------------------------------

def test_buncombe_source_url_points_at_working_catalog_route():
    li = _to_listing({"last": "SMITH", "first": "JOHN"}, "NC", "Buncombe")
    assert li.source_url == "https://buncombecountyso.policetocitizen.com/Inmates/Catalog"
    assert "/en/Inmates" not in li.source_url


def test_to_listing_carries_buncombe_rich_fields():
    rec = {
        "last": "HUMES", "first": "ELIZABETH", "middle": "TYREE",
        "race": "WHITE", "sex": "FEMALE", "height": "5' 06\"", "weight": "126",
        "scars_marks_tattoos": 'TATT LEFT RIB: "TRUST NO ONE"',
        "other_charges": "RESISTING ARREST",
        "holding_facility": "MAIN JAIL", "booking_agency": "BUNCOMBE COUNTY SHERIFF DEPT",
        "court_date": "10/5/2026 9:30:00 AM", "total_bond_amount": 0.0,
        "home_address": None,
        "mugshot_url": "https://buncombecountyso.policetocitizen.com/api/Inmates/Image/23/1495507.01",
    }
    li = _to_listing(rec, "NC", "Buncombe")
    jb = li.raw["jail_booking"]
    assert jb["middle_name"] == "TYREE"
    assert jb["scars_marks_tattoos"] == 'TATT LEFT RIB: "TRUST NO ONE"'
    assert jb["other_charges"] == "RESISTING ARREST"
    assert jb["holding_facility"] == "MAIN JAIL"
    assert jb["booking_agency"] == "BUNCOMBE COUNTY SHERIFF DEPT"
    assert jb["mugshot"] == "https://buncombecountyso.policetocitizen.com/api/Inmates/Image/23/1495507.01"


def test_to_listing_survives_raw_keep_slim():
    from foreclosure_scraper.web_artifact import _slim_raw

    rec = {"last": "SMITH", "first": "JOHN", "middle": "Q", "book_id": "999",
           "scars_marks_tattoos": "TATT ARM", "mugshot_url": "https://x/y.png"}
    li = _to_listing(rec, "NC", "Buncombe")
    slim = _slim_raw(li.raw)
    assert slim["jail_booking"] == li.raw["jail_booking"]


# ---------------------------------------------------------------------------
# Source-completeness audit 2026-10-13/14: "mugshot inconsistency across
# vendors in the same file". Zuercher + Buncombe already had one (tests
# above); Henderson (Citizen Connect) and Gaston (Tyler) silently had none
# despite both genuinely publishing one; Cleveland (jqGrid) has no cheap
# direct URL at all, so it gets a standalone on-demand helper instead of an
# eager fetch (budget reasoning in the module docstring / helper docstring).
# ---------------------------------------------------------------------------

# Real card shape live-verified 2026-10-14 against Henderson NC's roster
# (https://cc.southernsoftware.com/bookingsearch/.../fetch_current_confinements.php).
_CC_REAL_CARD = """<div class="card booking-card">
<div class="card-body"><div class="booking-header d-flex justify-content-between align-items-start">
                <h5 class="mb-0">MICHAEL LEE ABSHER</h5>
                <span ></span>
              </div><div class="row mt-3"><div class="col-auto"><!-- IMAGE VERSION 6.1 --><img class='booking-mugshot booking-mugshot-v6'
                       src='https://ssmugshots.blob.core.windows.net/images/NC0450000-27651-97946-535287-Mugshot-1.jpg'
                       data-fallback='https://nucleuspsp.com/ccdata/assets/crons/CCMugshots/NoMugshot.jpg'
                       alt='Booking photo for MICHAEL LEE ABSHER'></div><div class="col">
                <div class="booking-details"><div class="detail-row">
                <span class="detail-label">Demographics:</span>
                <span class="detail-value">37 years / W / M</span>
              </div><div class="detail-row">
                    <span class="detail-label">Date of Birth:</span>
                    <span class="detail-value">09/26/1989</span>
                  </div><div class="detail-row">
                <span class="detail-label">Booked:</span>
                <span class="detail-value">10/10/2026 08:00</span>
              </div></div></div></div></div></div>"""

# Real fallback shape (no real photo on file) -- the vendor's own literal
# shared asset, live-confirmed on 1/180 Henderson rows.
_CC_FALLBACK_CARD = """<div class="card booking-card">
<div class="card-body"><div class="booking-header d-flex justify-content-between align-items-start">
                <h5 class="mb-0">JANE DOE SMITH</h5>
              </div><div class="row mt-3"><div class="col-auto"><img class='booking-mugshot booking-mugshot-v6'
                       src='https://nucleuspsp.com/ccdata/assets/crons/CCMugshots/NoMugshot.jpg'
                       alt='Booking photo for JANE DOE SMITH'></div><div class="col">
                <div class="booking-details"></div></div></div></div></div>"""


def test_citizen_connect_captures_real_mugshot_url():
    recs = _parse_citizen_connect_cards(_CC_REAL_CARD)
    assert len(recs) == 1
    assert recs[0]["mugshot_url"] == (
        "https://ssmugshots.blob.core.windows.net/images/"
        "NC0450000-27651-97946-535287-Mugshot-1.jpg"
    )


def test_citizen_connect_drops_the_shared_no_photo_fallback():
    recs = _parse_citizen_connect_cards(_CC_FALLBACK_CARD)
    assert len(recs) == 1
    assert recs[0]["mugshot_url"] is None


def test_citizen_connect_mugshot_survives_to_listing():
    rec = _parse_citizen_connect_cards(_CC_REAL_CARD)[0]
    li = _to_listing(rec, "NC", "Henderson")
    assert li.raw["jail_booking"]["mugshot"] == rec["mugshot_url"]


# Real grid row shape live-verified 2026-10-14 against Gaston NC's roster
# (https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty).
_TNW_REAL_ROW = """<tr>
<td class="Photo"><img src="/NewWorld.InmateInquiry/GastonCounty/Inmate/Photo/0WM5GI5N?type=Search" alt="0WM5GI5N" aria-label="Mugshot for Abdul-Wali, Khalid" /></td>
<td class="Name"><a href="/NewWorld.InmateInquiry/GastonCounty/Inmate/Detail/3932378">Abdul-Wali, Khalid</a></td>
<td class="SubjectNumber">392643</td>
<td class="InCustody">Yes</td>
<td class="ScheduledReleaseDate"></td>
<td class="Race">Black</td>
<td class="Gender">Male</td>
<td class="DateOfBirth">08/10/1967</td>
<td class="Height">5&#39; 8&quot;</td>
<td class="Weight">160.0 lbs</td>
<td class="MultipleBookings"></td>
<td class="HousingFacility">Gaston County Jail -Main</td>
</tr>"""

_TNW_BASE = "https://tepsweb.cityofgastonia.com/NewWorld.InmateInquiry/GastonCounty"


def test_tyler_photo_cell_survives_strip_tags_regression():
    """Regression guard: `_TNW_CELL_RE` + `_strip_tags` alone reduce the
    Photo cell to "" (an <img>-only cell has no text) -- this is exactly the
    silent-drop the audit flagged, confirmed still true of the generic cell
    parse before `_TNW_PHOTO_RE` was added."""
    from foreclosure_scraper.scrapers.national.jail_bookings import (
        _TNW_CELL_RE, _strip_tags,
    )
    cells = {k: _strip_tags(v) for k, v in _TNW_CELL_RE.findall(_TNW_REAL_ROW)}
    assert cells.get("Photo") == ""


def test_tyler_captures_real_mugshot_url_absolute():
    recs = _parse_tyler_rows(_TNW_REAL_ROW, base=_TNW_BASE)
    assert len(recs) == 1
    assert recs[0]["mugshot_url"] == (
        f"{_TNW_BASE}/Inmate/Photo/0WM5GI5N?type=Search"
    )


def test_tyler_mugshot_survives_to_listing():
    rec = _parse_tyler_rows(_TNW_REAL_ROW, base=_TNW_BASE)[0]
    li = _to_listing(rec, "NC", "Gaston")
    assert li.raw["jail_booking"]["mugshot"] == rec["mugshot_url"]


def test_tyler_no_photo_cell_is_handled():
    row_no_photo = _TNW_REAL_ROW.replace(
        '<td class="Photo"><img src="/NewWorld.InmateInquiry/GastonCounty/'
        'Inmate/Photo/0WM5GI5N?type=Search" alt="0WM5GI5N" '
        'aria-label="Mugshot for Abdul-Wali, Khalid" /></td>',
        '<td class="Photo"></td>',
    )
    recs = _parse_tyler_rows(row_no_photo, base=_TNW_BASE)
    assert recs[0]["mugshot_url"] is None


# ---------------------------------------------------------------------------
# CentralSquare P2C jqGrid (Cleveland NC) mugshot: no direct URL exists, so
# this is a standalone, selectively-called helper (never called from
# _fetch_p2c_jqgrid itself -- see its docstring for the budget reasoning).
# ---------------------------------------------------------------------------

class _FakeJqgridMugshotSession:
    """Scripts the exact 4-call sequence _fetch_p2c_jqgrid_mugshot makes:
    GET page (viewstate) -> POST grid (rows incl. our book_id) -> POST
    postback (selects that row) -> GET Mug.aspx (the photo bytes)."""

    def __init__(self, rows, photo_bytes=b"\xff\xd8\xff\xe0fakejpeg"):
        self._rows = rows
        self._photo_bytes = photo_bytes
        self.posts: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, timeout=None):
        if "Mug.aspx" in url:
            return _FakeHttpResp(content=self._photo_bytes, status_code=200)
        # The initial page GET -- needs real-shaped hidden-field HTML.
        html_body = (
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS123" />'
            '<input type="hidden" name="__VIEWSTATEGENERATOR" '
            'id="__VIEWSTATEGENERATOR" value="GEN1" />'
            '<input type="hidden" name="__EVENTVALIDATION" '
            'id="__EVENTVALIDATION" value="EV456" />'
        )
        return _FakeHttpResp(text=html_body)

    async def post(self, url, data=None, json=None, timeout=None):
        self.posts.append(data or json or {})
        if "jqHandler" in url:
            return _FakeHttpResp(json_data={"rows": self._rows})
        return _FakeHttpResp(text="")  # the postback itself


class _FakeHttpResp:
    def __init__(self, text="", json_data=None, content=b"", status_code=200):
        self.text = text
        self._json = json_data
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._json


def test_p2c_jqgrid_mugshot_not_called_eagerly(monkeypatch):
    """The whole point of the standalone helper: fetching a roster must NOT
    trigger any mugshot postback traffic."""
    calls = {"n": 0}

    async def _spy(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(
        "foreclosure_scraper.scrapers.national.jail_bookings._fetch_p2c_jqgrid_mugshot",
        _spy,
    )
    _patch_session(monkeypatch, get_data={}, post_data={"rows": [_jqgrid_row()]})
    asyncio.run(_fetch_p2c_jqgrid("http://74.218.167.200/p2c"))
    assert calls["n"] == 0


def test_p2c_jqgrid_mugshot_fetches_real_bytes_for_matching_book_id(monkeypatch):
    import curl_cffi.requests as ccr
    fake = _FakeJqgridMugshotSession(rows=[
        {"invid": "1", "book_id": "146145"},
        {"invid": "2", "book_id": "999999"},
    ])
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)

    result = asyncio.run(
        _fetch_p2c_jqgrid_mugshot("http://74.218.167.200/p2c", "146145")
    )
    assert result == "data:image/jpeg;base64," + base64.b64encode(
        b"\xff\xd8\xff\xe0fakejpeg"
    ).decode("ascii")
    # The postback must select invid "1" (146145's row), not "2".
    postback = fake.posts[-1]
    assert postback[
        "ctl00$MasterPage$mainContent$CenterColumnContent$hfRecordIndex"
    ] == "1"


def test_p2c_jqgrid_mugshot_returns_none_for_unknown_book_id(monkeypatch):
    import curl_cffi.requests as ccr
    fake = _FakeJqgridMugshotSession(rows=[{"invid": "1", "book_id": "146145"}])
    monkeypatch.setattr(ccr, "AsyncSession", lambda *a, **k: fake)

    result = asyncio.run(
        _fetch_p2c_jqgrid_mugshot("http://74.218.167.200/p2c", "no-such-id")
    )
    assert result is None

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

from foreclosure_scraper.scrapers.national.jail_bookings import (
    _fetch_p2c_jqgrid,
    _fetch_zuercher,
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

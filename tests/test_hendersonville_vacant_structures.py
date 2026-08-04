"""City of Hendersonville NC vacant / condemned structures register.

Offline tests run against the SAVED 52-row payload
(``tests/fixtures/hendersonville_vacant_structures.json``), pulled live with
the module's own enumerated ``outFields`` — so the fixture, like the scraper,
simply has no PHONE__ / EMAIL / column19 in it at all.

Two live rows type contact details into the free-text NOTES cell (one owner
email, one tenant phone number). The fixture keeps that SHAPE but substitutes
synthetic values, so the scrubber is exercised for real without this repo
storing a real person's email or phone. The privacy tests below assert on both
the fixture output and — under RUN_LIVE — the live payload.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc import hendersonville_vacant_structures as mod

from tests._arcgis_fakes import FakeHttp

FIX = Path(__file__).parent / "fixtures"

EMAIL_PAT = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE_PAT = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")


def _payload() -> dict:
    return json.loads((FIX / "hendersonville_vacant_structures.json").read_text())


class _ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run(http=None) -> list:
    http = http or FakeHttp({}, pages=[_payload()])
    original = mod.client
    mod.client = lambda *a, **kw: _ctx(http)      # noqa: E731
    try:
        return list(asyncio.run(mod.HendersonvilleVacantStructures().fetch()))
    finally:
        mod.client = original


def _blob(rows) -> str:
    return json.dumps([li.model_dump(mode="json") for li in rows])


# --------------------------------------------------------------------------- #
# PRIVACY — blocking. These are the reason the module exists in this shape.
# --------------------------------------------------------------------------- #

def test_contact_columns_are_never_requested():
    """PHONE__, EMAIL and the unlabeled column19 are on the layer. None may be
    named in outFields, and query_features separately rejects '*'."""
    for f in mod.FORBIDDEN_FIELDS:
        assert f not in mod._OUT_FIELDS
    assert "*" not in mod._OUT_FIELDS
    assert "PHONE" not in mod._OUT_FIELDS.upper()
    assert "EMAIL" not in mod._OUT_FIELDS.upper()


def test_the_query_actually_sends_the_enumerated_field_list():
    http = FakeHttp({}, pages=[_payload()])
    _run(http)
    _verb, _url, params = http.calls[0]
    assert params["outFields"] == mod._OUT_FIELDS
    assert params["outFields"] != "*"
    for f in mod.FORBIDDEN_FIELDS:
        assert f not in params["outFields"]


def test_out_fields_only_names_columns_that_are_property_record_data():
    assert set(mod._FIELDS) == {
        "FID", "DATE", "ADDRESS", "City", "State",
        "OCCUPIED", "BOARDED_UP", "CONDEMNED", "DELINQUENT_TAX", "UTILITIES",
        "NOV___CONTACT_LETTER_SENT", "CODE_COLOR", "NOTES",
        "OWNER", "MAILING_ADDRESS", "MAIL_CITY", "ST", "ZIP",
    }


def test_no_email_or_phone_survives_into_any_emitted_listing():
    """Omitting the contact COLUMNS is not enough — officers paste contact
    details into free text. This asserts on the whole serialized payload."""
    blob = _blob(_run())
    assert not EMAIL_PAT.search(blob), "an email address reached the board"
    assert not PHONE_PAT.search(blob), "a phone number reached the board"
    for f in mod.FORBIDDEN_FIELDS:
        assert f not in blob


def test_the_fixture_really_does_contain_contact_data_to_scrub():
    """Guards against the test above passing vacuously if the city ever cleans
    the register — if that happens this fails loudly rather than going quiet."""
    raw = (FIX / "hendersonville_vacant_structures.json").read_text()
    assert EMAIL_PAT.search(raw), "fixture must retain an email inside NOTES"
    assert PHONE_PAT.search(raw), "fixture must retain a phone inside NOTES"


@pytest.mark.parametrize("raw,want", [
    ("BUILDING IS VACANT - owner1965@example.net", "BUILDING IS VACANT [redacted]"),
    ("TENANT IS JANE DOE 828-555-0100", "TENANT IS JANE DOE [redacted]"),
    ("CALL (828) 555 0100 FIRST", "CALL [redacted] FIRST"),
    ("METER PULLED FEB 2020", "METER PULLED FEB 2020"),
    ("NO WATER USAGE IN 3 YRS", "NO WATER USAGE IN 3 YRS"),
    ("a@b.com", "[redacted]"),
    ("", None), (None, None),
])
def test_scrub_contact(raw, want):
    assert mod.scrub_contact(raw) == want


def test_scrubbing_preserves_the_rest_of_the_note():
    li = next(li for li in _run() if li.street_address == "115 RHODES ST")
    note = li.raw["code_enforcement"]["notes"]
    assert note.startswith("BUILDING IS VACANT")
    assert "@" not in note


# --------------------------------------------------------------------------- #
# join key
# --------------------------------------------------------------------------- #

def test_the_owner_mailing_zip_is_never_used_as_the_property_zip():
    """The only ZIP on the row belongs to the OWNER. Stamping it on the listing
    would build the dedupe key off the wrong property — 112 N BLUE RIDGE AVE in
    Hendersonville NC would key on 91344 (Granada Hills, CA)."""
    li = next(li for li in _run() if li.street_address == "112 N BLUE RIDGE AVE")
    assert li.zip_code is None
    assert li.raw["owner_mailing"]["zip"] == "91344"
    assert li.raw["owner_mailing"]["state"] == "CA"
    assert li.dedupe_key() == "addr:112 n blue ridge ave|NC:henderson"


def test_address_is_the_join_key_and_county_matches_the_other_henderson_sources():
    """counties_nc.henderson_code_violations uses county='Henderson'; these must
    merge, not sit beside each other."""
    for li in _run():
        assert li.county == "Henderson" and li.state == "NC"
        assert li.dedupe_key().startswith("addr:")
        assert li.dedupe_key().endswith("|NC:henderson")


def test_no_parcel_id_is_invented():
    assert all(li.parcel_id is None for li in _run())


# --------------------------------------------------------------------------- #
# field parsing
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,want", [
    ("NO", False), ("no", False), ("N/A", False), ("0", False), ("NONE", False),
    ("YES", True), ("yes", True),
    ("PRTL", True),                       # partially boarded is still boarded
    ("POSSIBLY IN 2022", True),
    ("6/30/2022 12:00:00 AM", True),      # a date in a yes/no box means yes
    ("UNKNOWN", None), ("", None), (None, None), (" ", None),
])
def test_tri(raw, want):
    assert mod._tri(raw) is want


@pytest.mark.parametrize("raw,want", [
    ("6/30/2022 12:00:00 AM", "2022-06-30"),
    ("11/9/2022 POSTED", "2022-11-09"),
    ("2023-07-25", "2023-07-25"),
    ("N/A", None), ("YES", None), ("", None), (None, None),
    ("13/45/2022", None),                 # impossible date, not a crash
])
def test_date_in(raw, want):
    assert mod._date_in(raw) == want


def test_tax_note_parses_amounts_and_years():
    t = mod._tax_note("2022- $612.87  2021 - $726.94")
    assert t["delinquent"] is True
    assert t["amount_owed"] == 726.94
    assert t["total_noted"] == 1339.81
    assert t["years"] == [2021, 2022]


@pytest.mark.parametrize("raw,delinquent", [
    ("2022 - DUE $659.41", True),
    ("PAID", False), ("CURRENT", False), ("NO", False), ("0", False),
])
def test_tax_note_clearance_words(raw, delinquent):
    assert mod._tax_note(raw)["delinquent"] is delinquent


def test_tax_note_is_none_when_blank():
    assert mod._tax_note("") is None and mod._tax_note(None) is None


# --------------------------------------------------------------------------- #
# listing shape / signals
# --------------------------------------------------------------------------- #

def test_listing_shape():
    li = next(li for li in _run() if li.street_address == "1001 TEMON ST")
    assert li.source == "counties_nc.hendersonville_vacant_structures"
    assert li.listing_type is ListingType.UNKNOWN
    assert li.city == "Hendersonville"
    assert li.sale_date is None
    assert li.owner_name == li.defendant == "BILLY HOLDEN JR & KEISHA"
    assert 35.0 < li.latitude < 35.6 and -82.7 < li.longitude < -82.2
    assert li.raw["vacancy"]["vacant"] is True
    assert li.raw["absentee_owner"] is True
    assert li.raw["code_enforcement"]["source"] == \
        "hendersonville_vacant_structures_register"


def test_confirmed_vacant_and_condemned_rows_score_as_property_signals():
    from foreclosure_scraper.distress_score import _signals_for
    li = next(li for li in _run() if li.raw.get("condemned"))
    names = [n for n, _b, _w in _signals_for(li)]
    assert "code_enforcement" in names
    assert "distressed_condition" in names


def test_occupied_property_is_not_flagged_vacant():
    payload = {"objectIdFieldName": "FID", "features": [
        {"attributes": {"FID": 1, "ADDRESS": "1 LIVED IN ST", "OCCUPIED": "YES",
                        "OWNER": "SOMEONE", "MAILING_ADDRESS": "1 LIVED IN ST",
                        "MAIL_CITY": "HENDERSONVILLE", "ST": "NC"}}]}
    li = _run(FakeHttp({}, pages=[payload]))[0]
    assert li.raw["vacancy"]["vacant"] is None
    assert "distressed" not in li.raw


def test_demolished_row_closes_the_case_but_keeps_the_lot_as_a_lead():
    li = next(li for li in _run() if li.street_address == "1030 N JUSTICE ST")
    ce = li.raw["code_enforcement"]
    assert ce["demolished"] is True
    assert ce["has_open"] is False and ce["open_violations"] == 0
    assert li.property_kind is PropertyKind.LAND
    assert li.owner_name == "HUNTING CREEK ASSOCIATES LLC"


def test_utility_note_is_carried_as_a_vacancy_duration_signal():
    li = next(li for li in _run() if li.street_address == "1003 3RD AVE W")
    assert li.raw["vacancy"]["utility_status"].startswith("BILLED BASE FOR WATER")


def test_delinquent_tax_note_rides_along():
    rows = [li for li in _run() if li.raw.get("hendersonville_delinquent_tax")]
    assert len(rows) >= 5
    amt = [li for li in rows
           if li.raw["hendersonville_delinquent_tax"]["amount_owed"]]
    assert amt


def test_absentee_detection():
    assert mod._is_absentee({"ST": "CA", "MAIL_CITY": "GRANADA HILLS",
                             "MAILING_ADDRESS": "17508 LOS ALIMOS ST",
                             "ADDRESS": "112 N BLUE RIDGE AVE"}) is True
    assert mod._is_absentee({"ST": "NC", "MAIL_CITY": "HENDERSONVILLE",
                             "MAILING_ADDRESS": "PO BOX 5",
                             "ADDRESS": "1 MAIN ST"}) is True
    assert mod._is_absentee({"ST": "NC", "MAIL_CITY": "HENDERSONVILLE",
                             "MAILING_ADDRESS": "1 MAIN ST",
                             "ADDRESS": "1 MAIN ST"}) is False


def test_government_owner_is_dropped():
    payload = {"objectIdFieldName": "FID", "features": [
        {"attributes": {"FID": 1, "ADDRESS": "1 CITY LOT", "OWNER": "CITY OF HENDERSONVILLE"}},
        {"attributes": {"FID": 2, "ADDRESS": "2 PRIVATE LN", "OWNER": "JANE ROE"}}]}
    rows = _run(FakeHttp({}, pages=[payload]))
    assert [li.owner_name for li in rows] == ["JANE ROE"]


def test_row_without_an_address_is_dropped():
    payload = {"objectIdFieldName": "FID", "features": [
        {"attributes": {"FID": 1, "ADDRESS": " ", "OWNER": "X"}}]}
    assert _run(FakeHttp({}, pages=[payload])) == []


def test_a_row_with_no_owner_is_still_a_lead():
    """The address and the vacancy finding are the lead; the owner backfills."""
    rows = _run()
    assert any(li.owner_name is None for li in rows)


def test_duplicate_addresses_collapse():
    payload = {"objectIdFieldName": "FID", "features": [
        {"attributes": {"FID": 1, "ADDRESS": "5 SAME ST", "OWNER": "A"}},
        {"attributes": {"FID": 2, "ADDRESS": "5 same st", "OWNER": "B"}}]}
    assert len(_run(FakeHttp({}, pages=[payload]))) == 1


def test_env_gate_skips_without_fetching(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "0")
    http = FakeHttp({}, pages=[_payload()])
    assert _run(http) == []
    assert http.calls == []


# --------------------------------------------------------------------------- #
# wiring guard (fails until main.py is updated — see the report)
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    from foreclosure_scraper import main
    slug = mod.HendersonvilleVacantStructures.slug
    assert slug in main.DATELESS_OK_SOURCES, (
        f'add "{slug}" to main.DATELESS_OK_SOURCES')


def test_scraper_is_auto_discovered_by_the_registry():
    from foreclosure_scraper.scrapers._registry import discover
    assert mod.HendersonvilleVacantStructures in discover()


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live():
    s = mod.HendersonvilleVacantStructures()
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(rows) >= s.expected_min_count
    blob = _blob(rows)
    assert not EMAIL_PAT.search(blob), "an email reached the board from LIVE data"
    assert not PHONE_PAT.search(blob), "a phone reached the board from LIVE data"
    for f in mod.FORBIDDEN_FIELDS:
        assert f not in blob
    assert all(li.zip_code is None for li in rows)
    print(f"live hendersonville vacant={len(rows)} "
          f"confirmed_vacant={sum(1 for li in rows if li.raw['vacancy']['vacant'])} "
          f"condemned={sum(1 for li in rows if li.raw.get('condemned'))} "
          f"absentee={sum(1 for li in rows if li.raw.get('absentee_owner'))}")

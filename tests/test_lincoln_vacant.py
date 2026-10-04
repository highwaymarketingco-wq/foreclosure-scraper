"""Lincoln County NC vacant-parcels extraction-completeness audit (2026-10-03,
HERMES batch 5).

Diffed the live ArcGIS layer schema (MapServer/25?f=json, 55 fields) against
the old 9-field outFields list and live-sampled 500 real VACANT='YES' rows:

  - CITY/STATE/ZIP (499/500 filled) -- the owner's own MAILING address --
    were never even REQUESTED. This scraper's whole stated purpose is
    flagging out-of-area owners as motivated-seller prospects, yet nothing
    in the old code could tell an in-county owner from one mailing from
    Boca Raton FL. ADDRESS1 WAS already fetched but only stashed under the
    private raw["lincoln_vacant"] key nothing downstream reads.
  - DEEDBK/DEEDPG/DEEDYR (100% filled) -- a real deed reference.
  - SDATE (100% filled) -- the last-sale DATE; SALEPRICE was already
    captured but its paired date was not, so enrichment_last_sale's
    raw['gis']['last_sale'] key was unreachable even on a real sale amount.
  - NAME2 (51% filled) -- a co-owner dropped on jointly-owned parcels.
  - PLATBK/PLATPG (31%) -- a plat reference.

GOTCHA caught live-verifying the absentee heuristic: PHYSICALADDR on vacant
land is usually just a road name with NO house number ("CAT SQUARE RD"), so
comparing leading street tokens unconditionally (the Pickens-style original)
flagged ~99% of the live 14,731-row set absentee on formatting alone, not a
real signal. _is_absentee only runs that comparison when situs itself starts
with a digit; live re-check after the guard: 3,048/14,731 (21%), matching the
893 out-of-state + 1,157 PO-box counts plus genuine street mismatches.
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import lincoln_vacant as m
from tests._arcgis_fakes import FakeHttp


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run_fetch(features: list[dict]):
    http = FakeHttp(pages=[{"features": features}])
    original = m.httpx.AsyncClient
    m.httpx.AsyncClient = lambda *a, **kw: _Ctx(http)  # noqa: E731
    try:
        return asyncio.run(m.LincolnVacant().fetch())
    finally:
        m.httpx.AsyncClient = original


ROW_FULL = {
    "PARCELID": "50396", "PIN": "2646977606", "PHYSICALADDR": "OLD NC 18 RD",
    "NAME1": "LUTZ MARVIN L III", "NAME2": "LUTZ THOMAS L",
    "ADDRESS1": "2646 GOLDENROD LN", "ADDRESS2": "UNIT 4",
    "CITY": "GLENVIEW", "STATE": "IL", "ZIP": "60026",
    "IMPROVALUE": 0, "TOTALVALUE": 77868, "MAINAREASQFT": None,
    "SALEPRICE": 190000, "SDATE": "04/16/2024",
    "DEEDBK": "3317", "DEEDPG": "847", "DEEDYR": 2024,
    "PLATBK": "12", "PLATPG": "158", "SBDIVN": "BOBBY L MARTIN FAMILY",
}

ROW_SPARSE = {
    "PARCELID": "00104", "PIN": "2685460418", "PHYSICALADDR": "CAT SQUARE RD",
    "NAME1": "RICHARDSON JERRY PAUL HEIRS OF", "NAME2": None,
    "ADDRESS1": "7347 HENRY RD", "ADDRESS2": None,
    "CITY": "VALE", "STATE": "NC", "ZIP": "28168",
    "IMPROVALUE": 0, "TOTALVALUE": 27755, "MAINAREASQFT": None,
    "SALEPRICE": 0, "SDATE": None,
    "DEEDBK": None, "DEEDPG": None, "DEEDYR": None,
    "PLATBK": None, "PLATPG": None, "SBDIVN": None,
}

ROW_INSTATE_NO_HOUSENUM = {
    # Same county, mailing street has NO house number paired with a situs
    # that also has none -- must NOT be flagged absentee by formatting alone.
    "PARCELID": "99999", "PIN": "1112223334", "PHYSICALADDR": "ROCKDALE RD",
    "NAME1": "LOCAL OWNER", "NAME2": None,
    "ADDRESS1": "PO BOX 10", "ADDRESS2": None,
    "CITY": "LINCOLNTON", "STATE": "NC", "ZIP": "28092",
    "IMPROVALUE": 0, "TOTALVALUE": 5000, "MAINAREASQFT": None,
    "SALEPRICE": 0, "SDATE": None,
    "DEEDBK": None, "DEEDPG": None, "DEEDYR": None,
    "PLATBK": None, "PLATPG": None, "SBDIVN": None,
}


def test_out_of_state_mailing_surfaces_owner_mailing_and_absentee_flag():
    out = _run_fetch([{"attributes": ROW_FULL}])
    assert len(out) == 1
    li = out[0]

    assert li.raw["owner_mailing"] == {
        "street": "2646 GOLDENROD LN", "street2": "UNIT 4",
        "city": "GLENVIEW", "state": "IL", "zip": "60026",
        "source": "lincoln_county_gis",
    }
    assert li.raw["absentee_owner"] is True
    assert li.raw["lincoln_vacant"]["co_owner"] == "LUTZ THOMAS L"
    assert li.raw["lincoln_vacant"]["deed_book"] == "3317"
    assert li.raw["lincoln_vacant"]["deed_page"] == "847"
    assert li.raw["lincoln_vacant"]["deed_year"] == 2024
    assert li.raw["lincoln_vacant"]["plat_book"] == "12"
    assert li.raw["lincoln_vacant"]["subdivision"] == "BOBBY L MARTIN FAMILY"
    # Canonical shape enrichment_last_sale.py reads.
    assert li.raw["gis"]["last_sale"] == {
        "amount": 190000.0, "date": "04/16/2024", "source": "lincoln_county_gis",
    }


def test_sparse_row_does_not_fabricate_optional_fields():
    out = _run_fetch([{"attributes": ROW_SPARSE}])
    assert len(out) == 1
    li = out[0]
    assert "absentee_owner" not in li.raw
    assert "gis" not in li.raw
    assert li.raw["lincoln_vacant"]["deed_book"] is None
    assert li.raw["lincoln_vacant"]["co_owner"] is None
    # Still gets owner_mailing (CITY/STATE present) even though not absentee.
    assert li.raw["owner_mailing"]["state"] == "NC"


def test_po_box_mailing_is_absentee_even_in_state():
    out = _run_fetch([{"attributes": ROW_INSTATE_NO_HOUSENUM}])
    li = out[0]
    assert li.raw["absentee_owner"] is True  # PO Box tell, not the street-token tell


def test_street_token_mismatch_only_checked_when_situs_has_a_house_number():
    """Regression guard for the false-positive-inflation bug: a vacant-land
    situs with no house number must not, by itself, trigger the absentee
    street-mismatch tell just because it fails a leading-token comparison
    against a real mailing street."""
    row = {**ROW_SPARSE, "ADDRESS1": "123 SOME OTHER ST", "STATE": "NC",
           "CITY": "LINCOLNTON"}
    out = _run_fetch([{"attributes": row}])
    li = out[0]
    # In-state, no PO box, situs has no leading digit -> not flagged.
    assert "absentee_owner" not in li.raw


def test_is_absentee_runs_street_check_only_with_house_numbered_situs():
    assert m._is_absentee("NC", "123 ELM ST", "456 OAK ST") is True
    assert m._is_absentee("NC", "123 ELM ST", "123 ELM ST") is False
    assert m._is_absentee("NC", "123 ELM ST", "OAK RD") is False  # no house # on situs
    assert m._is_absentee("SC", "123 ELM ST", "OAK RD") is True   # out of state
    assert m._is_absentee("NC", "PO BOX 5", "OAK RD") is True     # PO box

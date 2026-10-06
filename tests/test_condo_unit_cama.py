"""The CAMA condition join a Buncombe condominium unit used to miss (docs/HANDOFF.md items 75, 80).

enrichment_cama_condition built a lead's lookup key by stripping every non-digit (`_pin_key`), so a
unit keyed by its pinnum ('9627023924C0102', condo_units.py) asked the CAMA table for
'96270239240102', a key it does not hold: the table's `PIN` keeps the unit's full pinnum, letter
included (live 2026-10-06, Real Estate Appraisal Residential Building 2024/FeatureServer/0?f=json: PIN
string(16)). Measured live the same day: 130 of the 130 exempt units' pinnums are in the table (131
records), none of the 130 digits-only keys; the 39 unit-shaped ids other sources already publish
(44 board rows, none with a condition stamp) hit 27. A response key was stripped the same way, which
would also have made two units of a building ('C0102', 'D0102') one key.

REAL SHAPES. tests/fixtures/buncombe_cama_unit_records.json holds the table's real records for the 13
pinnums of tests/fixtures/buncombe_elderly_condo_layer.json (11 units, 2 plain parcels; PIN,
Condition, Grade, YearBuilt, no owner data). The fake table evaluates the `PIN IN (...)` clause the
enricher sends against them.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import condo_units as C
from foreclosure_scraper import enrichment_cama_condition as CAMA
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from tests._arcgis_fakes import FakeResponse

FIX = Path(__file__).parent / "fixtures"
LAYER = [f["attributes"] for f in json.loads((FIX / "buncombe_elderly_condo_layer.json").read_text())["features"]]
CAMA_RECORDS = json.loads((FIX / "buncombe_cama_unit_records.json").read_text())["records"]
NOW = datetime(2026, 10, 6, 12, 0, 0)

UNIT = "9627023924C0102"
PLAIN_PIN = "0609715480"        # pinnum '060971548000000'
BAD_KEY = "96270239240102"      # what the old key made of the unit: the letter stripped


def _lead(parcel_id, **kw) -> Listing:
    base = dict(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
                source_url="https://example.test/bills", listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Buncombe",
                parcel_id=parcel_id, first_seen=NOW, last_seen=NOW)
    base.update(kw)
    return Listing(**base)


def _in_clause(where: str) -> set[str]:
    m = re.fullmatch(r"PIN IN \((.*)\)", where.strip())
    assert m, f"clause the fake table does not model: {where!r}"
    return {v.strip().strip("'") for v in m.group(1).split(",")}


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def test_cama_pin_key_keeps_a_units_letters_and_nothing_else_changes():
    pk = CAMA._pin_key
    assert pk(UNIT, True, True) == UNIT
    assert pk("9627-02-3924-c0102", True, True) == UNIT
    assert pk("9627023924D0102", True, True) != pk(UNIT, True, True)        # no digit-only collision
    assert pk(UNIT, True) == BAD_KEY                                          # the layers without units
    assert pk(PLAIN_PIN, True, True) == "060971548000000"                     # a plain parcel is padded
    assert pk("060971548000000", True, True) == "060971548000000"
    assert pk("9639454911", True) == "963945491100000"                        # unchanged for Carteret
    assert pk(None, True, True) is None and pk("", True, True) is None


def test_cama_stored_key_of_a_unit_keeps_its_letters():
    assert CAMA._stored_key(UNIT, True) == UNIT
    assert CAMA._stored_key("060971548000000", True) == "060971548000000"
    assert CAMA._stored_key(UNIT, False) == BAD_KEY


class CamaHttp:
    """The CAMA table: `PIN IN (...)` over the real records."""

    def __init__(self):
        self.wheres = []

    async def get(self, url, params=None, timeout=None):
        where = (params or {}).get("where", "")
        self.wheres.append(where)
        wanted = _in_clause(where)
        hits = [r for r in CAMA_RECORDS if r["PIN"] in wanted]
        return FakeResponse({"features": [{"attributes": r} for r in hits]})


def _cama(leads):
    http = CamaHttp()
    original = CAMA.client
    CAMA.client = lambda *a, **kw: _Ctx(http)
    try:
        stats = asyncio.run(CAMA.enrich_cama_condition(leads))
    finally:
        CAMA.client = original
    return stats, http


def test_cama_stamps_condominium_units_by_their_full_pinnum():
    units = [a["pinnum"] for a in LAYER if C.unit_parts(a["pinnum"])]
    assert len(units) == 11
    leads = [_lead(p) for p in units]
    stats, http = _cama(leads)
    assert stats["eligible"] == 11 and stats["matched"] == 11 and stats["stamped"] == 11
    for li in leads:
        block = li.raw["condition_cama"]
        assert (block["source"], block["condition"], block["grade"]) == ("cama:NC:Buncombe", "average", "C")
        assert li.year_built == block["year_built"]
    assert {li.parcel_id: li.year_built for li in leads}[UNIT] == 1995
    asked = " ".join(http.wheres)
    assert f"'{UNIT}'" in asked and f"'{BAD_KEY}'" not in asked


def test_cama_still_stamps_plain_parcels_padded_and_reads_a_poor_condition():
    leads = [_lead(PLAIN_PIN), _lead("0605880879")]
    stats, http = _cama(leads)
    assert stats["matched"] == 2
    assert leads[0].raw["condition_cama"]["condition"] == "fair"
    poor = leads[1].raw["condition_cama"]
    assert poor["condition"] == "poor" and poor["distressed"] is True
    assert leads[1].raw["distressed"] is True
    assert "'060588087900000'" in " ".join(http.wheres)


def test_cama_other_counties_are_not_given_unit_keys():
    assert [k for k, v in CAMA.CAMA_SOURCES.items() if v.get("pin_units")] == [("NC", "Buncombe")]



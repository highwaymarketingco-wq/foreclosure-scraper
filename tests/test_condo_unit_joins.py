"""Owner/mailing and tax relief joins a Buncombe condominium unit used to miss (docs/HANDOFF.md items 75, 80).

Since cbdce842 a unit's parcel_id is its own pinnum ('9627023924C0102', condo_units.py) and `pin` on the
county layers is the BUILDING's 10 digits. enrichment_owner_mailing and enrichment_tax_relief matched a
lead to its layer record with `pin LIKE '%<parcel_id>%'`, which finds no unit (before that change it
found an arbitrary unit of the building: the bare pin matched all of them). Both layers carry `pinnum`
(string, 15) beside `pin` (10) and `pinext` (5), checked live 2026-10-06 with `?f=json` on the owner/
mailing layer (property_bc_dis/MapServer/1) and the tax relief layer (Property_2025/FeatureServer/0).
The CAMA table is tests/test_condo_unit_cama.py; the rollback-deferral key is reported at the end.

REAL SHAPES. tests/fixtures/buncombe_elderly_condo_layer.json holds the live layer's attributes for
three buildings and two plain parcels (owners and mailing blocks replaced, see test_condo_units.py).
The fake layer below evaluates the WHERE clause each enricher sends against those records, so a join
that cannot match its key finds nothing, as on the live layer.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from foreclosure_scraper import condo_units as C
from foreclosure_scraper import enrichment_owner_mailing as OM
from foreclosure_scraper import enrichment_rollback_deferral as RB
from foreclosure_scraper import enrichment_tax_relief as TR
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from tests._arcgis_fakes import FakeResponse

FIX = Path(__file__).parent / "fixtures"
LAYER = [f["attributes"] for f in json.loads((FIX / "buncombe_elderly_condo_layer.json").read_text())["features"]]
NOW = datetime(2026, 10, 6, 12, 0, 0)

UNIT = "9627023924C0102"        # exempt (ELD) unit of a 225-unit building
UNIT_OWNER = "CORINNE DARNELL DELMAR;CORINNE EMBRY ELOISE"
SIBLING = "9627023924C4501"     # another exempt unit of the same building (a different owner)
VET_UNIT = "9654438960CB201"    # exemption VET: not one the tax relief layer's where lists
PLAIN_PIN = "0609715480"        # a plain parcel: pinnum '060971548000000'


def _lead(parcel_id, **kw) -> Listing:
    base = dict(source="counties_generic.arcgis_distress.buncombe_unpaid_bills",
                source_url="https://example.test/bills", listing_type=ListingType.DISTRESSED,
                property_kind=PropertyKind.SINGLE_FAMILY, state="NC", county="Buncombe",
                parcel_id=parcel_id, first_seen=NOW, last_seen=NOW)
    base.update(kw)
    return Listing(**base)


# --------------------------------------------------------------------------- a fake layer
def _where_matches(attrs: dict, where: str) -> bool:
    """The clauses these enrichers send: `f LIKE '%v%'`, `f IN ('a','b')`, joined by AND."""
    for clause in (c.strip() for c in where.split(" AND ")):
        like = re.fullmatch(r"(\w+) LIKE '%(.*)%'", clause)
        member = re.fullmatch(r"(\w+) IN \((.*)\)", clause)
        if like:
            if like.group(2).lower() not in str(attrs.get(like.group(1)) or "").lower():
                return False
        elif member:
            allowed = {v.strip().strip("'") for v in member.group(2).split(",")}
            if str(attrs.get(member.group(1))) not in allowed:
                return False
        else:
            raise AssertionError(f"clause the fake layer does not model: {clause!r}")
    return True


class LayerHttp:
    """A fake httpx client: the Buncombe parcel layer (the fixture's features) behind any URL that
    names it, an empty answer for every other URL. Every WHERE sent is recorded."""

    def __init__(self, host: str, rows: list[dict]):
        self.host, self.rows, self.wheres = host, rows, []

    async def get(self, url, params=None, timeout=None):
        if self.host not in url:
            return FakeResponse({"features": []})
        where = (params or {}).get("where", "")
        self.wheres.append(where)
        hits = [r for r in self.rows if _where_matches(r, where)]
        return FakeResponse({"features": [{"attributes": r} for r in hits]})


class _Ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


# --------------------------------------------------------------------------- the helper
def test_unit_pinnum_is_the_layers_own_pinnum_of_a_unit_only():
    assert C.unit_pinnum("NC", "Buncombe", UNIT) == UNIT
    assert C.unit_pinnum("NC", "Buncombe County", "9627-02-3924-c0102") == UNIT
    for plain in (PLAIN_PIN, "060971548000000", "", None, "SC-1234"):
        assert C.unit_pinnum("NC", "Buncombe", plain) is None
    # a unit-shaped id of another county is not Buncombe's pinnum
    assert C.unit_pinnum("NC", "Henderson", UNIT) is None
    assert C.unit_pinnum("SC", "Buncombe", UNIT) is None


# --------------------------------------------------------------------------- owner mailing
SPEC = OM.COUNTY_GIS["NC:Buncombe"]


def _match(parcel_id, **kw):
    http = LayerHttp("property_bc_dis", LAYER)
    attrs = asyncio.run(OM._match_attrs(http, _lead(parcel_id, **kw), SPEC))
    return attrs, http


def test_owner_mailing_finds_a_unit_by_its_own_pinnum():
    attrs, http = _match(UNIT)
    assert attrs is not None and attrs["pinnum"] == UNIT and attrs["owner"] == UNIT_OWNER
    assert http.wheres == [f"pinnum LIKE '%{UNIT}%'"]


def test_owner_mailing_finds_a_dashed_unit_id_and_not_a_sibling():
    attrs, http = _match("9627-02-3924-C4501")
    assert attrs["pinnum"] == SIBLING
    assert http.wheres == [f"pinnum LIKE '%{SIBLING}%'"]


def test_owner_mailing_still_matches_a_plain_parcel_by_pin():
    attrs, http = _match(PLAIN_PIN)
    assert attrs["pin"] == PLAIN_PIN and attrs["pinnum"] == "060971548000000"
    assert http.wheres == [f"pin LIKE '%{PLAIN_PIN}%'"]


def test_owner_mailing_resolves_a_unit_row_end_to_end(monkeypatch):
    http = LayerHttp("property_bc_dis", LAYER)
    monkeypatch.setattr(OM, "client", lambda *a, **kw: _Ctx(http))
    li = _lead(UNIT)
    counts = asyncio.run(OM.enrich_owner_mailing([li]))
    assert counts["resolved"] == 1
    block = li.raw["owner_mailing"]
    assert block["owner"] == UNIT_OWNER                      # the unit's owner, not another unit's
    assert block["mailing"] == "103 SAMPLE WAY ANYTOWN NC 28899"
    assert li.parcel_id == UNIT                               # a row keeps the id it was keyed by


# --------------------------------------------------------------------------- tax relief
def _relief(parcel_id):
    seen = []

    async def fake_query(_http, url, where, out_fields=None, count=1):
        seen.append(where)
        return [r for r in LAYER if _where_matches(r, where)][:count]

    original = TR._query
    TR._query = fake_query
    try:
        li = _lead(parcel_id)
        stats = asyncio.run(TR.enrich_tax_relief([li]))
    finally:
        TR._query = original
    return li, stats, seen


def test_tax_relief_tags_a_unit_by_its_own_pinnum():
    li, stats, seen = _relief(UNIT)
    assert stats == {"queried": 1, "tagged": 1}
    assert li.raw["tax_relief"] == {"kind": "elderly", "basis": "elderly_disabled_exclusion",
                                    "code": "ELD", "county": "Buncombe"}
    assert seen == [f"pinnum LIKE '%{UNIT}%' AND Exempt IN ('ELD','DIS','BLD')"]


def test_tax_relief_reads_each_unit_of_a_building_on_its_own_exemption():
    """C3606 is DIS and C4501 ELD in the same building: the bare pin answered with whichever the layer
    listed first for both."""
    kinds = {}
    for unit in ("9627023924C3606", SIBLING):
        li, _, _ = _relief(unit)
        kinds[unit] = li.raw["tax_relief"]["kind"]
    assert kinds == {"9627023924C3606": "disabled", SIBLING: "elderly"}


def test_tax_relief_leaves_a_unit_with_another_exemption_untagged():
    li, stats, _ = _relief(VET_UNIT)                 # VET is not in the layer's ELD/DIS/BLD where
    assert stats == {"queried": 1, "tagged": 0} and "tax_relief" not in li.raw


def test_tax_relief_still_matches_a_plain_parcel_by_pin():
    li, stats, seen = _relief(PLAIN_PIN)
    assert stats == {"queried": 1, "tagged": 1}
    assert seen == [f"pin LIKE '%{PLAIN_PIN}%' AND Exempt IN ('ELD','DIS','BLD')"]


# --------------------------------------------------------------------------- rollback deferral (no change)
def test_rollback_deferral_keys_still_meet_the_bills_layer_for_a_unit():
    """Reported, not changed (item 80). The bills layer (Buncombe_County_All_Property_Bills_from_2025)
    holds `pin` as the dashed 15-character pinnum ('9627-02-3924-C0102', live 2026-10-06); the enricher
    indexes it through _normalize_parcel, which is exactly the key a unit lead (parcel_id = its
    pinnum) builds, so the unit still matches its OWN bill (the bare building pin used to meet only
    the common area's). Present-use deferral does not occur on a condominium unit in practice (the
    unit's bill carries deferred_value '0'), so there is nothing to change here."""
    bill_pin = "9627-02-3924-C0102"
    index_key = RB._normalize_parcel(bill_pin)
    assert index_key in RB._lead_keys(_lead(UNIT))
    assert RB._lead_keys(_lead("9627023924")) == ["9627023924"]            # the old bare-pin key
    assert index_key not in RB._lead_keys(_lead("9627023924"))
    assert RB._lead_keys(_lead(SIBLING)) != RB._lead_keys(_lead(UNIT))    # each unit its own key

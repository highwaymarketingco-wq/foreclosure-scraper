"""counties_nc.nc_heir_estate_parcels — multi-subfield owner-name bug.

Several target counties' COUNTY_GIS owner spec lists MORE THAN ONE subfield
(Gaston CURR_NAME1/CURR_NAME2, Polk OWNAM1/2/3, McDowell/Cleveland
ownname/ownname2, Lincoln/Pickens NAME1/NAME2, Mitchell Owner1/Owner2). The
scraper's old `_owner()` returned only the FIRST non-empty subfield, which
(live-captured 2026-10-01, direct ArcGIS query):

  1. Silently dropped a second heir's name entirely (Gaston HARDIN row), and
  2. Worse, could drop the WHOLE listing, because `_is_decedent()` was then
     checked against only that first field's text: Polk's "HUNTER LINDA PACE
     ET VIR" / "HUNTER DONALD L HEIRS" and McDowell's "SWOFFORD RONALD
     TRUSTEE 1/2" / "SWOFFORD LEONARD HEIRS 1/2" both have the HEIRS token
     only on the SECOND subfield — the SQL WHERE clause matches the row (it
     ORs across every subfield), but the old Python-side owner picker would
     have thrown the row away.

Fixtures below are verbatim `attributes` shapes captured live against the
real COUNTY_GIS endpoints (Gaston, Polk, McDowell) on 2026-10-01. Hermetic —
`_query` is monkeypatched, no network.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from foreclosure_scraper.enrichment_owner_mailing import COUNTY_GIS
from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.counties_nc import nc_heir_estate_parcels as m


# --------------------------------------------------------------------------- pure helpers

def test_field_is_decedent_flags_heir_and_estate_tokens():
    assert m._field_is_decedent("HARDIN CLARENCE HEIRS")
    assert m._field_is_decedent("WALKER SALLY ESTATE")
    assert not m._field_is_decedent("HUNTER LINDA PACE ET VIR")
    assert not m._field_is_decedent("")


def test_field_is_decedent_excludes_entities_even_with_the_token():
    assert not m._field_is_decedent("NEW HOPE REAL ESTATE INVST LLC")
    assert not m._field_is_decedent("HEIRS LAW LLC")


def test_is_decedent_checks_every_subfield_not_just_the_first():
    """The exact Polk/McDowell shape: token lands on the SECOND subfield."""
    assert m._is_decedent(["HUNTER LINDA PACE ET VIR", "HUNTER DONALD L HEIRS"])
    assert m._is_decedent(["SWOFFORD RONALD TRUSTEE 1/2", "SWOFFORD LEONARD HEIRS 1/2"])
    assert not m._is_decedent(["HUNTER LINDA PACE ET VIR", ""])


def test_is_decedent_one_entity_subfield_does_not_mask_a_real_heir_subfield():
    """A co-field that's a bank/firm contact line must not hide a genuine
    HEIRS token sitting in a DIFFERENT subfield of the same row."""
    assert m._is_decedent(["SMITH HEIRS", "C/O FIRST BANK TRUST DEPT"])


def test_owner_display_joins_and_dedupes():
    assert m._owner_display(["A HEIRS", "B HEIRS"]) == "A HEIRS; B HEIRS"
    assert m._owner_display(["A HEIRS", "A HEIRS"]) == "A HEIRS"
    assert m._owner_display([]) is None


# --------------------------------------------------------------------------- live-shaped fixtures

# gis.gastoncountync.gov .../Parcels/FeatureServer/11 — CURR_NAME1/CURR_NAME2.
GASTON_MULTI_HEIR = {
    "CURR_NAME1": "HARDIN CLARENCE HEIRS",
    "CURR_NAME2": "HARDIN OMA HEIRS",
    "SITUS_ADDRESS": "123 MAIN ST",
}

# services1.arcgis.com/.../Parcels/FeatureServer/0 (Polk) — OWNAM1/2/3.
# Token lands ONLY on OWNAM2; OWNAM1 alone has no HEIR/ESTATE text.
POLK_TOKEN_ON_SECOND_FIELD = {
    "OWNAM1": "HUNTER LINDA PACE ET VIR",
    "OWNAM2": "HUNTER DONALD L HEIRS",
    "OWNAM3": "",
}

# McDowell_Parcels/FeatureServer/0 — ownname/ownname2. Same shape as Polk.
MCDOWELL_TOKEN_ON_SECOND_FIELD = {
    "ownname": "SWOFFORD RONALD TRUSTEE 1/2",
    "ownname2": "SWOFFORD LEONARD HEIRS 1/2",
}

# A single-field entity row that must stay excluded (regression guard).
GASTON_ENTITY_NOT_A_DECEDENT = {
    "CURR_NAME1": "NEW HOPE REAL ESTATE INVST LLC",
    "CURR_NAME2": "",
}


@pytest.fixture
def canned(monkeypatch):
    """Drive fetch() offline: `_query` answers per-county by COUNTY_GIS url."""
    table: dict[str, list[dict]] = {}
    calls: list[str] = []

    async def fake_query(http, url, where, out_fields="*", count=80):
        calls.append(url)
        return list(table.get(url, []))

    @asynccontextmanager
    async def fake_client(*a, **kw):
        yield object()

    monkeypatch.setattr(m, "_query", fake_query)
    monkeypatch.setattr(m, "client", fake_client)
    return table, calls


def _url(key: str) -> str:
    return COUNTY_GIS[key]["url"]


def test_gaston_second_heir_is_no_longer_dropped(canned):
    table, _ = canned
    table[_url("NC:Gaston")] = [GASTON_MULTI_HEIR]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "Gaston"]
    assert len(rows) == 1
    assert rows[0].listing_type == ListingType.ESTATE_LEAD
    assert "HARDIN CLARENCE HEIRS" in rows[0].defendant
    assert "HARDIN OMA HEIRS" in rows[0].defendant
    assert rows[0].raw["relationship_signal"]["kind"] == "probate"


def test_polk_row_with_token_on_second_field_is_no_longer_dropped(canned):
    table, _ = canned
    table[_url("NC:Polk")] = [POLK_TOKEN_ON_SECOND_FIELD]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "Polk"]
    assert len(rows) == 1, "old _owner() checked only OWNAM1 and would drop this row"
    assert "HUNTER DONALD L HEIRS" in rows[0].defendant
    assert "HUNTER LINDA PACE ET VIR" in rows[0].defendant


def test_mcdowell_row_with_token_on_second_field_is_no_longer_dropped(canned):
    table, _ = canned
    table[_url("NC:McDowell")] = [MCDOWELL_TOKEN_ON_SECOND_FIELD]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "McDowell"]
    assert len(rows) == 1
    assert "SWOFFORD LEONARD HEIRS 1/2" in rows[0].defendant
    assert "SWOFFORD RONALD TRUSTEE 1/2" in rows[0].defendant


def test_entity_owner_is_still_excluded(canned):
    table, _ = canned
    table[_url("NC:Gaston")] = [GASTON_ENTITY_NOT_A_DECEDENT]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    assert [li for li in out if li.county == "Gaston"] == []


# --------------------------------------------------------------------------- 2026-10-02 extension
# (1) word-boundary fix, (2) new SC counties, (3) NC statewide OneMap fallback.

def test_field_is_decedent_no_longer_false_positives_on_a_surname_containing_heir():
    """Live-found (York SC roll): 'PINHEIRO ...' contains the substring 'HEIR' with
    no word boundary on either side -- a living owner, not a decedent."""
    assert not m._field_is_decedent("PINHEIRO GUILHON DANILO WILLIAM ETAL")
    # Real tokens, same shapes the existing tests already cover, must still match.
    assert m._field_is_decedent("HARDIN CLARENCE HEIRS")
    assert m._field_is_decedent("WALKER SALLY ESTATE")
    assert m._field_is_decedent("GARDNER ISRAEL HEIRS OF")


def test_field_is_decedent_estate_token_still_excludes_the_plural():
    """\\bESTATE\\b must not match inside 'ESTATES' -- the SQL-side _EXCLUDE list
    already filters this, but the Python gate should agree rather than rely only
    on the SQL side."""
    assert not m._field_is_decedent("SOME ESTATES")
    assert not m._field_is_decedent("STILL FAMILY AMENDED AND RESTATE TRUST")


def test_heir_counties_includes_the_new_sc_additions_and_still_excludes_dead_ends():
    assert "SC:Oconee" in m._HEIR_COUNTIES      # 2026-10-02 correction: real hits, not 0
    assert "SC:York" in m._HEIR_COUNTIES
    assert "SC:Charleston" in m._HEIR_COUNTIES
    assert "SC:Beaufort" in m._HEIR_COUNTIES
    # Still genuinely unfixable via this technique -- no owner column / no ArcGIS layer.
    assert "SC:Anderson" not in m._HEIR_COUNTIES
    assert "SC:Cherokee" not in m._HEIR_COUNTIES


def test_nc_statewide_fallback_excludes_dedicated_counties_and_covers_the_rest():
    fallback = set(m.NC_STATEWIDE_FALLBACK_COUNTIES)
    dedicated = set(m._NC_DEDICATED_COUNTIES)
    assert dedicated == {
        "Buncombe", "Henderson", "Rutherford", "Gaston", "Transylvania",
        "Polk", "Lincoln", "Mitchell", "Burke", "McDowell", "Cleveland",
    }
    assert not (fallback & dedicated)
    # Live-verified sample counties (module docstring) must be in the fallback set.
    for c in ("Catawba", "Watauga", "Avery", "Yadkin", "Surry", "Wilkes",
              "Caldwell", "Madison", "Ashe", "Alexander", "Iredell", "Yancey"):
        assert c in fallback, c
    # Sanity: every real NC county is accounted for exactly once between the two sets.
    from foreclosure_scraper.validation import NC_COUNTIES
    assert dedicated | fallback == set(NC_COUNTIES)
    assert len(fallback) == len(NC_COUNTIES) - len(dedicated)


@pytest.fixture
def canned_statewide(monkeypatch):
    """Drive fetch() offline for the STATEWIDE fallback, where every county shares
    the SAME COUNTY_GIS url -- the plain `canned` fixture above (keyed by url only)
    can't distinguish counties here, so this fakes `_query` keyed by the county name
    parsed back out of the WHERE clause's `UPPER(cntyname) = 'X'` fragment, exactly
    as `_where()` generates it."""
    import re as _re
    table: dict[str, list[dict]] = {}
    calls: list[str] = []

    async def fake_query(http, url, where, out_fields="*", count=80):
        m2 = _re.search(r"UPPER\(cntyname\) = '([A-Z ]+)'", where)
        county = m2.group(1).title() if m2 else None
        calls.append(county)
        return list(table.get(county, []))

    @asynccontextmanager
    async def fake_client(*a, **kw):
        yield object()

    monkeypatch.setattr(m, "_query", fake_query)
    monkeypatch.setattr(m, "client", fake_client)
    # Shrink the dedicated-layer loop to nothing so assertions are purely about the
    # statewide fallback path.
    monkeypatch.setattr(m, "_HEIR_COUNTIES", [])
    return table, calls


CATAWBA_HEIR = {
    "ownname": "DOVER MARY HOLHOUSER HEIRS", "ownname2": "",
    "siteadd": "2136 STOVE DR", "parno": "366903111618",
}


def test_statewide_fallback_is_queried_for_a_non_dedicated_county(canned_statewide):
    table, calls = canned_statewide
    table["Catawba"] = [CATAWBA_HEIR]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "Catawba"]
    assert len(rows) == 1
    assert rows[0].state == "NC"
    assert rows[0].listing_type == ListingType.ESTATE_LEAD
    assert "DOVER MARY HOLHOUSER HEIRS" in rows[0].defendant
    assert rows[0].street_address == "2136 STOVE DR"
    assert rows[0].parcel_id == "366903111618"
    # Every NC statewide-fallback county was actually asked (not just Catawba).
    assert set(calls) >= {"Catawba", "Wake", "Mecklenburg"}


def test_statewide_fallback_never_double_queries_a_dedicated_county(canned_statewide):
    """Cleveland has its OWN COUNTY_GIS entry (also the onemap url) -- it must not
    also appear in NC_STATEWIDE_FALLBACK_COUNTIES."""
    assert "Cleveland" not in m.NC_STATEWIDE_FALLBACK_COUNTIES


def test_partial_is_populated_for_soft_timeout_salvage(canned_statewide):
    """`out` must be `self.partial`, or a soft-timeout mid-sweep (89 counties) would
    silently discard every row already fetched."""
    table, _ = canned_statewide
    table["Catawba"] = [CATAWBA_HEIR]
    s = m.NCHeirEstateParcels()
    out = asyncio.run(s.fetch())
    assert len(s.partial) >= len(out) > 0
    assert any(li.county == "Catawba" for li in s.partial)

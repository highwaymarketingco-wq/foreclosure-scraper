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


# --------------------------------------------------------------------------- 2026-10-02
# structured heir_names (owner: "if its multiple heirs and who they are. i
# dont just want a name i want ALL data") -- `defendant`/`owner_of_record`
# stayed a single ";"-joined string; this adds a real list.

def test_parse_owner_field_strips_trailing_heirs_token():
    assert m._parse_owner_field("HARDIN CLARENCE HEIRS") == {
        "raw": "HARDIN CLARENCE HEIRS", "name": "HARDIN CLARENCE", "role": "heir",
    }


def test_parse_owner_field_strips_trailing_estate_token():
    assert m._parse_owner_field("WALKER SALLY ESTATE") == {
        "raw": "WALKER SALLY ESTATE", "name": "WALKER SALLY", "role": "estate",
    }


def test_parse_owner_field_strips_leading_estate_of():
    assert m._parse_owner_field("ESTATE OF JOHN SMITH") == {
        "raw": "ESTATE OF JOHN SMITH", "name": "JOHN SMITH", "role": "estate",
    }


def test_parse_owner_field_strips_trailing_fraction_after_role_token():
    """McDowell live shape: 'SWOFFORD LEONARD HEIRS 1/2' -- the fractional
    interest sits AFTER the role token, not at the very end of the string
    before stripping."""
    assert m._parse_owner_field("SWOFFORD LEONARD HEIRS 1/2") == {
        "raw": "SWOFFORD LEONARD HEIRS 1/2", "name": "SWOFFORD LEONARD", "role": "heir",
    }
    assert m._parse_owner_field("SWOFFORD RONALD TRUSTEE 1/2") == {
        "raw": "SWOFFORD RONALD TRUSTEE 1/2", "name": "SWOFFORD RONALD", "role": "trustee",
    }


def test_parse_owner_field_keeps_a_no_token_subfield_as_role_other():
    """A plain co-owner line with no HEIR/ESTATE/TRUSTEE token still gets a
    dict (nothing silently dropped from the structured list)."""
    assert m._parse_owner_field("HUNTER LINDA PACE ET VIR") == {
        "raw": "HUNTER LINDA PACE ET VIR", "name": "HUNTER LINDA PACE ET VIR", "role": "other",
    }


def test_heir_names_preserves_order_and_every_subfield():
    out = m._heir_names(["HARDIN CLARENCE HEIRS", "HARDIN OMA HEIRS"])
    assert [h["name"] for h in out] == ["HARDIN CLARENCE", "HARDIN OMA"]
    assert all(h["role"] == "heir" for h in out)


def test_gaston_multi_heir_row_gets_a_real_list_not_just_the_joined_string(canned):
    """The exact live-captured Gaston shape: two distinct heirs in one row.
    `defendant` stays the joined string (unchanged); `raw['heir_estate']
    ['heir_names']` must resolve each one to its own clean name."""
    table, _ = canned
    table[_url("NC:Gaston")] = [GASTON_MULTI_HEIR]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "Gaston"]
    assert len(rows) == 1
    names = rows[0].raw["heir_estate"]["heir_names"]
    assert [h["name"] for h in names] == ["HARDIN CLARENCE", "HARDIN OMA"]
    assert all(h["role"] == "heir" for h in names)
    # The raw originals are kept too, not just the stripped name.
    assert names[0]["raw"] == "HARDIN CLARENCE HEIRS"


# --------------------------------------------------------------------------- 2026-10-04
# Regression pin for task_heir_names_coverage_gap: confirmed LIVE that 0 of 1,039
# estate_lead rows on the published board carry heir_names (board predates this
# field's 2026-10-02 commit). Before trusting that "it'll reach the board on the
# next run" claim, PROVE the publish pipeline really does preserve the nested
# {raw,name,role} list end-to-end -- scraper emits heir_names -> simulate the
# publish step (web_artifact._to_dict / _slim_raw, the SAME function every real
# write_artifact()/append_new_rows()/patch_existing_rows() call uses) -> assert it
# survives byte-for-byte. RAW_KEEP["heir_estate"] = "*" is a wildcard (keeps the
# WHOLE sub-dict, not a per-subkey allowlist), so this also pins that a future
# narrowing of that entry to an explicit tuple of subkeys (the shape "gis"/
# "zillow" use) would break this test rather than silently dropping heir_names
# again with no error, the way the original 2026-09-10 RAW_KEEP audit found
# heir_estate itself being dropped entirely.
def test_gaston_multi_heir_heir_names_survives_the_publish_slim(canned):
    from foreclosure_scraper.web_artifact import RAW_KEEP, _to_dict

    assert RAW_KEEP.get("heir_estate") == "*", (
        "heir_estate's RAW_KEEP entry changed from a wildcard -- the rest of "
        "this test's reasoning (whole sub-dict survives, no per-subkey "
        "registration needed) no longer applies; re-verify before editing this "
        "pin"
    )

    table, _ = canned
    table[_url("NC:Gaston")] = [GASTON_MULTI_HEIR]
    out = asyncio.run(m.NCHeirEstateParcels().fetch())
    rows = [li for li in out if li.county == "Gaston"]
    assert len(rows) == 1
    li = rows[0]

    before = li.raw["heir_estate"]["heir_names"]
    assert before, "fixture regressed -- nothing to prove survives"

    published = _to_dict(li)
    after = published["raw"]["heir_estate"]["heir_names"]

    assert after == before
    assert [h["name"] for h in after] == ["HARDIN CLARENCE", "HARDIN OMA"]
    assert all(h["role"] == "heir" for h in after)
    # Every OTHER heir_estate sibling key must also still be there -- a
    # wildcard keep is "the whole dict survives", not "heir_names in
    # particular happens to survive while something else is sub-projected".
    for sibling in ("owner_of_record", "mailing", "care_of", "match"):
        assert sibling in published["raw"]["heir_estate"]


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


# --- 2026-10-07: cap raised in stages to 400, highest-value parcels first, cap in run stats,
# NULL-safe exclusions. Names below are made up. ---

class _Resp:
    status_code = 200

    def __init__(self, body):
        self._b = body

    def json(self):
        return self._b


class _SchemaHttp:
    """Answers the layer schema GET; the row reads go through the patched helpers."""

    def __init__(self, fields):
        self.fields = fields
        self.gets = 0

    async def get(self, url, params=None, timeout=None):
        self.gets += 1
        return _Resp({"fields": self.fields})


def _row(i, value):
    return {"CURR_NAME1": f"SAMPLE{i} PAT HEIRS", "CURR_NAME2": None, "PIN": f"P{i}",
            "FMV_TOTAL": value, "WHOLE_ADDRESS": f"{i} TEST ST"}


def test_value_field_is_a_numeric_total_value_column():
    assert m._pick_value_field({"fields": [
        {"name": "TotalMarketValue", "type": "esriFieldTypeString"},
        {"name": "parval", "type": "esriFieldTypeDouble"}]}) == "parval"
    assert m._pick_value_field({"fields": [
        {"name": "TotalMarketValue", "type": "esriFieldTypeString"}]}) is None


def test_default_cap_is_400_and_env_adjustable():
    assert m._PER_COUNTY_CAP == 400 or "HEIR_ESTATE_PER_COUNTY_CAP" in __import__("os").environ


def test_exclusions_sit_on_the_first_owner_field_only():
    """`UPPER(f2) NOT LIKE` is NULL when f2 is NULL and dropped every single-owner row."""
    w = m._where({"owner": ["NAME1", "NAME2"]}, "Lincoln")
    assert "UPPER(NAME1) NOT LIKE '%REAL ESTATE%'" in w
    assert "UPPER(NAME2) NOT LIKE" not in w
    assert "UPPER(NAME2) LIKE '%HEIR%'" in w          # matching still reads every field


def test_an_excluded_phrase_on_a_second_field_still_drops_the_row():
    assert m._excluded_row(["SMITH JOHN HEIRS", "LIFE ESTATE"])
    assert not m._excluded_row(["SMITH JOHN HEIRS", None])


def _drive(monkeypatch, rows_by_page, fields, cap=3):
    monkeypatch.setattr(m, "_PER_COUNTY_CAP", cap)
    monkeypatch.setattr(m, "_RANK_PAGE", 2)
    calls = []

    async def fake_page(http, url, where, out_fields="*", count=25, offset=0, order_by=""):
        calls.append({"count": count, "offset": offset, "order_by": order_by,
                      "out_fields": out_fields})
        page = rows_by_page[len(calls) - 1] if len(calls) <= len(rows_by_page) else []
        return page, len(calls) < len(rows_by_page)

    unordered = []

    async def fake_query(http, url, where, out_fields="*", count=80):
        unordered.append(count)
        return [_row(9, 1.0)]

    monkeypatch.setattr(m, "_query_page", fake_page)
    monkeypatch.setattr(m, "_query", fake_query)
    s = m.NCHeirEstateParcels()
    spec = m.COUNTY_GIS["NC:Gaston"]
    out = asyncio.run(s._process_county(_SchemaHttp(fields), "NC", "Gaston", spec))
    return s, out, calls, unordered


def test_rows_are_read_highest_value_first_up_to_the_cap(monkeypatch):
    fields = [{"name": "FMV_TOTAL", "type": "esriFieldTypeDouble"}]
    pages = [[_row(1, 900.0), _row(2, 500.0)], [_row(3, 100.0), _row(4, 50.0)]]
    s, out, calls, unordered = _drive(monkeypatch, pages, fields, cap=3)
    assert [c["order_by"] for c in calls] == ["FMV_TOTAL DESC", "FMV_TOTAL DESC"]
    assert [c["offset"] for c in calls] == [0, 2] and calls[1]["count"] == 1
    assert "*" not in calls[0]["out_fields"] and "FMV_TOTAL" in calls[0]["out_fields"]
    assert not unordered
    assert [li.raw["heir_estate"]["value_rank"] for li in out] == [1, 2, 3]
    assert out[0].raw["heir_estate"]["value"] == 900.0
    assert out[0].raw["heir_estate"]["per_county_cap"] == 3
    assert s.run_stats["per_county_cap"] == 3
    assert s.run_stats["capped_counties"] == ["NC:Gaston"]
    assert s.run_stats["ranked_by_value"] == 1


def test_an_empty_ranked_read_falls_back_to_the_unordered_one(monkeypatch):
    fields = [{"name": "FMV_TOTAL", "type": "esriFieldTypeDouble"}]
    s, out, calls, unordered = _drive(monkeypatch, [[]], fields, cap=3)
    assert unordered == [3] and len(out) == 1
    assert "value_rank" not in out[0].raw["heir_estate"]


def test_a_layer_without_a_numeric_value_column_reads_unordered(monkeypatch):
    s, out, calls, unordered = _drive(monkeypatch, [], [{"name": "X", "type": "esriFieldTypeString"}])
    assert not calls and unordered == [3]


# --- 2026-10-08: parcel facts the layer carries (value / acreage / sale / legal / deed / card
# link) are requested and kept. Names, ids and values below are made up. ---

def test_onemap_rows_request_and_keep_the_parcel_facts(monkeypatch):
    calls = []

    async def fake_page(http, url, where, out_fields="*", count=25, offset=0, order_by=""):
        calls.append(out_fields)
        row = {"ownname": "SAMPLE PAT HEIRS", "ownname2": None, "parno": "1234567890",
               "siteadd": "1 TEST ST", "parval": 150000.0, "gisacres": 2.5, "saledate": None,
               "legdecfull": "LOT 4 SAMPLE ACRES", "mapref": " ", "structyear": 1978}
        return [row], False

    monkeypatch.setattr(m, "_query_page", fake_page)
    s = m.NCHeirEstateParcels()
    spec = m._NC_ONEMAP_SPEC
    out = asyncio.run(s._process_county(
        _SchemaHttp([{"name": "parval", "type": "esriFieldTypeDouble"}]), "NC", "Ashe", spec))
    for f in ("gisacres", "legdecfull", "saledate", "structyear", "altparno"):
        assert f in calls[0].split(",")
    facts = out[0].raw["heir_estate"]["parcel_facts"]
    assert facts == {"gisacres": 2.5, "parval": 150000.0, "legdecfull": "LOT 4 SAMPLE ACRES",
                     "structyear": 1978}
    assert out[0].acreage == 2.5 and out[0].legal_description == "LOT 4 SAMPLE ACRES"


def test_polk_rows_keep_tax_owed_deed_and_record_card():
    spec = m.COUNTY_GIS["NC:Polk"]
    facts = m._parcel_facts(spec, {"TMS": "P1-2", "TOTAL_TAX_OWED": 525.01, "DEEDED_ACRES": 3.1,
                                   "DEED_BOOK": "88", "DEED_PAGE": "101",
                                   "PropertyRecordCard": "http://example.invalid/P1-2.pdf"})
    assert facts["TOTAL_TAX_OWED"] == 525.01 and facts["DEED_BOOK"] == "88"
    assert facts["PropertyRecordCard"].endswith("P1-2.pdf")


def test_a_layer_without_listed_facts_requests_nothing_extra():
    spec = m.COUNTY_GIS["NC:Gaston"]
    assert m._parcel_facts(spec, {"FMV_TOTAL": 1.0, "anything": "x"}) == {}

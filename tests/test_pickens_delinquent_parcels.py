"""Pickens County SC pre-sale delinquent-tax parcels (multi-year GIS rolls).

Offline tests run against a SAVED slice of all eight real layers
(``tests/fixtures/pickens_delinquent_layers.json``), built from the live
services and kept verbatim: four parcels that appear in EVERY cycle 2020-2025
(the chronic-delinquency case) plus three that appear only in the current 2025
posting cycle (the case where owner + amount exist but situs/mailing must come
from nowhere). That exercises the per-layer column map, the cross-cycle
backfill, PIN normalization across the MAP_NUMBER / PIN / DelqParcel spellings,
and the pre-sale flag on real shapes.

RUN_LIVE=1 adds an opt-in smoke test against the live org.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from foreclosure_scraper import arcgis_webmap as agw
from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_sc import pickens_delinquent_parcels as mod

from tests._arcgis_fakes import FakeHttp

FIX = Path(__file__).parent / "fixtures"


def _payloads() -> dict:
    return json.loads((FIX / "pickens_delinquent_layers.json").read_text())


def _routes(payloads: dict | None = None) -> dict:
    p = payloads if payloads is not None else _payloads()
    return {f"/services/{svc}/FeatureServer": body for svc, body in p.items()}


class _ctx:
    def __init__(self, http):
        self.http = http

    async def __aenter__(self):
        return self.http

    async def __aexit__(self, *a):
        return False


def _run(http=None) -> list:
    http = http or FakeHttp(_routes())
    original = mod.client
    mod.client = lambda *a, **kw: _ctx(http)      # noqa: E731
    try:
        return list(asyncio.run(mod.PickensDelinquentParcels().fetch()))
    finally:
        mod.client = original


# --------------------------------------------------------------------------- #
# layer enumeration
# --------------------------------------------------------------------------- #

def test_every_delinquent_layer_on_the_org_is_wired():
    """The eight services enumerated off the org's /services listing. FLC_2022
    is deliberately absent — that is post-sale inventory owned by sc_flc."""
    assert [L.service for L in mod.LAYERS] == [
        "delinquent_2020", "del_2021", "dqnt_2022", "dqnt_2023", "dqnt_2024",
        "DelParces_October2025NewsAd", "DelqParcels_Ad_paperlisting2", "Posting3",
    ]
    assert not any(L.service.startswith("FLC") for L in mod.LAYERS)


def test_layers_are_ordered_oldest_to_newest():
    """build_listing's 'newest value wins' backfill depends on this order."""
    cycles = [L.cycle for L in mod.LAYERS]
    assert cycles == sorted(cycles)


def test_only_the_2025_posting_layers_are_the_current_cycle():
    assert {L.service for L in mod.LAYERS if L.current} == {
        "DelParces_October2025NewsAd", "DelqParcels_Ad_paperlisting2", "Posting3"}
    assert all(L.cycle == 2025 for L in mod.LAYERS if L.current)


def test_out_fields_are_enumerated_never_star():
    """PRIVACY: query_features hard-rejects '*'; every layer must name columns."""
    for L in mod.LAYERS:
        assert L.out_fields and "*" not in L.out_fields
        assert L.out_fields.startswith("FID,")
        assert L.pin in L.out_fields


def test_every_layer_url_is_the_pickens_org():
    for L in mod.LAYERS:
        assert L.url.startswith(
            "https://services1.arcgis.com/59960rq18IxUcAVI/arcgis/rest/services/")


def test_query_uses_enumerated_fields_and_paginates_properly():
    http = FakeHttp(_routes())
    _run(http)
    assert len(http.calls) == len(mod.LAYERS)
    for _verb, url, params in http.calls:
        assert params["outFields"] != "*"
        assert params["where"] == "1=1"
        assert params["orderByFields"] == "FID ASC"
        assert "resultOffset" in params and "resultRecordCount" in params
        assert params["returnGeometry"] == "true" and params["outSR"] == "4326"


# --------------------------------------------------------------------------- #
# PIN normalization
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw,want", [
    ("4065-16-73-6947", "4065-16-73-6947"),
    ("406516736947", "4065-16-73-6947"),        # undashed spelling normalizes
    # Interior whitespace is a data-entry artifact, not a different parcel: the
    # digit run is still unambiguously 12 long. Same convention as
    # counties_nc.henderson_code_violations, whose county data ships a
    # tab-prefixed PIN.
    ("4065167 36947", "4065-16-73-6947"),
    ("\t4065-16-73-6947", "4065-16-73-6947"),
    (" 5019-11-66-7470 ", "5019-11-66-7470"),
    ("R0056724", None),                         # account number, not a PIN
    ("40651673694", None),                      # 11 digits — too short
    ("4065167369477", None),                    # 13 digits — too long
    ("", None), (None, None), (" ", None),
])
def test_norm_pin(raw, want):
    assert mod._norm_pin(raw) == want


def test_map_number_and_delqparcel_spellings_reach_the_same_parcel_key():
    """delinquent_2020 keys on MAP_NUMBER, the 2025 ad keys on DelqParcel, the
    rest on PIN. All three must fold into one parcel, or a chronic delinquent
    would read as three separate one-off leads."""
    rows = _run()
    multi = [li for li in rows
             if li.raw["pickens_delinquent"]["cycle_count"] >= 6]
    assert len(multi) == 4, "fixture holds four parcels present in all six cycles"
    for li in multi:
        d = li.raw["pickens_delinquent"]
        assert d["cycles"] == [2020, 2021, 2022, 2023, 2024, 2025]
        assert d["first_cycle"] == 2020 and d["latest_cycle"] == 2025
        assert d["chronic"] is True and d["repeat_delinquent"] is True


# --------------------------------------------------------------------------- #
# cross-cycle backfill — the whole point of folding the layers together
# --------------------------------------------------------------------------- #

def test_current_cycle_rows_are_backfilled_with_situs_and_mailing_from_older_rolls():
    """The 2025 posting layers publish owner + amount ONLY. Everything that
    makes the lead mailable (situs, owner mailing address) comes from the
    2022-2024 rolls at the same parcel."""
    li = next(li for li in _run() if li.parcel_id == "4065-16-73-6947")
    assert li.raw["pickens_delinquent"]["pre_sale"] is True
    assert li.street_address                      # from a 20xx roll
    assert li.city and li.zip_code
    assert li.raw["owner_mailing"]["street"]      # from a 20xx roll
    assert li.owner_name


def test_a_2025_only_parcel_has_owner_and_amount_but_no_situs():
    """Honest about what the current cycle actually carries — no invention."""
    li = next(li for li in _run() if li.parcel_id == "4053-10-46-7469")
    d = li.raw["pickens_delinquent"]
    assert d["cycles"] == [2025] and d["pre_sale"] is True
    assert li.owner_name and d["amount_owed"]
    assert li.street_address is None
    assert "owner_mailing" not in li.raw


def test_amount_comes_from_the_newest_publication_not_the_oldest():
    payload = {
        "/services/dqnt_2022/FeatureServer": {"objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4065-16-73-6947", "AMOUNT_DUE": 111.0,
                            "NAME1": "OLD OWNER", "LOCADD": "1 OLD RD"}}]},
        "/services/Posting3/FeatureServer": {"objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4065-16-73-6947", "AMOUNT_DUE": 999.0,
                            "OWNER__NOW": "NEW OWNER"}}]},
    }
    rows = _run(FakeHttp(payload))
    li = rows[0]
    assert li.raw["pickens_delinquent"]["amount_owed"] == 999.0
    assert li.owner_name == "NEW OWNER"
    assert li.street_address == "1 OLD RD"        # backfilled, not overwritten


def test_owner_now_long_form_beats_the_terse_name1_index_form():
    """'KIRKLAND, DELIA F., HEIRS OF,' carries the heirship the index form
    ('KIRKLAND DELIA F') throws away."""
    payload = {"/services/dqnt_2023/FeatureServer": {
        "objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4046-20-90-7980",
                            "NAME1": "KIRKLAND DELIA F",
                            "OWNER__NOW": "KIRKLAND, DELIA F., HEIRS OF,",
                            "AMOUNT_DUE": 2802.17}}]}}
    li = _run(FakeHttp(payload))[0]
    assert li.owner_name == "KIRKLAND, DELIA F., HEIRS OF,"


# --------------------------------------------------------------------------- #
# listing shape / joining
# --------------------------------------------------------------------------- #

def test_listing_shape():
    li = next(li for li in _run() if li.parcel_id == "5019-11-66-7470")
    assert li.source == "counties_sc.pickens_delinquent_parcels"
    assert li.listing_type is ListingType.TAX_LIEN
    assert li.state == "SC" and li.county == "Pickens"
    assert li.sale_date is None
    assert li.foreclosure_process == "tax"
    assert li.defendant == li.owner_name
    d = li.raw["pickens_delinquent"]
    assert d["source"] == "pickens_county_gis_delinquent_layers"
    assert d["parcel_id"] == li.parcel_id
    assert len(d["publications"]) >= d["cycle_count"]


def test_parcel_is_the_join_key_onto_the_rest_of_the_board():
    for li in _run():
        assert li.dedupe_key() == f"parcel:SC:pickens:{li.parcel_id.replace('-', '').lower()}"


def test_delinquent_balance_never_lands_in_a_property_value_field():
    """calc.py prices ARV off tax_value — a $300 tax bill there would collapse
    every valuation at the parcel."""
    for li in _run():
        assert li.tax_value is None
        assert li.assessed_value is None
        assert li.market_value is None
        assert li.opening_bid is None
        assert li.judgment_amount is None
    # ...and the balance really is present somewhere, so this is not vacuous.
    assert any(li.raw["pickens_delinquent"]["amount_owed"] for li in _run())


def test_amount_owed_is_normalized_by_enrichment_tax_owed():
    """The generic _TAXISH scan keys off 'delinquent' in the slug plus an
    'amount_owed' key in a raw subdict. Assert the contract really holds rather
    than assuming it."""
    from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
    rows = [li for li in _run() if li.raw["pickens_delinquent"]["amount_owed"]]
    assert rows
    enrich_tax_owed(rows)
    for li in rows:
        assert li.raw["tax_owed"]["balance"] == li.raw["pickens_delinquent"]["amount_owed"]
        assert li.raw["tax_owed"]["kind"] == "delinquent_tax"


def test_chronic_delinquency_sets_the_distressed_property_signal():
    from foreclosure_scraper.distress_score import _signals_for
    li = next(li for li in _run()
              if li.raw["pickens_delinquent"]["cycle_count"] >= 3)
    assert li.raw["distressed"] is True
    assert "distressed_condition" in [n for n, _b, _w in _signals_for(li)]


def test_a_single_cycle_parcel_is_not_flagged_chronic():
    li = next(li for li in _run()
              if li.raw["pickens_delinquent"]["cycle_count"] == 1)
    assert li.raw["pickens_delinquent"]["chronic"] is False
    assert "distressed" not in li.raw


def test_absentee_owner_flagged_from_the_mailing_address():
    payload = {"/services/dqnt_2023/FeatureServer": {
        "objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4046-04-83-6249", "NAME1": "DAVIS JOHN THOMAS",
                            "ADD1": "30343 TAKARA TERRACE", "CITY": "MOUNT DORA",
                            "STATE": "FL", "ZIP": 32757, "AMOUNT_DUE": 295.22}}]}}
    li = _run(FakeHttp(payload))[0]
    assert li.raw["absentee_owner"] is True
    assert li.raw["owner_mailing"]["state"] == "FL"


def test_owner_occupied_parcel_is_not_flagged_absentee():
    payload = {"/services/dqnt_2023/FeatureServer": {
        "objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4037-00-83-2164", "NAME1": "LADD PEGGY S",
                            "ADD1": "126 SHEMAIAH RD", "CITY": "CENTRAL", "STATE": "SC",
                            "ZIP": 29630, "LOCADD": "126  SHEMAIAH RD",
                            "LOCCITY": "CENTRAL", "LOCZIP": 29630, "AMOUNT_DUE": 231.39}}]}}
    li = _run(FakeHttp(payload))[0]
    assert "absentee_owner" not in li.raw


def test_zip_plus_four_padding_is_reduced_to_five_digits():
    assert mod._zip5(296730000) == "29673"
    assert mod._zip5(29640) == "29640"
    assert mod._zip5(0) is None and mod._zip5(" ") is None


def test_vacant_flag_drives_property_kind_but_a_zero_building_count_does_not():
    """BLDGS=0 shows up on parcels that plainly have a house; only the
    assessor's own IMPVAC flag is trusted to call LAND."""
    assert mod._property_kind("Vacant", 0) is PropertyKind.LAND
    assert mod._property_kind(" ", 0) is PropertyKind.UNKNOWN
    assert mod._property_kind(None, 1) is PropertyKind.UNKNOWN


def test_government_owners_are_dropped():
    payload = {"/services/Posting3/FeatureServer": {
        "objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": "4053-10-46-7469",
                            "OWNER__NOW": "CITY OF EASLEY", "AMOUNT_DUE": 100.0}},
            {"attributes": {"FID": 2, "PIN": "4054-11-55-7793",
                            "OWNER__NOW": "WILLIAMS, ALVIN M., JR.", "AMOUNT_DUE": 638.8}}]}}
    rows = _run(FakeHttp(payload))
    assert [li.owner_name for li in rows] == ["WILLIAMS, ALVIN M., JR."]


def test_row_without_a_parseable_pin_is_dropped():
    payload = {"/services/Posting3/FeatureServer": {
        "objectIdFieldName": "FID", "features": [
            {"attributes": {"FID": 1, "PIN": " ", "OWNER__NOW": "X", "AMOUNT_DUE": 5.0}}]}}
    assert _run(FakeHttp(payload)) == []


# --------------------------------------------------------------------------- #
# resilience
# --------------------------------------------------------------------------- #

def test_one_dead_layer_costs_that_layer_not_the_run():
    """The county retires and renames these services between cycles."""
    p = _payloads()
    p["dqnt_2024"] = {"error": {"code": 400, "message": "Invalid URL"}}
    rows = _run(FakeHttp(_routes(p)))
    assert rows, "the other seven layers must still produce leads"
    assert any(li.raw["pickens_delinquent"]["pre_sale"] for li in rows)


def test_all_layers_dead_returns_empty_rather_than_raising():
    rows = _run(FakeHttp({}))          # every route 400s
    assert rows == []


def test_env_gate_skips_without_fetching(monkeypatch):
    monkeypatch.setenv(mod.ENV_OFF, "0")
    http = FakeHttp(_routes())
    assert _run(http) == []
    assert http.calls == []


def test_where_clause_passes_the_safe_expression_guard():
    assert agw.is_safe_expression("1=1")


# --------------------------------------------------------------------------- #
# wiring guard (fails until main.py is updated — see the report)
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    """A delinquent balance is a standing debt, not a dated sale. Without the
    whitelist entry main._active_only silently drops all ~2,100 rows."""
    from foreclosure_scraper import main
    slug = mod.PickensDelinquentParcels.slug
    assert slug in main.DATELESS_OK_SOURCES, (
        f'add "{slug}" to main.DATELESS_OK_SOURCES')


def test_scraper_is_auto_discovered_by_the_registry():
    from foreclosure_scraper.scrapers._registry import discover
    assert mod.PickensDelinquentParcels in discover()


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live():
    s = mod.PickensDelinquentParcels()
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(rows) >= s.expected_min_count
    d = [li.raw["pickens_delinquent"] for li in rows]
    assert sum(1 for x in d if x["pre_sale"]) >= 300      # current cycle
    assert sum(1 for x in d if x["repeat_delinquent"]) >= 500
    assert sum(1 for li in rows if li.owner_name) / len(rows) > 0.8
    assert all(li.parcel_id for li in rows)
    print(f"live pickens delinquent parcels={len(rows)} "
          f"pre_sale={sum(1 for x in d if x['pre_sale'])} "
          f"repeat={sum(1 for x in d if x['repeat_delinquent'])} "
          f"chronic={sum(1 for x in d if x['chronic'])} "
          f"situs={sum(1 for li in rows if li.street_address)}")

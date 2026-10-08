"""The four scrapers added by the 2026-10-07 distress-source sweep
(docs/new_sources_2026-10-07_distress.md):

    counties_sc.york_tax_sale_parcels      York County SC 2026 tax-sale list (ArcGIS)
    counties_nc.rocky_mount_blight_survey  Rocky Mount 2025 dilapidated / deteriorated / vacant-boarded
    city_websites.raleigh_structure_fires  Raleigh Open Data structure fires
    counties_nc.kinston_proposed_demolition Kinston 2026 proposed demolition list

Offline. Field names and value shapes are the live layers' (checked 2026-10-07); every
name, street and number below is invented.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import pytest

from foreclosure_scraper.models import ListingType
from foreclosure_scraper.scrapers.city_websites import raleigh_structure_fires as RF
from foreclosure_scraper.scrapers.counties_generic import _layer_kit as KIT
from foreclosure_scraper.scrapers.counties_nc import kinston_proposed_demolition as KD
from foreclosure_scraper.scrapers.counties_nc import rocky_mount_blight_survey as RM
from foreclosure_scraper.scrapers.counties_sc import york_tax_sale_parcels as YK

NOW = datetime(2026, 10, 7, 12, 0)


@asynccontextmanager
async def _fake_client(*a, **kw):
    yield object()


def _patch_fetch(monkeypatch, module, payload_by_url):
    calls = []

    async def fake_fetch(http, url, fields, where="1=1", page=1000):
        assert "*" not in fields
        calls.append((url, tuple(fields), where))
        return [dict(r) for r in payload_by_url.get(url, [])]

    monkeypatch.setattr(module, "fetch_attrs", fake_fetch)
    monkeypatch.setattr(module, "client", _fake_client)
    return calls


# --------------------------------------------------------------------------- shared kit

def test_kit_owner_mailing_flags_absentee_and_out_of_state():
    m = KIT.owner_mailing("DOE JANE", ("PO BOX 12", "NEWARK", "NJ", "07101"), "NJ",
                          "10 ELM ST", "123", "SC", "t")
    assert m["absentee"] is True and m["out_of_state"] is True and m["mail_state"] == "NJ"
    local = KIT.owner_mailing("DOE JANE", ("10 ELM ST", "YORK", "SC", "29745"), "SC",
                              "10 ELM ST", "123", "SC", "t")
    assert local["absentee"] is False and local["out_of_state"] is False
    assert KIT.owner_mailing("X", (None, " ", ""), None, "1 A ST", None, "SC", "t") is None


def test_kit_fetch_drops_sensitive_columns(monkeypatch):
    async def fake_query(http, url, out_fields, where, page):
        return [{"PIN": "1", "OWNER_SSN": "000-00-0000", "TCDLC1": "X1", "CLASSNAME": "RES"}]

    monkeypatch.setattr(KIT.agw, "query_attributes", fake_query)
    rows = asyncio.run(KIT.fetch_attrs(None, "https://x/FeatureServer/0", ("PIN",)))
    assert rows == [{"PIN": "1", "CLASSNAME": "RES"}]


def test_dateless_family_prefix_is_whitelisted_by_main():
    from foreclosure_scraper.main import DATELESS_OK_SOURCES
    base = KIT.DATELESS_PREFIX.rstrip(".")
    assert base in DATELESS_OK_SOURCES
    for src in (RM.SOURCE, RF.SOURCE, KD.SOURCE):
        assert src.startswith(KIT.DATELESS_PREFIX)


def test_new_raw_keys_survive_the_publish_slim():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    for k in ("york_tax_sale", "tax_sale_year", "sold_flag", "blight_survey", "fire_incident",
              "kinston_demolition", "utility_cutoff", "heir_property", "condemned", "vacancy",
              "distressed", "owner_mailing", "arcgis_distress", "vacant_lot"):
        assert k in RAW_KEEP, k


def test_all_four_are_registered():
    from foreclosure_scraper.scrapers._registry import discover
    slugs = {c.slug for c in discover()}
    for s in (YK.SOURCE, RM.SLUG, RF.SLUG, KD.SLUG):
        assert s in slugs, s


# --------------------------------------------------------------------------- York

YORK_ROW = {
    "TAXMAPID": "5550000999", "ParcelID": "5550000999", "TAX_YEAR": "2026", "SOLD": "N",
    "Owner1": "SAMPLE OWNER ONE", "Owner2": "SAMPLE OWNER TWO",
    "MailAddr1": "77 FICTION AVE", "MailAddr2": None, "MailApt": None,
    "MailCity": "TRENTON", "MailState": "NJ", "MailZip": "08601",
    "PropertyAddress": "123 IMAGINARY RD", "AprTotVal": 150000, "TaxTotVal": 9000,
    "LandUseDesc": "Residential", "ImprovedStatus": "Improved", "YearBuilt": 1978,
    "deededacres": 0.5,
}


def test_york_sale_day_is_second_monday_of_october():
    assert YK.sale_date_for("2026") == datetime(2026, 10, 12)
    assert YK.sale_date_for(2025) == datetime(2025, 10, 13)
    assert YK.sale_date_for("") is None and YK.sale_date_for("abc") is None


def test_york_row_becomes_a_dated_tax_sale_lead():
    li = YK.to_listing(dict(YORK_ROW), now=NOW)
    assert li.listing_type == ListingType.TAX_SALE and li.foreclosure_process == "tax"
    assert (li.state, li.county, li.parcel_id) == ("SC", "York", "5550000999")
    assert li.sale_date == datetime(2026, 10, 12) and li.auction_status == "scheduled"
    assert li.owner_name == "SAMPLE OWNER ONE & SAMPLE OWNER TWO"
    assert li.street_address == "123 IMAGINARY RD" and li.zip_code is None   # mail ZIP never on the property
    assert li.market_value == 150000 and li.tax_value == 9000 and li.year_built == 1978
    om = li.raw["owner_mailing"]
    assert om["out_of_state"] is True and om["absentee"] is True
    assert "Owner1" not in li.raw["york_tax_sale"] and "MailAddr1" not in li.raw["york_tax_sale"]


def test_york_sold_flag_is_never_terminal_and_vacant_land_is_marked():
    row = dict(YORK_ROW, SOLD="Y", ImprovedStatus="Vacant")
    li = YK.to_listing(row, now=NOW)
    assert li.auction_status is None and li.raw["sold_flag"] == "Y"
    assert li.raw["vacant_lot"] is True


def test_york_row_without_tms_or_situs_is_dropped():
    assert YK.to_listing({"TAX_YEAR": "2026", "Owner1": "NOBODY"}) is None


def test_york_fetch_requests_explicit_fields(monkeypatch):
    calls = _patch_fetch(monkeypatch, YK, {YK.LAYER: [YORK_ROW, {"TAX_YEAR": "2026"}]})
    out = asyncio.run(YK.YorkTaxSaleParcels().fetch())
    assert len(out) == 1 and calls[0][0] == YK.LAYER
    assert "Owner1" in calls[0][1] and "*" not in calls[0][1]


def test_york_env_gate(monkeypatch):
    monkeypatch.setenv(YK.ENV_OFF, "0")
    assert asyncio.run(YK.YorkTaxSaleParcels().fetch()) == []


# --------------------------------------------------------------------------- Rocky Mount

def _rm_row(parno, site, owner="FAKE HOLDINGS LLC", mstate="GA"):
    return {"PARNO": parno, "ALTPARNO": None, "OWNNAME": owner, "OWNNAME2": None,
            "MAILADD": "1 PRETEND PLZ", "MCITY": "ATLANTA", "MSTATE": mstate, "MZIP": "30301",
            "SITEADD": site, "SCITY": "ROCKY MOUNT", "SZIP": "27801", "PARVAL": 41000,
            "IMPROVVAL": 30000, "LANDVAL": 11000, "STRUCTYEAR": 1940,
            "PARUSEDESC": "RESIDENTIAL", "GISACRES": 0.2}


def test_rocky_mount_folds_one_parcel_across_classes():
    lay = {l.name: l for l in RM.LAYERS}
    pairs = [
        (lay["edgecombe_vacant_boarded"], _rm_row("3851-01-0001", "5 INVENTED ST")),
        (lay["edgecombe_dilapidated"], _rm_row("3851-01-0001", "5 INVENTED ST")),
        (lay["nash_deteriorated"], _rm_row("3850-02-0002", "9 MADEUP AVE", mstate="NC")),
    ]
    slots = RM.fold(pairs)
    assert len(slots) == 2
    both = slots[("Edgecombe", "p:3851-01-0001")]
    assert both["classes"] == ["dilapidated", "vacant_boarded"]       # severity order
    li = RM.to_listing(both, now=NOW)
    assert li.source == RM.SOURCE and li.listing_type == ListingType.DISTRESSED
    assert (li.state, li.county, li.parcel_id) == ("NC", "Edgecombe", "3851-01-0001")
    assert li.raw["condemned"] is True and li.raw["distressed"] is True
    assert li.raw["vacancy"]["vacant"] is True and li.raw["vacancy"]["boarded_up"] is True
    assert li.raw["owner_mailing"]["out_of_state"] is True
    assert li.year_built == 1940 and li.tax_value == 41000 and li.city == "ROCKY MOUNT"

    only_det = RM.to_listing(slots[("Nash", "p:3850-02-0002")], now=NOW)
    assert "condemned" not in only_det.raw and "vacancy" not in only_det.raw
    assert only_det.raw["distressed"] is True
    assert only_det.raw["owner_mailing"]["out_of_state"] is False


def test_rocky_mount_layers_cover_both_counties_and_three_classes():
    assert {l.county for l in RM.LAYERS} == {"Nash", "Edgecombe"}
    assert {l.klass for l in RM.LAYERS} == {"dilapidated", "deteriorated", "vacant_boarded"}
    assert "*" not in RM.FIELDS


def test_rocky_mount_fetch_reads_every_layer(monkeypatch):
    payload = {l.url: [_rm_row(f"P{i}", f"{i} INVENTED ST")] for i, l in enumerate(RM.LAYERS)}
    calls = _patch_fetch(monkeypatch, RM, payload)
    out = asyncio.run(RM.RockyMountBlightSurvey().fetch())
    assert len(calls) == len(RM.LAYERS) and len(out) == len(RM.LAYERS)


def test_rocky_mount_a_dead_layer_fails_the_run(monkeypatch):
    async def flaky(http, url, fields, where="1=1", page=1000):
        if "nash_vacant" in url:
            raise RuntimeError("HTTP 500")
        return []

    monkeypatch.setattr(RM, "fetch_attrs", flaky)
    monkeypatch.setattr(RM, "client", _fake_client)
    with pytest.raises(Exception):
        asyncio.run(RM.RockyMountBlightSurvey().fetch())


# --------------------------------------------------------------------------- Raleigh fires

def test_raleigh_where_clause_covers_both_vocabularies():
    w = RF.where_clause(datetime(2024, 10, 7))
    assert "DATE '2024-10-07'" in w
    assert "incident_type IN (111,112)" in w
    for t in ("Structural Involvement", "Room and Contents Fire",
              "Building Collapse / Structure Collapse"):
        assert t in w
    assert "Cooking" not in w and "Vehicle" not in w and "Chimney" not in w


@pytest.mark.parametrize("raw,expect", [
    ("123 IMAGINARY RD RALEIGH, NC 27603", ("123 IMAGINARY RD", "Raleigh", "27603")),
    ("9 FAKE CT WAKE FOREST, NC 27587", ("9 FAKE CT", "Wake Forest", "27587")),
    ("44 NOWHERE LN, NC 27610", ("44 NOWHERE LN", None, "27610")),
    ("FAKE ST / PRETEND AVE", ("FAKE ST / PRETEND AVE", None, None)),
    (None, (None, None, None)),
])
def test_raleigh_address_split(raw, expect):
    assert RF.split_address(raw) == expect


def test_raleigh_folds_repeat_fires_and_skips_intersections():
    rows = [
        {"incident_number": "25-000001", "incident_type": 111,
         "incident_type_description": "Building fire", "dispatch_date_time": 1735689600000,
         "address": "123 IMAGINARY RD RALEIGH, NC 27603"},
        {"incident_number": "26-000002", "incident_type": None,
         "incident_type_name": "Structural Involvement", "dispatch_date_time": 1767225600000,
         "address": "123 IMAGINARY RD RALEIGH, NC 27603"},
        {"incident_number": "26-000003", "incident_type_name": "Room and Contents Fire",
         "dispatch_date_time": 1767225600000, "address": "FAKE ST / PRETEND AVE"},
    ]
    groups = RF.fold(rows)
    assert len(groups) == 1
    li = RF.to_listing(groups[0], now=NOW)
    fi = li.raw["fire_incident"]
    assert fi["count"] == 2 and fi["latest_type"] == "Structural Involvement"
    assert fi["incidents"][0]["incident_number"] == "26-000002"
    assert li.raw["distressed"] is True and li.foreclosure_process == "fire_damage"
    assert (li.state, li.county, li.city, li.zip_code) == ("NC", "Wake", "Raleigh", "27603")
    assert li.parcel_id is None and li.owner_name is None


def test_raleigh_fetch_passes_the_filter(monkeypatch):
    calls = _patch_fetch(monkeypatch, RF, {RF.LAYER: [
        {"incident_number": "25-1", "incident_type": 111, "dispatch_date_time": 1735689600000,
         "address": "1 TEST WAY RALEIGH, NC 27601"}]})
    out = asyncio.run(RF.RaleighStructureFires().fetch())
    assert len(out) == 1 and "incident_type IN (111,112)" in calls[0][2]


# --------------------------------------------------------------------------- Kinston

KIN_ROW = {
    "record_num": 1, "nc_pin": "4525-00-0000", "PARCEL_NUM": 1, "TAX_YEAR": 2026,
    "NAME_1": "PRETEND ESTATE HEIRS", "NAME_2": None,
    "TAYPAYER_A": "500 SAMPLE BLVD", "TAYPAYER_1": " ", "TAYPAYER_2": " ",
    "TAXPAYER_C": "WASHINGTON", "STATE": "DC", "ZIP_CODE": 20001,
    "PHYSICAL_S": "1 EXAMPLE ST", "ADDRESS": None, "TOTAL_FMV_": 9000, "TOTAL_FMV1": 12000, "YEAR_ACTUA": 1926,
    "DEED_ACR_1": 0.14, "CONDEMENED": "2019-01-01", "POWER_CUT_OFF": "Yes-2019",
    "SEWER_CUTOFF": None, "GAS_CUT_OFF": "No", "HEIR_PROPERTY": "Yes",
}


def test_kinston_row_is_a_condemned_lead_with_utility_and_heir_flags():
    li = KD.to_listing(dict(KIN_ROW), now=NOW)
    assert li.source == KD.SOURCE and li.listing_type == ListingType.DISTRESSED
    assert (li.state, li.county, li.parcel_id) == ("NC", "Lenoir", "4525-00-0000")
    assert li.raw["condemned"] is True and li.raw["heir_property"] is True
    assert li.raw["utility_cutoff"]["power"] == "Yes-2019" and "gas" not in li.raw["utility_cutoff"]
    assert li.raw["vacancy"]["basis"] == "utility_cut_off"
    assert li.raw["owner_mailing"]["out_of_state"] is True
    assert li.tax_value == 9000 and li.year_built == 1926
    assert li.raw["kinston_demolition"]["condemned_date"] == "2019-01-01"


def test_kinston_situs_falls_back_to_city_address_column():
    row = dict(KIN_ROW, PHYSICAL_S=None, ADDRESS="2 SAMPLE AVE")
    assert KD.to_listing(row, now=NOW).street_address == "2 SAMPLE AVE"
    assert KD.to_listing(dict(KIN_ROW), now=NOW).street_address == "1 EXAMPLE ST"


def test_kinston_row_without_cutoffs_has_no_vacancy_claim():
    row = dict(KIN_ROW, POWER_CUT_OFF=None, GAS_CUT_OFF=None, HEIR_PROPERTY=None)
    li = KD.to_listing(row, now=NOW)
    assert "vacancy" not in li.raw and "utility_cutoff" not in li.raw
    assert "heir_property" not in li.raw and li.raw["condemned"] is True


def test_kinston_reads_only_the_demolition_layer(monkeypatch):
    calls = _patch_fetch(monkeypatch, KD, {KD.LAYER: [KIN_ROW]})
    out = asyncio.run(KD.KinstonProposedDemolition().fetch())
    assert len(out) == 1 and calls[0][0].endswith("FeatureServer/0")
    assert "*" not in KD.FIELDS



def test_raleigh_dispatch_date_is_the_local_date():
    """2026-01-01 01:30 UTC is the evening of 2025-12-31 in Raleigh (audit 2026-10-09)."""
    d = RF._epoch_ms(1767231000000)
    assert d is not None and d.date().isoformat() == "2025-12-31" and d.hour == 20

"""Henderson NC tax-foreclosure parcels (the ArcGIS web-map definitionExpression list).

Offline tests drive the real code path — walk the SAVED Experience Builder app
doc, follow it to the SAVED web map, read the live-captured definitionExpression,
then map the SAVED 15-row parcel query response to Listings. The fixtures are
verbatim captures, so field-name drift on the county layer surfaces in the
RUN_LIVE=1 smoke test rather than being papered over by invented data.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from foreclosure_scraper import arcgis_webmap as agw
from foreclosure_scraper.models import ListingType, PropertyKind
from foreclosure_scraper.scrapers.counties_nc import henderson_foreclosure_parcels as mod

from tests._arcgis_fakes import FakeHttp

FIX = Path(__file__).parent / "fixtures"
SRC = mod._SOURCES[0]
APP_ITEM = SRC["app_item"]
WEBMAP_ITEM = "7c89c21f8cf6401bbb71560ab9c09ab8"


def _fx(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _http(webmap=None, query=None) -> FakeHttp:
    return FakeHttp({
        f"items/{APP_ITEM}/data": _fx("henderson_exb_app.json"),
        f"items/{WEBMAP_ITEM}/data": webmap or _fx("henderson_webmap.json"),
        "/query": query or _fx("henderson_foreclosure_parcels_query.json"),
    })


def _run(http=None, src=None):
    return asyncio.run(mod.fetch_source(http or _http(), src or SRC))


# --------------------------------------------------------------------------- #
# end-to-end mapping
# --------------------------------------------------------------------------- #

def test_source_attribution_matches_the_scraper_slug():
    """A drift here would silently drop every (dateless) row in _active_only."""
    assert mod.SLUG == mod.HendersonForeclosureParcels.slug
    assert {li.source for li in _run()} == {mod.SLUG}


def test_walks_the_chain_and_emits_every_filtered_parcel():
    http = _http()
    rows = _run(http)
    assert len(rows) == 15
    # The filter, not a hardcoded list, drove the query.
    where = [c[2]["where"] for c in http.calls if "/query" in c[1]][0]
    assert where.startswith("REID = '301249'")
    assert len(agw.literal_values(where, "REID")) == 15


def test_listing_fields_are_fully_populated():
    by_pin = {li.parcel_id: li for li in _run()}
    li = by_pin["9681030858"]                      # 482 HARPER RD
    assert li.source == "counties_nc.henderson_foreclosure_parcels"
    assert li.listing_type is ListingType.TAX_SALE
    assert li.foreclosure_process == "tax"
    assert li.state == "NC" and li.county == "Henderson"
    assert li.street_address == "482 HARPER RD"
    assert li.city == "HENDERSONVILLE" and li.zip_code == "28792"
    assert li.defendant == li.owner_name == "KNOX, CAROLINE ADMINISTRATOR;HARPER, EDNA V ESTATE"
    assert li.tax_value == 50000.0 and li.assessed_value == 50000.0
    assert li.acreage == 1.92 and li.living_sqft == 960.0
    assert li.property_kind is PropertyKind.SINGLE_FAMILY
    assert 35.3 < li.latitude < 35.5 and -82.6 < li.longitude < -82.3
    assert li.sale_date is None                    # dateless by nature


def test_parcel_id_is_the_join_key():
    """Every row lands on parcel:<state>:<county>:<pin> so a code violation /
    delinquent-tax / heir hit on the same parcel MERGES instead of duplicating."""
    for li in _run():
        assert li.parcel_id
        assert li.dedupe_key() == f"parcel:NC:henderson:{li.parcel_id}"


def test_owner_mailing_block_matches_pipeline_shape():
    by_pin = {li.parcel_id: li for li in _run()}
    om = by_pin["0601970510"].raw["owner_mailing"]   # mails from Southwest Ranches FL
    assert om["owner"] == "PATRICIA A JONES TRUST;JONES, PATRICIA A. TRUSTEE"
    assert om["mailing"] == "17420 SW 54TH ST SOUTHWEST RANCHES FL 33331"
    assert om["mail_state"] == "FL"
    assert om["out_of_state"] is True
    assert om["parcel_id"] == "0601970510"
    assert set(om) >= {"owner", "mailing", "situs", "parcel_id", "mail_state",
                       "absentee", "out_of_state", "source"}


def test_absentee_only_when_a_real_situs_disagrees_with_the_mailing():
    by_pin = {li.parcel_id: li for li in _run()}
    # 204 GULL AVE: owner mails to the property itself -> not absentee.
    assert by_pin["9577984987"].raw["owner_mailing"]["absentee"] is False
    # 482 HARPER RD: situs != mailing -> absentee.
    assert by_pin["9681030858"].raw["owner_mailing"]["absentee"] is True
    # No situs at all -> we must NOT guess absentee.
    assert by_pin["0601332696"].raw["owner_mailing"]["absentee"] is False


def test_no_address_assigned_is_not_treated_as_an_address():
    by_pin = {li.parcel_id: li for li in _run()}
    li = by_pin["0601332696"]
    assert li.street_address is None               # '0 NO ADDRESS ASSIGNED'
    assert li.property_kind is PropertyKind.LAND
    assert li.parcel_id                            # still keyed + still a lead


def test_raw_records_the_filter_provenance():
    li = next(iter(_run()))
    tf = li.raw["tax_foreclosure"]
    assert tf["roster"] == "Foreclosure Parcels Henderson County NC"
    assert tf["layer_url"].startswith("https://gisweb.hendersoncountync.gov/")
    assert tf["filter_field"] == "REID" and tf["filter_id"]


# --------------------------------------------------------------------------- #
# extraction-completeness audit 2026-10-03: legal desc / deed+plat ref / sale
# --------------------------------------------------------------------------- #

_LAYER = agw.MapLayer(title="Foreclosure Parcels Henderson County NC",
                      url="https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0")

# Shape mirrors a real live row (captured 2026-10-03, PIN/owner unchanged from
# the public roster at the time): a real deed reference + a priced land sale +
# a CCHS viewer link on both DEED_URL and PLAT_URL.
_ATTRS_FULL = {
    "PIN": "0601970510", "REID": "9970187", "PROPERTY_OWNER": "JONES, PATRICIA A. TRUSTEE",
    "LOCATION_ADDR": "US64 ON", "PHYADDR_CITY": "HENDERSONVILLE", "PHYADDR_ZIP": "28792",
    "TOTAL_PROP_VALUE": 12000.0, "ACREAGE": 0.5, "HEATED_AREA": 0, "LAND_CLASS": "VACANT",
    "Centroid_Latitude": 35.3, "Centroid_Longitude": -82.5,
    "OWNER_MAIL_1": "123 MAIN ST", "OWNER_MAIL_CITY": "HENDERSONVILLE", "OWNER_MAIL_STATE": "NC",
    "OWNER_MAIL_ZIP": "28792",
    "PROPERTY_DESCR": "US64 ON",
    "DEED_BOOK": "001541", "DEED_PAGE": "00445", "DEED_DATE": 1374638460000,
    "PLAT_BOOK": None, "PLAT_PAGE": None,
    "DEED_URL": ("https://us4.courthousecomputersystems.com/hendersonncnw/application.asp"
                 "?cmd=image_link&image_link_book=1541&image_link_page=445"),
    "PLAT_URL": "https://www.hendersoncountync.gov/rd/page/deed-or-plat-not-available",
    "LAND_SALE_DATE": 1374639060000, "LAND_SALE_PRICE": 185000.0,
    "PKG_SALE_DATE": None, "PKG_SALE_PRICE": None,
}

# A $0 LAND_SALE_PRICE means no arms-length sale (inheritance / correction
# deed) -- must not be surfaced as a priced sale.
_ATTRS_ZERO_SALE = {**_ATTRS_FULL, "PIN": "0601975215",
                    "LAND_SALE_DATE": 1374639060000, "LAND_SALE_PRICE": 0.0}


def test_legal_description_is_wired():
    li = mod.build_listing(SRC, _LAYER, _ATTRS_FULL)
    assert li.legal_description == "US64 ON"


def test_deed_and_plat_reference_captured_as_metadata():
    tf = mod.build_listing(SRC, _LAYER, _ATTRS_FULL).raw["tax_foreclosure"]
    assert tf["deed_book"] == "001541" and tf["deed_page"] == "00445"
    assert tf["deed_date"] == "2013-07-24T04:01:00"


def test_deed_url_kept_as_reference_only_not_in_documents():
    """Must NOT go through stamp_documents()/OCR -- it's a Cloudflare-fronted,
    robots-disallowed CCHS viewer shell, not a direct document byte stream."""
    li = mod.build_listing(SRC, _LAYER, _ATTRS_FULL)
    assert li.raw["tax_foreclosure"]["deed_url"].startswith(
        "https://us4.courthousecomputersystems.com/")
    assert "documents" not in li.raw
    assert "document_url" not in li.raw


def test_plat_url_not_available_placeholder_is_dropped():
    assert mod.build_listing(SRC, _LAYER, _ATTRS_FULL).raw["tax_foreclosure"]["plat_url"] is None


def test_priced_land_sale_surfaces_into_raw_gis_last_sale():
    li = mod.build_listing(SRC, _LAYER, _ATTRS_FULL)
    assert li.raw["gis"]["last_sale"] == {
        "date": "2013-07-24T04:11:00", "amount": 185000.0, "source": "henderson_county_gis",
    }


def test_zero_price_sale_is_not_surfaced_as_a_free_property():
    li = mod.build_listing(SRC, _LAYER, _ATTRS_ZERO_SALE)
    assert "gis" not in li.raw


# --------------------------------------------------------------------------- #
# estate / heir signal
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("owner,expected", [
    ("TAYLOR, JULIA HEIRS", "heirs"),
    ("TOWERY, NETTIE ELIZABETH HEIRS", "heirs"),
    ("MAY, KENNETH F EST", "estate"),
    ("KNOX, CAROLINE ADMINISTRATOR;HARPER, EDNA V ESTATE", "administrator"),
    ("SMITH, JOHN EXECUTOR", "executor"),
    ("DOE, JANE DECEASED", "deceased"),
    # Not decedents:
    ("CHIMNEY ROCK ESTATES, HOA", None),           # plural + entity
    ("PATRICIA A JONES TRUST;JONES, PATRICIA A. TRUSTEE", None),
    ("DION HOLDINGS LLC ANC LLC", None),
    ("ARETE INVESTMENT STRATEGIES, LLC", None),
    ("BLUE RIDGE REAL ESTATE CO", None),
    ("SMITH, JOHN LIFE ESTATE", None),             # living owner
    ("HIGHLAND ESTATES HOMEOWNERS ASSN", None),
    ("GILKERSON, DREW;GILKERSON, LEYDA", None),
    ("", None), (None, None),
])
def test_estate_signal(owner, expected):
    assert mod.estate_signal(owner) == expected


def test_estate_owners_carry_a_probate_relationship_signal():
    rows = _run()
    estates = {li.parcel_id: li for li in rows if "heir_estate" in li.raw}
    assert len(estates) == 4                       # the four the county roster shows
    li = estates["0623059712"]                     # TAYLOR, JULIA HEIRS
    assert li.raw["relationship_signal"]["kind"] == "probate"
    assert li.raw["relationship_signal"]["keyword"] == "heirs_owner_of_record"
    assert li.raw["heir_estate"]["match"] == "heirs"
    # ...and the HOA/LLC/TRUST rows did NOT get one.
    assert "relationship_signal" not in {k for li2 in rows if li2.parcel_id == "0601975215"
                                         for k in li2.raw}


def test_probate_signal_is_scored():
    from foreclosure_scraper.distress_score import _signals_for
    li = next(li for li in _run() if li.raw.get("heir_estate"))
    assert any(name == "probate_deed" for name, _bucket, _w in _signals_for(li))


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #

def test_refuses_a_layer_re_pointed_at_an_unexpected_host():
    webmap = _fx("henderson_webmap.json")
    for lyr in webmap["operationalLayers"]:
        if "Foreclosure" in (lyr.get("title") or ""):
            lyr["url"] = "https://evil.example.com/arcgis/rest/services/Parcels/FeatureServer/0"
    http = _http(webmap=webmap)
    assert _run(http) == []
    assert not any("/query" in c[1] for c in http.calls)   # never fetched


def test_refuses_an_unsafe_definition_expression():
    webmap = _fx("henderson_webmap.json")
    for lyr in webmap["operationalLayers"]:
        if "Foreclosure" in (lyr.get("title") or ""):
            lyr["layerDefinition"]["definitionExpression"] = "1=1; DROP TABLE parcels"
    http = _http(webmap=webmap)
    assert _run(http) == []
    assert not any("/query" in c[1] for c in http.calls)


def test_missing_layer_yields_nothing_rather_than_the_unfiltered_roll():
    """If the foreclosure layer disappears we must NOT fall back to
    'ALL Parcels' and dump 60k parcels onto the board."""
    webmap = _fx("henderson_webmap.json")
    webmap["operationalLayers"] = [lyr for lyr in webmap["operationalLayers"]
                                   if "Foreclosure" not in (lyr.get("title") or "")]
    http = _http(webmap=webmap)
    assert _run(http) == []
    assert not any("/query" in c[1] for c in http.calls)


def test_out_fields_are_enumerated_never_star():
    http = _http()
    _run(http)
    of = [c[2]["outFields"] for c in http.calls if "/query" in c[1]][0]
    assert of != "*" and "PIN" in of and "PROPERTY_OWNER" in of


def test_query_error_body_propagates_as_an_exception():
    """HTTP 200 + {'error':...} must not read as a legitimate empty roster."""
    http = _http(query={"error": {"code": 400, "message": "Invalid field: REID"}})
    with pytest.raises(agw.ArcGisError):
        _run(http)


def test_scraper_reports_error_not_zero_when_the_chain_breaks(monkeypatch):
    async def boom(*a, **kw):
        raise agw.ArcGisError("layer gone")
    monkeypatch.setattr(mod.agw, "walk_layers", boom)
    s = mod.HendersonForeclosureParcels()
    rows = asyncio.run(s.safe_run())
    assert rows == []
    assert s.last_outcome != "ZERO_RESULT"


def test_row_without_pin_or_situs_is_dropped():
    assert mod.build_listing(SRC, agw.MapLayer(title="t", url="https://x/0"),
                             {"PROPERTY_OWNER": "SOMEONE"}) is None


# --------------------------------------------------------------------------- #
# wiring guard (fails until main.py is updated — see the report)
# --------------------------------------------------------------------------- #

def test_slug_must_be_in_dateless_ok_sources():
    """These rows carry no sale_date by nature. Without the whitelist entry,
    main._active_only silently drops every one of them and the source reads 0."""
    from foreclosure_scraper import main
    assert mod.SLUG in main.DATELESS_OK_SOURCES, (
        f'add "{mod.SLUG}" to main.DATELESS_OK_SOURCES')


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not __import__("os").environ.get("RUN_LIVE"),
                    reason="live smoke; set RUN_LIVE=1")
def test_live():
    s = mod.HendersonForeclosureParcels()
    rows = asyncio.run(s.safe_run())
    assert s.last_outcome == "OK"
    assert len(rows) >= s.expected_min_count
    assert all(li.parcel_id for li in rows)
    assert any(li.raw.get("heir_estate") for li in rows)
    assert any(li.raw["owner_mailing"].get("owner") for li in rows)
    print(f"live henderson foreclosure parcels={len(rows)} "
          f"estate={sum(1 for li in rows if li.raw.get('heir_estate'))}")

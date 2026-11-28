"""Montgomery NC (www.webgis.net) ArcGIS parcel-layer integration.

Live-verified 2026-11-28 against 3 real board parcel_ids (PinNoDash matches the
board's parcel_id format exactly) and a webgis.net TLS cert fix (missing
intermediate -- see _montgomery_ssl_context() in enrichment_arcgis.py). These
tests drive the real _apply_attrs/_arcgis_query code path against a captured
real attribute sample from that live probe, offline.
"""
from __future__ import annotations

import ssl

import pytest

from foreclosure_scraper.enrichment_arcgis import (
    FIELD_ALIASES, NC_GIS, _apply_attrs, _arcgis_query, _client_for,
    _montgomery_ssl_context, _pick,
)
from foreclosure_scraper.models import Listing

from tests._arcgis_fakes import FakeHttp

# Real attributes captured live 2026-11-28 for board parcel_id '667200471107'
# (229 Porters Glen Ln) -- the one sample of the 3 live-checked rows with full
# CAMA data (the other two have 0 for YearBuilt/FinishedAr/Num_Baths/Num_Bedrms,
# which maybe()/_apply_attrs correctly treats as "no value", not a real zero).
_REAL_ATTRS = {
    "PIN": "6672 00 47 1107",
    "PinNoDash": "667200471107",
    "Name_1": "ALEXANDER ROBERT K",
    "PhyAddress": "229 PORTERS GLEN LN",
    "DeedBook": "828",
    "DeedPage": "218",
    "DeedYear": 2019,
    "TransDate": 20190628,
    "SalesAmt": 1550000,
    "LandASVCur": 403000,
    "ImpMajASVC": 1081418,
    "ImpMisASVC": 43509,
    "TotASVCur": 1527927,
    "YearBuilt": 2006,
    "FinishedAr": 7607,
    "Num_Baths": 5,
    "Num_Bedrms": 4,
    "Deed_Acre": 1.12,
    "ACRES": "",
    "_match_confident": True,
}


def _bare_listing(**kw) -> Listing:
    base = dict(county="Montgomery", state="NC", street_address="229 Porters Glen Ln",
                parcel_id="667200471107", source="test", source_url="https://example.com")
    base.update(kw)
    return Listing(**base)


def test_montgomery_registered_in_nc_gis_with_webgis_url():
    cfg = NC_GIS["Montgomery"]
    assert cfg["url"] == (
        "https://www.webgis.net/arcgis/rest/services/NC/Montgomery/MapServer/1/query"
    )
    assert cfg["addr_field"] == "PhyAddress"
    # Explicit out_fields, not "*" -- matches the Gaston/Cleveland safety convention.
    assert "PinNoDash" in cfg["out_fields"]


def test_apply_attrs_fills_beds_baths_sqft_from_real_sample():
    li = _bare_listing()
    filled = _apply_attrs(li, dict(_REAL_ATTRS))
    assert filled > 0
    assert li.bedrooms == 4
    assert li.bathrooms == 5
    assert li.living_sqft == 7607
    assert li.year_built == 2006
    assert li.tax_value == 1527927


def test_apply_attrs_fills_owner_and_last_sale():
    li = _bare_listing()
    _apply_attrs(li, dict(_REAL_ATTRS))
    assert li.raw["gis"]["owner"] == "ALEXANDER ROBERT K"
    sale = li.raw["gis"]["last_sale"]
    assert sale["book"] == "828"
    assert sale["page"] == "218"
    assert sale["amount"] == 1550000.0


def test_apply_attrs_zero_cama_fields_are_not_written_as_real_zeros():
    """2 of the 3 live-sampled rows have YearBuilt=0/FinishedAr=0/Num_Baths=0/
    Num_Bedrms=0 (vacant lot or unfilled CAMA cell) -- maybe() must treat 0 as
    absent, never as a genuine zero-bedroom house."""
    sparse = dict(_REAL_ATTRS)
    sparse.update(YearBuilt=0, FinishedAr=0, Num_Baths=0, Num_Bedrms=0)
    li = _bare_listing()
    _apply_attrs(li, sparse)
    assert li.bedrooms is None
    assert li.bathrooms is None
    assert li.living_sqft is None
    assert li.year_built is None


def test_field_aliases_cover_every_montgomery_column_used():
    for role, col in (("owner_name", "Name_1"), ("site_address", "PhyAddress"),
                       ("bedrooms", "Num_Bedrms"), ("bathrooms", "Num_Baths"),
                       ("living_sqft", "FinishedAr"), ("tax_value", "TotASVCur"),
                       ("sale_date", "TransDate"), ("sale_amount", "SalesAmt"),
                       ("land_value", "LandASVCur"), ("improvement_value", "ImpMajASVC")):
        assert col in FIELD_ALIASES[role], f"{col} missing from FIELD_ALIASES[{role!r}]"
    # parcel_id / deed_book / deed_page / year_built already had exact matches
    # (PIN / DeedBook / DeedPage / YearBuilt) before this change -- confirm they
    # still do, so a future edit can't silently drop the free coverage.
    for role, col in (("parcel_id", "PIN"), ("deed_book", "DeedBook"),
                       ("deed_page", "DeedPage"), ("year_built", "YearBuilt")):
        assert col in FIELD_ALIASES[role]


@pytest.mark.asyncio
async def test_arcgis_query_against_fake_webgis_returns_real_shaped_row():
    fake = FakeHttp(routes={"webgis.net": {"features": [
        {"attributes": dict(_REAL_ATTRS), "geometry": {}}
    ]}})
    out = await _arcgis_query(
        fake, NC_GIS["Montgomery"]["url"], "PhyAddress", "229 Porters Glen Ln",
        "229", out_fields=NC_GIS["Montgomery"]["out_fields"],
    )
    assert len(out) == 1
    assert _pick(out[0], FIELD_ALIASES["owner_name"]) == "ALEXANDER ROBERT K"


def test_client_for_routes_webgis_host_to_cert_client_and_everything_else_to_default():
    default = object()
    cert = object()
    assert _client_for(NC_GIS["Montgomery"]["url"], default, cert) is cert
    assert _client_for(NC_GIS["Mecklenburg"]["url"], default, cert) is default
    # No cert client available (e.g. a caller that never built one) -- always fall
    # back to default rather than returning None.
    assert _client_for(NC_GIS["Montgomery"]["url"], default, None) is default


def test_montgomery_ssl_context_trusts_default_bundle_plus_the_extra_intermediate():
    ctx = _montgomery_ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    # Cached -- built once per process (mirrors enrichment_incarceration._ssl_context).
    assert _montgomery_ssl_context() is ctx

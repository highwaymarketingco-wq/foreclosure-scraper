"""Generic ArcGIS web-map walker (arcgis_webmap).

Unit tests run offline against SAVED fixtures of the real Henderson County
Experience Builder app doc + web map doc, so an upstream schema change shows up
as a live-smoke failure rather than a silently-passing suite.

Covered: the app -> web map -> layer walk, definitionExpression extraction
(including group/sub layers and top-level placement), the SQL + host trust
guards, literal parsing, the '*'-outFields ban, error-body detection, and
resultOffset pagination incl. the ignored-offset guard.

RUN_LIVE=1 adds an opt-in smoke test against the real chain.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from foreclosure_scraper import arcgis_webmap as agw

from tests._arcgis_fakes import FakeHttp

FIX = Path(__file__).parent / "fixtures"
APP_ITEM = "e25ea4d18d30427cacb1064168c0dea3"
WEBMAP_ITEM = "7c89c21f8cf6401bbb71560ab9c09ab8"
PARCEL_LAYER = "https://gisweb.hendersoncountync.gov/arcgis/rest/services/Parcels/FeatureServer/0"


def _fx(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def _walk_http() -> FakeHttp:
    return FakeHttp({
        f"items/{APP_ITEM}/data": _fx("henderson_exb_app.json"),
        f"items/{WEBMAP_ITEM}/data": _fx("henderson_webmap.json"),
    })


# --------------------------------------------------------------------------- #
# walk
# --------------------------------------------------------------------------- #

def test_walk_app_to_webmap_to_filtered_layer():
    http = _walk_http()
    layers = asyncio.run(agw.walk_layers(http, APP_ITEM))
    titles = [lyr.title for lyr in layers]
    assert "Foreclosure Parcels Henderson County NC" in titles
    lyr = agw.find_layer(layers, r"foreclos")
    assert lyr is not None
    assert lyr.url == PARCEL_LAYER
    assert lyr.definition_expression.startswith("REID = '301249'")
    assert lyr.item_id == WEBMAP_ITEM
    # It followed the app doc first, then the web map doc.
    assert any(APP_ITEM in c[1] for c in http.calls)
    assert any(WEBMAP_ITEM in c[1] for c in http.calls)


def test_find_layer_prefers_the_filtered_copy_of_a_shared_layer():
    """Both 'ALL Parcels' and 'Foreclosure Parcels' point at the SAME layer URL.
    Only the filtered one is the list."""
    layers = asyncio.run(agw.walk_layers(_walk_http(), APP_ITEM))
    same_url = [lyr for lyr in layers if lyr.url == PARCEL_LAYER]
    assert len(same_url) == 2
    picked = agw.find_layer(layers, r"parcels")
    assert picked.definition_expression  # never the unfiltered twin
    assert "Foreclosure" in picked.title


def test_walk_accepts_a_webmap_item_directly():
    http = FakeHttp({f"items/{WEBMAP_ITEM}/data": _fx("henderson_webmap.json")})
    layers = asyncio.run(agw.walk_layers(http, WEBMAP_ITEM))
    assert agw.find_layer(layers, r"foreclos") is not None


def test_walk_is_current_not_cached():
    """Re-reading picks up an edited REID list — the whole point of walking."""
    wm = _fx("henderson_webmap.json")
    for lyr in wm["operationalLayers"]:
        if (lyr.get("layerDefinition") or {}).get("definitionExpression"):
            lyr["layerDefinition"]["definitionExpression"] = "REID = '999'"
    http = FakeHttp({f"items/{APP_ITEM}/data": _fx("henderson_exb_app.json"),
                     f"items/{WEBMAP_ITEM}/data": wm})
    lyr = agw.find_layer(asyncio.run(agw.walk_layers(http, APP_ITEM)), r"foreclos")
    assert lyr.definition_expression == "REID = '999'"


def test_extract_layers_handles_group_and_sublayers():
    webmap = {"operationalLayers": [{
        "title": "Group", "layerType": "GroupLayer",
        "layers": [
            {"title": "Nested FS", "url": "https://x.gov/rest/services/A/FeatureServer/2",
             "layerDefinition": {"definitionExpression": "STATUS = 'OPEN'"}},
            # MapServer sublayer: carries an int id, no url of its own.
            {"title": "Sub", "id": 7,
             "layerDefinition": {"definitionExpression": "YR = 2026"}},
        ],
        "url": "https://x.gov/rest/services/B/MapServer",
    }]}
    layers = agw.extract_layers(webmap)
    by_title = {lyr.title: lyr for lyr in layers}
    assert by_title["Nested FS"].definition_expression == "STATUS = 'OPEN'"
    assert by_title["Sub"].url == "https://x.gov/rest/services/B/MapServer/7"


def test_extract_layers_reads_top_level_definition_expression():
    webmap = {"operationalLayers": [
        {"title": "T", "url": "https://x.gov/FeatureServer/0",
         "definitionExpression": "A = 1"}]}
    assert agw.extract_layers(webmap)[0].definition_expression == "A = 1"


def test_referenced_item_ids_puts_web_maps_first():
    data = {"dataSources": {
        "a": {"type": "FEATURE_LAYER", "itemId": "b" * 32},
        "b": {"type": "WEB_MAP", "itemId": "a" * 32},
    }}
    assert agw.referenced_item_ids(data)[0] == "a" * 32


def test_referenced_item_ids_falls_back_to_scanning():
    """A layout without dataSources (dashboard/storymap) still resolves."""
    data = {"widgets": {"w1": {"nested": {"itemId": "c" * 32}}}}
    assert agw.referenced_item_ids(data) == ["c" * 32]


def test_fetch_item_data_raises_on_error_body():
    http = FakeHttp({"items/": {"error": {"code": 403, "message": "denied"}}})
    with pytest.raises(agw.ArcGisError):
        asyncio.run(agw.fetch_item_data(http, "d" * 32))


def test_fetch_item_data_falls_through_to_second_portal():
    http = FakeHttp({"hendersoncounty.maps.arcgis.com": _fx("henderson_webmap.json")})
    data = asyncio.run(agw.fetch_item_data(
        http, WEBMAP_ITEM,
        portals=("https://www.arcgis.com", "https://hendersoncounty.maps.arcgis.com")))
    assert data["operationalLayers"]


# --------------------------------------------------------------------------- #
# guards
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("expr", [
    "REID = '1' OR REID = '2'",
    "STATUS IN ('A','B') AND YR >= 2020",
    "dispositionStatus NOT LIKE '%No Further Action%'",
])
def test_safe_expressions_accepted(expr):
    assert agw.is_safe_expression(expr)


@pytest.mark.parametrize("expr", [
    None, "", "   ",
    "1=1; DROP TABLE parcels",
    "REID = '1' -- comment",
    "REID = '1' /* x */",
    "1=1 OR 1=1 UNION SELECT 1; DELETE FROM x",
    "A" * (agw._MAX_EXPR_CHARS + 1),
])
def test_unsafe_expressions_rejected(expr):
    assert not agw.is_safe_expression(expr)


def test_host_matches_pins_the_expected_server():
    assert agw.host_matches(PARCEL_LAYER, ("gisweb.hendersoncountync.gov",))
    assert agw.host_matches("https://a.b.example.gov/x", ("example.gov",))  # subdomain
    assert not agw.host_matches("https://evil.example.com/x", ("gisweb.hendersoncountync.gov",))
    assert not agw.host_matches(None, ("gisweb.hendersoncountync.gov",))


def test_literal_values_parses_or_chain_and_in_list():
    expr = _fx("henderson_webmap.json")["operationalLayers"][2]["layerDefinition"]["definitionExpression"]
    ids = agw.literal_values(expr, "REID")
    assert len(ids) == 15
    assert "301249" in ids and "1001771" in ids
    assert agw.literal_values("PIN IN ('a','b', 'c')", "PIN") == ["a", "b", "c"]
    assert agw.literal_values("YR = 2026", "YR") == ["2026"]


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #

def test_query_features_rejects_star_out_fields():
    with pytest.raises(ValueError):
        asyncio.run(agw.query_features(FakeHttp({}), PARCEL_LAYER, out_fields="*"))


def test_query_features_rejects_unsafe_where():
    with pytest.raises(agw.ArcGisError):
        asyncio.run(agw.query_features(FakeHttp({}), PARCEL_LAYER,
                                       out_fields="PIN", where="1=1; DROP TABLE x"))


def test_query_features_raises_on_http_200_error_body():
    """The silent-death shape: HTTP 200 with an error payload and 0 features."""
    http = FakeHttp({"/query": {"error": {"code": 400,
                                          "message": "Invalid field: REID"}}})
    with pytest.raises(agw.ArcGisError):
        asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN"))


def _feat(oid):
    return {"attributes": {"OBJECTID": oid, "PIN": f"p{oid}"}}


def test_query_features_paginates_until_transfer_limit_clears():
    pages = [
        {"objectIdFieldName": "OBJECTID",
         "features": [_feat(i) for i in range(1000)], "exceededTransferLimit": True},
        {"objectIdFieldName": "OBJECTID",
         "features": [_feat(i) for i in range(1000, 1233)]},
    ]
    http = FakeHttp({}, pages=pages)
    rows = asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN,OBJECTID"))
    assert len(rows) == 1233
    offsets = [int(c[2]["resultOffset"]) for c in http.calls]
    assert offsets == [0, 1000]


def test_query_features_stops_on_explicit_false_transfer_limit():
    pages = [{"objectIdFieldName": "OBJECTID",
              "features": [_feat(i) for i in range(1000)],
              "exceededTransferLimit": False}]
    http = FakeHttp({}, pages=pages)
    rows = asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN,OBJECTID"))
    assert len(rows) == 1000
    assert len(http.calls) == 1


def test_query_features_guards_against_ignored_result_offset():
    """Older MapServer layers ignore resultOffset — without the OID guard this
    would loop forever re-reading page one."""
    same = {"objectIdFieldName": "OBJECTID",
            "features": [_feat(i) for i in range(1000)], "exceededTransferLimit": True}
    http = FakeHttp({}, pages=[json.loads(json.dumps(same)) for _ in range(5)])
    rows = asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN,OBJECTID"))
    assert len(rows) == 1000
    assert len(http.calls) == 2  # one real page, one that returned nothing new


def test_query_features_switches_to_post_for_a_long_where():
    long_where = "PIN IN (" + ",".join(f"'{i:010d}'" for i in range(300)) + ")"
    http = FakeHttp({}, pages=[{"objectIdFieldName": "OBJECTID", "features": []}])
    asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN",
                                   where=long_where))
    assert http.calls[0][0] == "POST"


def test_query_features_honours_max_records():
    pages = [{"objectIdFieldName": "OBJECTID",
              "features": [_feat(i) for i in range(1000)], "exceededTransferLimit": True}]
    http = FakeHttp({}, pages=pages)
    rows = asyncio.run(agw.query_features(http, PARCEL_LAYER, out_fields="PIN,OBJECTID",
                                          max_records=10))
    assert len(rows) == 10


# --------------------------------------------------------------------------- #
# live smoke
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="live smoke; set RUN_LIVE=1")
def test_live_walk_and_query():
    from foreclosure_scraper.http_client import client

    async def run():
        async with client(timeout=45.0) as http:
            layers = await agw.walk_layers(
                http, APP_ITEM,
                portals=("https://www.arcgis.com", "https://hendersoncounty.maps.arcgis.com"))
            lyr = agw.find_layer(layers, r"foreclos")
            assert lyr and lyr.url and lyr.definition_expression
            assert agw.host_matches(lyr.url, ("gisweb.hendersoncountync.gov",))
            rows = await agw.query_attributes(
                http, lyr.url, where=lyr.definition_expression,
                out_fields="REID,PIN,PROPERTY_OWNER")
            return len(agw.literal_values(lyr.definition_expression, "REID")), len(rows)

    n_ids, n_rows = asyncio.run(run())
    assert n_ids >= 1 and n_rows >= 1
    assert n_rows == n_ids, f"filter listed {n_ids} REIDs but layer returned {n_rows}"
    print(f"live henderson foreclosure filter: {n_ids} REIDs -> {n_rows} parcels")

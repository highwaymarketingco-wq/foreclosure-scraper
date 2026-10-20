"""Pure-parsing tests for scripts/ingest_williamsburg_wthgis_parcels.py -- the
Williamsburg SC WTH-tgis cache builder (2026-10-20, vacant_lot/heir_estate gap).

No network: these exercise the HTML/overlay parsers against real response shapes
captured live from williamsburgsc.wthgis.com while building the script, and the
board-parcel_id / GIS-Map-Number matching logic (_base_mapno, _surname)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ingest_williamsburg_wthgis_parcels as ing  # noqa: E402


# A real search response shape (SearchType=Name, SearchCriteria=ESTATE|), trimmed to
# two result rows -- captured live 2026-10-20.
SEARCH_FIXTURE = (
    "<overlay><numpts2>,,,37355664,53763928,18-069-015,2342,3787,18-071-051"
    "</numpts2><zoomto>37273470,53697417,37491573,53859495,16</zoomto>"
    "<info><![CDATA[<div id=\"searchResultContainer\">"
    "<div id=\"searchResultCountMessage\">Your search returned 2 items</div>"
    "<div id=\"searchResultItems\">"
    "<div id='evenContainer' class='resultContainer'><div class='propertyCardView'>"
    "<div id=oli0 onclick='showf(56 , 710)'></div>"
    "<button id=btnViewPropertyRecordCard onclick='printPropertyRecordCard(56 , 710)'>Card</button>"
    "<button id=btnZoomToParcel onclick='showf(56 , 710)'>Zoom</button></div>"
    "<div id=resultsParcelNumber class='mainResultItem'>18-069-015</div>"
    "<div class='secondaryResultItem'>Everly Mae Real Estate Fund LLC</div></div>"
    "<div id='oddContainer' class='resultContainer'><div class='propertyCardView'>"
    "<div id=oli1 onclick='showf(56 , 925)'></div>"
    "<button id=btnViewPropertyRecordCard onclick='printPropertyRecordCard(56 , 925)'>Card</button>"
    "<button id=btnZoomToParcel onclick='showf(56 , 925)'>Zoom</button></div>"
    "<div id=resultsParcelNumber class='mainResultItem'>18-071-051</div>"
    "<div class='secondaryResultItem'>Bradley Bonner P Estate</div></div>"
    "</div></div>]]></info></overlay>"
)

# A real getftr.aspx detail response shape, trimmed -- captured live 2026-10-20
# (FeatureID 710, the Everly Mae Real Estate Fund LLC parcel above).
DETAIL_FIXTURE = (
    "<overlay><info><![CDATA["
    "<table><tr><th>Map&nbsp;Number</th><td>18-069-015</td></tr>"
    "<tr><th>Owner&nbsp;Name</th><td>Everly Mae Real Estate Fund LLC</td></tr>"
    "<tr><th>Owner&nbsp;Name2</th><td></td></tr>"
    "<tr><th>Mailing&nbsp;Address1</th><td>11956 Bernardo Plaza Dr #259</td></tr>"
    "<tr><th>Mailing&nbsp;Address2</th><td></td></tr>"
    "<tr><th>Mailing&nbsp;City</th><td>San Diego</td></tr>"
    "<tr><th>Mailing&nbsp;State</th><td>CA</td></tr>"
    "<tr><th>Mailing&nbsp;ZipCode</th><td>92128</td></tr>"
    "<tr><th>Property&nbsp;Address1</th><td>11011 Hemingway Hwy</td></tr>"
    "<tr><th>Property&nbsp;Address2</th><td></td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueAcres</th>"
    "<td style=\"text-align: right;\">0.50</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueBuildings</th>"
    "<td style=\"text-align: right;\">1.00</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueBuildingsValue</th>"
    "<td style=\"text-align: right;\">53349.00</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueTotalValue</th>"
    "<td style=\"text-align: right;\">61974.00</td></tr>"
    "<tr><th style=\"text-align: right;\">TaxValueTotalValue</th>"
    "<td style=\"text-align: right;\">61974.00</td></tr>"
    "<tr><td>09/24/2024</td><td>$10.00</td><td>Kirkland Financial LLC</td>"
    "<td>Everly Mae Real Estate Fund LLC</td><td>821</td><td>297</td></tr>"
    "</table>]]></info></overlay>"
)

# A detail response for a genuinely vacant parcel (MarketValueBuildings/Value both 0),
# matching F=100 (45-485-016) captured live.
DETAIL_FIXTURE_VACANT = (
    "<overlay><info><![CDATA["
    "<table><tr><th>Map&nbsp;Number</th><td>45-485-016</td></tr>"
    "<tr><th>Owner&nbsp;Name</th><td>Holliday Robert Mark</td></tr>"
    "<tr><th>Owner&nbsp;Name2</th><td></td></tr>"
    "<tr><th>Mailing&nbsp;Address1</th><td>123 Main St</td></tr>"
    "<tr><th>Mailing&nbsp;Address2</th><td></td></tr>"
    "<tr><th>Mailing&nbsp;City</th><td>Kingstree</td></tr>"
    "<tr><th>Mailing&nbsp;State</th><td>SC</td></tr>"
    "<tr><th>Mailing&nbsp;ZipCode</th><td>29556</td></tr>"
    "<tr><th>Property&nbsp;Address1</th><td></td></tr>"
    "<tr><th>Property&nbsp;Address2</th><td></td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueAcres</th>"
    "<td style=\"text-align: right;\">1.20</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueBuildings</th>"
    "<td style=\"text-align: right;\">0.00</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueBuildingsValue</th>"
    "<td style=\"text-align: right;\">0.00</td></tr>"
    "<tr><th style=\"text-align: right;\">MarketValueTotalValue</th>"
    "<td style=\"text-align: right;\">32500.00</td></tr>"
    "<tr><th style=\"text-align: right;\">TaxValueTotalValue</th>"
    "<td style=\"text-align: right;\">32500.00</td></tr>"
    "</table>]]></info></overlay>"
)


def test_parse_search_extracts_mapnumber_to_featureid():
    out = ing._parse_search(SEARCH_FIXTURE)
    assert out == {"18-069-015": 710, "18-071-051": 925}


def test_parse_search_empty_response():
    assert ing._parse_search("<overlay><info><![CDATA[]]></info></overlay>") == {}


def test_parse_detail_full_record():
    rec = ing._parse_detail(DETAIL_FIXTURE)
    assert rec["MapNumber"] == "18-069-015"
    assert rec["OwnerName"] == "Everly Mae Real Estate Fund LLC"
    assert rec["MailingCity"] == "San Diego"
    assert rec["MailingState"] == "CA"
    assert rec["PropertyAddress1"] == "11011 Hemingway Hwy"
    assert rec["MarketValueBuildingsValue"] == "53349.00"
    assert rec["MarketValueTotalValue"] == "61974.00"
    assert rec["MarketValueAcres"] == "0.50"
    # most recent sale picked up from the History tab
    assert rec["SaleDate"] == "09/24/2024"
    assert rec["SalePrice"] == "10.00"


def test_parse_detail_vacant_record_zero_building_value():
    rec = ing._parse_detail(DETAIL_FIXTURE_VACANT)
    assert rec["MapNumber"] == "45-485-016"
    assert rec["MarketValueBuildingsValue"] == "0.00"
    assert rec["MarketValueTotalValue"] == "32500.00"


def test_parse_detail_no_map_number_returns_none():
    assert ing._parse_detail("<overlay><info><![CDATA[no data here]]></info></overlay>") is None


def test_map_val_improvement_value_zero_is_falsy_float_not_none():
    """enrichment_vacant_landuse.py's gate checks `imprv is not None` then
    `float(imprv) == 0.0` -- confirm _map_val round-trips "0.00" to 0.0, not None,
    through the real PARCEL_LAYERS["Williamsburg"]["map"] spec this script uses."""
    from foreclosure_scraper import parcel_cache
    rec = ing._parse_detail(DETAIL_FIXTURE_VACANT)
    val = parcel_cache._map_val(rec, "improvement_value", ing.WILLIAMSBURG_MAP["improvement_value"])
    assert val == 0.0
    assert val is not None


def test_map_val_nonzero_improvement_value():
    from foreclosure_scraper import parcel_cache
    rec = ing._parse_detail(DETAIL_FIXTURE)
    val = parcel_cache._map_val(rec, "improvement_value", ing.WILLIAMSBURG_MAP["improvement_value"])
    assert val == 53349.0


# --- board parcel_id <-> GIS Map Number matching ------------------------------------

def test_base_mapno_strips_qpaybill_sub_account_suffix():
    assert ing._base_mapno("45-120-068.A") == "45-120-068"
    assert ing._base_mapno("45-405-002.C") == "45-405-002"
    assert ing._base_mapno("45-232-002.J") == "45-232-002"


def test_base_mapno_leaves_clean_id_unchanged():
    assert ing._base_mapno("45-279-255") == "45-279-255"


def test_base_mapno_unrecognized_shape_passed_through():
    assert ing._base_mapno("") == ""
    assert ing._base_mapno("not-a-parcel-id") == "not-a-parcel-id"


def test_surname_takes_first_token_strips_punctuation():
    assert ing._surname("AHRENS OLIVIA") == "AHRENS"
    assert ing._surname("ANDERSON CORA ETAL") == "ANDERSON"
    assert ing._surname("ALTMAN BOBBY E JR") == "ALTMAN"
    assert ing._surname("") == ""


def test_write_cache_indexes_under_both_gis_and_board_parcel_id(tmp_path, monkeypatch):
    """A record resolved via the base Map Number must still be looked up successfully
    under the board's OWN (suffixed) parcel_id -- this is the whole point of carrying
    board_pids through to _write_cache."""
    from foreclosure_scraper import parcel_cache
    monkeypatch.setattr(parcel_cache, "CACHE_DIR", tmp_path)
    rec = ing._parse_detail(DETAIL_FIXTURE_VACANT)
    rec["MapNumber"] = "45-120-068"  # bare GIS form
    ing._write_cache([(rec, ["45-120-068.A"])])  # board's suffixed form
    hit = parcel_cache.lookup("Williamsburg", "45-120-068.A", "SC")
    assert hit is not None
    assert hit["improvement_value"] == 0.0

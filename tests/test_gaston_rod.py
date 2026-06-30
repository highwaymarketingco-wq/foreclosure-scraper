"""Offline tests for the Gaston ROD lien-existence enricher (parser + classifier).

Uses a captured-shape DevExpress grid fixture so CI never hits the network.
"""
from foreclosure_scraper.enrichment_gaston_rod import (
    parse_rows, classify, _body, _name_parts,
)

SAMPLE = """
<tr id="gridTrad_DXDataRow0" class="dxgvDataRow dx_grid_row">
<td class="dx_grid_cell Cell_Date dxgv" style="font-size:12pt;">01/02/2020</td>
<td class="dx_grid_cell Cell_Kind dxgv" style="font-size:12pt;">D/T</td>
<td class="dx_grid_cell Cell_Grantor dxgv" style="font-size:12pt;">COLONIAL OAKS APARTMENTS</td>
<td class="dx_grid_cell Cell_Grantee dxgv" style="font-size:12pt;">BANK OF AMERICA</td>
<td title="[ MTG ]" class="dx_grid_cell Cell_Description dxgv">[ MTG ]</td>
<td class="dx_grid_cell Cell_DocNo dxgv"><span class='pointer' onclick='x'>0001234567</span></td>
<td class="dx_grid_cell Cell_Book dxgv">5012</td>
<td class="dx_grid_cell Cell_Page dxgv">221</td>
</tr>
<tr id="gridTrad_DXDataRow1" class="dxgvDataRow dx_grid_row">
<td class="dx_grid_cell Cell_Date dxgv">03/04/2019</td>
<td class="dx_grid_cell Cell_Kind dxgv">DEED</td>
<td class="dx_grid_cell Cell_Grantor dxgv">SMITH JOHN</td>
<td class="dx_grid_cell Cell_Grantee dxgv">COLONIAL OAKS APARTMENTS</td>
<td class="dx_grid_cell Cell_Description dxgv">[ WD ]</td>
<td class="dx_grid_cell Cell_DocNo dxgv"><span>0001234500</span></td>
<td class="dx_grid_cell Cell_Book dxgv">4900</td>
<td class="dx_grid_cell Cell_Page dxgv">10</td>
</tr>
"""


def test_parse_rows():
    rows = parse_rows(SAMPLE)
    assert len(rows) == 2
    assert rows[0]["kind"] == "D/T"
    assert rows[0]["grantor"] == "COLONIAL OAKS APARTMENTS"
    assert rows[0]["grantee"] == "BANK OF AMERICA"
    assert rows[0]["book"] == "5012" and rows[0]["page"] == "221"
    assert rows[1]["kind"] == "DEED"


def test_classify_mortgage():
    c = classify(parse_rows(SAMPLE))
    assert c["instrument_count"] == 2
    assert c["has_mortgage"] is True          # D/T => deed of trust
    assert c["kinds"].get("D/T") == 1
    assert c["has_adverse_lien"] is False


def test_classify_adverse():
    c = classify([{"kind": "JUDG", "description": "TAX LIEN"}])
    assert c["has_adverse_lien"] is True
    assert "JUDG" in c["adverse_types"]


def test_parse_empty():
    assert parse_rows("") == []
    assert parse_rows("<html>Object reference not set</html>") == []


def test_name_parts():
    assert _name_parts("SMITH, JOHN") == ("SMITH", "JOHN")
    assert _name_parts("COLONIAL OAKS APARTMENTS") == ("COLONIAL OAKS APARTMENTS", "")


def test_body_encodes_name():
    b = _body("SMITH", "JOHN")
    assert "MultiNameLast%5B%5D=SMITH" in b
    assert "MultiNameGiven%5B%5D=JOHN" in b
    assert "MatchType=beginswith" in b
    assert "DXScript" not in b   # robust: no app-version tokens

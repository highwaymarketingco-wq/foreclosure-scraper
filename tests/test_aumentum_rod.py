"""Offline tests for the Buncombe/Aumentum (Cott eSearch v4) ROD parser + classifier.

Fixture mirrors the live cpgvInstruments grid row shape (verified 2026-06-30): per-<tr>
columns [row#, Date Filed, Index, Type, Grantor, Grantee, Description, File Number, Book/Page].
CI never hits the network.
"""
from foreclosure_scraper.rod.aumentum import _parse_instruments_grid
from foreclosure_scraper.enrichment_aumentum_rod import _classify, _owner_doc, _name_parts

SAMPLE = """
<table id="ctl00_cphMain_tcMain_tpInstruments_ucInstrumentsGridV2_cpgvInstruments">
<tr class="dxgvDataRow"><td>1</td><td>06/02/2026</td><td>CRP</td><td>DEED OF TRUST</td>
<td>SMITH, ELIZABETH B.</td><td>BANK OF AMERICA</td><td>LOT 5</td><td>2026012345</td><td>6598 / 1020</td></tr>
<tr class="dxgvDataRow"><td>2</td><td>03/04/2019</td><td>CRP</td><td>DEED</td>
<td>JONES, SARA</td><td>SMITH, ELIZABETH B.</td><td>WD</td><td>2019001234</td><td>5012 / 221</td></tr>
<tr class="dxgvDataRow"><td>3</td><td>01/10/2022</td><td>CRP</td><td>FORECLOSURE</td>
<td>SMITH, ELIZABETH B.</td><td>SUBSTITUTE TRUSTEE</td><td>NOS</td><td>2022000099</td><td>5800 / 12</td></tr>
</table>
"""


def test_parse_returns_rows_with_grantor_and_bookpage():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    assert len(rows) >= 1
    r0 = rows[0]
    assert r0.grantor and "SMITH" in r0.grantor      # non-empty grantor
    assert r0.book == "6598" and r0.page == "1020"    # Book/Page split on '/'
    assert r0.doc_type                                 # normalized type present


def test_classify_mortgage_and_adverse():
    c = _classify(_parse_instruments_grid(SAMPLE, "Buncombe", "NC"))
    assert c["instrument_count"] == 3
    assert c["has_mortgage"] is True       # DEED OF TRUST
    assert c["has_adverse_lien"] is True   # FORECLOSURE


def test_owner_filter_keeps_only_owner_rows():
    rows = _parse_instruments_grid(SAMPLE, "Buncombe", "NC")
    last, first = _name_parts("SMITH, ELIZABETH")
    mine = [r for r in rows if _owner_doc(r, last, first)]
    # the DT + the FORECLOSURE (SMITH grantor) match; the DEED where SMITH is grantee also matches
    assert len(mine) >= 2


def test_empty():
    assert _parse_instruments_grid("", "Buncombe", "NC") == []

"""Tests for the Orangeburg County SC legacy-ASP Register of Deeds scraper.

Row fixtures below are trimmed, structurally-faithful copies of real rows returned
by https://orangeburgscrod.org/InstrumentsIndex.asp (confirmed live 2026-11-11),
not invented markup -- the blank-line-between-tags quirk that broke an earlier
version of _cell_lines() is preserved on purpose.
"""
from foreclosure_scraper.scrapers.counties_sc.orangeburg_scrod import (
    OrangeburgSCROD,
    _dedupe_mech_rows,
    _is_active,
    _parse_rows,
    _to_listing,
)

_FEDERAL_HTML = """
<tr>
<td valign="top" align="center"><input type="radio" name="detail" onClick="javascript:submitSearch(this,'DetailIndex.asp?Table=FederalLiens&Instrument=2024000082&FileDate=11/4/2024')"></td>
<td valign="top" align="center"><input type="checkbox" name="selectInstrument" id="selectInstrument" value="2024000082"></td>
<td valign="top" align="center"><font class="Data">&nbsp;</font></td>
<td align="Left" ><font class="Data">

<font color="#800000">HAPPYLAND AFTER SCHOOL CLUBHOUSE INC </font>
<br>
1167 HENLEY ST                &nbsp;&nbsp;&nbsp;                              <br />
ORANGEBURG SC 29115                     <br />
Tax:2663.60   <br>

<br>
Desc:                                                                           &nbsp;&nbsp;&nbsp;Instrument #:2024000082
<br>

Discharge Date:2/4/2025&nbsp;&nbsp;&nbsp;Discharge Type1
</font></td>
<td valign="top" align="Left"><font class="Data">11/4/2024</font></td>
<td valign="top" align="Left"><font class="Data">&nbsp;</font></td>
<td valign="top" align="center">&nbsp;</td>
</tr>
<tr>
<td valign="top" align="center"><input type="radio" name="detail" onClick="javascript:submitSearch(this,'DetailIndex.asp?Table=FederalLiens&Instrument=2026000024&FileDate=9/15/2026')"></td>
<td valign="top" align="center"><input type="checkbox" name="selectInstrument" id="selectInstrument" value="2026000024"></td>
<td valign="top" align="center"><font class="Data">&nbsp;</font></td>
<td align="Left" ><font class="Data">

<font color="#800000">ROBINSON WYONDA </font>
<br>
4469 CLEVELAND ST                                                          <br />
Tax:1200.00   <br>
</font></td>
<td valign="top" align="Left"><font class="Data">9/15/2026</font></td>
<td valign="top" align="Left"><font class="Data">&nbsp;</font></td>
<td valign="top" align="center">&nbsp;</td>
</tr>
"""

_MECH_HTML = """
<tr>
<td valign="top" align="center"><input type="radio" name="detail" onClick="javascript:submitSearch(this,'DetailIndex.asp?Table=MechLiens&Instrument=2026000018&FileDate=3/10/2026')"></td>
<td valign="top" align="center"><input type="checkbox" name="selectInstrument" id="selectInstrument" value="2026000018"></td>
<td valign="top" align="center"><font class="Data">J</font></td>
<td align="Left" ><font class="Data">

<font color="#800000">ORANGEBURG REDI MIX CONCRETE INC </font>&nbsp;|&nbsp;HEXAGON SERVICE GROUP LLC THE
<br>
Book:02014&nbsp;&nbsp;&nbsp;Page:00008&nbsp;&nbsp;&nbsp;Instrument #:2026000018
<br>
</font></td>
<td valign="top" align="Left"><font class="Data">3/10/2026</font></td>
<td valign="top" align="Left"><font class="Data">MECH LIEN  </font></td>
<td valign="top" align="center">&nbsp;</td>
</tr>
<tr>
<td valign="top" align="center"><input type="radio" name="detail" onClick="javascript:submitSearch(this,'DetailIndex.asp?Table=MechLiens&Instrument=2026000018&FileDate=3/10/2026')"></td>
<td valign="top" align="center"><input type="checkbox" name="selectInstrument" id="selectInstrument" value="2026000018"></td>
<td valign="top" align="center"><font class="Data">K</font></td>
<td align="Left" ><font class="Data">

<font color="#800000">HEXAGON SERVICE GROUP LLC THE </font>&nbsp;|&nbsp;ORANGEBURG REDI MIX CONCRETE INC
<br>
Book:02014&nbsp;&nbsp;&nbsp;Page:00008&nbsp;&nbsp;&nbsp;Instrument #:2026000018
<br>
</font></td>
<td valign="top" align="Left"><font class="Data">3/10/2026</font></td>
<td valign="top" align="Left"><font class="Data">MECH LIEN  </font></td>
<td valign="top" align="center">&nbsp;</td>
</tr>
<tr>
<td valign="top" align="center"><input type="radio" name="detail" onClick="javascript:submitSearch(this,'DetailIndex.asp?Table=MechLiens&Instrument=2025000007&FileDate=3/10/2025')"></td>
<td valign="top" align="center"><input type="checkbox" name="selectInstrument" id="selectInstrument" value="2025000007"></td>
<td valign="top" align="center"><font class="Data">J</font></td>
<td align="Left" ><font class="Data">

<font color="#800000">MARTIN MARIETTA MATERIALS INC </font>&nbsp;|&nbsp;SUPER LAND HOLDINGS LLC
<br>
Book:02014&nbsp;&nbsp;&nbsp;Page:00008&nbsp;&nbsp;&nbsp;Instrument #:2025000007
<br>
</font></td>
<td valign="top" align="Left"><font class="Data">3/10/2025</font></td>
<td valign="top" align="Left"><font class="Data">MECH REL  </font></td>
<td valign="top" align="center">&nbsp;</td>
</tr>
"""


def test_slug():
    assert OrangeburgSCROD().slug == "counties_sc.orangeburg_scrod"


def test_parse_federal_rows():
    rows = _parse_rows(_FEDERAL_HTML, "FederalLiens")
    assert len(rows) == 2
    discharged, active = rows[0], rows[1]
    assert discharged["primary"] == "HAPPYLAND AFTER SCHOOL CLUBHOUSE INC"
    assert discharged["address"] == "1167 HENLEY ST"
    assert discharged["tax_amount"] == "2663.60"
    assert discharged["discharge_date"] == "2/4/2025"
    assert not _is_active("FederalLiens", discharged)

    assert active["primary"] == "ROBINSON WYONDA"
    assert active["address"] == "4469 CLEVELAND ST"
    assert active["discharge_date"] is None
    assert _is_active("FederalLiens", active)


def test_federal_listing_uses_taxpayer_as_owner():
    rows = _parse_rows(_FEDERAL_HTML, "FederalLiens")
    li = _to_listing(rows[1], "FederalLiens", "counties_sc.orangeburg_scrod")
    assert li is not None
    assert li.owner_name == "ROBINSON WYONDA"
    assert li.street_address == "4469 CLEVELAND ST"
    assert li.plaintiff is None
    # the discharged row must not produce a listing at all
    assert _to_listing(rows[0], "FederalLiens", "counties_sc.orangeburg_scrod") is None


def test_mech_rolecode_decides_owner_not_position():
    """The SAME instrument (2026000018) appears twice with the highlighted name
    swapped -- the 'K' row's primary is the real property owner, the 'J' row's
    primary is the claimant, regardless of which one happens to be colored in
    a given row. Getting this backwards tags every contractor as the distressed
    owner on half of all mechanic-lien rows."""
    rows = _parse_rows(_MECH_HTML, "MechLiens")
    j_row = next(r for r in rows if r["instrument"] == "2026000018" and r["rolecode"] == "J")
    k_row = next(r for r in rows if r["instrument"] == "2026000018" and r["rolecode"] == "K")

    li_j = _to_listing(j_row, "MechLiens", "counties_sc.orangeburg_scrod")
    li_k = _to_listing(k_row, "MechLiens", "counties_sc.orangeburg_scrod")
    assert li_j.plaintiff == "ORANGEBURG REDI MIX CONCRETE INC"
    assert li_j.defendant == "HEXAGON SERVICE GROUP LLC THE"
    assert li_k.plaintiff == "ORANGEBURG REDI MIX CONCRETE INC"
    assert li_k.defendant == "HEXAGON SERVICE GROUP LLC THE"


def test_dedupe_mech_rows_collapses_the_j_k_pair():
    rows = _parse_rows(_MECH_HTML, "MechLiens")
    assert len(rows) == 3  # two rows for 2026000018 (J+K) + one for 2025000007 (release)
    deduped = _dedupe_mech_rows(rows)
    insts = sorted(r["instrument"] for r in deduped)
    assert insts == ["2025000007", "2026000018"]


def test_mech_release_is_skipped():
    rows = _parse_rows(_MECH_HTML, "MechLiens")
    rel = next(r for r in rows if r["instrument"] == "2025000007")
    assert rel["doctype"] == "MECH REL"
    assert not _is_active("MechLiens", rel)
    assert _to_listing(rel, "MechLiens", "counties_sc.orangeburg_scrod") is None

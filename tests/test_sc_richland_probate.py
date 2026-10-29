"""counties_sc.sc_richland_probate: pure-function tests (_parse_results / _is_current), no
network. The fixture HTML below is a trimmed-but-real capture of main.aspx's response to a real
Last="SIMS" First="ISOM" search, live-verified 2026-10-28 -- not reconstructed by hand."""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.scrapers.counties_sc.sc_richland_probate import (
    _is_current, _parse_detail, _parse_results, case_number_parts,
)

REAL_DETAIL_LUCAS = """
<span id="lblCaseNumber">2026-ES40-00110</span>
<table id="dlPR" cellspacing="2" cellpadding="2" border="0">
	<tr>
		<td>
                        <td class="rowHeading2">Name</td>
                        <td class="rowHeading2">1st Line Address</td>
                        <td class="rowHeading2">2nd Line Address</td>
                        <td class="rowHeading2">City</td>
                        <td class="rowHeading2">State Zip</td>
                        <td class="rowHeading2">Work Phone</td>
                        <td class="rowHeading2">Home Phone</td>
                    </td>
	</tr><tr>
		<td>
                        <td class="rowHeading3">Marjan S. Lucas</td>
                        <td class="rowHeading3">100 SUNSET BLVD</td>
                        <td class="rowHeading3">APT 704</td>
                        <td class="rowHeading3">WEST COLUMBIA</td>
                        <td class="rowHeading3">SC 29169</td>
                        <td class="rowHeading3"></td>
                        <td class="rowHeading3">8034147444</td>
                    </td>
	</tr>
</table>
<table id="dlAT" cellspacing="2" cellpadding="2" border="0">
	<tr>
		<td>
                        <td class="rowHeading2">Name</td>
                        <td class="rowHeading2">1st Line Address</td>
                        <td class="rowHeading2">2nd Line Address</td>
                        <td class="rowHeading2">City</td>
                        <td class="rowHeading2">State Zip</td>
                        <td class="rowHeading2">Work Phone</td>
                        <td class="rowHeading2">Home Phone</td>
                    </td>
	</tr><tr>
		<td>
                        <td class="rowHeading3">Madison Elizabeth    Barnhill            </td>
                        <td class="rowHeading3">609 Sims Avenue</td>
                        <td class="rowHeading3"></td>
                        <td class="rowHeading3">COLUMBIA</td>
                        <td class="rowHeading3">SC 29205</td>
                        <td class="rowHeading3"></td>
                        <td class="rowHeading3">8032521500</td>
                    </td>
	</tr>
</table>
"""

REAL_RESULTS_SIMS_ISOM = """
<table tabindex="6" cellspacing="0" cellpadding="6" border="0" id="gvEstates" width="100%">
    <tr>
        <th class="tableHeading" scope="col">&nbsp;</th><th class="tableHeading" scope="col">Case Number</th><th class="tableHeading" scope="col">Decedent's Name</th><th class="tableHeading" scope="col" width="50">Date of Death</th><th class="tableHeading" scope="col" width="50">Date Opened</th><th class="tableHeading" scope="col" width="50">Date Closed</th><th class="tableHeadingEmailWidth" scope="col">Estate Clerk eMail</th><th class="tableHeading" scope="col">&nbsp;</th>
    </tr><tr bgcolor="#FFFFCC">
        <td>
            <input type="submit" name="gvEstates$ctl02$btnRequestCD" value="View Estate Documents" id="gvEstates_ctl02_btnRequestCD" disabled="disabled" class="smalltext" />
        </td><td class="smalltext">
            1985-ES40-00304
        </td><td class="smalltext">
          <span id="gvEstates_ctl02_lblDecedentLastName" class="smalltext">Sims                </span>,
          <span id="gvEstates_ctl02_lblDecedentFirstName" class="smalltext">Isom                </span>
          <span id="gvEstates_ctl02_lblDecedentMiddleName" class="smalltext"></span>
          <span id="gvEstates_ctl02_lblNameSuffix" class="smalltext"></span>
      </td><td class="smalltext">
            06/25/1977
        </td><td class="smalltext">
            07/05/2023
        </td><td class="smalltext">
            04/01/1985
        </td><td><a href="mailto:{0}"></a></td><td><input type="button" value="View Parties" onclick="javascript:__doPostBack(&#39;gvEstates&#39;,&#39;Parties$0&#39;)" class="optout" /></td>
    </tr><tr bgcolor="White">
        <td>
            <input type="submit" name="gvEstates$ctl03$btnRequestCD" value="View Estate Documents" id="gvEstates_ctl03_btnRequestCD" disabled="disabled" class="smalltext" />
        </td><td class="smalltext">
            1991-ES40-00827
        </td><td class="smalltext">
          <span id="gvEstates_ctl03_lblDecedentLastName" class="smalltext">Sims                </span>,
          <span id="gvEstates_ctl03_lblDecedentFirstName" class="smalltext">Isom Jr             </span>
          <span id="gvEstates_ctl03_lblDecedentMiddleName" class="smalltext"></span>
          <span id="gvEstates_ctl03_lblNameSuffix" class="smalltext"></span>
      </td><td class="smalltext">
        </td><td class="smalltext">
            08/29/1991
        </td><td class="smalltext">
            08/29/1991
        </td><td><a href="mailto:{0}"></a></td><td><input type="button" value="View Parties" onclick="javascript:__doPostBack(&#39;gvEstates&#39;,&#39;Parties$1&#39;)" class="optout" /></td>
    </tr>
</table>
"""

NO_RECORDS_FORM = """
<table>
  <tr><td colspan="5">Please enter the decedent's name.</td></tr>
  <tr><td class="tdRight">Last name: </td><td><input name="txtLastName" /></td>
      <td class="tdRight">First name: </td><td><input name="txtFirstName" /></td></tr>
</table>
"""


def test_parse_results_reads_real_grid():
    rows = _parse_results(REAL_RESULTS_SIMS_ISOM)
    assert len(rows) == 2
    assert rows[0]["case_number"] == "1985-ES40-00304"
    assert rows[0]["decedent"] == "Isom Sims"
    assert rows[0]["date_of_death"] == "06/25/1977"
    assert rows[0]["date_opened"] == "07/05/2023"
    assert rows[0]["date_closed"] == "04/01/1985"
    assert rows[1]["case_number"] == "1991-ES40-00827"
    assert rows[1]["decedent"] == "Isom Jr Sims"
    assert rows[1]["date_of_death"] is None


def test_parse_results_empty_on_bare_search_form():
    assert _parse_results(NO_RECORDS_FORM) == []


def test_parse_results_empty_on_garbage():
    assert _parse_results("<html><body>not a grid</body></html>") == []


def test_is_current_keeps_open_estate():
    row = {"date_closed": None}
    assert _is_current(row, datetime(2026, 10, 28)) is True


def test_is_current_keeps_recently_closed_estate():
    row = {"date_closed": "06/01/2026"}
    assert _is_current(row, datetime(2026, 10, 28)) is True


def test_is_current_drops_long_closed_estate():
    row = {"date_closed": "04/01/1985"}
    assert _is_current(row, datetime(2026, 10, 28)) is False


def test_case_number_parts_reads_real_format():
    assert case_number_parts("1991-ES40-00827") == ("1991", "827")
    assert case_number_parts("2026-ES40-00110") == ("2026", "110")


def test_case_number_parts_none_on_unrecognized_format():
    assert case_number_parts("not-a-case-number") is None
    assert case_number_parts("") is None


def test_parse_detail_reads_real_pr_and_attorney():
    d = _parse_detail(REAL_DETAIL_LUCAS)
    assert d["pr"]["name"] == "Marjan S. Lucas"
    assert d["pr"]["address_line1"] == "100 SUNSET BLVD"
    assert d["pr"]["city"] == "WEST COLUMBIA"
    assert d["pr"]["home_phone"] == "8034147444"
    assert d["attorney"]["name"] == "Madison Elizabeth    Barnhill"
    assert d["attorney"]["address_line1"] == "609 Sims Avenue"
    assert d["attorney"]["home_phone"] == "8032521500"


def test_parse_detail_none_on_garbage():
    d = _parse_detail("<html><body>not a detail page</body></html>")
    assert d["pr"] is None
    assert d["attorney"] is None

"""counties_sc.greenville_probate — offline tests against real DOM fixtures.

Greenville County SC runs its own probate search (appsas400), separate from
southcarolinaprobate.net (sc_probate_net.py) -- a different ASP.NET app with different
mechanics entirely (plain query-string GET + redirect-to-token, not VIEWSTATE postback;
different results-table shape; different detail-page shape). An earlier draft of this
scraper assumed sc_probate_net's own POST/VIEWSTATE flow and field names and got 0 results
against the real site -- these fixtures are trimmed, whitespace-padding-preserving copies of
real HTML captured live 2026-10-13 (search "Smith"+EST, and cases APT29F27 [1 PR, blank
address], APT23F34 [2 PRs], APT1390F21 [0 parties], 2020ES23016822 [the literal
'788OLLAND FORD ROAD' no-space source bug], 2026ES2302389 [a real, modern, fully-populated
case]), so a regression here means the parser broke against the ACTUAL site shape, not a
guessed one.
"""
from __future__ import annotations

from datetime import datetime

from foreclosure_scraper.scrapers.counties_sc.greenville_probate import (
    _build_listing,
    _clean,
    _clean_address,
    _parse_detail,
    _parse_results,
    _personal_representative,
    is_current,
)

# --- search-results grid (table.JobsTable, no element id, single-quoted hrefs with
# trailing whitespace baked into the href value itself) --------------------------------

_RESULTS_HTML = """
<table width="100%" cellspacing="0" cellpadding="3" class="JobsTable">
    <thead><tr><th scope="col">Case #</th><th scope="col">Name</th><th scope="col">Party Type</th></tr></thead>
    <tr>
        <td><a href='SearchDetails.aspx?CaseNumber=APT29F27            '>
            APT29F27            </a></td>
        <td>SMITH                                                       , A                    H                       </td>
        <td>Deceased Person                                             </td>
    </tr>
    <tr>
        <td><a href='SearchDetails.aspx?CaseNumber=2026ES2300430      '>
            2026ES2300430      </a></td>
        <td>SMITH                                                       , ANGELA              ELAINE                  </td>
        <td>Deceased Person                                             </td>
    </tr>
</table>
"""


def test_parse_results_strips_padding_and_cleans_name():
    rows = _parse_results(_RESULTS_HTML)
    assert len(rows) == 2
    assert rows[0]["case_number"] == "APT29F27"          # trailing href padding stripped
    assert rows[0]["name"] == "SMITH, A H"                # fixed-width padding collapsed
    assert rows[1]["case_number"] == "2026ES2300430"
    assert rows[1]["name"] == "SMITH, ANGELA ELAINE"


def test_parse_results_empty_when_no_case_links():
    assert _parse_results("<table class='JobsTable'><tr><td>0 Matches Found</td></tr></table>") == []


# --- detail page (table.altDetailsTable: one heading table + one data table per
# section) -------------------------------------------------------------------------------

def _detail_page(decedent_rows: str, parties_heading: str, parties_rows: str) -> str:
    return f"""
    <table class="altDetailsTable" style="width: 100%;">
        <tr><th class="heading"><h2><span>Case Details (X)</span></h2></th></tr>
    </table>
    <table cellspacing="0" cellpadding="3" class="altDetailsTable">
        {decedent_rows}
    </table>
    <table class="altDetailsTable" style="width: 100%;">
        <tr><th class="heading"><h2>Parties Involved&nbsp;({parties_heading})</h2></th></tr>
    </table>
    <table width="100%" cellspacing="0" class="altDetailsTable">
        {parties_rows}
    </table>
    """


def _row(label: str, value: str) -> str:
    return f"<tr><th>{label}:</th><td>{value}</td></tr>"


# APT29F27 live shape: blank Address, 1 PR, no attorney-type row exists on this site.
_APT29F27_DECEDENT = (
    _row("Name", "SMITH" + " " * 59 + ", A" + " " * 20 + "H" + " " * 23)
    + _row("Party Type", "Deceased Person" + " " * 25)
    + _row("Address", "")
    + _row("Date of Death", "")
    + _row("Date of Birth", "")
    + _row("Sex", "")
    + _row("Status", "Estates- I" + " " * 10)
    + _row("Case Type", "Estate" + " " * 9)
    + _row("Case SubType", "Batch Intestate" + " " * 5)
    + _row("File Date", "12/31/1866")
    + _row("Expiration of Estate Creditor Claims Period", "")
    + _row("PR Appointed Date", "12/31/1866")
    + _row("Closed Date", "12/31/1900")
)
_APT29F27_PARTIES = (
    _row("Name", "MOORE" + " " * 59 + ", JAMES" + " " * 16 + "P" + " " * 23)
    + _row("Party Type", "Personal Representative" + " " * 17)
    + _row("Address", " " * 100)
    + "<tr><td colspan='2' style='background-color: #fff; border: none;'>&nbsp;</td></tr>"
)


def test_parse_detail_single_pr_blank_address_ancient_dates():
    html = _detail_page(_APT29F27_DECEDENT, "1", _APT29F27_PARTIES)
    detail = _parse_detail(html)
    assert detail["name"] == "SMITH, A H"
    assert detail["address"] == ""
    assert detail["file_date"] == "12/31/1866"
    assert detail["closed_date"] == "12/31/1900"
    assert len(detail["parties"]) == 1
    assert detail["parties"][0]["name"] == "MOORE, JAMES P"
    assert detail["parties"][0]["party_type"] == "Personal Representative"


def test_parse_detail_two_parties_both_prs():
    parties = (
        _row("Name", "SMITH, LEMUEL") + _row("Party Type", "Personal Representative")
        + _row("Address", "")
        + "<tr><td colspan='2'>&nbsp;</td></tr>"
        + _row("Name", "SMITH, W M") + _row("Party Type", "Personal Representative")
        + _row("Address", "")
        + "<tr><td colspan='2'>&nbsp;</td></tr>"
    )
    html = _detail_page(_APT29F27_DECEDENT, "2", parties)
    detail = _parse_detail(html)
    assert [p["name"] for p in detail["parties"]] == ["SMITH, LEMUEL", "SMITH, W M"]


def test_parse_detail_zero_parties():
    html = _detail_page(_APT29F27_DECEDENT, "0", "")
    detail = _parse_detail(html)
    assert detail["parties"] == []


def test_parse_detail_modern_populated_case():
    """2026ES2302389, live-verified 2026-10-13: a fully-populated modern case."""
    decedent = (
        _row("Name", "SMITH, JAMES M")
        + _row("Party Type", "Deceased Person")
        + _row("Address", "46 THUNDERBIRD DRIVE" + " " * 60 + "TRAVELERS REST" + " " * 15 + "SC 29690")
        + _row("Date of Death", "9/19/2026")
        + _row("Date of Birth", "4/12/1946")
        + _row("Sex", "M")
        + _row("Status", "Will Filed w/ 306ES")
        + _row("Case Type", "Estate")
        + _row("Case SubType", "306 Will4Record 2014")
        + _row("File Date", "9/29/2026")
        + _row("Expiration of Estate Creditor Claims Period", "")
        + _row("PR Appointed Date", "")
        + _row("Closed Date", "")
    )
    detail = _parse_detail(_detail_page(decedent, "0", ""))
    assert detail["address"] == "46 THUNDERBIRD DRIVE TRAVELERS REST SC 29690"
    assert detail["closed_date"] == ""
    assert detail["file_date"] == "9/29/2026"
    assert is_current(detail, now=datetime(2026, 10, 13))   # no closed_date -> always current


# --- the real source-data bug: house number glued to street name with no space --------

def test_clean_address_fixes_missing_space_bug():
    # live source text, case 2020ES23016822 -- not a whitespace-collapse artifact of this
    # scraper, the raw HTML itself has no space between "788" and "OLLAND".
    raw = "788OLLAND FORD ROAD" + " " * 60 + "PELZER" + " " * 20 + "SC 29669     "
    assert _clean_address(raw) == "788 OLLAND FORD ROAD PELZER SC 29669"


def test_clean_address_leaves_well_formed_address_alone():
    raw = "46 THUNDERBIRD DRIVE" + " " * 60 + "TRAVELERS REST" + " " * 15 + "SC 29690"
    assert _clean_address(raw) == "46 THUNDERBIRD DRIVE TRAVELERS REST SC 29690"


def test_clean_address_blank_stays_blank():
    assert _clean_address("") == ""
    assert _clean_address(None) == ""


def test_clean_collapses_padding_and_space_before_comma():
    assert _clean("SMITH" + " " * 20 + ", A" + " " * 10 + "H") == "SMITH, A H"
    assert _clean(None) == ""


# --- is_current: Closed Date presence decides the rule, matching sc_probate_net's own
# "not closed -> always kept" logic but off a different field -----------------------------

def test_is_current_true_when_no_closed_date_regardless_of_age():
    assert is_current({"closed_date": "", "file_date": "1/1/1900"}, now=datetime(2026, 10, 13))


def test_is_current_true_when_closed_but_recently_filed():
    assert is_current({"closed_date": "5/5/2026", "file_date": "3/20/2026"}, now=datetime(2026, 10, 13))


def test_is_current_false_when_closed_and_ancient():
    assert not is_current({"closed_date": "12/31/1900", "file_date": "12/31/1866"},
                           now=datetime(2026, 10, 13))


def test_is_current_false_when_closed_and_no_parseable_dates_at_all():
    assert not is_current({"closed_date": "12/31/1980", "file_date": "", "date_of_death": ""},
                           now=datetime(2026, 10, 13))


def test_is_current_falls_back_to_date_of_death_when_file_date_missing():
    assert is_current({"closed_date": "1/1/2026", "file_date": "", "date_of_death": "9/1/2026"},
                       now=datetime(2026, 10, 13))


def test_max_age_days_zero_disables_the_filter(monkeypatch):
    import foreclosure_scraper.scrapers.counties_sc.greenville_probate as mod
    monkeypatch.setattr(mod, "MAX_AGE_DAYS", 0)
    assert mod.is_current({"closed_date": "12/31/1900", "file_date": "12/31/1866"})


# --- _personal_representative + _build_listing -----------------------------------------

def test_personal_representative_picks_pr_type_among_mixed_parties():
    parties = [{"name": "A", "party_type": "Heir"}, {"name": "B", "party_type": "Personal Representative"}]
    assert _personal_representative(parties)["name"] == "B"


def test_personal_representative_falls_back_to_first_when_no_pr_type():
    parties = [{"name": "A", "party_type": "Heir"}]
    assert _personal_representative(parties)["name"] == "A"


def test_personal_representative_none_when_no_parties():
    assert _personal_representative([]) is None


def test_build_listing_real_sample_albert_david_smith():
    """Live-verified 2026-10-13: a real, current, actionable lead with a real address."""
    summary = {"case_number": "2020ES23016822", "name": "SMITH, ALBERT DAVID", "party_type": "Deceased Person"}
    detail = {
        "name": "SMITH, ALBERT DAVID", "address": "788OLLAND FORD ROAD" + " " * 40 + "PELZER" + " " * 20 + "SC 29669",
        "file_date": "12/5/2025", "date_of_death": "", "closed_date": "8/10/2026",
        "case_type": "Estate", "case_subtype": "Subsequent Admin", "status": "Subsequent Admin",
        "pr_appointed_date": "",
        "parties": [{"name": "SMITH, DEBORAH JEAN", "party_type": "Personal Representative", "address": ""}],
    }
    li = _build_listing(summary, detail)
    assert li.source == "counties_sc.greenville_probate"
    assert li.state == "SC" and li.county == "Greenville"
    assert li.owner_name == "SMITH, ALBERT DAVID"
    assert li.defendant == "SMITH, DEBORAH JEAN"
    assert li.street_address == "788 OLLAND FORD ROAD PELZER SC 29669"   # no-space bug fixed
    assert li.case_number == "2020ES23016822"
    assert "decedent SMITH, ALBERT DAVID" in li.description
    assert "PR SMITH, DEBORAH JEAN" in li.description
    assert li.raw["greenville_probate"]["closed_date"] == "8/10/2026"


def test_build_listing_no_parties_leaves_defendant_and_address_none():
    summary = {"case_number": "APT1390F21", "name": "SMITH, A J", "party_type": "Deceased Person"}
    detail = {
        "name": "SMITH, A J", "address": "", "file_date": "12/31/1975", "date_of_death": "",
        "closed_date": "12/31/1975", "case_type": "Estate", "case_subtype": "Certifed Copies",
        "status": "Certified Copy", "pr_appointed_date": "", "parties": [],
    }
    li = _build_listing(summary, detail)
    assert li.defendant is None
    assert li.street_address is None

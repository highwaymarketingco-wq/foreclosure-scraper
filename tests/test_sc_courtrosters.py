"""Tests for the SC court-rosters scraper.

Live testing requires Scrapling stealth + a real browser context (not
available in CI). These tests pin the parser logic against a fixture
HTML and verify the scraper class metadata.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.sc_courtrosters import (
    COUNTY_ROSTER_URLS,
    SCCourtRosters,
    _parse_roster,
)


def test_covers_9_counties():
    assert len(COUNTY_ROSTER_URLS) == 9
    expected = {"Greenville", "Charleston", "Richland", "Lexington", "Horry",
                "York", "Berkeley", "Beaufort", "Aiken"}
    assert set(COUNTY_ROSTER_URLS) == expected


def test_does_not_overlap_with_lis_pendens_scraper():
    """The original SC lis-pendens scraper covers Spartanburg/Anderson/
    Pickens/Oconee/Cherokee/Union/Laurens. This scraper must NOT
    duplicate those counties — would double-count listings."""
    from foreclosure_scraper.scrapers.counties_sc.sc_public_index_lis_pendens import (
        COUNTIES as LP_COUNTIES,
    )
    overlap = set(COUNTY_ROSTER_URLS) & set(LP_COUNTIES)
    assert overlap == set(), f"counties double-covered: {overlap}"


def test_scraper_metadata():
    s = SCCourtRosters()
    assert s.slug == "counties_sc.sc_courtrosters"
    assert s.expected_min_count == 0  # Monthly cadence; runs may land between rosters
    assert s.requires_apify is False


def test_parse_extracts_case_number_and_date():
    # Padded with realistic boilerplate so length > 500 chars
    html = """
    <html><head><title>Greenville Court Rosters</title></head>
    <body>
    <h1>Master in Equity Sale Roster</h1>
    <p>The following sales are scheduled for the upcoming term.
    All sales conducted on the steps of the Greenville County Courthouse
    at 11:00 AM on the date indicated. Bidders must register prior to
    the auction. 5% deposit required at time of bid acceptance.</p>
    <table>
      <tr><td>2026-CP-23-01234 — ABC Bank vs Smith John —
          Sale 06/15/2026 — 100 Main Street, Greenville SC</td></tr>
      <tr><td>2026-CP-23-05678 — XYZ Mortgage vs Jones Mary —
          Sale 06/15/2026 — 200 Oak Drive, Greenville SC</td></tr>
    </table>
    <p>For more information contact the Master in Equity office.</p>
    </body></html>
    """
    listings = _parse_roster(html, "Greenville", "http://x")
    assert len(listings) == 2
    cases = sorted(li.case_number for li in listings)
    assert cases == ["2026-CP-23-01234", "2026-CP-23-05678"]
    # Sale date parsed
    assert all(li.sale_date and li.sale_date.year == 2026 for li in listings)
    # Address extracted
    assert any("Main Street" in (li.street_address or "") for li in listings)


def test_parse_handles_no_cases():
    html = "<html><body>No upcoming sales scheduled.</body></html>"
    listings = _parse_roster(html, "Greenville", "http://x")
    assert listings == []


def test_parse_dedups_same_case():
    html = """
    <html><head><title>Roster</title></head><body>
    <h1>Master in Equity Sale Roster</h1>
    <p>The following sales are scheduled. Lorem ipsum dolor sit amet,
    consectetur adipiscing elit, sed do eiusmod tempor incididunt ut
    labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud
    exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.
    Duis aute irure dolor in reprehenderit in voluptate velit esse cillum.</p>
    <p>Case 2026-CP-23-01234 ABC Bank vs Smith — Sale 06/15/2026 — 100 Main St</p>
    <p>... later in document, same case mentioned ...</p>
    <p>2026-CP-23-01234 already listed above</p>
    </body></html>
    """
    listings = _parse_roster(html, "Greenville", "http://x")
    assert len(listings) == 1

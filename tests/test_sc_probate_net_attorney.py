"""counties_sc.sc_probate_net — attorney-of-record gap (audit 2026-10-01).

Per-source extraction audit (docs/HERMES.md sec 8, which explicitly lists
"attorney/trustee" as a required field): live-queried southcarolinaprobate.net's
Charleston Probate grid (search "Smith") and found that every case's gvParties
sub-grid carries BOTH a "PERSONAL REPRESENTATIVE" row AND a distinct "Attorney"
row, each with its own name + full mailing address -- but `_pr_from_parties`
only ever looked at (and returned) one party, so the attorney was dropped.

Live-verified 2026-10-01: a 20-row fetch for Charleston Probate / "Smith" came
back with the attorney's name + address on all 20 rows via the fix below.

This test is offline (no network): a two-row gvParties fixture (PR + Attorney)
mirrors the live DOM shape 1:1 (same header strings, same Type values) and
checks that `_parse_probate` now carries the attorney into `trustee` (this
codebase's standing convention for the attorney/firm handling a case) and into
raw['sc_probate_net']['attorney'], without breaking the existing PR extraction
or the marriage-grid code path (which has no PR/Attorney Type and must keep
its old spouse-fallback behavior).
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc.sc_probate_net import (
    _parse_marriage,
    _parse_probate,
    _pr_from_parties,
)

PARTY_HEADER = (
    "<tr><th>First Name</th><th>Last Name</th><th>Middle Name</th><th>Suffix</th>"
    "<th>Address 1</th><th>Address 2</th><th>City</th><th>State</th><th>Zip</th>"
    "<th>Type</th></tr>"
)


def _party_table(table_id: str, *rows: str) -> str:
    return f'<table id="{table_id}">{PARTY_HEADER}{"".join(rows)}</table>'


def _pr_row(first="NORMAN", last="ANDERSON", a1="21 COVENTRY CLOSE", city="SAVANNAH",
            state="GA", zip_="31411", type_="PERSONAL REPRESENTATIVE") -> str:
    return (f"<tr><td>{first}</td><td>{last}</td><td>C.</td><td>JR.</td>"
            f"<td>{a1}</td><td></td><td>{city}</td><td>{state}</td><td>{zip_}</td>"
            f"<td>{type_}</td></tr>")


def _atty_row(first="EVAN", last="SMITH", a1="656 GATE POST DR", city="MOUNT PLEASANT",
              state="SC", zip_="29464") -> str:
    return (f"<tr><td>{first}</td><td>{last}</td><td>A.</td><td>ESQ.</td>"
            f"<td>{a1}</td><td></td><td>{city}</td><td>{state}</td><td>{zip_}</td>"
            f"<td>Attorney</td></tr>")


def _case_row(case_number="2019ES1001293") -> str:
    return (f"<tr><td></td><td>{case_number}</td><td>ANDERSON, NORMAN CALHOUN</td>"
            f"<td>Attorney: SMITH, EVAN A.</td><td>STANDARD ESTATE TESTATE</td>"
            f"<td>07/25/2019</td><td>Charleston Probate</td><td></td><td></td>"
            f"<td>Closed</td></tr>")


def _page(case_rows: str, party_tables: str) -> str:
    return (
        '<table id="ctl00_ContentPlaceHolder1_cgvCases">'
        '<tr><td></td><td>Case Number</td><td>Case Name</td><td>Party</td>'
        '<td>Type of Case</td><td>Filing Date</td><td>County</td>'
        '<td>Appointment Date</td><td>Creditor Claim Due</td><td>Case Status</td></tr>'
        f"{case_rows}</table>{party_tables}"
    )


def test_pr_from_parties_returns_both_pr_and_attorney():
    table_html = _party_table("t1", _pr_row(), _atty_row())
    from selectolax.parser import HTMLParser
    tree = HTMLParser(table_html)
    pr_name, pr_addr, atty_name, atty_addr = _pr_from_parties(tree.css_first("table"))
    assert pr_name == "NORMAN C. ANDERSON JR."
    assert pr_addr["city"] == "SAVANNAH"
    assert atty_name == "EVAN A. SMITH ESQ."
    assert atty_addr["address1"] == "656 GATE POST DR"
    assert atty_addr["city"] == "MOUNT PLEASANT"


def test_pr_from_parties_attorney_absent_when_no_attorney_row():
    table_html = _party_table("t1", _pr_row())
    from selectolax.parser import HTMLParser
    tree = HTMLParser(table_html)
    pr_name, pr_addr, atty_name, atty_addr = _pr_from_parties(tree.css_first("table"))
    assert pr_name == "NORMAN C. ANDERSON JR."
    assert atty_name is None
    assert atty_addr is None


def test_parse_probate_carries_attorney_into_trustee_and_raw():
    html = _page(
        _case_row(),
        _party_table("ctl00_ContentPlaceHolder1_cgvCases_ctl24_gvParties",
                     _pr_row(), _atty_row()),
    )
    rows = _parse_probate(html, "Charleston", "SC")
    assert len(rows) == 1
    li = rows[0]
    assert li.owner_name == "ANDERSON, NORMAN CALHOUN"
    assert li.defendant == "NORMAN C. ANDERSON JR."       # PR unaffected
    assert li.trustee == "EVAN A. SMITH ESQ."              # NEW: attorney captured
    atty = li.raw["sc_probate_net"]["attorney"]
    assert atty["name"] == "EVAN A. SMITH ESQ."
    assert atty["address1"] == "656 GATE POST DR"
    assert atty["zip"] == "29464"


def test_parse_probate_trustee_is_none_without_an_attorney_row():
    html = _page(
        _case_row(),
        _party_table("ctl00_ContentPlaceHolder1_cgvCases_ctl24_gvParties", _pr_row()),
    )
    rows = _parse_probate(html, "Charleston", "SC")
    assert rows[0].trustee is None
    assert rows[0].raw["sc_probate_net"]["attorney"] is None


def test_parse_marriage_unaffected_by_the_attorney_extension():
    marriage_html = (
        '<table id="ctl00_ContentPlaceHolder1_cgvMarriage">'
        '<tr><td></td><td>License</td><td>Couple</td><td>App Date</td><td>Marriage Date</td></tr>'
        '<tr><td></td><td>202612345</td><td>SMITH/JONES</td><td>01/01/2026</td><td>02/01/2026</td></tr>'
        '</table>'
        + _party_table(
            "ctl00_ContentPlaceHolder1_cgvMarriage_ctl24_gvParties",
            _pr_row(first="JOHN", last="SMITH", type_="GROOM"),
        )
    )
    rows = _parse_marriage(marriage_html, "Charleston", "SC")
    assert len(rows) == 1
    assert rows[0].owner_name == "SMITH/JONES"
    assert rows[0].defendant == "JOHN C. SMITH JR."

"""Darlington's parser must not turn the county's office-hours table into leads.

Found by the adversarial verifier in the 2026-09-10 SC statewide pass, and the chain
is worth recording because it is subtle.

`counties_sc.darlington_delinquent_tax` was added to `main.DATELESS_OK_SOURCES` --
correctly in principle, since a delinquent-tax balance is a standing condition with
no sale date. But `_active_only()` deleting dateless rows had been acting as this
parser's accidental last line of defence, and removing it exposed a latent hazard:

  * the header filter skips only cells containing owner/name/tms/map/#, so "Monday"
    and "Days" pass straight through;
  * the digit test is satisfied by "8:30 a.m. - 5:00 p.m.";
  * `parcel` was allowed to be None and the row was still emitted.

Fed a POPULATED hours table, the parser therefore produced
`defendant='Monday' street_address='8:30 a.m. - 5:00 p.m.'` as a TAX_SALE lead. It
returned zero only because those cells happen to be empty on the live page today.

The fix is at the parser, not by reverting the DATELESS entry: weekday rows are
skipped, and a row with no TMS is dropped because a delinquent-tax lead with no
parcel cannot be underwritten, joined to the assessor, or routed anyway. This engine
has ingested junk before (six rows off /careers/ and /missing-persons/ pages), so a
parser that can emit plausible-looking nonsense is a real defect even when the live
page is currently benign.
"""
from __future__ import annotations

import pytest

from foreclosure_scraper.scrapers.counties_sc.darlington_delinquent_tax import parse_rows

_PAD = "x" * 300  # the parser ignores html shorter than 200 chars


def _table(rows: str) -> str:
    return f"<table>{rows}</table>{_PAD}"


OFFICE_HOURS = _table(
    "<tr><td>Days</td><td>Hours</td></tr>"
    "<tr><td>Monday</td><td>8:30 a.m. - 5:00 p.m.</td></tr>"
    "<tr><td>Tuesday</td><td>8:30 a.m. - 5:00 p.m.</td></tr>"
    "<tr><td>Saturday</td><td>Closed 24/7 843-398-4170</td></tr>"
)

REAL_SALE = _table(
    "<tr><td>Owner</td><td>TMS</td><td>Address</td></tr>"
    "<tr><td>SMITH JOHN</td><td>123-45-67-890</td><td>101 Main St</td></tr>"
    "<tr><td>JONES MARY</td><td>456-78-90-123</td><td>202 Oak Ave</td></tr>"
)


def test_office_hours_table_yields_no_leads():
    """The exact input the verifier used. Must be zero, not 'zero by luck'."""
    assert parse_rows(OFFICE_HOURS) == []


def test_real_tax_sale_rows_still_parse():
    rows = parse_rows(REAL_SALE)
    assert len(rows) == 2
    assert rows[0].defendant == "SMITH JOHN"
    assert rows[0].parcel_id == "123-45-67-890"
    assert rows[0].street_address == "101 Main St"
    assert rows[0].county == "Darlington"
    assert rows[0].state == "SC"


def test_a_row_without_a_tms_is_dropped():
    """No parcel means the lead cannot be underwritten, joined or routed."""
    no_tms = _table(
        "<tr><td>Owner</td><td>Address</td></tr>"
        "<tr><td>SMITH JOHN</td><td>101 Main St</td></tr>"
    )
    assert parse_rows(no_tms) == []


@pytest.mark.parametrize("day", ["Monday", "Friday", "Sunday", "Days", "Hours"])
def test_every_weekday_label_is_skipped(day):
    html = _table(f"<tr><td>{day}</td><td>123-45-67-890 9:00 a.m.</td></tr>")
    assert parse_rows(html) == []


def test_mixed_table_keeps_only_the_real_row():
    """A page carrying both tables must yield exactly the tax-sale row."""
    rows = parse_rows(_table(
        "<tr><td>Monday</td><td>8:30 a.m. - 5:00 p.m.</td></tr>"
        "<tr><td>SMITH JOHN</td><td>123-45-67-890</td><td>101 Main St</td></tr>"
    ))
    assert len(rows) == 1
    assert rows[0].defendant == "SMITH JOHN"


def test_the_dateless_entry_is_present_so_this_guard_is_load_bearing():
    """If someone removes the DATELESS_OK_SOURCES entry, _active_only goes back to
    masking the hazard and these tests stop being the thing protecting the board.
    They should still pass -- but the coupling is worth asserting explicitly."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "src" / "foreclosure_scraper" / "main.py").read_text()
    block = re.search(r"DATELESS_OK_SOURCES\s*=\s*\{(.*?)\n\}", src, re.S).group(1)
    assert "counties_sc.darlington_delinquent_tax" in block

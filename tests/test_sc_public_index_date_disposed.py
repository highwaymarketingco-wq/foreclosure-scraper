"""national.sc_public_index — HERMES extraction-completeness audit, batch 18
(2026-10-04).

FOUND: `_parse_search_results()` already parses a 6th table column,
`date_disposed` (right alongside date_filed/status, same cells[5] read),
off every search-result row -- but `_to_listings()` never read it back out
of the parsed case dict, so it was silently thrown away on every single
case, every run. Fixed: now carried through into
`raw["sc_public_index"]["date_disposed"]` (an existing, already-wildcarded
RAW_KEEP key -- `"sc_public_index": "*"` -- so no new RAW_KEEP entry is
needed).

A disposed-case date is a real, free signal this search table already
carries (a disposed Common Pleas foreclosure case may mean the matter
already concluded, context useful to whoever scores lead freshness
downstream) and costs nothing extra to capture since it was already being
parsed off the same row.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.national.sc_public_index import (
    SCPublicIndexScraper,
    _parse_search_results,
)
from foreclosure_scraper.web_artifact import RAW_KEEP


_RESULTS_TABLE_HTML = """
<html><body>
<table>
<tr><th>Name</th><th>Role</th><th>Case#</th><th>Filed</th><th>Status</th><th>Disposed</th></tr>
<tr><td>Doe, Jane</td><td>Defendant</td><td>2024CP1012345</td><td>01/15/2024</td><td>Disposed</td><td>06/01/2024</td></tr>
<tr><td>Roe, John</td><td>Defendant</td><td>2024CP1067890</td><td>02/20/2024</td><td>Active</td><td></td></tr>
</table>
</body></html>
"""


def test_parse_search_results_captures_date_disposed_column():
    """Sanity check on the already-existing parser -- date_disposed was
    always parsed here, the bug was downstream in _to_listings."""
    rows = _parse_search_results(_RESULTS_TABLE_HTML)
    assert len(rows) == 2
    assert rows[0]["date_disposed"] == "06/01/2024"
    assert rows[1]["date_disposed"] == ""


def test_to_listings_now_carries_date_disposed_through():
    cases = [
        {
            "case_number": "2024CP1012345",
            "_county": "charleston",
            "name": "Doe, Jane",
            "role": "Defendant",
            "date_filed": "01/15/2024",
            "status": "Disposed",
            "date_disposed": "06/01/2024",
        },
    ]
    scraper = SCPublicIndexScraper()
    listings = scraper._to_listings(cases)
    assert len(listings) == 1
    li = listings[0]
    assert li.raw["sc_public_index"]["date_disposed"] == "06/01/2024"
    assert li.raw["sc_public_index"]["status"] == "Disposed"
    assert li.raw["sc_public_index"]["date_filed"] == "01/15/2024"


def test_to_listings_missing_date_disposed_does_not_crash():
    cases = [
        {
            "case_number": "2024CP1067890",
            "_county": "charleston",
            "name": "Roe, John",
            "role": "Defendant",
            "date_filed": "02/20/2024",
            "status": "Active",
            # no date_disposed key at all -- case still active
        },
    ]
    scraper = SCPublicIndexScraper()
    listings = scraper._to_listings(cases)
    assert len(listings) == 1
    assert listings[0].raw["sc_public_index"]["date_disposed"] == ""


def test_sc_public_index_already_wildcarded_in_raw_keep():
    assert RAW_KEEP.get("sc_public_index") == "*"

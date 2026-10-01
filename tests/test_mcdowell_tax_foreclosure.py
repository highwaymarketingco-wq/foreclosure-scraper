"""McDowell County NC tax foreclosures — audited 2026-10-01.

Live finding: the page has THREE separate tables (scheduled sales /
upset-bid-period sales / pending-not-yet-upset-bid foreclosures), each with
its OWN "nothing here" placeholder wording. The old `_PLACEHOLDER_RE` only
matched "NO FORECLOSURE SALES SCHEDULED AT THIS TIME" (table 1's wording),
so table 3's placeholder ("NO PENDING FORECLOSURES AT THIS TIME") leaked
through as a FABRICATED Listing — parcel_id=None, case_number="NO PENDING
FORECLOSURES AT THIS TIME" — exactly the fake-listing "silent success"
failure mode this repo is built to catch. Live `fetch()` went from 2 rows (1
real + 1 fabricated) to 1 (the real upset-bid-period sale only).
"""
from __future__ import annotations

import asyncio

from foreclosure_scraper.scrapers.counties_nc import mcdowell_tax_foreclosure as mod

# The real live HTML shape (3 tables) confirmed 2026-10-01, reconstructed as
# plain HTML so pandas.read_html parses it the same way get_text()'s real
# response would.
_LIVE_HTML = """
<table>
<tr><td>SALE DATE</td><td>SALE TIME</td><td>PARCEL NUMBER</td><td>OPENING BID AMOUNT</td><td>FILE NUMBER</td></tr>
<tr><td>NO FORECLOSURE SALES SCHEDULED AT THIS TIME</td><td>NO FORECLOSURE SALES SCHEDULED AT THIS TIME</td><td>NO FORECLOSURE SALES SCHEDULED AT THIS TIME</td><td>NO FORECLOSURE SALES SCHEDULED AT THIS TIME</td><td>NO FORECLOSURE SALES SCHEDULED AT THIS TIME</td></tr>
</table>
<table>
<tr><td>ORIGINAL SALE DATE</td><td>10-DAY UPSET BID PERIOD ENDS</td><td>PARCEL NUMBER</td><td>HIGHEST BID RECORDED</td><td>FILE NUMBER</td></tr>
<tr><td>08/07/2026</td><td>10/05/2026</td><td>1739-00-31-2535 / 1739-00-21-7533</td><td>$ 18,500.00</td><td>26CV000538-580</td></tr>
</table>
<table>
<tr><td>PARCEL NUMBER</td><td>FILE NUMBER</td><td></td><td></td><td></td></tr>
<tr><td>NO PENDING FORECLOSURES AT THIS TIME</td><td>NO PENDING FORECLOSURES AT THIS TIME</td><td>NO PENDING FORECLOSURES AT THIS TIME</td><td>NO PENDING FORECLOSURES AT THIS TIME</td><td>NO PENDING FORECLOSURES AT THIS TIME</td></tr>
</table>
"""


def _run_fetch(monkeypatch):
    async def fake_get_text(url, impersonate=True, timeout=45.0):
        return _LIVE_HTML

    monkeypatch.setattr(mod, "get_text", fake_get_text)
    return asyncio.run(mod.McDowellTaxForeclosure().fetch())


def test_pending_table_placeholder_is_not_fabricated_into_a_listing(monkeypatch):
    out = _run_fetch(monkeypatch)
    assert all(li.case_number != "NO PENDING FORECLOSURES AT THIS TIME" for li in out)
    assert all(li.parcel_id is not None for li in out)


def test_scheduled_table_placeholder_still_excluded(monkeypatch):
    out = _run_fetch(monkeypatch)
    assert all("NO FORECLOSURE SALES SCHEDULED" not in (li.case_number or "") for li in out)


def test_the_one_real_row_still_parses(monkeypatch):
    out = _run_fetch(monkeypatch)
    assert len(out) == 1
    row = out[0]
    assert row.parcel_id == "1739-00-31-2535"
    assert row.case_number == "26CV000538-580"
    assert row.opening_bid == 18500.0
    assert row.upset_bid_deadline is not None


def test_placeholder_regex_matches_both_known_phrasings():
    assert mod._PLACEHOLDER_RE.search("NO FORECLOSURE SALES SCHEDULED AT THIS TIME")
    assert mod._PLACEHOLDER_RE.search("NO PENDING FORECLOSURES AT THIS TIME")
    assert not mod._PLACEHOLDER_RE.search("1739-00-31-2535 / 1739-00-21-7533")


def test_scraper_registered():
    from foreclosure_scraper.scrapers._registry import all_scrapers
    assert "counties_nc.mcdowell_tax_foreclosure" in {s.slug for s in all_scrapers()}

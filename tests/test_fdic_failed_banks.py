"""fdic_failed_banks.py.

2026-10-01 (batch-5 extraction-completeness audit): the live table has a
7th column (Fund #) the module's own docstring already named but the code
never read, and the Bank Name cell carries a per-bank FDIC detail-page link
that every row discarded in favor of one shared generic source_url (same bug
class as counties_generic.epa_frs_sites, fixed the same day). Both fixed
then.

2026-10-04 (national.* extraction-completeness audit, batch 15): rewritten
for the switch from the paginated HTML table (25-of-578 rows) to the
complete CSV export, PLUS the fix for the fatal scope-gate bug this source
has had since day one -- listing_type REO + no county ever set meant
main._in_scope() silently deleted every row, forever (see
fdic_failed_banks.py's module docstring for the full root-cause). These
tests now cover: CSV parsing (State already abbreviated, date format
%d-%b-%y), county derivation from City via the bankruptcy gazetteer, the
Cert#-keyed best-effort detail-url map, and -- the regression that matters
most -- that main._in_scope() actually admits a row this scraper produces,
both when the gazetteer resolves the county and when it doesn't.
"""
import asyncio
from datetime import datetime, timedelta

from foreclosure_scraper.scrapers.national import fdic_failed_banks as fdic
from foreclosure_scraper.scrapers.national.fdic_failed_banks import (
    FDICFailedBanks,
    _detail_url_map,
    _normalize_state,
)


def test_full_nc_name_normalizes_to_abbreviation():
    assert _normalize_state("North Carolina") == "NC"


def test_full_sc_name_normalizes_to_abbreviation():
    assert _normalize_state("South Carolina") == "SC"


def test_case_insensitive():
    assert _normalize_state("north carolina") == "NC"


def test_already_abbreviated_passes_through():
    assert _normalize_state("NC") == "NC"


def test_unrelated_state_passes_through_unchanged():
    assert _normalize_state("Texas") == "Texas"


def test_empty_or_none_is_safe():
    assert _normalize_state("") == ""
    assert _normalize_state(None) == ""


def _sample_csv(fail_date: str) -> str:
    """Structurally faithful trim of the real CSV export (captured
    2026-10-04): State is already 2-letter, dates are D-Mon-YY, header row
    carries a stray U+FFFD artifact after each column name (harmless, read
    by position not content)."""
    header = "Bank Name�,City�,State�,Cert�,Acquiring Institution�,Closing Date�,Fund"
    rows = [
        header,
        f"The Bank of Asheville,Asheville,NC,34516,First Bank,{fail_date},10330",
        # No Fund column -- must be tolerated. Same recent date so this row
        # isn't incidentally dropped by the (separately-tested) 2-year
        # recency filter.
        f"Some Bank,Townsville,TX,12345,Acquirer Bank,{fail_date},",
    ]
    return "\r\n".join(rows) + "\r\n"


def _sample_detail_html() -> str:
    """One row of the paginated HTML table, carrying the per-bank detail
    link keyed by Cert# (matches the first CSV row's cert 34516)."""
    return f"""
    <!-- {"padding " * 60} -->
    <table>
    <tr><th>Bank Name</th><th>City</th><th>State</th><th>Cert</th>
        <th>Acquiring Institution</th><th>Closing Date</th><th>Fund</th></tr>
    <tr>
      <td><a href="/bank-failures/failed-bank-list/the-bank-of-asheville">The Bank of Asheville</a></td>
      <td>Asheville</td><td>North Carolina</td><td>34516</td>
      <td>First Bank</td><td>January 21, 2011</td><td>10330</td>
    </tr>
    </table>
    """


def test_csv_parsed_with_county_derived_and_detail_url(monkeypatch):
    """End-to-end: CSV gives the row, county comes from City via the
    bankruptcy gazetteer (not from the source table, which has none), and
    the detail-url map (built from a second, best-effort HTML fetch) is
    joined in by Cert#."""
    recent = (datetime.now() - timedelta(days=5)).strftime("%d-%b-%y")

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if url == fdic.CSV_URL:
            return _sample_csv(recent)
        if url == fdic.PAGE_URL:
            return _sample_detail_html()
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(fdic, "get_text", fake_get_text)
    rows = asyncio.run(FDICFailedBanks().fetch())

    by_city = {li.city: li for li in rows}
    assert "Asheville" in by_city
    li = by_city["Asheville"]
    assert li.state == "NC"
    assert li.county == "Buncombe"  # derived from City, not on the source table
    assert li.listing_type.value == "distressed"  # was REO -- see module docstring
    assert li.raw["fund_number"] == "10330"
    assert li.raw["cert_number"] == "34516"
    assert li.source_url == "https://www.fdic.gov/bank-failures/failed-bank-list/the-bank-of-asheville"

    # Second row: no Fund column, a county the gazetteer won't resolve for
    # a non-NC/SC state, and no detail-url match -- all tolerated.
    tx_row = by_city["Townsville"]
    assert tx_row.raw["fund_number"] is None
    assert tx_row.county is None
    assert tx_row.source_url == fdic.PAGE_URL  # no cert match -- generic fallback


def test_detail_url_map_keys_by_cert_not_name():
    """Cert# is the join key specifically so HTML-entity/punctuation drift
    between the CSV's plain bank name and the HTML table's escaped one
    (e.g. '&amp;' vs '&') can never break the join."""
    html = """
    <table><tr>
      <td><a href="/bank-failures/failed-bank-list/metro-bank">Metropolitan Capital Bank &amp; Trust</a></td>
      <td>Chicago</td><td>Illinois</td><td>57488</td>
      <td>First Independence Bank</td><td>January 30, 2026</td><td>10550</td>
    </tr></table>
    """
    m = _detail_url_map(html)
    assert m["57488"] == "https://www.fdic.gov/bank-failures/failed-bank-list/metro-bank"


def test_detail_fetch_failure_does_not_block_csv_data(monkeypatch):
    """The HTML detail-url fetch is best-effort -- its failure must not
    swallow the (authoritative, complete) CSV data."""
    recent = (datetime.now() - timedelta(days=5)).strftime("%d-%b-%y")

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if url == fdic.CSV_URL:
            return _sample_csv(recent)
        raise RuntimeError("simulated HTML fetch failure")

    monkeypatch.setattr(fdic, "get_text", fake_get_text)
    rows = asyncio.run(FDICFailedBanks().fetch())
    assert len(rows) == 2
    assert all(li.source_url == fdic.PAGE_URL for li in rows)


def test_stale_failure_outside_lookback_is_dropped(monkeypatch):
    old_date = (datetime.now() - timedelta(days=800)).strftime("%d-%b-%y")

    async def fake_get_text(url, impersonate=True, timeout=30.0):
        if url == fdic.CSV_URL:
            return _sample_csv(old_date)
        return ""

    monkeypatch.setattr(fdic, "get_text", fake_get_text)
    rows = asyncio.run(FDICFailedBanks().fetch())
    assert rows == []


def test_scope_regression_distressed_row_with_resolved_county_is_admitted():
    """The bug this batch fixed: listing_type REO + county always None meant
    main._in_scope() deleted every row from this source, forever (REO routes
    through the narrow 18-county config.in_scope(), which requires a truthy
    county). Prove the NEW shape (DISTRESSED + a gazetteer-resolved county)
    clears the gate via the ordinary distressed-anywhere-in-NC/SC path, with
    no dependency on the SCOPE_BYPASS_SOURCES entry."""
    from foreclosure_scraper import main
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    li = Listing(
        source="national.fdic_failed_banks",
        source_url=fdic.PAGE_URL,
        listing_type=ListingType.DISTRESSED,
        street_address="The Bank of Asheville",
        city="Asheville",
        county="Buncombe",
        state="NC",
        property_kind=PropertyKind.UNKNOWN,
        raw={"bank_name": "The Bank of Asheville"},
        sale_date=datetime(2011, 1, 21),
    )
    assert main._county_in_scope(li) is True
    assert main._in_scope(li) is True


def test_scope_regression_old_reo_shape_was_never_admitted():
    """Pin down the actual pre-fix failure mode directly: REO type with no
    county fails config.in_scope() (requires a truthy county) regardless of
    any bypass list, confirming the root cause this batch's fix addresses."""
    from foreclosure_scraper import main
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    li_old_shape = Listing(
        source="national.fdic_failed_banks",
        source_url=fdic.PAGE_URL,
        listing_type=ListingType.REO,
        street_address="The Bank of Asheville",
        city="Asheville",
        county=None,  # the FDIC table never carried a county -- the actual old bug
        state="NC",
        property_kind=PropertyKind.UNKNOWN,
        raw={"bank_name": "The Bank of Asheville"},
        sale_date=datetime(2011, 1, 21),
    )
    # REO is a flip type -> _county_in_scope() routes through the narrow
    # config.in_scope(), which returns False immediately for a falsy county.
    assert main._county_in_scope(li_old_shape) is False


def test_scope_regression_unresolved_city_still_admitted_via_bypass():
    """A real historical NC/SC bank-failure city the gazetteer does not
    cover (Pawleys Island) must still ship, tagged state-only, via the
    SCOPE_BYPASS_SOURCES entry added alongside the listing_type fix --
    county resolution gaps in the gazetteer must not reopen the drop bug."""
    from foreclosure_scraper import main
    from foreclosure_scraper.models import Listing, ListingType, PropertyKind

    li = Listing(
        source="national.fdic_failed_banks",
        source_url=fdic.PAGE_URL,
        listing_type=ListingType.DISTRESSED,
        street_address="Plantation Federal Bank",
        city="Pawleys Island",
        county=None,  # genuine gazetteer gap, confirmed live 2026-10-04
        state="SC",
        property_kind=PropertyKind.UNKNOWN,
        raw={"bank_name": "Plantation Federal Bank"},
        sale_date=datetime(2012, 4, 27),
    )
    assert main._in_scope(li) is True

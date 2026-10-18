"""enrichment_gaston_multiyear_tax: Gaston County NC multi-year delinquent-tax history, read
per parcel from gastonnc.devnetwedge.com (tax_lien_devnet.py's own GIS + parcel-page chain,
reused verbatim). No network -- a FakeSite stands in for the live GIS layer + parcel page the
same way test_verification_tax_lien_devnet.py's own FakeSite does.

The REAL_PARCEL_PAGE_102990 fixture below is genuine markup, captured live 2026-10-18 from
https://gastonnc.devnetwedge.com/parcel/view/102990/2026 (board parcel 3535-68-1884, real board
row, source counties_nc.gaston_vacant) -- not reconstructed by hand. Every dollar figure and
year in the assertions against it is read straight off that live page, not invented.
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.verifiers import tax_lien_devnet as dn
from foreclosure_scraper import enrichment_gaston_multiyear_tax as mod
from foreclosure_scraper.enrichment_gaston_multiyear_tax import (
    build_block, enrich_with_gaston_multiyear_tax, _resolve_and_fetch,
)

TODAY = date(2026, 10, 18)

#: Genuine markup, trimmed -- captured live 2026-10-18 off parcel 102990's own page. The
#: "Parcel Number" block and the full "Payment History" table, verbatim; everything else on the
#: real page (Class/Tax Code/owner panels, nav chrome) is cut, same convention
#: test_ustaxdata_tax_search.py uses for its own trimmed-but-real fixtures.
REAL_PARCEL_PAGE_102990 = """
<div class="md:flex">
                    <div class="inner-label md:w-5/12">Parcel Number</div>
                    <div class="md:w-7/12">102990</div>
                </div>
    <div id="PaymentHistory1" class="panel panel-info">
        <div class="panel-body">
            <div class="overflow-auto">
                <table class="table table-bordered show-more">
                    <thead>
                        <tr>
                            <th class="w-1/8">Tax Year</th>
                            <th class="w-1/4">Total Due</th>
                            <th class="w-1/4">Total Paid</th>
                            <th class="w-1/4">Amount Unpaid</th>
                            <th class="w-1/8">Date Paid</th>
                        </tr>
                    </thead>
                    <tbody>
                            <tr class="text-center">
                                <td>2026</td><td>$24.05</td><td>$0.00</td><td>$24.05</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2025</td><td>$30.15</td><td>$0.00</td><td>$30.15</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2024</td><td>$32.32</td><td>$0.00</td><td>$32.32</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2023</td><td>$34.80</td><td>$0.00</td><td>$34.80</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2022</td><td>$49.14</td><td>$0.00</td><td>$49.14</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2021</td><td>$52.86</td><td>$0.00</td><td>$52.86</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2020</td><td>$55.90</td><td>$0.00</td><td>$55.90</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2019</td><td>$59.34</td><td>$0.00</td><td>$59.34</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2018</td><td>$234.83</td><td>$0.00</td><td>$234.83</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2017</td><td>$246.93</td><td>$0.00</td><td>$246.93</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2016</td><td>$0.00</td><td>$0.00</td><td>$0.00</td><td></td>
                            </tr>
                            <tr class="text-center">
                                <td>2009</td><td>$0.00</td><td>$0.00</td><td>$0.00</td><td></td>
                            </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
"""

PIN_102990 = "3535-68-1884"


def _gis_payload(pin: str, pid: str) -> dict:
    return {"features": [{"attributes": {"PIN": pin, "PID": pid, "PHYSSTRADD": "HARTMAN ST"}}]}


def _parcel_page(history: list[tuple[int, float, float]]) -> str:
    """A synthetic Payment History page in the SAME real shape REAL_PARCEL_PAGE_102990 uses,
    for the scenarios no live page was captured for (gaps, current-only, etc). (year, due, paid)
    -- unpaid is due-paid, matching the live page's own arithmetic."""
    rows = "".join(
        f'<tr class="text-center"><td>{y}</td><td>${due:,.2f}</td><td>${paid:,.2f}</td>'
        f'<td>${due - paid:,.2f}</td><td></td></tr>'
        for y, due, paid in history)
    return (f'<div class="md:flex"><div class="inner-label md:w-5/12">Parcel Number</div>'
            f'<div class="md:w-7/12">900001</div></div>'
            f'<div id="PaymentHistory1" class="panel"><table><tbody>{rows}</tbody></table></div>')


class FakeSite:
    """Same shape as test_verification_tax_lien_devnet.py's FakeSite -- a client exposing the
    get_json/get_text pair tax_lien_devnet.lookup_pin/fetch_parcel actually call."""

    def __init__(self, page, *, gis=None, fail=0, portal_down=None):
        self.page, self.fail, self.portal_down = page, fail, portal_down
        self.gis = gis if gis is not None else _gis_payload(PIN_102990, "102990")
        self.asked: list[str] = []

    async def get_json(self, url, **_):
        self.asked.append(url)
        return self.gis

    async def get_text(self, url, **_):
        self.asked.append(url)
        if self.portal_down:
            raise dn.PortalDown(self.portal_down)
        if self.fail:
            self.fail -= 1
            raise RuntimeError("HTTP 503")
        return self.page


def _li(parcel, county="Gaston", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.gaston_vacant", source_url="https://x/1",
                  listing_type=ListingType.DISTRESSED, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_block: pure, real numbers off the live-captured page
# ---------------------------------------------------------------------------

def _real_bills() -> list[dict]:
    parsed = dn.parse_parcel(REAL_PARCEL_PAGE_102990)
    assert parsed is not None and parsed["pid"] == "102990"
    return parsed["bills"]


def test_real_chronic_parcel_qualifies_with_the_live_dollar_figures():
    block = build_block(PIN_102990, _real_bills(), today=TODAY)
    assert block is not None
    assert block["years"] == list(range(2017, 2027))
    assert block["consecutive_years"] == 10
    assert block["total_due"] == block["total_owed"] == 820.32
    assert block["matured_years"] == list(range(2017, 2026))
    assert block["matured_owed"] == 796.27
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["latest_matured_year"] == 2025
    assert block["still_accruing"] is True
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"] == "3535681884"
    # Paid-up years (2016, 2009) must never surface as "unpaid" just for being in the table.
    assert 2016 not in block["years"] and 2009 not in block["years"]


def test_a_gap_year_breaks_the_consecutive_run_not_just_the_year_count():
    """2025 paid, every other year 2017-2024+2026 unpaid -- longest run is 8, not 9 (real board
    parcel 3516-35-2020, live-verified 2026-10-18)."""
    history = [(2026, 21.83, 0.0), (2025, 26.92, 26.92)]  # 2025 PAID -- the gap
    history += [(y, 30.0, 0.0) for y in range(2024, 2016, -1)]  # 2024..2017 unpaid
    block = build_block("3516-35-2020", _parcel_page_bills(history), today=TODAY)
    assert block["years"] == [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2026]
    assert block["consecutive_years"] == 8
    assert 2025 not in block["years"]


def _parcel_page_bills(history: list[tuple[int, float, float]]) -> list[dict]:
    parsed = dn.parse_parcel(_parcel_page(history))
    return parsed["bills"]


def test_below_min_years_does_not_qualify():
    bills = _parcel_page_bills([(2026, 100.0, 0.0)])
    assert build_block("3500-00-0001", bills, today=TODAY) is None


def test_two_unpaid_years_is_the_minimum_qualifying_shape():
    """Real board parcel 3504-98-8203, live-verified 2026-10-18: exactly 2025-2026 unpaid."""
    bills = _parcel_page_bills([(2026, 91.5, 0.0), (2025, 103.51, 0.0)])
    block = build_block("3504-98-8203", bills, today=TODAY)
    assert block["years"] == [2025, 2026]
    assert block["matured_years"] == [2025]
    assert block["total_due"] == 195.01 and block["matured_owed"] == 103.51


def test_unpaid_years_with_none_matured_does_not_qualify():
    """Two years unpaid but BOTH still current (no levy past its delinquent date yet) must not
    be reported as repeat delinquency -- it's two not-yet-due bills, not arrears."""
    bills = _parcel_page_bills([(2026, 50.0, 0.0), (2027, 60.0, 0.0)])
    assert build_block("3500-00-0002", bills, today=TODAY) is None


def test_growing_and_shrinking_trend_compares_earliest_to_latest_matured_year():
    """Each year is its own bill (module docstring): the owner falling further behind every
    cycle is GROWING arrears (earliest matured year owed less than the latest); partly catching
    up is SHRINKING. Row order in the source page must not matter -- only the YEAR does."""
    growing = _parcel_page_bills([(2022, 10.0, 0.0), (2023, 100.0, 0.0), (2024, 200.0, 0.0)])
    assert build_block("3500-00-0003", growing, today=TODAY)["trend"] == "growing"
    # same three years/amounts, rows given newest-first instead of oldest-first.
    shrinking = _parcel_page_bills([(2024, 10.0, 0.0), (2023, 100.0, 0.0), (2022, 200.0, 0.0)])
    assert build_block("3500-00-0004", shrinking, today=TODAY)["trend"] == "shrinking"


def test_parcel_key_is_normalized_like_tax_bindings_own_matching():
    bills = _parcel_page_bills([(2024, 10.0, 0.0), (2023, 10.0, 0.0)])
    assert build_block("3535-68-1884", bills, today=TODAY)["parcel_key"] == "3535681884"


# ---------------------------------------------------------------------------
# _resolve_and_fetch: the live GIS + parcel chain, faked
# ---------------------------------------------------------------------------

def test_resolve_and_fetch_ok_path_reuses_devnet_verbatim():
    site = FakeSite(REAL_PARCEL_PAGE_102990)
    pid, bills, status = run(_resolve_and_fetch(site, PIN_102990, TODAY))
    assert (pid, status) == ("102990", "ok")
    assert bills[0]["year"] == 2026 and bills[0]["unpaid"] == 24.05


def test_resolve_and_fetch_no_gis_match():
    site = FakeSite(REAL_PARCEL_PAGE_102990, gis={"features": []})
    pid, bills, status = run(_resolve_and_fetch(site, PIN_102990, TODAY))
    assert (pid, bills, status) == (None, None, "gis_no_match")


def test_resolve_and_fetch_portal_down_propagates_as_a_reason():
    site = FakeSite(REAL_PARCEL_PAGE_102990, portal_down="3 failures in a row")
    pid, bills, status = run(_resolve_and_fetch(site, PIN_102990, TODAY))
    assert bills is None and status.startswith("portal_unhealthy:")


def test_resolve_and_fetch_a_bad_parcel_page_is_reported_not_raised():
    site = FakeSite("<html>not a parcel page</html>")
    pid, bills, status = run(_resolve_and_fetch(site, PIN_102990, TODAY))
    assert pid == "102990" and bills is None and status.startswith("no_parcel_page:")


# ---------------------------------------------------------------------------
# enrich_with_gaston_multiyear_tax: end to end, eligibility + idempotency + privacy
# ---------------------------------------------------------------------------

def test_only_gaston_nc_rows_with_a_real_pin_are_eligible():
    rows = [
        _li(PIN_102990),                                   # eligible
        _li(PIN_102990, county="Lincoln"),                  # wrong county
        _li(PIN_102990, state="SC"),                         # wrong state
        _li(None),                                          # no parcel
        _li("not-a-pin"),                                   # not a 10-digit PIN
        _li(PIN_102990, raw={"multi_year_delinquent_tax": {"already": True}}),  # already done
        _li(PIN_102990, raw={"_gaston_mydt_checked": "insufficient_history"}),  # already checked
    ]
    stats = run(enrich_with_gaston_multiyear_tax(rows, client=FakeSite(REAL_PARCEL_PAGE_102990)))
    assert stats["eligible"] == 1 and stats["attempted"] == 1 and stats["qualified"] == 1


def test_a_qualifying_row_is_stamped_with_the_shared_signal_key():
    li = _li(PIN_102990)
    stats = run(enrich_with_gaston_multiyear_tax([li], client=FakeSite(REAL_PARCEL_PAGE_102990)))
    assert stats["qualified"] == 1
    block = li.raw["multi_year_delinquent_tax"]
    assert block["total_due"] == 820.32 and block["parcel_key"] == "3535681884"
    assert block["pid"] == "102990"
    assert "_gaston_mydt_checked" not in li.raw
    # Privacy: no owner/payer name is ever read or written by this module.
    assert "owner" not in block and "mailing" not in block


def test_a_resolved_but_non_qualifying_row_gets_the_checked_sentinel_not_the_real_key():
    li = _li(PIN_102990)
    page = _parcel_page([(2026, 10.0, 0.0)])   # one unpaid year only -- below MIN_YEARS
    stats = run(enrich_with_gaston_multiyear_tax([li], client=FakeSite(page)))
    assert stats["qualified"] == 0 and stats["insufficient_history"] == 1
    assert li.raw.get("_gaston_mydt_checked") == "insufficient_history"
    assert "multi_year_delinquent_tax" not in li.raw


def test_an_unresolvable_row_gets_the_checked_sentinel_with_its_real_reason():
    li = _li(PIN_102990)
    stats = run(enrich_with_gaston_multiyear_tax(
        [li], client=FakeSite(REAL_PARCEL_PAGE_102990, gis={"features": []})))
    assert stats["no_gis_match"] == 1
    assert li.raw.get("_gaston_mydt_checked") == "gis_no_match"


def test_the_checked_sentinel_makes_the_next_run_a_no_op():
    """The whole reason this sentinel exists: without it, every run re-fetches the same
    negative parcel forever (web_artifact.RAW_KEEP's own comment on this exact failure mode,
    documented first against enrichment_land_buildability.py)."""
    li = _li(PIN_102990, raw={"_gaston_mydt_checked": "gis_no_match"})
    site = FakeSite(REAL_PARCEL_PAGE_102990)
    stats = run(enrich_with_gaston_multiyear_tax([li], client=site))
    assert stats == {"eligible": 0, "attempted": 0, "qualified": 0, "insufficient_history": 0,
                     "no_gis_match": 0, "no_parcel_page": 0, "fetch_errors": 0,
                     "skipped_cap": 0, "skipped_budget": 0}
    assert site.asked == []   # never even fetched


def test_the_kill_switch_short_circuits_with_no_network_at_all(monkeypatch):
    monkeypatch.setattr(mod, "ENABLED", False)
    li = _li(PIN_102990)
    site = FakeSite(REAL_PARCEL_PAGE_102990)
    stats = run(enrich_with_gaston_multiyear_tax([li], client=site))
    assert stats["eligible"] == 0
    assert site.asked == []


def test_the_per_run_cap_is_respected(monkeypatch):
    monkeypatch.setattr(mod, "MAX_ROWS", 2)
    rows = [_li(PIN_102990) for _ in range(5)]
    stats = run(enrich_with_gaston_multiyear_tax(rows, client=FakeSite(REAL_PARCEL_PAGE_102990)))
    assert stats["eligible"] == 5 and stats["attempted"] == 2 and stats["skipped_cap"] == 3

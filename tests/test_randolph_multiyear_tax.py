"""enrichment_randolph_multiyear_tax: Randolph County NC multi-year delinquent-tax history,
read live via verification/verifiers/tax_lien_pwa.py's own live-proven form/grid chain, reused
verbatim (not re-implemented). Bill fixtures below use the exact dict shape
tax_lien_pwa.parse_grid() produces (year/bill/parcel/owner/address/flags/due).
"""
from __future__ import annotations

import asyncio
from datetime import date

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.verification.fetch import ReplayFetcher, form_key
from foreclosure_scraper.verification.verifiers import tax_lien_pwa as pwa
from foreclosure_scraper import enrichment_randolph_multiyear_tax as mod
from foreclosure_scraper.enrichment_randolph_multiyear_tax import (
    build_block, enrich_with_randolph_multiyear_tax, _fetch,
)

TODAY = date(2026, 10, 18)
PARCEL = "7751357444"

FORM_PAGE = """<html><form>
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="vs1" />
<select name="taxYear"><option value="">ALL</option></select>
<select name="lookupCriterion"><option selected="true" value=""></option>
<option value="Parcel Number">Parcel Number</option></select>
<input name="txtSearchString" type="text" />
</form></html>"""


def _grid(*bills, pages=1):
    """(year, owner, due, addr, flags, parcel) tuples -> a real-shaped dgResults grid page."""
    rows = ""
    for i, (year, owner, due, addr, flags, parcel) in enumerate(bills):
        rows += (f"<tr id='dgResults_r_{i}' level='{i}'><td level=\"{i}_0\"><a href='x'>"
                 f"0001735463-{year}-{year}-0000-00</a></td><td level=\"{i}_1\">&nbsp;</td>"
                 f"<td uV=\"{parcel}\" level=\"{i}_2\"><a href=\"x\">{parcel}</a></td>"
                 f"<td level=\"{i}_3\">{owner}</td><td level=\"{i}_4\">{addr}</td>"
                 f"<td level=\"{i}_5\">{flags}</td>"
                 f"<td uV=\"{due:.2f}\" level=\"{i}_7\">${due:,.2f}</td></tr>")
    return (f'<html><input type="hidden" name="__VIEWSTATE" value="vs2" /> [Page 1 of {pages}] '
            f'<table id="dgResults">{rows}</table></html>')


def _bills_from_grid(html: str, parcel: str = PARCEL) -> list[dict]:
    g = pwa.parse_grid(html)
    return [b for b in g["bills"]]


def _li(parcel=PARCEL, county="Randolph", state="NC", raw=None) -> Listing:
    return Listing(source="counties_nc.nc_tax_lien_ads", source_url="https://x/1",
                  listing_type=ListingType.TAX_LIEN, property_kind=PropertyKind.UNKNOWN,
                  county=county, state=state, parcel_id=parcel, raw=raw or {})


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# build_block -- pure, using the live-shaped dollar figures from recon
# ---------------------------------------------------------------------------

def test_real_shaped_chronic_parcel_qualifies():
    """Real board parcel 7751357444 (TAYLOR, DORETHA GARNER COBLE HEIRS), live-verified
    2026-10-18: unpaid 2023/2024/2025/2026."""
    page = _grid(
        (2026, "TAYLOR, DORETHA GARNER COBLE HEIRS", 168.05, "1 TEST RD", "", PARCEL),
        (2025, "TAYLOR, DORETHA GARNER COBLE HEIRS", 248.02, "1 TEST RD", "DLQ", PARCEL),
        (2024, "TAYLOR, DORETHA GARNER COBLE HEIRS", 203.59, "1 TEST RD", "DLQ", PARCEL),
        (2023, "TAYLOR, DORETHA GARNER COBLE HEIRS", 219.16, "1 TEST RD", "DLQ", PARCEL),
    )
    block = build_block(PARCEL, _bills_from_grid(page), today=TODAY)
    assert block is not None
    assert block["years"] == [2023, 2024, 2025, 2026]
    assert block["matured_years"] == [2023, 2024, 2025]
    assert block["years_delinquent"] == 3
    assert block["total_due"] == round(168.05 + 248.02 + 203.59 + 219.16, 2)
    assert block["matured_owed"] == round(248.02 + 203.59 + 219.16, 2)
    assert block["current_levy_year"] == 2026 and block["in_current_levy"] is True
    assert block["amount_basis"] == "annual_bill"
    assert block["parcel_key"] == PARCEL
    assert "txpwa.randolphcountync.gov" in block["source_url"]


def test_two_matured_years_is_the_minimum_qualifying_shape():
    """Real board parcel 7728633591 (TALBERT, ELANOR J HEIRS), live-verified 2026-10-18:
    unpaid 2024/2025/2026 -- 2 matured years."""
    page = _grid(
        (2026, "TALBERT, ELANOR J HEIRS", 164.61, "2 TEST RD", "", PARCEL),
        (2025, "TALBERT, ELANOR J HEIRS", 184.27, "2 TEST RD", "DLQ", PARCEL),
        (2024, "TALBERT, ELANOR J HEIRS", 196.88, "2 TEST RD", "DLQ", PARCEL),
    )
    block = build_block(PARCEL, _bills_from_grid(page), today=TODAY)
    assert block["years"] == [2024, 2025, 2026]
    assert block["matured_years"] == [2024, 2025]


def test_single_unpaid_year_fails_gate():
    page = _grid((2026, "SOMEONE", 100.0, "3 TEST RD", "", PARCEL))
    assert build_block(PARCEL, _bills_from_grid(page), today=TODAY) is None


def test_two_unpaid_years_both_current_does_not_qualify():
    """Current-year-only bills (no levy past its delinquent date) must not read as repeat
    delinquency -- same guard as Gaston's/PTS-Cloud's own enrichments."""
    page = _grid(
        (2026, "SOMEONE", 50.0, "4 TEST RD", "", PARCEL),
        (2027, "SOMEONE", 60.0, "4 TEST RD", "", PARCEL),
    )
    assert build_block(PARCEL, _bills_from_grid(page), today=TODAY) is None


def test_paid_years_never_surface_as_unpaid():
    page = _grid(
        (2025, "SOMEONE", 0.0, "5 TEST RD", "", PARCEL),
        (2024, "SOMEONE", 30.0, "5 TEST RD", "DLQ", PARCEL),
        (2023, "SOMEONE", 32.0, "5 TEST RD", "DLQ", PARCEL),
    )
    block = build_block(PARCEL, _bills_from_grid(page), today=TODAY)
    assert block["years"] == [2023, 2024]
    assert 2025 not in block["years"]


def test_ignores_bills_on_the_page_for_a_different_parcel():
    """taxYear=ALL by owner/street can in principle return another parcel's row too -- only
    this row's own parcel counts, same safety tax_lien_pwa.verify() already applies."""
    page = _grid(
        (2024, "SOMEONE", 30.0, "6 TEST RD", "DLQ", PARCEL),
        (2023, "SOMEONE", 32.0, "6 TEST RD", "DLQ", PARCEL),
        (2023, "OTHER OWNER", 999.0, "9 OTHER ST", "DLQ", "0000000001"),
    )
    block = build_block(PARCEL, _bills_from_grid(page), today=TODAY)
    assert block["years"] == [2023, 2024]
    assert block["total_due"] == 62.0  # the other parcel's $999 never counted


def test_duplicate_year_keeps_larger_not_sum():
    page = _grid(
        (2024, "SOMEONE", 10.0, "7 TEST RD", "DLQ", PARCEL),
        (2024, "SOMEONE", 40.0, "7 TEST RD", "DLQ", PARCEL),
        (2023, "SOMEONE", 5.0, "7 TEST RD", "DLQ", PARCEL),
    )
    block = build_block(PARCEL, _bills_from_grid(page), today=TODAY)
    assert block["per_year"]["2024"] == 40.0
    assert block["total_due"] == 45.0


# ---------------------------------------------------------------------------
# _fetch / enrich_with_randolph_multiyear_tax -- the live form/grid chain, replayed
# ---------------------------------------------------------------------------

def _replay_fetcher(parcel: str, results_page: str | None):
    portal = pwa.PORTALS["Randolph"]
    resp = {portal.form_url: FORM_PAGE}
    if results_page is not None:
        resp[form_key(portal.post_url, pwa.build_form(FORM_PAGE, parcel))] = results_page
    return ReplayFetcher(resp)


def test_fetch_ok_path_reuses_tax_lien_pwa_verbatim():
    page = _grid((2024, "SOMEONE", 30.0, "8 TEST RD", "DLQ", PARCEL),
                (2023, "SOMEONE", 32.0, "8 TEST RD", "DLQ", PARCEL))
    f = _replay_fetcher(PARCEL, page)
    bills, status = run(_fetch(f, PARCEL))
    assert status == "ok"
    assert {b["year"] for b in bills} == {2023, 2024}


def test_fetch_no_bills():
    f = _replay_fetcher(PARCEL, _grid())
    bills, status = run(_fetch(f, PARCEL))
    assert (bills, status) == (None, "no_bills_on_page")


def test_enrich_eligible_only_randolph_nc_with_parcel():
    eligible = _li()
    wrong_county = _li(county="Wake")
    wrong_state = _li(state="SC", county="Randolph")
    no_parcel = _li(parcel="")
    already = _li(raw={"_randolph_mydt_checked": "insufficient_history"})
    rows = [eligible, wrong_county, wrong_state, no_parcel, already]
    targets = [li for li in rows if mod._eligible(li)]
    assert targets == [eligible]


def test_enrich_end_to_end_qualifies_and_stamps_block():
    page = _grid(
        (2026, "SOMEONE", 100.0, "9 TEST RD", "", PARCEL),
        (2025, "SOMEONE", 50.0, "9 TEST RD", "DLQ", PARCEL),
        (2024, "SOMEONE", 52.0, "9 TEST RD", "DLQ", PARCEL),
    )
    li = _li()
    f = _replay_fetcher(PARCEL, page)
    stats = run(enrich_with_randolph_multiyear_tax([li], client=f))
    assert stats["eligible"] == 1 and stats["qualified"] == 1
    assert li.raw["multi_year_delinquent_tax"]["years"] == [2024, 2025, 2026]
    assert li.raw["multi_year_delinquent_tax"]["matured_years"] == [2024, 2025]


def test_enrich_insufficient_history_stamps_checked_sentinel_not_block():
    page = _grid((2026, "SOMEONE", 100.0, "10 TEST RD", "", PARCEL))
    li = _li()
    f = _replay_fetcher(PARCEL, page)
    stats = run(enrich_with_randolph_multiyear_tax([li], client=f))
    assert stats["qualified"] == 0 and stats["insufficient_history"] == 1
    assert "multi_year_delinquent_tax" not in li.raw
    assert li.raw["_randolph_mydt_checked"] == "insufficient_history"


def test_enrich_does_not_overwrite_existing_block():
    sentinel = {"years": [1999], "manual": True}
    li = _li(raw={"multi_year_delinquent_tax": sentinel})
    f = _replay_fetcher(PARCEL, _grid())
    stats = run(enrich_with_randolph_multiyear_tax([li], client=f))
    assert stats["eligible"] == 0
    assert li.raw["multi_year_delinquent_tax"] is sentinel

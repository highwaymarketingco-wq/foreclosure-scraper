"""years_delinquent = LATE unpaid levy years (tax_calendar), everywhere it is produced.

Owner + attorney rule, 2026-10-07: a current-year bill that is not late yet is not a delinquency.
Hand-made rows only; every name and number here is invented.
"""
from __future__ import annotations

from datetime import date, datetime

from foreclosure_scraper.enrichment_tax_aging import enrich_tax_aging
from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed, tax_year_status, unpaid_levy_years
from foreclosure_scraper.fullmer_rank import years_delinquent as fullmer_years
from foreclosure_scraper.models import Listing, ListingType, PropertyKind

OCT_7 = date(2026, 10, 7)


def _li(source, raw, state="NC", county="Buncombe", parcel="1234-56-7890", lt=ListingType.TAX_LIEN):
    now = datetime(2026, 10, 7)
    return Listing(source=source, source_url="https://x.invalid/1", listing_type=lt,
                   property_kind=PropertyKind.UNKNOWN, state=state, county=county,
                   parcel_id=parcel, first_seen=now, last_seen=now, raw=raw)


def _myd(years, per_year):
    """A multi_year_delinquent_tax block the way the scraper writes it (years incl. the current
    levy, years_delinquent = len(years) on boards scraped before the fix)."""
    return {"years": years, "years_delinquent": len(years), "per_year": per_year,
            "total_due": sum(per_year.values()), "year": years[-1], "parcel_key": "1234567890"}


def test_current_levy_is_not_counted():
    li = _li("counties_generic.arcgis_distress.buncombe_unpaid_bills",
             {"multi_year_delinquent_tax": _myd([2025, 2026], {"2025": 4400.0, "2026": 4800.0})})
    enrich_tax_owed([li], today=OCT_7)
    enrich_tax_aging([li], today=OCT_7)
    to = li.raw["tax_owed"]
    assert to["balance"] == 9200.0
    assert to["years_delinquent"] == 1 and to["unpaid_bill_years"] == 2
    assert to["not_yet_late_years"] == [2026]
    assert to["not_yet_late_amount"] == 4800.0          # the part of the balance not late yet
    surf = li.raw["tax_aging_surfaced"]
    assert surf["years_delinquent"] == 1 and surf["basis"] == "year_list"
    assert surf["status"] == "delinquent"
    assert li.raw["tax_aging_high"] is False


def test_three_unpaid_bills_are_two_years_late():
    li = _li("counties.multi_year_delinquent_tax",
             {"multi_year_delinquent_tax": _myd([2024, 2025, 2026],
                                                {"2024": 900.0, "2025": 950.0, "2026": 990.0})})
    enrich_tax_owed([li], today=OCT_7)
    enrich_tax_aging([li], today=OCT_7)
    assert li.raw["tax_owed"]["years_delinquent"] == 2
    assert li.raw["tax_aging_surfaced"]["years_delinquent"] == 2
    assert li.raw["tax_aging_high"] is True


def test_the_count_moves_on_the_delinquent_date():
    raw = {"multi_year_delinquent_tax": _myd([2025, 2026], {"2025": 100.0, "2026": 100.0})}
    assert tax_year_status(raw, "NC", "Buncombe", date(2027, 1, 5))["years_delinquent"] == 1
    assert tax_year_status(raw, "NC", "Buncombe", date(2027, 1, 6))["years_delinquent"] == 2
    sc = {"qpaybill_roll": {"balance_owed": 300.0, "years_unpaid": ["2025"],
                            "all_unpaid_years": ["2025", "2026"]}}
    assert tax_year_status(sc, "SC", "Pickens", date(2027, 1, 15))["years_delinquent"] == 1
    assert tax_year_status(sc, "SC", "Pickens", date(2027, 1, 16))["years_delinquent"] == 2


def test_qpaybill_current_year_is_listed_but_not_counted():
    raw = {"qpaybill_roll": {"balance_owed": 2500.0, "years_unpaid": ["2024", "2025"],
                             "all_unpaid_years": ["2024", "2025", "2026"], "years_delinquent": 2}}
    st = tax_year_status(raw, "SC", "Oconee", OCT_7)
    assert st["years_delinquent"] == 2 and st["unpaid_bill_years"] == 3
    assert st["not_yet_late_years"] == [2026]
    assert "not_yet_late_amount" not in st          # the roll states no per-year amounts


def test_single_current_year_is_zero_years():
    li = _li("counties_nc.nc_ptscloud_delinquent_tax",
             {"nc_ptscloud_delinquent_tax": {"principal_tax_due": 812.0, "tax_year": "2026"}},
             county="Lincoln")
    enrich_tax_owed([li], today=OCT_7)
    enrich_tax_aging([li], today=OCT_7)
    surf = li.raw["tax_aging_surfaced"]
    assert surf["years_delinquent"] == 0
    assert surf["status"] == "not_yet_late"
    assert surf["not_yet_late_years"] == [2026]
    yrs, two_plus = fullmer_years(li)
    assert not yrs and two_plus is False          # no ripeness, early or ripe


def test_single_past_year_counts_the_years_since():
    st = tax_year_status({"tax_owed": {"balance": 50.0, "year": 2020}}, "SC", "York", OCT_7)
    assert st["basis"] == "single_year" and st["years_delinquent"] == 6
    # a bill still inside its January grace window is not a year yet
    st = tax_year_status({"tax_owed": {"balance": 50.0, "year": 2025}}, "NC", "Wake", date(2026, 1, 5))
    assert st["years_delinquent"] == 0 and st["not_yet_late_years"] == [2025]


def test_a_stated_count_loses_the_current_year_once_and_only_once():
    """A row whose source block is gone keeps an older run's count; the newest year (current)
    comes off it, and re-running does not take it off again."""
    li = _li("counties_nc.buncombe_tax",
             {"tax_owed": {"balance": 3000.0, "kind": "delinquent_tax", "year": 2026,
                           "years_delinquent": 3, "basis": "own_record"},
              "buncombe_tax": {"tax_due": 3000.0}})
    enrich_tax_owed([li], today=OCT_7)
    assert li.raw["tax_owed"]["years_delinquent"] == 2
    assert li.raw["tax_owed"]["unpaid_bill_years"] == 3
    enrich_tax_owed([li], today=OCT_7)
    assert li.raw["tax_owed"]["years_delinquent"] == 2
    enrich_tax_owed([li], today=date(2027, 2, 1))     # the 2026 bill is late now
    assert li.raw["tax_owed"]["years_delinquent"] == 3


def test_cross_referenced_row_carries_the_late_count():
    roll = _li("counties.multi_year_delinquent_tax",
               {"multi_year_delinquent_tax": _myd([2025, 2026], {"2025": 10.0, "2026": 10.0})})
    court = _li("counties_nc.some_court_source", {}, lt=ListingType.LIS_PENDENS)
    enrich_tax_owed([roll, court], today=OCT_7)
    assert court.raw["tax_owed"]["basis"] == "parcel_cross_ref"
    assert court.raw["tax_owed"]["years_delinquent"] == 1
    st = tax_year_status(court.raw, "NC", "Buncombe", OCT_7)
    assert st["years_delinquent"] == 1 and st["not_yet_late_years"] == [2026]


def test_year_lists_only_from_tax_source_blocks():
    raw = {"lexington_assessment": {"years": [2026]},           # an assessment, not a bill
           "catalis_roll": {"years": [2023, 2026]},
           "tax_aging_surfaced": {"years": [2019]},
           "multi_year_delinquent_tax": {"years": ["2024"]}}
    assert unpaid_levy_years(raw) == [2023, 2026]          # the live roll beats a list history
    del raw["catalis_roll"]
    assert unpaid_levy_years(raw) == [2024]


def test_a_qpaybill_block_merged_from_two_reads_keeps_its_balance_years():
    # all_unpaid_years is a superset of years_unpaid in one read; here it is not
    raw = {"qpaybill_roll": {"balance_owed": 300.0, "years_unpaid": ["2025"],
                             "all_unpaid_years": ["2018", "2019", "2020"]}}
    assert unpaid_levy_years(raw) == [2025]
    raw["qpaybill_roll"]["all_unpaid_years"] = ["2019", "2026"]
    assert unpaid_levy_years(raw) == [2025, 2026]


def test_live_roll_beats_an_advertised_list_history():
    raw = {"multi_year_delinquent_tax": {"years": [2015, 2023]},   # years the parcel was advertised
           "qpaybill_roll": {"years_unpaid": ["2025"], "balance_owed": 236.0}}
    assert tax_year_status(raw, "SC", "Oconee", OCT_7)["years_delinquent"] == 1


def test_fullmer_ignores_a_scraper_two_year_flag_that_counted_the_current_bill():
    # a roll scraper's flag: len(unpaid years) >= 2, here 2025 + the current 2026 bill
    li = _li("counties_sc.sc_catalis_delinquent_roll",
             {"catalis_roll": {"years": [2025, 2026], "total_due": 4100.0,
                               "bills": [{"year": 2025, "total_due": 2000.0},
                                         {"year": 2026, "total_due": 2100.0}]},
              "two_year_delinquent": {"is_two_year_plus": True, "years": 2}},
             state="SC", county="Chester")
    enrich_tax_owed([li], today=OCT_7)
    enrich_tax_aging([li], today=OCT_7)
    assert li.raw["tax_owed"]["not_yet_late_amount"] == 2100.0
    yrs, two_plus = fullmer_years(li)
    assert yrs == 1 and two_plus is False


def test_fullmer_keeps_a_two_year_flag_with_no_year_list():
    li = _li("x.some_source", {"two_year_delinquent": {"is_two_year_plus": True},
                               "tax_aging_surfaced": {"years_delinquent": 1, "source": "tax_owed",
                                                      "basis": "single_year"}})
    assert fullmer_years(li) == (1.0, True)


def test_scraper_counts_only_late_years():
    """multi_year_delinquent_tax.build_listing: the current levy stays in `years` and in the raw
    count, not in years_delinquent (2099 is never late in a test run)."""
    from foreclosure_scraper.scrapers.counties_generic import multi_year_delinquent_tax as myd
    obs = [myd._Obs(year=2025, amount=10.0), myd._Obs(year=2099, amount=11.0)]
    b = myd.build_listing("NC", "Buncombe", "P1", obs, "https://x.invalid", 2099).raw[
        "multi_year_delinquent_tax"]
    assert b["years"] == [2025, 2099]
    assert b["years_delinquent"] == 1 and b["unpaid_bill_years"] == 2


def test_qpaybill_january_grace_window():
    from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import _delinquent_years
    assert _delinquent_years(["2025", "2026"], date(2027, 1, 10)) == ["2025"]
    assert _delinquent_years(["2025", "2026"], date(2027, 1, 16)) == ["2025", "2026"]

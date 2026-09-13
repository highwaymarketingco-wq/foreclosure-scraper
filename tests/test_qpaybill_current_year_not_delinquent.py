"""THE BUG THIS PINS. SC bills a tax year in the autumn; it falls due 15 January of
the FOLLOWING year. So an unpaid bill for tax year Y is not a delinquency until Y+1.

Colleton's portal had the 2026 year loaded when the county was first harvested on
2026-09-13: 18,199 of its 18,289 parcels carried a 2026 unpaid year and 16,790
carried NOTHING ELSE, at a median balance of $504 — an ordinary annual tax bill.
Every other county in the same sweep reported ~0 rows for 2026.

Ingesting that would have put ~16,790 people on a distressed-property board for not
paying a bill that was not yet due, and made Colleton the largest "distressed"
county in the dataset. Caught by asking why one county returned 60% of its parcels.
"""
from datetime import date

from foreclosure_scraper.scrapers.counties_sc.qpaybill_delinquent_roll import (
    _delinquent_years,
)

SEP_2026 = date(2026, 9, 13)


def test_the_current_tax_year_is_not_delinquent():
    assert _delinquent_years(["2026"], SEP_2026) == []


def test_a_real_arrear_alongside_the_current_year_survives():
    # The 2025 bill IS past due; the 2026 one is not. Keeping the row but dropping
    # the not-yet-due year is the point — this is a genuine lead.
    assert _delinquent_years(["2025", "2026"], SEP_2026) == ["2025"]


def test_prior_years_are_delinquent():
    assert _delinquent_years(["2025"], SEP_2026) == ["2025"]
    assert _delinquent_years(["2015", "2024"], SEP_2026) == ["2015", "2024"]


def test_the_january_boundary_errs_toward_silence():
    # In February 2026 the 2025 bill became delinquent on 15 January.
    assert _delinquent_years(["2025"], date(2026, 2, 1)) == ["2025"]
    # And the 2026 bill still is not.
    assert _delinquent_years(["2026"], date(2026, 2, 1)) == []


def test_unparseable_years_are_dropped_not_assumed_delinquent():
    assert _delinquent_years(["bad", "2024"], SEP_2026) == ["2024"]
    assert _delinquent_years([], SEP_2026) == []

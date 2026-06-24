"""Spartan Weekly legal-notice parser — defendant + sale-date extraction.

Patterns are pinned to the real SC Master-in-Equity caption formats observed
live on spartanweeklyonline.com (captured 2026-06-24), so the regex tightening
that lifted the live hit rate (defendant 3/8 -> 6/8, sale-date 1/8 -> 6/8) can't
silently regress.
"""
from __future__ import annotations

from foreclosure_scraper.scrapers.counties_sc import spartan_weekly_legals as sw


# ---- defendant caption variants ----

def test_defendant_handles_vs_with_and():
    body = ("...in the case of Rodger C. Jarrell Real Estate & Mortgages, Inc. v. "
            "Gurdip S. Ghataora and Jaspal K. Ghataora, I, the undersigned as Master...")
    assert sw._defendant(body, "foreclosure") == "Gurdip S. Ghataora and Jaspal K. Ghataora"


def test_defendant_stops_before_etal_on_semicolon_list():
    body = "...in the case of NewRez LLC vs. Nitikki Miller; et.al., I, the undersigned..."
    assert sw._defendant(body, "foreclosure") == "Nitikki Miller"


def test_defendant_keeps_multiple_semicolon_parties():
    body = ("...South Carolina Federal Credit Union vs. Mihail Chiosac; Elena Chiosac; "
            "et.al., I, the undersigned will sell...")
    assert sw._defendant(body, "foreclosure") == "Mihail Chiosac; Elena Chiosac"


def test_defendant_handles_against_and_master_terminator():
    body = ("...case of South Carolina State Housing Finance and Development Authority "
            "against Lori M. Martin et al., I, the Master in Equity for Spartanburg County, will sell...")
    assert sw._defendant(body, "foreclosure") == "Lori M. Martin"


# ---- sale-date variants ----

def test_saledate_skips_weekday_prefix():
    m = sw._SALEDATE_RE.search("will sell on Monday, July 6, 2026 at 11:00 AM, at the County Judicial Center")
    assert m and m.group(1) == "July 6, 2026"


def test_saledate_plain_no_weekday():
    m = sw._SALEDATE_RE.search("will sell on July 6, 2026 at 11:00 AM at Spartanburg County Court House")
    assert m and m.group(1) == "July 6, 2026"


def test_saledate_ignores_unrelated_dates():
    # A published-on date elsewhere in the body must not be mistaken for the sale date.
    assert sw._SALEDATE_RE.search("Published June 18, 2026. The property is located at 12 Main St.") is None

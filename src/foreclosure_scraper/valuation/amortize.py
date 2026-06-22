"""Estimate a mortgage's CURRENT balance from its original principal + date.

Owner equity = ARV − mortgage payoff − junior liens. The payoff is rarely
published, but the original loan (a recorded Deed of Trust 'amount', or a proxy
from the last arms-length sale price) plus the recording date lets us amortize a
standard 30-yr fixed note to an estimated current balance. Free, pure-Python.

When the note rate is unknown we use the Freddie Mac PMMS annual-average 30-yr
fixed rate for the recording year (public reference) — good enough for an equity
estimate, and the result is labeled an estimate with its confidence.
"""
from __future__ import annotations

from datetime import date, datetime

# Freddie Mac PMMS annual-average 30-yr fixed mortgage rate (public, free).
_AVG_30YR: dict[int, float] = {
    2000: 0.0805, 2001: 0.0697, 2002: 0.0654, 2003: 0.0583, 2004: 0.0584,
    2005: 0.0587, 2006: 0.0641, 2007: 0.0634, 2008: 0.0603, 2009: 0.0504,
    2010: 0.0469, 2011: 0.0445, 2012: 0.0366, 2013: 0.0398, 2014: 0.0417,
    2015: 0.0385, 2016: 0.0365, 2017: 0.0399, 2018: 0.0454, 2019: 0.0394,
    2020: 0.0311, 2021: 0.0299, 2022: 0.0534, 2023: 0.0680, 2024: 0.0672,
    2025: 0.0660, 2026: 0.0650,
}
_DEFAULT_RATE = 0.065


def rate_for_year(year: int | None) -> float:
    if year is None:
        return _DEFAULT_RATE
    if year in _AVG_30YR:
        return _AVG_30YR[year]
    return 0.075 if year < 2000 else _DEFAULT_RATE


def _as_date(d) -> date | None:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str) and d.strip():
        s = d.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%Y%m", "%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def amortized_balance(orig_principal: float | None, recorded_date,
                      *, rate: float | None = None, term_years: int = 30,
                      as_of: date | None = None) -> float | None:
    """Remaining principal on a fully-amortizing fixed loan. None if inputs bad.

    bal = P · ((1+r)^N − (1+r)^n) / ((1+r)^N − 1)   where r = monthly rate,
    N = total payments, n = payments made.
    """
    if not orig_principal or orig_principal <= 0:
        return None
    rd = _as_date(recorded_date)
    if rd is None:
        return None
    today = as_of or date.today()
    n_total = term_years * 12
    n_paid = months_between(rd, today)
    if n_paid <= 0:
        return float(orig_principal)
    if n_paid >= n_total:
        return 0.0
    r = (rate if rate is not None else rate_for_year(rd.year)) / 12.0
    if r <= 0:
        return round(orig_principal * (1 - n_paid / n_total), 2)
    f = 1.0 + r
    bal = orig_principal * ((f ** n_total - f ** n_paid) / (f ** n_total - 1.0))
    return round(max(0.0, bal), 2)

"""Estimate a mortgage's CURRENT balance from its original principal + date.

Owner equity = ARV − mortgage payoff − junior liens. The payoff is rarely
published, but the original loan (a recorded Deed of Trust 'amount', or a proxy
from the last arms-length sale price) plus the recording date lets us amortize a
standard 30-yr fixed note to an estimated current balance. Free, pure-Python.

When the note rate is unknown we use the Freddie Mac PMMS annual-average 30-yr
fixed rate for the recording year (public reference) — good enough for an equity
estimate, and the result is labeled an estimate with its confidence.

IT IS AN ESTIMATE, NOT A PAYOFF. A true payoff figure is borrower-only: TILA /
RESPA (12 CFR 1026.36(c)(3)) obligate the servicer to give a payoff statement to
the CONSUMER or their authorized agent, and there is no public feed of it. What
we compute here is a modeled remaining principal from public inputs, and it
ignores everything a real payoff includes — escrow, arrears, fees, PMI, an ARM
or interest-only or balloon structure, extra principal payments, refinances,
HELOC draws and modifications. `estimate_current_balance` therefore returns the
number WITH `is_estimate: True` and an explicit confidence, and every caller is
expected to surface it as "estimated balance", never as a payoff.
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


def rate_for_month(year: int | None, month: int | None = None) -> tuple[float, str]:
    """(rate, source) for a note recorded in `year`/`month`.

    The PMMS series above is the published ANNUAL AVERAGE, so a note recorded in
    January is closer to the prior year's average than to its own. Interpolate
    linearly between adjacent annual averages anchored at each year's midpoint
    (July 1) to get a month-resolved rate; that is materially better than the
    flat annual step across a year like 2022 (3.1% -> 6.4% within 12 months)
    while adding no new data source. Falls back to the annual value whenever a
    neighbouring year is outside the table.

    `source` is one of "pmms_annual" / "pmms_month_interpolated" / "default" so
    the caller can degrade confidence honestly.
    """
    if year is None:
        return _DEFAULT_RATE, "default"
    base = rate_for_year(year)
    if year not in _AVG_30YR:
        return base, "default"
    if not month or not (1 <= int(month) <= 12):
        return base, "pmms_annual"
    month = int(month)
    # Anchor each annual average at mid-year; blend toward the adjacent year.
    offset = (month - 7) / 12.0          # -0.5 (Jan) .. +0.417 (Dec)
    neighbour_year = year - 1 if offset < 0 else year + 1
    if neighbour_year not in _AVG_30YR:
        return base, "pmms_annual"
    w = abs(offset)
    return round(base * (1 - w) + _AVG_30YR[neighbour_year] * w, 6), "pmms_month_interpolated"


def _as_date(d) -> date | None:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    # ArcGIS frequently returns dates as epoch-milliseconds (int, float, or a
    # numeric string after str()). A bare 13-digit value never matched any
    # strptime format below, so it silently fell through to None and killed
    # the last-sale equity path. Parse it explicitly.
    if isinstance(d, (int, float)) and not isinstance(d, bool):
        try:
            return datetime.fromtimestamp(float(d) / 1000.0).date()
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(d, str) and d.strip():
        s = d.strip()
        digits = s[1:] if s.startswith("-") else s
        if digits.isdigit() and len(digits) >= 12:  # epoch-ms (~2001+)
            try:
                return datetime.fromtimestamp(float(s) / 1000.0).date()
            except (ValueError, OverflowError, OSError):
                return None
        # ISO 8601 DATETIME — '2023-02-21T00:00:00' (± timezone). This is what
        # rod/models.RodDoc.to_dict() and every ROD enricher emit via
        # .isoformat(), and it matched NONE of the strptime formats below, so
        # the whole recorded-Deed-of-Trust payoff path silently died for every
        # ROD-sourced document and fell through to the opening-bid proxy.
        # Live-caught 2026-08-04: 22 board rows carried a recorded principal
        # with a valid date and produced 0 recorded_deed_of_trust payoffs.
        if "T" in s or "+" in s[10:]:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            except ValueError:
                pass
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
    r = (rate if rate is not None else rate_for_month(rd.year, rd.month)[0]) / 12.0
    if r <= 0:
        return round(orig_principal * (1 - n_paid / n_total), 2)
    f = 1.0 + r
    bal = orig_principal * ((f ** n_total - f ** n_paid) / (f ** n_total - 1.0))
    return round(max(0.0, bal), 2)


# --- labelled estimate ------------------------------------------------------
#: Beyond this many months of assumed paydown the model has drifted far from any
#: real note (refis, HELOCs, modifications all intervene), so confidence drops.
_STALE_MONTHS = 15 * 12


def estimate_current_balance(orig_principal: float | None, recorded_date, *,
                             rate: float | None = None, term_years: int = 30,
                             as_of: date | None = None,
                             basis: str = "recorded_principal") -> dict | None:
    """Modeled remaining principal, LABELLED as an estimate. None if unusable.

    Returns::

        {"estimated_balance": 148230.11, "is_estimate": True,
         "method": "amortized_30yr_fixed", "basis": "recorded_principal",
         "original_principal": 165000.0, "recorded_date": "2019-04-12",
         "rate_used": 0.0402, "rate_source": "pmms_month_interpolated",
         "term_years": 30, "months_paid": 87, "as_of": "2026-08-04",
         "confidence": "medium",
         "disclaimer": "estimated balance, not a payoff — ..."}

    Confidence ladder (deliberately never "high" — see the module docstring):
      * medium — PMMS rate resolved for the recording month AND the note is
        younger than 15 years, i.e. the amortization assumption is still close.
      * low    — the rate had to be defaulted (recording year outside the PMMS
        table), the note is 15+ years old, or the basis is a proxy rather than a
        recorded principal.
    """
    bal = amortized_balance(orig_principal, recorded_date, rate=rate,
                            term_years=term_years, as_of=as_of)
    if bal is None:
        return None
    rd = _as_date(recorded_date)
    today = as_of or date.today()
    n_paid = months_between(rd, today) if rd else 0
    if rate is not None:
        rate_used, rate_source = float(rate), "caller_supplied"
    else:
        rate_used, rate_source = rate_for_month(rd.year if rd else None,
                                                rd.month if rd else None)
    conf = "medium"
    if rate_source == "default" or n_paid >= _STALE_MONTHS or basis != "recorded_principal":
        conf = "low"
    return {
        "estimated_balance": bal,
        "is_estimate": True,
        "method": f"amortized_{term_years}yr_fixed",
        "basis": basis,
        "original_principal": float(orig_principal) if orig_principal else None,
        "recorded_date": rd.isoformat() if rd else None,
        "rate_used": rate_used,
        "rate_source": rate_source,
        "term_years": term_years,
        "months_paid": n_paid,
        "as_of": today.isoformat(),
        "confidence": conf,
        "disclaimer": ("estimated balance from the recorded original principal — "
                       "NOT a payoff; a true payoff is borrower-only under "
                       "TILA/RESPA and excludes escrow, arrears and fees"),
    }

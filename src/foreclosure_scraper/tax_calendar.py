"""When an unpaid county property-tax bill is LATE. Pure: no I/O, and no clock unless `today` is
left out.

THE RULE (owner and attorney, 2026-10-07; Logan Fullmer's buy-box ripeness counts the same
thing, fullmer_rank.DELINQ_RIPE_*): a current-year bill that is not yet late is not a
delinquency. The years that count are the levy years whose delinquent date has passed and that
are still unpaid. A board row that shows "unpaid 2025 and 2026" in October 2026 is ONE year
delinquent, not two, and a row whose only unpaid bill is the 2026 one is not delinquent at all.

STATE DEFAULTS (the first day a levy-year Y bill is delinquent)
  NC  January 6 of Y+1. The bill is due September 1 of Y and payable at par through January 5
      of Y+1; interest attaches from January 6 (G.S. 105-360(a)). The same date the NC
      verifiers use (verification/verifiers/tax_lien_buncombe.delinquent_after,
      tax_lien_ptscloud.delinquent_from) and quiet_title/taxyears.interest_date. No weekend
      roll, as in those verifiers.
  SC  The day after January 15 of Y+1. Real-property tax for levy year Y is due by January 15
      of Y+1 (S.C. Code 12-45-70) and the first penalty attaches after it (12-45-180). A
      deadline that falls on a weekend moves to the Monday, the rule the SC verifier applies
      (verification/verifiers/tax_lien_qpaybill.deadline, _tax_common.next_weekday). So January
      16 in most years, January 18 when the 15th is a Saturday (2028, 2033).
  any other state: no rule is on file, so the later of the two (SC's) is used. A bill is never
      called late earlier than either known state would call it.

COUNTY_RULES carries a county whose date was checked against the county's own records, each with
its evidence. None checked so far differs from its state default; an entry that did would change
the date for that county only. Add a county only with evidence (the statute, a county page, or a
county record the repo already reads), never by assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from .verification.verifiers._tax_common import next_weekday


@dataclass(frozen=True)
class DueRule:
    """The last day a levy-year Y bill is paid on time, as (month, day) of Y+1, and whether a last
    day on a Saturday or Sunday moves to the Monday. The bill is delinquent from the next day."""
    last_on_time: tuple[int, int]
    weekend_roll: bool
    evidence: str


STATE_RULES: dict[str, DueRule] = {
    "NC": DueRule((1, 5), False,
                  "G.S. 105-360(a): due Sept 1 of the levy year, payable at par through Jan 5 of "
                  "the next year, interest from Jan 6"),
    "SC": DueRule((1, 15), True,
                  "S.C. Code 12-45-70 (due by Jan 15 of the next year) and 12-45-180 (penalty "
                  "after it); weekend deadline moved to Monday as tax_lien_qpaybill.deadline does"),
}

#: Used for a state with no rule on file: the later of the known state rules (see module doc).
FALLBACK_RULE = DueRule((1, 15), True, "no state rule on file: the latest known state rule (SC)")

#: (state, county) -> the county's rule, with the evidence it was checked against.
COUNTY_RULES: dict[tuple[str, str], DueRule] = {
    ("NC", "Buncombe"): DueRule(
        (1, 5), False,
        "tax.buncombenc.gov Bill Details pages charge interest from Jan 6 of the next year "
        "(the interest-date check in verification/verifiers/tax_lien_buncombe.py, G.S. "
        "105-360)"),
    ("NC", "Rutherford"): DueRule(
        (1, 5), False,
        "every Rutherford bill record carries BillInterest.BeginDate = Jan 6 of the next year "
        "(scrapers/counties_nc/rutherford_wildfire_tax.py)"),
    ("SC", "Union"): DueRule(
        (1, 15), True,
        "Union County delinquent-tax procedures (gearupunionsc.com taxprocedures.pdf, recorded "
        "in docs/enumeration_r3/r3_Union.md): 3% penalty after Jan 15, 10% after Feb 1, then "
        "Mar 16"),
}

_YEAR_MIN, _YEAR_MAX = 1990, 2100


def _county_key(county: Optional[str]) -> str:
    return (county or "").replace(" County", "").strip().title()


def rule_for(state: Optional[str], county: Optional[str] = None) -> DueRule:
    """The county's own rule when one is on file, else the state's, else FALLBACK_RULE."""
    st = (state or "").strip().upper()
    return (COUNTY_RULES.get((st, _county_key(county)))
            or STATE_RULES.get(st)
            or FALLBACK_RULE)


def delinquent_after(year: int, state: Optional[str], county: Optional[str] = None) -> date:
    """The first day the levy-year `year` bill is delinquent (late) if still unpaid."""
    r = rule_for(state, county)
    last = date(int(year) + 1, *r.last_on_time)
    if r.weekend_roll:
        last = next_weekday(last)
    return last + timedelta(days=1)


def levy_year_is_delinquent(year: int, state: Optional[str], county: Optional[str] = None,
                            today: Optional[date] = None) -> bool:
    """True once the levy-year bill's delinquent date has come (an unpaid bill is late)."""
    return (today or date.today()) >= delinquent_after(year, state, county)


def levy_year(value) -> Optional[int]:
    """A levy year read from an int, a "2025" string, a "2025-2026" span (its first year) or a
    "2025-..." bill number prefix; None when there is none in range."""
    if value is None or isinstance(value, bool):
        return None
    try:
        y = int(str(value).strip()[:4])
    except ValueError:
        return None
    return y if _YEAR_MIN <= y <= _YEAR_MAX else None


def _years(unpaid_years: Iterable) -> list[int]:
    return sorted({y for y in (levy_year(v) for v in (unpaid_years or ())) if y is not None})


def completed_delinquent_years(unpaid_years: Iterable, state: Optional[str],
                               county: Optional[str] = None,
                               today: Optional[date] = None) -> list[int]:
    """The unpaid levy years whose delinquent date has passed, oldest first. Their count is the
    number of years delinquent. Unreadable or out-of-range years are ignored."""
    return [y for y in _years(unpaid_years) if levy_year_is_delinquent(y, state, county, today)]


def not_yet_late_years(unpaid_years: Iterable, state: Optional[str],
                       county: Optional[str] = None, today: Optional[date] = None) -> list[int]:
    """The unpaid levy years that are not late yet (the current bill), oldest first."""
    return [y for y in _years(unpaid_years) if not levy_year_is_delinquent(y, state, county, today)]


def latest_delinquent_levy_year(state: Optional[str], county: Optional[str] = None,
                                today: Optional[date] = None) -> int:
    """The newest levy year whose bill can be late on `today`."""
    today = today or date.today()
    y = today.year - 1
    while not levy_year_is_delinquent(y, state, county, today):
        y -= 1
    return y


def years_since_levy(year: int, state: Optional[str], county: Optional[str] = None,
                     today: Optional[date] = None) -> int:
    """How many levy years from `year` through the newest late one: the delinquency a single
    unpaid year implies when a source states only that year and the account has stayed unpaid
    since (counties apply a payment to the oldest bill first). 0 when `year` is not late yet."""
    return max(0, latest_delinquent_levy_year(state, county, today) - int(year) + 1)

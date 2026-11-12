"""Which levy years count. Pure.

North Carolina: a levy year Y is billed in summer of Y, due September 1 of Y, and interest
begins January 6 of Y + 1 (G.S. 105-360). The attorney's rule: ignore the current year's unpaid
bill (it is not late yet) and look at the three most recent COMPLETED levy years, i.e. those
whose interest date has passed. The current bill is still listed, separately, as 'current year,
not yet late'.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

#: (month, day) of the following year on which interest begins, by state
INTEREST_BEGINS = {"NC": (1, 6)}


def interest_date(levy_year: int, state: str = "NC") -> date:
    m, d = INTEREST_BEGINS.get(state.upper(), (1, 6))
    return date(levy_year + 1, m, d)


def is_completed(levy_year: int, today: date, state: str = "NC") -> bool:
    """True once the levy year's interest date has passed (the bill can be late)."""
    return today >= interest_date(levy_year, state)


def current_levy_year(today: date, state: str = "NC") -> int:
    """The latest levy year that is not yet late on `today` (its bill may or may not exist yet)."""
    y = today.year
    return y if is_completed(y - 1, today, state) else y - 1


def split_years(levy_years: Iterable[int], today: date, state: str = "NC", n: int = 3
                ) -> tuple[list[int], list[int]]:
    """(the n most recent completed levy years, newest first; the levy years not yet late)."""
    ys = sorted({int(y) for y in levy_years}, reverse=True)
    done = [y for y in ys if is_completed(y, today, state)]
    pending = [y for y in ys if not is_completed(y, today, state)]
    return done[:n], pending

"""raw['tax_owed'] for a delinquent-list scraper, with the not-yet-late rule applied (2026-10-07).

THE RULE (owner and attorney, tax_calendar.py): a current-year bill that is not late yet is not a
delinquency. Only levy years whose delinquent date has passed count toward years_delinquent, and
a row whose only unpaid bill is not late yet is not a delinquent-tax lead at all (the caller drops
it). The shape matches what enrichment_tax_owed.tax_year_status reads and what the other tax
scrapers write (nc_ptscloud_delinquent_tax, sc_catalis_delinquent_roll, nc_its_public_tax):

    tax_owed = {"balance": <late bills only>, "kind": "delinquent_tax", "source": <slug>,
                "year": <latest unpaid levy year>, "basis": "own_record" | "advertised_list",
                "years_delinquent": <LATE levy years>, "unpaid_bill_years": <all unpaid years>,
                "not_yet_late_years": [...], "not_yet_late_amount": <when known>,
                "years_basis": "year_list"}

and the source's own block (its name contains "tax", so enrichment_tax_owed treats it as a tax
source block) carries "years_unpaid": the unpaid levy years, oldest first.

Leading underscore: the registry skips this module.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from ...tax_calendar import completed_delinquent_years, levy_year, not_yet_late_years


def tax_owed_block(bills: Iterable[tuple], *, state: str, county: str, source: str,
                   basis: str = "own_record", today: Optional[date] = None) -> Optional[dict]:
    """`bills` = (levy_year, amount or None) pairs for one parcel. None when no bill is late."""
    rows = [(levy_year(y), a) for y, a in bills]
    rows = [(y, a) for y, a in rows if y is not None]
    years = sorted({y for y, _a in rows})
    if not years:
        return None
    late = completed_delinquent_years(years, state, county, today)
    if not late:
        return None
    pending = not_yet_late_years(years, state, county, today)
    late_amt = [a for y, a in rows if y in late and a]
    pend_amt = [a for y, a in rows if y in pending and a]
    out = {
        "balance": round(sum(late_amt), 2) if late_amt else None,
        "kind": "delinquent_tax",
        "source": source,
        "year": years[-1],
        "basis": basis,
        "years_delinquent": len(late),
        "unpaid_bill_years": len(years),
        "not_yet_late_years": pending,
        "years_basis": "year_list",
    }
    if pend_amt:
        out["not_yet_late_amount"] = round(sum(pend_amt), 2)
    return out


def unpaid_years(bills: Iterable[tuple]) -> list[int]:
    return sorted({y for y in (levy_year(b[0]) for b in bills) if y is not None})

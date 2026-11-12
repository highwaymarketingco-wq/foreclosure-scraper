"""Shared verdict logic of the SC county tax-bill verifiers that read a parcel's own bill list,
paid dates included, from the county's own site (tax_lien_greenville, tax_lien_florence).

Private (the leading underscore keeps the registry from loading it). Pure: no I/O.

THE RULES (the tax_lien_paystar / tax_lien_qpaybill meanings, one to one). A levy-year Y bill is
late once unpaid after January 15 of Y+1, a weekend rolled to Monday (S.C. Code 12-45-70;
tax_lien_qpaybill.deadline). Only late levy years count.
  confirmed    a bill of a late levy year shows a balance due today on the parcel searched
               (sold_at_tax_sale as the reason when a recent levy went to a tax sale);
  stale        nothing late is owed and a claimed year (else the latest late levy) was paid after
               its deadline: the claim WAS true;
  refuted      nothing late is owed and those bills were paid by the deadline;
  unconfirmed  the parcel is not on the site, the site failed, the parcel's record ends before the
               latest late levy, a payment dated inside the postmark grace (GRACE_DAYS after the
               deadline: the county credits the postmark, so a few days late on the receipt is not
               proof of lateness), a bill with no paid date, the claim's parcel and the board's
               disagree (identity_conflict), or a parcel a resolver attached (a guess) whose owner
               does not agree (parcel_resolved_unbound: neither site prints the situs, so nothing
               else binds it to the row).
A county marker that the bill went delinquent (Greenville's "D", Florence's delinquent list)
proves lateness on its own.

TWO CLAIMS (_tax_common, TWO CLAIMS): every paid late levy from HISTORY_FROM_LEVY on is counted
(late_levy_years), the chronic claim judged on it, governs per record (_tax_common.governs_for).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from . import _tax_common as tc

#: days after the deadline a receipt date may carry for a payment the county credits by postmark
GRACE_DAYS = 10
#: Tax Sale levies still inside the redemption window
RECENT_SALE_YEARS = 3


def deadline(year: int) -> date:
    """January 15 of Y+1, a weekend rolled to Monday (tax_lien_qpaybill.deadline)."""
    return tc.next_weekday(date(year + 1, 1, 15))


def is_eligible(year: int, today: date) -> bool:
    return today > deadline(year)


def latest_eligible(today: date) -> int:
    return today.year - 1 if is_eligible(today.year - 1, today) else today.year - 2


@dataclass
class Bill:
    year: int
    owed: float = 0.0                    # balance due today
    paid_on: Optional[date] = None
    late_flag: Optional[bool] = None     # the county's own "went delinquent" marker
    sold: bool = False                   # the levy went to a tax sale
    owner: Optional[str] = None          # compared as a category only, never published
    billed: Optional[float] = None
    flags: list = field(default_factory=list)


def lateness(b: Bill) -> Optional[bool]:
    """True paid late, False paid by the deadline, None undecided (no date, or a receipt dated
    inside the postmark grace with no delinquency marker)."""
    if b.paid_on is None:
        return True if b.late_flag else None
    dl = deadline(b.year)
    if b.paid_on <= dl:
        return False
    if b.late_flag or b.paid_on > dl + timedelta(days=GRACE_DAYS):
        return True
    return None


def judge(bills: list[Bill], *, claimed: list[int], today: date, ev: dict,
          unbound: bool, history_complete: bool = True) -> tuple[str, dict]:
    """(verdict, evidence) for one parcel's bills (module doc). `unbound`: the parcel came from a
    resolver and only the owner can tie it to the row. ev carries owner_match already."""
    if not bills:
        return "unconfirmed", dict(ev, reason="parcel_not_found")
    last_ok = latest_eligible(today)
    by_year: dict[int, list[Bill]] = {}
    for b in bills:
        by_year.setdefault(b.year, []).append(b)
    ev["latest_levy_year"] = max(by_year)
    owed = {y: round(sum(b.owed for b in bs if b.owed > 0), 2)
            for y, bs in by_year.items() if is_eligible(y, today)}
    owed = {y: a for y, a in owed.items() if a > 0}
    current = {y: round(sum(b.owed for b in bs if b.owed > 0), 2)
               for y, bs in by_year.items() if not is_eligible(y, today)}
    ev["not_yet_delinquent_due"] = {str(y): a for y, a in sorted(current.items(), reverse=True) if a > 0}
    sold = sorted({b.year for b in bills if b.sold}, reverse=True)
    if sold:
        ev["sold_at_tax_sale_years"] = sold
    sold_recent = any(y > last_ok - RECENT_SALE_YEARS for y in sold)
    flags = sorted({f for b in bills for f in b.flags})
    if flags:
        ev["flags"] = flags
    # the history: late levy years from HISTORY_FROM_LEVY on, paid or not
    late_years = sorted(y for y, bs in by_year.items() if y >= tc.HISTORY_FROM_LEVY and is_eligible(y, today)
                        and (y in owed or any(lateness(b) for b in bs)))
    ev.update(history_from_levy=tc.HISTORY_FROM_LEVY, history_complete=history_complete,
              late_levy_years=late_years, chronic_claim=tc.history_claims(late_years, history_complete))
    if owed:
        if unbound and ev.get("owner_match") not in ("same", "partial"):
            return "unconfirmed", dict(ev, reason="parcel_resolved_unbound")
        ev.update(delinquent_by_year={str(y): a for y, a in sorted(owed.items(), reverse=True)},
                  total_delinquent=tc.money_total(owed), years_delinquent=len(owed))
        ev["under_500"] = ev["total_delinquent"] < 500
        ev["de_minimis"] = ev["total_delinquent"] < tc.DE_MINIMIS
        if any(y in sold for y in owed) or sold_recent:
            ev["reason"] = "sold_at_tax_sale"
        return "confirmed", ev
    ev.update(delinquent_by_year={}, total_delinquent=0.0, years_delinquent=0)
    if sold_recent:
        return "unconfirmed", dict(ev, reason="sold_at_tax_sale")
    if unbound:
        return "unconfirmed", dict(ev, reason="parcel_resolved_unbound")
    if ev["latest_levy_year"] < last_ok:
        return "unconfirmed", dict(ev, reason="parcel_record_ended", latest_delinquent_eligible_levy=last_ok)
    paid_years = sorted((y for y in by_year if is_eligible(y, today)), reverse=True)
    order = [y for y in claimed if y in by_year and is_eligible(y, today)]
    for y in paid_years[:2]:
        if y not in order:
            order.append(y)
    checks = []
    for y in order:
        bs = by_year[y]
        dates = [b.paid_on for b in bs if b.paid_on]
        late = [lateness(b) for b in bs]
        verdict = True if any(x is True for x in late) else (
            False if late and all(x is False for x in late) else None)
        checks.append({"year": y, "paid_on": max(dates).isoformat() if dates else None,
                       "deadline": deadline(y).isoformat(), "paid_late": verdict})
    ev["bills_checked"] = checks
    claimed_set = set(claimed)
    late = [c for c in checks if c["paid_late"]]
    if late:
        ev["current_claim_basis"] = ("claimed_year_paid_late" if any(c["year"] in claimed_set for c in late)
                                     else "latest_year_paid_late")
        return "stale", ev
    undecided_claim = [c for c in checks if c["year"] in claimed_set and c["paid_late"] is None]
    on_time = [c for c in checks if c["paid_late"] is False]
    if on_time and not undecided_claim:
        ev["current_claim_basis"] = ("claimed_years_on_time" if any(c["year"] in claimed_set for c in on_time)
                                     else "latest_year_on_time")
        if ev["not_yet_delinquent_due"]:
            ev["note"] = "only the current levy is unpaid; it is not delinquent yet"
        return "refuted", ev
    if any(c["paid_on"] for c in checks):
        return "unconfirmed", dict(ev, reason="paid_near_deadline")
    return "unconfirmed", dict(ev, reason="no_payment_date")

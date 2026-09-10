"""Shared row guards for the SC county delinquent-tax HTML table parsers.

Six SC county scrapers carry a near-identical hand-rolled table parser -- darlington,
fairfield, york, saluda, lancaster and newberry. They were copy-pasted, so they share
the same defect, and fixing it in one place is the only way it stays fixed when the
seventh copy is made.

THE DEFECT, found by the adversarial verifier on 2026-09-10
    Each parser skipped a row only when one of the first two cells contained
    owner/name/tms/map/#, and otherwise accepted any row where SOME cell held a digit.
    A county treasurer page's OFFICE-HOURS table is also a <table> of <tr>, and it
    passes both tests: "Monday" is not in the skip list and "8:30 a.m. - 5:00 p.m."
    contains digits. `parcel` was also allowed to be None and the row emitted anyway.

    So the parsers were one populated hours cell away from putting
    defendant='Monday' street_address='8:30 a.m. - 5:00 p.m.' on the board as a
    TAX_SALE lead. They returned zero only because those cells happen to be empty on
    the live pages today.

    `_active_only()` in main.py had been silently absorbing this: it deletes rows with
    no sale_date, and these rows have none. That made it an ACCIDENTAL last line of
    defence, and adding these slugs to DATELESS_OK_SOURCES -- correct in itself, since
    a delinquent-tax balance is a standing condition with no sale date -- removed it.
    A pipeline filter is not a data-quality guard; this module is.

This engine has ingested junk before (six rows scraped off /careers/ and
/missing-persons/ pages), so a parser able to emit plausible-looking nonsense is a
real defect even while the page it reads is currently benign.
"""
from __future__ import annotations

import re

#: Column headers these tables actually use.
_HEADER_LABELS = ("owner", "name", "tms", "map", "parcel", "#", "header", "total",
                  "amount due", "bid")

#: Weekday and schedule labels, so an office-hours table can never be read as leads.
_SCHEDULE_LABELS = ("monday", "tuesday", "wednesday", "thursday", "friday",
                    "saturday", "sunday", "days", "hours", "closed", "holiday",
                    "office", "a.m.", "p.m.")

#: SC TMS: 3-4 / 2 / 2 / 3-4 with optional separators, or a long bare parcel number.
_TMS_RE = re.compile(r"\b(\d{3,4}[-\s]?\d{2}[-\s]?\d{2}[-\s]?[\d.]{3,})\b")
_BARE_RE = re.compile(r"\b(\d{8,})\b")


def is_label_row(cells: list[str]) -> bool:
    """True when a row is a header, an office-hours line, or other page furniture.

    Checks the first THREE cells rather than two: several of these tables put a blank
    leading cell in front of the label, which slipped past the original two-cell test.
    """
    head = [(c or "").lower() for c in cells[:3]]
    if any(lbl in c for c in head for lbl in _HEADER_LABELS):
        return True
    return any(lbl in c for c in head for lbl in _SCHEDULE_LABELS)


def find_tms(cells: list[str]) -> str | None:
    """First plausible SC TMS / parcel number in the row, else None."""
    for c in cells:
        m = _TMS_RE.search(c or "")
        if m:
            return m.group(1).strip()
    for c in cells:
        m = _BARE_RE.search(c or "")
        if m:
            return m.group(1)
    return None


def is_usable_row(cells: list[str], parcel: str | None) -> bool:
    """The single gate every one of these parsers should pass a row through.

    A delinquent-tax row with no TMS is not a workable lead -- it cannot be
    underwritten, joined to the assessor, or routed to a county -- so requiring the
    parcel is what actually closes the junk class, rather than hoping a downstream
    filter deletes it.
    """
    if not cells or len(cells) < 2:
        return False
    if is_label_row(cells):
        return False
    if not any(re.search(r"\d", c or "") for c in cells):
        return False
    return bool(parcel)

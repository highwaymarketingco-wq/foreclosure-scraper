"""Foreclosure docket-history enrichment (Dirty Deeds Tier B #37).

"Foreclosure docket history per parcel, including dismissed and terminated
cases. Count how many times a lender filed and failed." See
`foreclosure_docket_history.py`'s module docstring for the full investigation:
which of the four docket-adjacent sources report a real case-status field,
why a case's ABSENCE from a later scrape must never be read as a dismissal
(two of the four sources are rolling filed-date windows that age cases out
long before a real dismissal is usually entered), and why only a literal
"Dismissed"/"Terminated"/"Withdrawn" status counts.

This module is the wiring, not the policy -- all the "is this actually a
dismissal" logic lives in the sidecar. Two jobs, both over THIS run's
`enriched` listings:

  1. RECORD every case this run touched from the four sources below into the
     sidecar (state, county, case_number, owner, plaintiff, status, filed
     date). Idempotent -- re-observing the same case with the same status
     just bumps last_seen_at/times_seen.
  2. FLAG: for each such listing, ask the sidecar whether its owner already
     has two or more OTHER cases in the same county with a directly-observed
     terminal status. If so, tag `raw['repeat_foreclosure_filing']` -- "this
     lender (or a prior one) already filed against this owner and failed,
     more than once, before this filing."

NC asymmetry: `counties_nc.nc_ecourts_lis_pendens` already discards a hit
whose status is terminal before it ever becomes a Listing (correctly -- a
dead lien is not an actionable lead), so THIS module can only ever see NC's
surviving (mostly "Active") listings. That scraper itself calls
`foreclosure_docket_history.observe_case` on every hit -- including the ones
it discards -- before filtering, so a dismissed NC case's history is not
lost even though it never reaches this function. This module still safely
re-observes the NC listings it does see (harmless -- same case, same or
newer status) and, more importantly, still FLAGS them using whatever history
the scraper-side recording already captured.

The three SC sources (`counties_sc.sc_public_index_lis_pendens`,
`counties_sc.sc_public_index`, `national.sc_public_index`) never discard
anything, so both recording and flagging happen here for all of them.

DRY-RUN PERSISTENCE -- INVESTIGATED, NOT A BUG (2026-09-29). This function has
no `dry_run` parameter, and `con.commit()` after the record loop below runs
unconditionally -- so `scripts/run_pending_signal_enrichers.py --dry-run`
DOES persist real observations into data/foreclosure_docket_history.db, on
its own read of the board, exactly like a real run. That is structurally the
same shape as the bug fixed the same day in `enrichment_jail_bookings.py`
(commit 1ec77297, "Fix jail-roster sidecar losing 590 signals to dry-run/
real-run sequencing") and confirmed to have actually happened here too, live:
the 2026-09-29 sidecar shows all 16,739 cases with `first_seen_at` stamped at
a dry run's timestamp and `times_seen>=2` from the real run re-observing the
same targets ~37 minutes later (`scripts/run_pending_signal_enrichers.py`
runs all 8 STEPS -- including this one -- in a single invocation, so the same
dry run that surfaced the jail-bookings bug touched this sidecar too).

Despite that, NO SIGNAL IS LOST here, and no fix was made. The difference is
`repeat_filing_flag`: unlike `jail_roster_history.diff_and_record`'s
`is_new`/`is_new_booking`, which is a DIFF against last-known roster state
(so a name marked "seen" by an early dry-run commit is invisible to the real
run's own diff -- the actual bug), `repeat_filing_flag` is a STATELESS
aggregate query -- "how many of this owner's currently-recorded cases have
`ever_dismissed=1` right now" -- run fresh against the sidecar every single
call. It does not care whether a given dismissed case was recorded by this
run, a dry run minutes ago, or the scraper-side `observe_case` hook in
`nc_ecourts_lis_pendens.py`; the real run's own flag computation sees the
exact same cumulative case history either way and writes the same, correct
`repeat_foreclosure_filing` payload to the board. See
`test_calling_the_enrichment_twice_does_not_lose_the_repeat_flag` in
tests/test_enrichment_foreclosure_docket_history.py (and the sidecar-level
pin in tests/test_foreclosure_docket_history.py) for a regression test of
this exact property. The only side effect of the early dry-run commit is
cosmetic sidecar metadata drift -- `times_seen` inflated by one extra count
and `first_seen_at` stamped at the dry run's time instead of the real run's
-- neither of which any code in this repo reads (grepped 2026-09-29), so no
sidecar cleanup was performed either (contrast with jail_roster_history.db,
where the lost `is_new` diff required deleting the dry run's wrongly-
committed rows so the next real run could re-discover them).
"""
from __future__ import annotations

from typing import Optional

import structlog

from . import foreclosure_docket_history as fdh
from .models import Listing

log = structlog.get_logger()

# The four docket-adjacent sources this feature covers. See module + sidecar
# docstrings for why each one is (or, for the two rolling-window SC sources,
# is NOT reliably) a source of ground-truth dismissal status on its own.
SOURCES = frozenset((
    "counties_nc.nc_ecourts_lis_pendens",
    "counties_sc.sc_public_index_lis_pendens",
    "counties_sc.sc_public_index",
    "national.sc_public_index",
))

# (state, county, case_number, owner_name, plaintiff, status, filed_date)
_Fields = tuple[str, str, str, str, Optional[str], Optional[str], Optional[str]]


def _extract(li: Listing) -> Optional[_Fields]:
    """Pull the uniform (state, county, case_number, owner, plaintiff, status,
    filed_date) tuple out of one of the four sources' own raw shape. Returns
    None when the listing isn't one we cover, or lacks a case_number/owner
    (nothing to key history on)."""
    if li.source == "counties_nc.nc_ecourts_lis_pendens":
        nc = li.raw.get("nc_ecourts") or {}
        status = nc.get("civilJudgmentStatus")
        filed_date = nc.get("ordered_date_iso") or nc.get("orderedDate")
    elif li.source == "counties_sc.sc_public_index_lis_pendens":
        sp = li.raw.get("sc_public_index") or {}
        status = sp.get("status")
        filed_date = sp.get("filed_date")
    elif li.source == "counties_sc.sc_public_index":
        ct = li.raw.get("court") or {}
        status = ct.get("status")
        filed_date = ct.get("filed_date")
    elif li.source == "national.sc_public_index":
        sp = li.raw.get("sc_public_index") or {}
        status = sp.get("status")
        filed_date = sp.get("date_filed")
    else:
        return None

    owner_name = li.defendant or li.owner_name
    if not (li.state and li.county and li.case_number and owner_name):
        return None
    return (li.state, li.county, li.case_number, owner_name, li.plaintiff,
            status, filed_date)


async def enrich_foreclosure_docket_history(listings: list[Listing]) -> dict:
    """Record this run's docket-adjacent cases and flag repeat filers.

    Two passes over the SAME filtered subset: record first (so two sibling
    cases scraped in the same run can see each other), then flag. Both
    passes are best-effort per-listing -- one malformed row must not stop
    the rest from being recorded/flagged.
    """
    targets: list[tuple[Listing, _Fields]] = []
    for li in listings:
        if li.source not in SOURCES:
            continue
        fields = _extract(li)
        if fields:
            targets.append((li, fields))

    counts = {"observed": 0, "flagged": 0}
    if not targets:
        return counts

    con = fdh.connect()
    try:
        for _li, (state, county, case_number, owner_name, plaintiff, status,
                  filed_date) in targets:
            try:
                meta = fdh.observe_case(
                    con, state=state, county=county, case_number=case_number,
                    owner_name=owner_name, plaintiff=plaintiff, status=status,
                    filed_date=filed_date, source=_li.source, commit=False,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("foreclosure_docket_history.observe_failed",
                            case_number=case_number, error=str(exc)[:160])
                continue
            if meta:
                counts["observed"] += 1
        con.commit()

        for li, (state, county, case_number, owner_name, _plaintiff, _status,
                 _filed_date) in targets:
            try:
                flag = fdh.repeat_filing_flag(
                    con, state=state, county=county, owner_name=owner_name,
                    exclude_case_number=case_number,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("foreclosure_docket_history.flag_failed",
                            case_number=case_number, error=str(exc)[:160])
                continue
            if flag:
                raw = li.raw if isinstance(li.raw, dict) else {}
                raw["repeat_foreclosure_filing"] = flag
                li.raw = raw
                counts["flagged"] += 1
    finally:
        con.close()

    log.info("foreclosure_docket_history.done", **counts, targets=len(targets))
    return counts

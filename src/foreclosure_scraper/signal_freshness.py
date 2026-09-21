"""Shared date and freshness helpers for the signal enrichers and the scorer.

A leaf module on purpose (same reason as `mailing_shape`): nothing imports it at
process start, so a long-running orchestrator always loads the current file, and it
imports nothing from the engine, so the scorer, the enrichers and the tests can all
use it without a cycle.

Audit 2026-09-21, F12: positives were stamped and never aged. A code-enforcement block
kept scoring after every case was closed, a bankruptcy match never expired, a jail
booking kept scoring after release. This module gives every stamping enricher one way
to say "this fact was recorded on D and stops meaning anything after D+N"
(`stamp`, `is_stale`) and gives the scorer one way to read the answer, plus the three
per-signal predicates whose rules were previously spread over the scorer.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

__all__ = [
    "to_date", "stamp", "is_stale", "code_enforcement_open", "bankruptcy_lapsed",
    "custody_ended", "owner_names_a_death", "BK_TTL_DAYS_CH7", "BK_TTL_DAYS_OTHER",
]

# A Chapter 7 case is over in roughly four to six months (discharge, then closure), so its
# automatic stay and its distress value are gone well inside a year. Chapter 13 plans run
# three to five years. The enricher only ever matched filings from the last 180 days, then
# the stamp lived forever; these are the lifetimes it should have had.
BK_TTL_DAYS_CH7 = 270
BK_TTL_DAYS_OTHER = 1095


def to_date(v: Any) -> Optional[date]:
    """A date out of whatever the sources write: datetime, date, ISO string, or the US
    MM/DD/YYYY form the NC and SC court sites use. None when it cannot be read."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if len(s) < 8:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s[:10].rstrip(" T,"), fmt).date()
        except ValueError:
            continue
    return None


def stamp(block: dict, *, today: Optional[date] = None, ttl_days: Optional[int] = None) -> dict:
    """Record when a positive was written and, when it has a lifetime, when it expires.
    Mutates and returns `block`."""
    t = today or date.today()
    block["stamped_at"] = t.isoformat()
    if ttl_days is not None:
        block["stale_after"] = (t + timedelta(days=int(ttl_days))).isoformat()
    return block


def is_stale(block: Any, today: Optional[date] = None) -> bool:
    """True when the block carries a `stale_after` date that has passed. A block with no
    such field is never stale by this test (older boards, sources that never stamped)."""
    if not isinstance(block, dict):
        return False
    sa = to_date(block.get("stale_after"))
    return sa is not None and sa < (today or date.today())


def code_enforcement_open(ce: Any, today: Optional[date] = None) -> bool:
    """Does raw['code_enforcement'] describe a case that is still open?

    The block has at least four shapes in the wild: the city-feed dict
    (`has_open`, `open_violations`), the county-scraper dict that carries the same two
    keys, a list of violation dicts each with a `status`, and a bare truthy marker. An
    explicit `has_open` wins; then `open_violations`; then the per-violation statuses;
    a shape that says nothing about status is kept (the old behaviour), because
    dropping a real case on a field the source never wrote is the worse error."""
    if isinstance(ce, dict):
        if is_stale(ce, today):
            return False
        if "has_open" in ce:
            return bool(ce.get("has_open"))
        if "open_violations" in ce:
            try:
                return float(ce.get("open_violations") or 0) > 0
            except (TypeError, ValueError):
                return True
        vs = ce.get("violations")
        if isinstance(vs, list) and vs and all(isinstance(v, dict) and v.get("status") for v in vs):
            return any(str(v.get("status")).strip().lower() not in _CLOSED for v in vs)
        return bool(ce)
    if isinstance(ce, list):
        if not ce:
            return False
        if all(isinstance(v, dict) and v.get("status") for v in ce):
            return any(str(v.get("status")).strip().lower() not in _CLOSED for v in ce)
        return True
    return bool(ce)


_CLOSED = frozenset({"closed", "resolved", "complete", "completed", "dismissed", "abated",
                     "compliance", "in compliance", "case closed"})


def bankruptcy_lapsed(bk: Any, today: Optional[date] = None) -> bool:
    """True when a bankruptcy match is old enough that the case, and the stay it created,
    are over. Unparseable or missing dates are NOT lapsed (nothing to measure)."""
    if not isinstance(bk, dict):
        return False
    filed = to_date(bk.get("date_filed"))
    if filed is None:
        return False
    chapter = str(bk.get("chapter") or "").strip()
    ttl = BK_TTL_DAYS_CH7 if chapter == "7" else BK_TTL_DAYS_OTHER
    return (today or date.today()) > filed + timedelta(days=ttl)


_RELEASED = ("released", "out of custody", "discharged", "no longer in custody")


def custody_ended(jail_booking: Any, today: Optional[date] = None) -> bool:
    """A jail-roster hit whose booking record says the person is out. The enricher stores
    `release_status` and `scheduled_release` and never rechecks; the scorer can at least
    stop counting a booking that itself says the release happened."""
    if not isinstance(jail_booking, dict):
        return False
    status = str(jail_booking.get("release_status") or "").strip().lower()
    if any(status.startswith(k) for k in _RELEASED):
        return True
    sr = to_date(jail_booking.get("scheduled_release"))
    return sr is not None and sr < (today or date.today())


# HEIRS / ESTATE OF / EST OF in an owner name says a death. `TRUST` (a living trust is ordinary
# estate planning) and a bare `ESTATE` ("ACME REAL ESTATE HOLDINGS LLC") do not (audit F13).
_DEATH_NAME_RE = re.compile(r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b", re.I)


def owner_names_a_death(owner_name: Any) -> bool:
    return bool(_DEATH_NAME_RE.search(str(owner_name or "")))

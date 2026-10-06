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
    "bankruptcy_case_age", "custody_ended", "owner_names_a_death", "has_real_probate",
    "BK_TTL_DAYS_CH7", "BK_TTL_DAYS_OTHER", "LONG_OPEN_THRESHOLD_DAYS",
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
    dropping a real case on a field the source never wrote is the worse error.

    `vacancy_adjacent` (optional, dict shape only): 2026-10-02 Henderson County
    validation (n=60/238 sampled via the county's own ArcGIS dashboard feed) found
    only 46.9% of open code-enforcement hits were genuinely vacancy/condemnation/
    structural -- the majority were a DIFFERENT case category (mostly Zoning) riding
    the same flat "any open case counts" rule, because the signal is read off
    `has_open`/`open_violations` with no regard for what the case is actually about.
    A source that reads the real category from its feed (e.g.
    `counties_nc.henderson_code_violations`, off the ArcGIS `violationType` field)
    can set `vacancy_adjacent=False` to say "there IS an open case here, but none of
    them is a category that indicates vacancy/condemnation/structural distress" --
    an explicit opt-in key, absent on every source that never computed the
    distinction, so this changes nothing for them."""
    if isinstance(ce, dict):
        if is_stale(ce, today):
            return False
        if ce.get("vacancy_adjacent") is False:
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


# docs/dirty_deeds_synthesis_2026-09-10.md Tier B #28: "bankruptcies open 10-15 years are
# the strongest variant" of the bankruptcy signal. `bankruptcy_lapsed` above answers a
# different question (has the automatic STAY ended -- months for Ch.7, ~3yr for Ch.13);
# a case can be long since lapsed and STILL show no date_terminated in PACER/RECAP for
# a decade or more, which is the distinct, rarer signal this answers.
LONG_OPEN_THRESHOLD_DAYS = 3650  # 10 years — the low end of the "10-15 years" framing


def bankruptcy_case_age(bk: Any, today: Optional[date] = None) -> dict:
    """Case age + "still open after a long time" flag, derived purely from the date_filed
    (and, when present, date_terminated) a bankruptcy match/docket already carries. Returns
    {} when date_filed can't be parsed — never invents an age from nothing.

    is_long_open requires BOTH: filed >= LONG_OPEN_THRESHOLD_DAYS ago, AND no
    date_terminated on record (a case that ran 12 years and then closed on time isn't the
    "still open" anomaly the synthesis flags — the ones worth surfacing are cases PACER/
    RECAP has never recorded a closure for, years after they would ordinarily be done).
    """
    if not isinstance(bk, dict):
        return {}
    filed = to_date(bk.get("date_filed"))
    if filed is None:
        return {}
    t = today or date.today()
    age_days = (t - filed).days
    terminated = to_date(bk.get("date_terminated"))
    is_long_open = age_days >= LONG_OPEN_THRESHOLD_DAYS and terminated is None
    return {
        "case_age_days": age_days,
        "case_age_years": round(age_days / 365.25, 1),
        "is_long_open": is_long_open,
    }


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


# The `source` values the state/federal prison lanes stamp on raw['incarceration']
# (enrichment_incarceration DAC_SOURCE/SCDC_SOURCE, enrichment_bop_federal BOP_SOURCE). Literals
# because this module imports nothing from the engine; tests/test_incarceration_active.py pins them.
PRISON_SOURCES = ("NC DAC offender search", "SC DOC inmate search", "BOP inmate locator")


def is_prison_sourced(incarceration: Any) -> bool:
    return isinstance(incarceration, dict) and incarceration.get("source") in PRISON_SOURCES


# The source enrichment_jail_bookings._apply_hit stamps on the flag it sets:
# f"{county} County jail roster" ("Buncombe County jail roster").
_JAIL_SOURCE_RE = re.compile(r"\bcounty jail roster\s*$", re.I)


def is_jail_sourced(incarceration: Any) -> bool:
    """A raw['incarceration'] flag the county-jail lane set (its `source` is "<county> County jail
    roster"). Not a legacy source-less flag, not a prison flag."""
    return (isinstance(incarceration, dict)
            and bool(_JAIL_SOURCE_RE.search(str(incarceration.get("source") or ""))))


def incarceration_active(incarceration: Any, jail_booking: Any,
                         today: Optional[date] = None, *,
                         jail_verdict_suppresses: bool = False) -> bool:
    """Whether raw['incarceration'] still counts. A state/federal prison match stands on its own;
    only a county-jail (or legacy source-less) flag is tied to the jail booking's custody, so a
    person moved from county jail to prison is not dropped when the jail stay ends.

    A jail-sourced flag needs its booking: with no raw['jail_booking'] record behind it there is
    no custody to be in, and nothing the jail lane's re-evaluation or the jail_booking verifier
    would ever re-check, so it would score forever (custody_ended(None) is False). Measured on
    the 2026-10-05 board: 44 rows (Anderson 20, Cherokee 12, Buncombe 9, Henderson 2, Polk 1)
    carried a "<county> County jail roster" flag with no jail_booking. Such a flag does not
    count. A legacy source-less flag keeps its old behaviour (none on that board).

    `jail_verdict_suppresses`: the row carries a non-expired refuted/stale jail_booking
    verification (GOVERNS "incarceration:jail", verification/verifiers/jail_booking.py; the
    scorer and the lead-signal tagger pass `"incarceration:jail" in drop`). It ends a jail-sourced
    flag only. The prison check runs first, so a NC DAC / SC DOC / BOP flag is never touched by
    a county-jail verdict, including the jail -> prison move where the jail verdict is `stale`."""
    if not incarceration:
        return False
    if is_prison_sourced(incarceration):
        return True
    if jail_verdict_suppresses:
        return False
    if is_jail_sourced(incarceration) and not (isinstance(jail_booking, dict) and jail_booking):
        return False                    # an orphan jail flag: no booking, no custody
    return not custody_ended(jail_booking, today)


# HEIRS / ESTATE OF / EST OF in an owner name says a death. `TRUST` (a living trust is ordinary
# estate planning) and a bare `ESTATE` ("ACME REAL ESTATE HOLDINGS LLC") do not (audit F13).
_DEATH_NAME_RE = re.compile(r"\bHEIRS?\b|\bEST(?:ATE)?\s+OF\b", re.I)


def owner_names_a_death(owner_name: Any) -> bool:
    return bool(_DEATH_NAME_RE.search(str(owner_name or "")))


# Audit 2026-10-01: raw['probate'] is written by several scrapers as an ALWAYS-PRESENT
# "we searched this notice" wrapper, the same bug class as the Greenville `distressed=True`
# stamp (commits d1fe4056/2190aa5a/8081e57b) and the SC `divorce` case_count:0 wrapper
# (distress_score._divorce_signal already guards on case_count for exactly this reason).
# sc_public_notices.py writes {"decedent": defendant or None, "es_case_number": ... or None,
# ...} for EVERY "probate" notice kind, whether or not a decedent name or case number was
# actually captured; column_legal_notices.py's SC probate path writes a dict with only
# date_of_death / personal_representative, never a decedent name or case number at all. A
# bare `if raw.get("probate")` reads that empty wrapper as a hit. Measured board-wide
# (2026-10-01): 135 of 555 raw['probate'] dicts carry none of the identifiers below --
# mostly column_legal_notices (83) and sc_public_notices (45) -- and 14 of those 135 were
# riding the scorer to a WARM tier on a notice that names no one.
_PROBATE_IDENTIFIERS = ("decedent", "case_number", "es_case_number", "nc_estate_file_no")


def has_real_probate(p: Any) -> bool:
    """True when raw['probate'] (or the raw['estate'] alias some readers also check) names an
    actual decedent or a real case/file number, not just an empty "notice seen, nothing
    matched" wrapper. A dict holding only `date_of_death` / `personal_representative` /
    `match_confidence` with no decedent name and no case number is not an actionable probate
    lead: there is no name or docket to work. Every current reader of raw['probate']
    (distress_score, enrichment_strategy_fit, enrichment_property_category,
    enrichment_lead_signals, fullmer_rank) should gate on this instead of bare presence."""
    if not isinstance(p, dict):
        return False
    return any(str(p.get(k) or "").strip() for k in _PROBATE_IDENTIFIERS)

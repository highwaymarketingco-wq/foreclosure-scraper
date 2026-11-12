"""Owner-identity freshness policy — lets `owner_name` REFRESH from a fresh
CURRENT-state source (parcel_cache / live GIS / live tax-assessor query)
instead of the "missing-only" fill-once policy this codebase otherwise uses
for that field everywhere it is written.

CONFIRMED BUG, re-verified live 2026-10-02/03 (see docs/HANDOFF.md item 52
Finding C, and this commit): a 59-row live sample of Buncombe NC tax-
delinquency candidates found 15 (25.4% on a strict token-overlap re-check;
HANDOFF's own number from a parallel pass: 22.6-25.4%) show a DIFFERENT
CURRENT owner than the board lists for the identical parcel_id — not a
wrong-parcel confound, since both lookups in every mismatched row are keyed
by that same parcel_id. Re-fetched fresh against the live
tax.buncombenc.gov/Parcel/Details/{pin} page just now (not just trusting the
earlier session's JSON): PIN 965488696900000 board owner_name "Brandon
Bryant" vs. live "SUSAN STANFILL, IAN HUGHES"; PIN 964695441000000 board
"SARAH CARPENTER LIM IRREVOCABLE TRUST" vs. live "FONDA HAIGHT"; PIN
966553276600000 board "Tim Magee" vs. live "JAMES DAVENPORT, LISA DAVENPORT"
— all three reproduce the earlier session's findings exactly, same day,
confirming this is a live, currently-active discrepancy, not a one-time
fetch artifact.

Root cause, traced to real code (not the naming-based guesses the task that
created this module started from): every owner-filling enrichment path in
this codebase only ever fires on `if not li.owner_name: ...`
(enrichment_arcgis.py, enrichment_gis_attrs.py, enrichment_ncpts_lrc.py), and
the generic `Listing.merge()` field loop (`models.py`) only overwrites a
field when the SIDE ALREADY ON THE BOARD is falsy. A parcel_cache snapshot
refreshed last week can sit right next to a board row whose owner_name was
baked in from whatever earlier date a scraper (e.g. the generic
`counties_generic.arcgis_distress` family, which sets `owner_name` once at
Listing-construction time straight off a live ArcGIS layer AT SCRAPE TIME)
first captured that row — and nothing will ever compare the two again.

ONLY FOR CURRENT-STATE FIELDS. owner_name sourced from a GIS parcel record,
a cached bulk parcel-layer snapshot, or a live tax-assessor query represents
"who the county says owns (and is billed for) this parcel right now" — real-
world state that changes on ownership turnover and SHOULD track the county's
current answer for marketing/outreach purposes. Do NOT wire this into a
field that is a deliberate HISTORICAL record of a specific filing (a court
docket defendant, a divorce-caption party, a bankruptcy debtor, a trustee's
foreclosure-notice "owner being foreclosed") — those name the party AT THE
TIME OF THAT FILING, which refreshing to "whoever owns it today" would make
WRONG, not right, since the whole point of those signals is who was
distressed/party-to-the-case back then. (enrichment_court_owner_verify.py's
end-of-pipeline revert of owner_name to the docket defendant on a surname
mismatch is a different, pre-existing mechanism — a wrong-PARCEL guard
against a bad geo-snap, not a staleness policy — and is untouched by this
module.)

Mechanism, deliberately mirroring parcel_cache.CACHE_VALUE_MAX_AGE_DAYS /
cache_is_stale() (landed earlier the same day, commit 16a55ccb, same
validation session, same file-mtime-style freshness-bound pattern — just at
the LISTING-field grain here instead of the cache-FILE grain there, because
no per-field timestamp previously existed to check at the listing grain; see
"NO EXISTING STALENESS SIGNAL" below): every refresh-capable write stamps
`raw['owner_name_as_of']` (an ISO date, UTC) the day it is set OR confirmed
unchanged against a fresh read. `is_owner_refreshable()` asks: was this field
EVER stamped (no -> treat as unknown-age -> stale, the same "missing cache
file == stale" convention cache_is_stale() already uses), or is its stamp at
least OWNER_REFRESH_MIN_AGE_DAYS old? The lower bound exists only to stop two
current-state enrichers that ran back-to-back in ONE pipeline invocation
(e.g. a formatting difference between the parcel_cache's owner string and a
live GIS query's owner string for the SAME real person) from re-stamping
each other back and forth within that single run. Real ownership turnover
happens on a scale of months, far above this bound, so the bound costs this
fix nothing in practice.

NO EXISTING STALENESS SIGNAL (separate real finding, worth its own callout):
before this module, there was NO way to tell how old a given board row's
owner_name actually was. `Listing.first_seen`/`last_seen` look like
candidates but are NOT a usable proxy — `Listing.merge()` bumps
`last_seen = max(self.last_seen, other.last_seen)` on EVERY merge
UNCONDITIONALLY, even on a merge that changes nothing else about the row (the
same method's generic field loop is what keeps owner_name frozen in the
first place). A row can show `last_seen` from this morning's run while its
`owner_name` has been untouched for a year — last_seen answers "when was
this row's dedupe_key last seen in a scrape," not "when was any particular
field on it last verified." raw['owner_name_as_of'], introduced here, is the
first field-grained freshness signal this codebase has for owner_name.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

#: Minimum age (days) an existing raw['owner_name_as_of'] stamp must reach
#: before a disagreeing fresh read is allowed to overwrite owner_name. Exists
#: only to prevent same-run flapping between two current-state sources (see
#: module docstring) -- real turnover is measured in months, not days.
OWNER_REFRESH_MIN_AGE_DAYS = 1.0

_WS_RE = re.compile(r"\s+")
_NONLETTER_RE = re.compile(r"[^A-Z ]")


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def owner_name_as_of(li) -> str | None:
    """The ISO-date freshness stamp on li.owner_name, or None if it was never
    stamped (legacy data, or set by a path that predates/is exempt from this
    module -- e.g. a court-caption/historical fill)."""
    raw = li.raw if isinstance(li.raw, dict) else None
    v = raw.get("owner_name_as_of") if raw else None
    return v if isinstance(v, str) and v.strip() else None


def owner_name_age_days(li) -> float | None:
    """Age in days of li.owner_name's freshness stamp, or None when unstamped."""
    stamp = owner_name_as_of(li)
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(stamp).date()
    except ValueError:
        return None
    return float((datetime.now(timezone.utc).date() - d).days)


def is_owner_refreshable(li, min_age_days: float = OWNER_REFRESH_MIN_AGE_DAYS) -> bool:
    """True when li.owner_name has no freshness stamp at all (unknown age --
    treated as stale, the same policy cache_is_stale() uses for a missing
    cache file) or its stamp is at least `min_age_days` old. False means "this
    was just confirmed/refreshed too recently in this same run -- don't
    re-touch it again right now"."""
    age = owner_name_age_days(li)
    return age is None or age >= min_age_days


def _norm_for_compare(s) -> str:
    """Comparison-only normalization (never stored): uppercase, letters+spaces
    only, collapsed whitespace. Enough to tell 'Smith, John' from 'SMITH JOHN'
    apart from a genuinely different name without being a real name parser."""
    return _WS_RE.sub(" ", _NONLETTER_RE.sub("", str(s or "").upper())).strip()


def stamp_owner_name(li, value: str) -> None:
    """Set li.owner_name = value and record today's date as this field's
    freshness stamp. Callers performing a CURRENT-state fill or refresh
    should use this (never `li.owner_name = value` directly) so later
    refresh decisions have a real age to check against."""
    li.owner_name = value
    if not isinstance(li.raw, dict):
        li.raw = {}
    li.raw["owner_name_as_of"] = _today_iso()


def should_refresh_owner_name(li, candidate: str | None) -> bool:
    """True when `candidate` is a real, different name from li.owner_name AND
    (li.owner_name is currently blank -- a plain fill, not a refresh, always
    allowed -- or the existing value is old enough/never stamped to refresh).

    Candidate QUALITY (non-empty, not pure digits/junk, minimum length, a
    plausible name shape) remains the CALLER's job, exactly as it was before
    this module existed -- this function only adds the comparison + staleness
    gate on top of whatever quality check the caller already runs before
    calling it. Deliberately does not re-stamp when the normalized candidate
    equals the normalized existing value, so a same-answer reconfirmation
    from a different source doesn't spam a new stamp date for no change.
    """
    if not candidate:
        return False
    if not (li.owner_name or "").strip():
        return True  # plain fill -- no staleness question
    if _norm_for_compare(candidate) == _norm_for_compare(li.owner_name):
        return False  # no real change
    return is_owner_refreshable(li)

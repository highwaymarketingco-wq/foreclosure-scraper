"""Surface delinquent-tax AGING (years-delinquent / 2yr+ ripeness) from whichever
real source already states it, into the two canonical fields this codebase's
actual readers consume: raw['tax_aging_surfaced'] (fullmer_rank.py's
years_delinquent(), the delinq_ripeness_points() ramp) and raw['tax_aging_high']
(enrichment_equity.py's 0.70-vs-0.60 payoff-estimate branch).

WHY THIS EXISTS. tax_aging_surfaced was, until now, written only by two one-shot
scripts (scripts/surface_tax_aging.py, scripts/fill_all_gaps.py's "TAX AGING"
section) -- never wired into main.py's regular pipeline. A lead scraped (or
re-enriched) after the last manual run never got it, and an updated
raw['tax_owed']['year'] from this run's OWN enrich_tax_owed() (which does run
every cycle) never propagated into it. Measured 2026-10-03, read-only via
board_stream.iter_board_rows() against the live 219,143-row board: 41,083 rows
across 49 counties already carry a real raw['tax_owed']['year'], and 13,313
rows across 14 counties carry raw['nc_ptscloud_delinquent_tax']['tax_year'] --
but only 2,120 rows across 11 counties were actually credited into
tax_aging_surfaced as real (source != "default"). The county_signal_coverage
tracker's 11/148 figure for this column is itself correctly computed -- it
already excludes the "default" placeholder the old scripts stamp on every
other row, matching fullmer_rank.py's own `years_delinquent()` discipline --
so 11/148 is not a presence-check-inflation bug. But it IS stale: the real
ceiling today, from data the pipeline has already collected, spans up to 49
counties, not 11. This enricher closes that gap going forward by recomputing
the two canonical fields from current raw['tax_owed']/raw['nc_ptscloud_
delinquent_tax'] on every pipeline run instead of a dead manual snapshot.

SECOND, SEPARATE BUG FIXED HERE: raw['tax_aging_high'] -- a flat top-level
boolean enrichment_equity.py reads directly (raw0.get("tax_aging_high")) to
choose between a 0.70 and a 0.60 assessed-value payoff-estimate multiplier --
was never registered in web_artifact.RAW_KEEP, so every value
scripts/surface_tax_aging.py ever wrote for it was silently dropped at
publish (confirmed: 0 of 219,143 live rows carry it). That branch has
therefore always taken the 0.60 estimate, never 0.70, for every tax-aging-high
lead actually published. Fixed by registering it alongside tax_aging_surfaced.
delinquent_tax_year/delinquent_years/delinquent_tax_amount/delinquent_tax_total/
tax_aging_bucket (the other keys the old one-shot script wrote) were checked
and have no reader anywhere in this codebase -- not bridged, per this repo's
existing discipline of only bridging a key into the shape an actual reader
wants, not inventing one.

Priority when both sources are present: nc_ptscloud_delinquent_tax (a direct
per-parcel vendor read) over tax_owed (broader, pipeline-normalized, but its
year can come from a generic text scan) -- the same priority
scripts/surface_tax_aging.py already used.

Idempotent and NOT missing-only: recomputed every run from whatever
raw['tax_owed']/raw['nc_ptscloud_delinquent_tax'] currently say, so a later
correction to either source is reflected immediately instead of freezing a
stale stamp. A listing with neither source is left untouched (any pre-existing
stamp, including an old "default" placeholder, is neither trusted nor
overwritten here -- no fabricated negative case).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from .models import Listing

_MIN_YEAR = 1990


def _current_year() -> int:
    return date.today().year


def _from_ptscloud(raw: dict, current_year: int) -> Optional[tuple[int, int]]:
    """(tax_year, years_delinquent) from raw['nc_ptscloud_delinquent_tax'], or None."""
    pts = raw.get("nc_ptscloud_delinquent_tax")
    if not isinstance(pts, dict):
        return None
    ty = pts.get("tax_year")
    try:
        ty = int(ty)
    except (TypeError, ValueError):
        return None
    if not (_MIN_YEAR <= ty <= current_year):
        return None
    return ty, current_year - ty


def _from_tax_owed(raw: dict, current_year: int) -> Optional[tuple[Optional[int], int]]:
    """(tax_year or None, years_delinquent) from raw['tax_owed'], or None.

    `years_delinquent` is preferred when the source already states a count
    directly (promoted by enrich_tax_owed from a sibling multi-year block) --
    more authoritative than subtracting the earliest delinquent year, and
    available even when `year` itself is absent. Falls back to computing from
    `year` otherwise.
    """
    to = raw.get("tax_owed")
    if not isinstance(to, dict):
        return None
    yr = to.get("year")
    try:
        yr = int(yr)
        if not (_MIN_YEAR <= yr <= current_year):
            yr = None
    except (TypeError, ValueError):
        yr = None

    yrs = to.get("years_delinquent")
    if isinstance(yrs, (int, float)) and yrs > 0:
        return yr, int(yrs)
    if yr is not None:
        return yr, current_year - yr
    return None


def enrich_tax_aging(listings: Iterable[Listing]) -> dict:
    """Surface years-delinquent onto raw['tax_aging_surfaced'] (and the
    derived raw['tax_aging_high'] flag) for every listing where a real tax
    source already states it. Returns run stats; never raises."""
    current_year = _current_year()
    stats = {"surfaced": 0, "high_2yr_plus": 0, "by_source": {"nc_ptscloud": 0, "tax_owed": 0}}

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if raw is None:
            continue

        tax_year: Optional[int] = None
        years_delinquent: Optional[int] = None
        source: Optional[str] = None

        hit = _from_ptscloud(raw, current_year)
        if hit is not None:
            tax_year, years_delinquent = hit
            source = "nc_ptscloud"
        else:
            hit = _from_tax_owed(raw, current_year)
            if hit is not None:
                tax_year, years_delinquent = hit
                source = "tax_owed"

        if source is None:
            continue  # no real measurement this run -- leave whatever's there alone

        raw["tax_aging_surfaced"] = {
            "tax_year": tax_year,
            "years_delinquent": years_delinquent,
            "status": "delinquent",
            "source": source,
        }
        is_high = years_delinquent >= 2
        raw["tax_aging_high"] = is_high

        stats["surfaced"] += 1
        stats["by_source"][source] += 1
        if is_high:
            stats["high_2yr_plus"] += 1

    return stats

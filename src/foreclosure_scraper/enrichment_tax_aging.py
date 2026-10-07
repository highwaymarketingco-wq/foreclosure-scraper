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

YEARS DELINQUENT = LATE YEARS (2026-10-07, owner + attorney rule). years_delinquent counts the
unpaid levy years whose delinquent date has passed (tax_calendar: NC January 6, SC January 16 of
the next year); a current bill that is not late yet is not counted. One reader for every source,
enrichment_tax_owed.tax_year_status(): a source block that lists the unpaid years wins, then a
stated count (less the newest year when that year is not late yet), then a single year (the
delinquency since that year, tax_calendar.years_since_levy; the old `current_year - year`, which
also counted a bill still inside its January grace window). Measured on the 10/7 board: the
Buncombe multi-year engine lists the current 2026 levy among its years, so "unpaid 2025 + 2026"
read as 2 years delinquent when it is 1. tax_aging_surfaced also carries `basis`,
`unpaid_bill_years` (the raw count) and `not_yet_late_years`, and `status` is "not_yet_late"
when nothing is late yet.

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

from .enrichment_tax_owed import tax_year_status
from .models import Listing

_MIN_YEAR = 1990


def _year(v) -> Optional[int]:
    try:
        y = int(str(v).strip()[:4])
    except (TypeError, ValueError):
        return None
    return y if _MIN_YEAR <= y <= date.today().year + 1 else None


def enrich_tax_aging(listings: Iterable[Listing], today: Optional[date] = None) -> dict:
    """Surface years-delinquent onto raw['tax_aging_surfaced'] (and the
    derived raw['tax_aging_high'] flag) for every listing where a real tax
    source already states it. Returns run stats; never raises."""
    today = today or date.today()
    stats = {"surfaced": 0, "high_2yr_plus": 0, "not_yet_late": 0,
             "by_source": {"nc_ptscloud": 0, "tax_owed": 0}}

    for li in listings:
        raw = li.raw if isinstance(li.raw, dict) else None
        if raw is None:
            continue
        pts = raw.get("nc_ptscloud_delinquent_tax")
        to = raw.get("tax_owed")
        pts_year = _year(pts.get("tax_year")) if isinstance(pts, dict) else None
        to_year = _year(to.get("year")) if isinstance(to, dict) else None
        if pts_year is not None:
            source, tax_year = "nc_ptscloud", pts_year
        elif isinstance(to, dict) and (to_year is not None or to.get("years_delinquent")):
            source, tax_year = "tax_owed", to_year
        else:
            continue  # no real measurement this run -- leave whatever's there alone

        status = tax_year_status(raw, li.state, li.county, today)
        if status is None:
            continue
        years_delinquent = status["years_delinquent"]
        surf = {
            "tax_year": tax_year,
            "years_delinquent": years_delinquent,
            "status": "delinquent" if years_delinquent >= 1 else "not_yet_late",
            "source": source,
            "basis": status["basis"],
        }
        if status.get("unpaid_bill_years") is not None:
            surf["unpaid_bill_years"] = status["unpaid_bill_years"]
        if status["not_yet_late_years"]:
            surf["not_yet_late_years"] = status["not_yet_late_years"]
        raw["tax_aging_surfaced"] = surf
        is_high = years_delinquent >= 2
        raw["tax_aging_high"] = is_high

        stats["surfaced"] += 1
        stats["by_source"][source] += 1
        if is_high:
            stats["high_2yr_plus"] += 1
        if not years_delinquent:
            stats["not_yet_late"] += 1

    return stats

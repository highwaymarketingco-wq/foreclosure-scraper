"""Per-source health JSON written alongside docs/listings.json each week.

Investors and ops alike need to see, at a glance:
  * Which sources produced data this week
  * Which were blocked (paywall / Apify / render-required) — expected
  * Which regressed (produced fewer listings than expected) — alert!
  * What the validation gate caught (cross-state, bad parcels, etc.)
  * Stats from each enrichment (lis-pendens resolved, vision-rehab applied)

Output:  docs/run_health.json
Format:  small JSON, GitHub-Pages-served and dashboard-friendly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_health_artifact(
    *,
    out_path: Path,
    summary: dict[str, Any],
    enrichment_stats: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Write the per-run health summary to a JSON file.

    Args:
      out_path: where to write (docs/run_health.json)
      summary:  the existing run summary dict (from main.py)
      enrichment_stats: optional dict of {enrichment_name: stats_dict}
    """
    health = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "total_listings": summary.get("total", 0),
            "by_state": summary.get("by_state", {}),
        },
        "sources": _per_source_section(summary),
        "regressions": summary.get("regressions") or [],
        "errors": summary.get("errors") or [],
        "enrichments": enrichment_stats or {},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(health, indent=2, sort_keys=False))
    return out_path


def _per_source_section(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Pivot the run summary's by_source + source_status into a list of
    per-source health rows, sorted by status severity (regressed first).
    """
    by_source = summary.get("by_source") or {}
    status = summary.get("source_status") or {}

    rows: list[dict[str, Any]] = []
    for slug in sorted(set(by_source) | set(status)):
        s = status.get(slug, "(no status)")
        rows.append({
            "source": slug,
            "count": int(by_source.get(slug, 0)),
            "status": s,
            "severity": _severity(s),
        })
    rows.sort(key=lambda r: (-r["severity"], r["source"]))
    return rows


def _severity(status: str) -> int:
    """Higher = more attention needed.
       3 = REGRESSED (alert)
       2 = render-required / no creds (action item)
       2 = CARRYOVER (stale prior-run data — needs investigation)
       1 = blocked (acknowledged failure)
       0 = OK / empty (verified)
    """
    if not status:
        return 0
    s = status.upper()
    if s.startswith("REGRESSED"):
        return 3
    if s.startswith("CARRYOVER"):
        # Carryover is a soft regression: data exists for the dashboard
        # via last-known-good replay, but the source itself failed this
        # run. Surface above blocked-but-OK so it gets eyes.
        return 2
    if "RENDER-REQUIRED" in s:
        return 2
    if "PAYWALL-BLOCKED" in s or "APIFY-BLOCKED" in s:
        return 1
    return 0

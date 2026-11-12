"""Tests for the per-run health artifact writer."""
from __future__ import annotations

import json
from pathlib import Path

from foreclosure_scraper.run_health import (
    _per_source_section,
    _severity,
    write_health_artifact,
)


def test_severity_ranking():
    assert _severity("REGRESSED (expected ≥ 5)") == 3
    assert _severity("RENDER-REQUIRED (Scrapling stealth not wired)") == 2
    assert _severity("PAYWALL-BLOCKED") == 1
    assert _severity("APIFY-BLOCKED") == 1
    assert _severity("OK (74)") == 0
    assert _severity("EMPTY (verified)") == 0
    assert _severity("") == 0


def test_per_source_section_sorts_regressions_first():
    summary = {
        "by_source": {"a": 0, "b": 50, "c": 0, "d": 0},
        "source_status": {
            "a": "REGRESSED (expected ≥ 10)",
            "b": "OK (50)",
            "c": "PAYWALL-BLOCKED",
            "d": "RENDER-REQUIRED (Scrapling stealth not wired)",
        },
    }
    rows = _per_source_section(summary)
    assert rows[0]["source"] == "a"   # severity 3 first
    assert rows[1]["source"] == "d"   # severity 2 next
    assert rows[2]["source"] == "c"   # severity 1
    assert rows[3]["source"] == "b"   # severity 0 last
    assert rows[0]["severity"] == 3


def test_writes_full_artifact(tmp_path: Path):
    summary = {
        "total": 1234,
        "by_state": {"NC": 700, "SC": 534},
        "by_source": {"law_firms.hutchens": 74, "national.foreclosure_dot_com": 0},
        "source_status": {
            "law_firms.hutchens": "OK (74)",
            "national.foreclosure_dot_com": "PAYWALL-BLOCKED",
        },
        "regressions": ["law_firms.brock_scott: got 0, expected ≥ 5"],
        "errors": [],
    }
    out = tmp_path / "run_health.json"
    written = write_health_artifact(
        out_path=out,
        summary=summary,
        enrichment_stats={
            "lis_pendens_resolver": {
                "queried": 70, "address_filled": 16,
                "ambiguous": 14, "no_match": 35, "fiduciary_skipped": 1,
            },
            "validation": {
                "county_normalized": 1, "parcel_nulled_too_short": 100,
            },
        },
    )
    assert written.exists()
    j = json.loads(written.read_text())
    assert j["totals"]["total_listings"] == 1234
    assert j["totals"]["by_state"]["NC"] == 700
    sources = {r["source"]: r for r in j["sources"]}
    assert sources["national.foreclosure_dot_com"]["severity"] == 1
    assert sources["law_firms.hutchens"]["severity"] == 0
    assert j["regressions"] == ["law_firms.brock_scott: got 0, expected ≥ 5"]
    # Enrichment stats round-trip
    assert j["enrichments"]["lis_pendens_resolver"]["address_filled"] == 16
    assert j["enrichments"]["validation"]["parcel_nulled_too_short"] == 100
    # generated_at is ISO 8601
    assert "T" in j["generated_at"]


def test_handles_empty_summary(tmp_path: Path):
    """Even with no scrapers run / no data, the artifact must be a valid JSON
    object — never blank, never crash."""
    out = tmp_path / "run_health.json"
    write_health_artifact(out_path=out, summary={})
    j = json.loads(out.read_text())
    assert j["totals"]["total_listings"] == 0
    assert j["sources"] == []
    assert j["regressions"] == []

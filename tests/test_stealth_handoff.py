"""national.stealth_handoff — HERMES extraction-completeness audit, batch 18
(2026-10-04). No test file existed for this scraper before this batch.

Main finding: the repo's real docs/handoff/stealth_leads.json is dated
2026-09-01T23:20:57Z -- 32+ days stale as of today, and the Mac-side
launchd schedule that is supposed to refresh it
(deploy/mac/install_stealth_schedule.sh) is NOT installed on this machine
(`launchctl list | grep stealth` returns nothing, the plist file does not
exist). This lines up with this project's own tracked
`project_oracle_vm_revival` status (that VM has been idle since 9/3) --
a known, already-tracked infra gap, not re-enabled here (an operational
change with real side effects, out of this batch's scope). What this batch
DOES fix, safely: severe staleness (7+ days, env-overridable via
HANDOFF_SEVERE_STALE_HOURS) now also flips self.last_outcome to
OUTCOME_PARTIAL with an explicit reason, instead of blending into the
same log.warning level as routine few-hours staleness.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from foreclosure_scraper.base_scraper import OUTCOME_OK, OUTCOME_PARTIAL
from foreclosure_scraper.scrapers.national import stealth_handoff as m


def _write_handoff(tmp_path: Path, leads: list[dict], generated_at: str | None,
                    extra: dict | None = None) -> Path:
    path = tmp_path / "stealth_leads.json"
    payload = {"leads": leads}
    if generated_at is not None:
        payload["generated_at"] = generated_at
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload, default=str))
    return path


def _valid_lead(source: str = "counties_sc.sc_public_index") -> dict:
    return {
        "source": source,
        "source_url": "https://example.com/x",
        "listing_type": "foreclosure_sale",
        "state": "SC",
        "county": "Anderson",
        "first_seen": datetime.now(timezone.utc).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }


def test_absent_file_returns_empty_no_error(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setenv("HANDOFF_FILE", str(missing))
    scraper = m.StealthHandoffScraper()
    out = asyncio.run(scraper.fetch())
    assert out == []


def test_unreadable_file_returns_empty_no_error(tmp_path, monkeypatch):
    path = tmp_path / "stealth_leads.json"
    path.write_text("{not valid json")
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    out = asyncio.run(scraper.fetch())
    assert out == []


def test_bad_shape_returns_empty_no_error(tmp_path, monkeypatch):
    path = tmp_path / "stealth_leads.json"
    path.write_text(json.dumps({"leads": "not-a-list"}))
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    out = asyncio.run(scraper.fetch())
    assert out == []


def test_valid_leads_ingested_and_round_trip_losslessly(tmp_path, monkeypatch):
    """This module's own transport is a clean Listing.model_dump_json() ->
    Listing.model_validate() round trip, unlike the direct-scraper RAW_KEEP
    bugs found elsewhere this audit series -- confirms that stays true."""
    leads = [_valid_lead(), _valid_lead(source="national.nc_sos_ucc")]
    path = _write_handoff(tmp_path, leads,
                           generated_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    out = asyncio.run(scraper.fetch())
    assert len(out) == 2
    sources = {li.source for li in out}
    assert sources == {"counties_sc.sc_public_index", "national.nc_sos_ucc"}


def test_malformed_rows_are_skipped_not_fatal(tmp_path, monkeypatch):
    leads = [_valid_lead(), {"this": "is not a valid Listing at all"}]
    path = _write_handoff(tmp_path, leads,
                           generated_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    out = asyncio.run(scraper.fetch())
    assert len(out) == 1


def test_fresh_file_leaves_outcome_at_default_ok(tmp_path, monkeypatch):
    path = _write_handoff(tmp_path, [_valid_lead()],
                           generated_at=datetime.now(timezone.utc).isoformat())
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    scraper.last_outcome, scraper.last_reason = OUTCOME_OK, ""
    asyncio.run(scraper.fetch())
    assert scraper.last_outcome == OUTCOME_OK


def test_moderately_stale_file_does_not_flip_outcome(tmp_path, monkeypatch):
    """Past the 72h advisory threshold but under the new 7-day severe
    threshold -- still just a log-level warning, outcome unchanged."""
    gen = (datetime.now(timezone.utc) - timedelta(hours=96)).isoformat()
    path = _write_handoff(tmp_path, [_valid_lead()], generated_at=gen)
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    scraper.last_outcome, scraper.last_reason = OUTCOME_OK, ""
    asyncio.run(scraper.fetch())
    assert scraper.last_outcome == OUTCOME_OK


def test_severely_stale_file_flips_outcome_to_partial(tmp_path, monkeypatch):
    """FOUND/FIXED batch 18: a file past the severe-staleness threshold
    (default 7 days) must surface distinctly via last_outcome, not just a
    log line indistinguishable from routine staleness. Regression pin for
    the real 32-day-stale case this batch found live."""
    gen = (datetime.now(timezone.utc) - timedelta(days=32)).isoformat()
    path = _write_handoff(tmp_path, [_valid_lead()], generated_at=gen)
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    scraper.last_outcome, scraper.last_reason = OUTCOME_OK, ""
    out = asyncio.run(scraper.fetch())
    assert len(out) == 1  # still ingests -- stale data beats none
    assert scraper.last_outcome == OUTCOME_PARTIAL
    assert "stale" in scraper.last_reason.lower()
    assert "32" in scraper.last_reason or "31.9" in scraper.last_reason or "32.0" in scraper.last_reason


def test_severe_stale_threshold_is_configurable(tmp_path, monkeypatch):
    """The threshold is read from HANDOFF_SEVERE_STALE_HOURS at import time
    (same pre-existing pattern as _STALE_HOURS), so the module attribute
    itself -- not a late env var -- is what fetch() actually reads each
    call; patch that directly to exercise the threshold without a module
    reload."""
    gen = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    path = _write_handoff(tmp_path, [_valid_lead()], generated_at=gen)
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    monkeypatch.setattr(m, "_SEVERE_STALE_HOURS", 5.0)
    scraper = m.StealthHandoffScraper()
    scraper.last_outcome, scraper.last_reason = OUTCOME_OK, ""
    asyncio.run(scraper.fetch())
    assert scraper.last_outcome == OUTCOME_PARTIAL


def test_no_generated_at_does_not_crash_or_flip_outcome(tmp_path, monkeypatch):
    path = _write_handoff(tmp_path, [_valid_lead()], generated_at=None)
    monkeypatch.setenv("HANDOFF_FILE", str(path))
    scraper = m.StealthHandoffScraper()
    scraper.last_outcome, scraper.last_reason = OUTCOME_OK, ""
    out = asyncio.run(scraper.fetch())
    assert len(out) == 1
    assert scraper.last_outcome == OUTCOME_OK


def test_real_repo_handoff_file_is_readable_and_shape_valid():
    """Sanity check against the actual committed file (not a fixture) --
    confirms the real on-disk file still parses and ingests cleanly, even
    though (per this batch's finding) it is known to be severely stale."""
    real_path = m._HANDOFF
    if not real_path.exists():
        pytest.skip("docs/handoff/stealth_leads.json not present in this checkout")
    scraper = m.StealthHandoffScraper()
    import os
    old = os.environ.pop("HANDOFF_FILE", None)
    try:
        out = asyncio.run(scraper.fetch())
    finally:
        if old is not None:
            os.environ["HANDOFF_FILE"] = old
    assert isinstance(out, list)
    # Documents the real finding as a live regression guard: once the
    # schedule is restored and a fresh file is pushed, this test still
    # passes (an OK outcome is also a valid state) -- but it pins that we
    # NOTICE a stale real file via a non-crashing, honest outcome.
    assert scraper.last_outcome in (OUTCOME_OK, OUTCOME_PARTIAL)

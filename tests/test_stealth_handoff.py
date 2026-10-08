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
    """Sanity check against the actual committed hand-off (not a fixture) --
    confirms the real on-disk hand-off (the sharded directory since 2026-10-09,
    or the legacy single file before it) still parses and ingests cleanly."""
    if not (m._HANDOFF_DIR / "manifest.json").exists() and not m._HANDOFF.exists():
        pytest.skip("no docs/handoff/stealth_leads/ or stealth_leads.json in this checkout")
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


# =================================================================================================
# Sharded hand-off (2026-10-09). The single file reached 93.8 MiB on 2026-10-08, 1.2 MiB under the
# repo's 95 MiB commit gate. The writer now emits docs/handoff/stealth_leads/manifest.json + one
# JSON Lines shard per source (stealth_handoff_store); the reader prefers it and falls back to the
# legacy file. Every row below is made up.
# =================================================================================================

import gzip  # noqa: E402
import importlib.util  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

from foreclosure_scraper import stealth_handoff_store as store  # noqa: E402
from foreclosure_scraper.models import Listing  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _line(source: str = "counties_sc.sc_public_index", case: str = "X-1") -> str:
    return json.dumps({**_valid_lead(source), "case_number": case})


def _lines(source: str, n: int) -> list[str]:
    """n made-up leads of one source, all the same length (fixed-width case numbers)."""
    return [_line(source, f"{source.rsplit('.', 1)[-1]}-{i:04d}") for i in range(n)]


def _meta(gen: str | None = None) -> dict:
    return {"generated_at": gen or datetime.now(timezone.utc).isoformat(), "host": "test-host",
            "sources_run": 2, "by_source": [{"slug": "a", "count": 1, "outcome": "OK"}]}


def _point_reader_at(monkeypatch, handoff_dir: Path) -> None:
    monkeypatch.delenv("HANDOFF_FILE", raising=False)
    monkeypatch.setattr(m, "_HANDOFF", store.legacy_file(handoff_dir))
    monkeypatch.setattr(m, "_HANDOFF_DIR", store.shard_dir(handoff_dir))


def _fresh_scraper():
    s = m.StealthHandoffScraper()
    s.last_outcome, s.last_reason = OUTCOME_OK, ""
    return s


def test_sharded_round_trip_one_source_per_shard_and_every_lead_back(tmp_path, monkeypatch):
    lines = {"counties_sc.sc_public_index": _lines("counties_sc.sc_public_index", 3),
             "national.nc_sos_ucc": _lines("national.nc_sos_ucc", 2)}
    man = store.write_sharded(tmp_path, _meta(), lines)
    assert man["format"] == store.FORMAT and man["lead_count"] == 5 and man["shard_count"] == 2
    files = sorted(p.name for p in (tmp_path / "stealth_leads").iterdir())
    assert files == ["counties_sc.sc_public_index.000.jsonl", "manifest.json",
                     "national.nc_sos_ucc.000.jsonl"]
    assert {sh["slug"]: sh["count"] for sh in man["shards"]} == {
        "counties_sc.sc_public_index": 3, "national.nc_sos_ucc": 2}
    _point_reader_at(monkeypatch, tmp_path)
    scraper = _fresh_scraper()
    out = asyncio.run(scraper.fetch())
    assert len(out) == 5 and scraper.last_outcome == OUTCOME_OK
    assert sorted(li.case_number for li in out) == sorted(
        json.loads(x)["case_number"] for v in lines.values() for x in v)


def test_a_source_over_the_cap_continues_in_numbered_shards_each_under_it(tmp_path):
    lines = {"counties_nc.nc_ecourts_lis_pendens": _lines("counties_nc.nc_ecourts_lis_pendens", 40)}
    one = len(lines["counties_nc.nc_ecourts_lis_pendens"][0].encode()) + 1
    cap = one * 7                                  # 7 leads per shard
    man = store.write_sharded(tmp_path, _meta(), lines, max_bytes=cap)
    assert [sh["file"] for sh in man["shards"]] == [
        f"counties_nc.nc_ecourts_lis_pendens.{i:03d}.jsonl" for i in range(6)]
    assert [sh["count"] for sh in man["shards"]] == [7, 7, 7, 7, 7, 5]
    for sh in man["shards"]:
        assert sh["bytes"] <= cap
        assert (tmp_path / "stealth_leads" / sh["file"]).stat().st_size == sh["bytes"]


def test_the_writer_removes_the_legacy_file_and_the_shards_of_a_source_that_vanished(tmp_path):
    (tmp_path / "stealth_leads.json").write_text(json.dumps({"leads": [_valid_lead()]}))
    store.write_sharded(tmp_path, _meta(), {"a.one": _lines("a.one", 2), "b.two": _lines("b.two", 1)})
    assert not (tmp_path / "stealth_leads.json").exists()
    store.write_sharded(tmp_path, _meta(), {"a.one": _lines("a.one", 1)})
    assert sorted(p.name for p in (tmp_path / "stealth_leads").iterdir()) == [
        "a.one.000.jsonl", "manifest.json"]
    assert not any(p.name.startswith(".stealth_leads") for p in tmp_path.iterdir()), \
        "the build and backup directories are gone after the swap"


def test_no_manifest_falls_back_to_the_legacy_single_file(tmp_path, monkeypatch):
    _write_handoff(tmp_path, [_valid_lead(), _valid_lead()],
                   generated_at=datetime.now(timezone.utc).isoformat())
    _point_reader_at(monkeypatch, tmp_path)
    scraper = _fresh_scraper()
    assert len(asyncio.run(scraper.fetch())) == 2 and scraper.last_outcome == OUTCOME_OK


def test_the_manifest_wins_unless_the_legacy_file_is_newer(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    store.write_sharded(tmp_path, _meta((now - timedelta(hours=1)).isoformat()),
                        {"a.one": _lines("a.one", 3)}, remove_legacy=False)
    _point_reader_at(monkeypatch, tmp_path)
    # an older legacy file next to the shards is ignored
    _write_handoff(tmp_path, [_valid_lead()], generated_at=(now - timedelta(days=2)).isoformat())
    assert len(asyncio.run(_fresh_scraper().fetch())) == 3
    # a NEWER legacy file (only an old writer makes one) is the hand-off to read
    _write_handoff(tmp_path, [_valid_lead()], generated_at=now.isoformat())
    assert len(asyncio.run(_fresh_scraper().fetch())) == 1


def test_a_missing_or_tampered_shard_is_reported_and_the_rest_still_ingest(tmp_path, monkeypatch):
    store.write_sharded(tmp_path, _meta(), {"a.one": _lines("a.one", 2), "b.two": _lines("b.two", 3),
                                            "c.three": _lines("c.three", 4)})
    d = tmp_path / "stealth_leads"
    (d / "a.one.000.jsonl").unlink()
    (d / "b.two.000.jsonl").write_text(_line("b.two", "edited") + "\n")     # sha256 no longer matches
    _point_reader_at(monkeypatch, tmp_path)
    scraper = _fresh_scraper()
    out = asyncio.run(scraper.fetch())
    assert len(out) == 4
    assert scraper.last_outcome == OUTCOME_PARTIAL
    assert "2 of 3 hand-off shards missing or corrupt (1 missing, 1 corrupt)" in scraper.last_reason


def test_a_shard_name_outside_the_directory_is_never_read(tmp_path, monkeypatch):
    store.write_sharded(tmp_path, _meta(), {"a.one": _lines("a.one", 1)})
    (tmp_path / "evil.jsonl").write_text(_line("x.evil", "evil") + "\n")
    man_path = tmp_path / "stealth_leads" / "manifest.json"
    man = json.loads(man_path.read_text())
    man["shards"].append({"file": "../evil.jsonl", "count": 1})
    man_path.write_text(json.dumps(man))
    _point_reader_at(monkeypatch, tmp_path)
    out = asyncio.run(_fresh_scraper().fetch())
    assert [li.case_number for li in out] == ["one-0000"]


def test_an_unreadable_manifest_falls_back_to_the_legacy_file_and_says_so(tmp_path, monkeypatch):
    (tmp_path / "stealth_leads").mkdir()
    (tmp_path / "stealth_leads" / "manifest.json").write_text("{not json")
    _point_reader_at(monkeypatch, tmp_path)
    scraper = _fresh_scraper()
    assert asyncio.run(scraper.fetch()) == []
    assert scraper.last_outcome == OUTCOME_PARTIAL and "unreadable" in scraper.last_reason
    _write_handoff(tmp_path, [_valid_lead()], generated_at=datetime.now(timezone.utc).isoformat())
    scraper = _fresh_scraper()
    assert len(asyncio.run(scraper.fetch())) == 1
    assert scraper.last_outcome == OUTCOME_PARTIAL and "legacy file" in scraper.last_reason


def test_gzip_shards_read_the_same(tmp_path, monkeypatch):
    man = store.write_sharded(tmp_path, _meta(), {"a.one": _lines("a.one", 3)}, gzip_shards=True)
    assert man["shards"][0]["file"] == "a.one.000.jsonl.gz"
    raw = (tmp_path / "stealth_leads" / "a.one.000.jsonl.gz").read_bytes()
    assert len(gzip.decompress(raw).splitlines()) == 3
    monkeypatch.setenv("HANDOFF_FILE", str(tmp_path / "stealth_leads" / "manifest.json"))
    assert len(asyncio.run(_fresh_scraper().fetch())) == 3


def test_freshness_comes_from_the_manifest(tmp_path, monkeypatch):
    store.write_sharded(tmp_path, _meta((datetime.now(timezone.utc) - timedelta(days=9)).isoformat()),
                        {"a.one": _lines("a.one", 1)})
    monkeypatch.setenv("HANDOFF_FILE", str(tmp_path / "stealth_leads"))
    scraper = _fresh_scraper()
    assert len(asyncio.run(scraper.fetch())) == 1
    assert scraper.last_outcome == OUTCOME_PARTIAL and "severely stale" in scraper.last_reason


# ---- the Mac writer, scripts/run_stealth_sources.py, end to end with fake scrapers ------------

def _load_writer():
    spec = importlib.util.spec_from_file_location("run_stealth_sources_t",
                                                  REPO / "scripts" / "run_stealth_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeScraper:
    def __init__(self, slug, rows, outcome="OK"):
        self.slug, self._rows, self.last_outcome = slug, rows, outcome

    async def safe_run(self):
        return self._rows


def test_the_mac_writer_shards_by_producing_scraper_and_the_vm_reader_gets_every_lead(
        tmp_path, monkeypatch):
    w = _load_writer()
    rows_a = [Listing.model_validate({**_valid_lead("counties_sc.sc_public_index"),
                                      "case_number": f"A-{i}"}) for i in range(3)]
    rows_b = [Listing.model_validate({**_valid_lead("national.nc_sos_ucc"), "case_number": "B-0"})]
    fakes = [_FakeScraper("counties_sc.sc_public_index", rows_a),
             _FakeScraper("national.nc_sos_ucc", rows_b), _FakeScraper("x.empty", [], "ZERO_RESULT")]
    monkeypatch.setattr(w, "residential_slugs", lambda: {f.slug for f in fakes})
    monkeypatch.setattr(w, "all_scrapers", lambda: fakes)
    monkeypatch.setattr(w, "HANDOFF_ROOT", tmp_path)
    monkeypatch.setattr(w, "HANDOFF_DIR", store.shard_dir(tmp_path))
    monkeypatch.setattr(w, "PUSH", False)
    assert asyncio.run(w.main()) == 0
    man = json.loads((tmp_path / "stealth_leads" / "manifest.json").read_text())
    assert man["lead_count"] == 4 and man["sources_run"] == 3
    assert [s["slug"] for s in man["by_source"]] == sorted(f.slug for f in fakes)
    assert {sh["file"] for sh in man["shards"]} == {"counties_sc.sc_public_index.000.jsonl",
                                                    "national.nc_sos_ucc.000.jsonl"}
    _point_reader_at(monkeypatch, tmp_path)
    out = asyncio.run(_fresh_scraper().fetch())
    assert sorted(li.case_number for li in out) == ["A-0", "A-1", "A-2", "B-0"]
    assert [li.model_dump() for li in sorted(out, key=lambda x: x.case_number)][:3] == \
        [li.model_dump() for li in rows_a]


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=env).stdout


def test_the_hand_off_commit_carries_only_the_hand_off_and_deletes_the_legacy_file(
        tmp_path, monkeypatch):
    origin, repo = tmp_path / "origin.git", tmp_path / "repo"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.org")
    _git(repo, "config", "core.hooksPath", "/dev/null")
    (repo / "docs" / "handoff").mkdir(parents=True)
    (repo / "docs" / "handoff" / "stealth_leads.json").write_text('{"leads": []}')
    (repo / "other.txt").write_text("v1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    (repo / "other.txt").write_text("v2 staged by someone else")
    _git(repo, "add", "other.txt")

    w = _load_writer()
    monkeypatch.setattr(w, "ROOT", repo)
    monkeypatch.setattr(w, "HANDOFF_ROOT", repo / "docs" / "handoff")
    monkeypatch.setattr(w, "HANDOFF_DIR", repo / "docs" / "handoff" / "stealth_leads")
    monkeypatch.setattr(w, "LEGACY", repo / "docs" / "handoff" / "stealth_leads.json")
    store.write_sharded(repo / "docs" / "handoff", _meta(), {"a.one": _lines("a.one", 2)})
    w._publish(2, [])

    changed = _git(repo, "show", "--name-status", "--format=%s", "HEAD").split("\n")
    assert changed[0].startswith("mac stealth hand-off: 2 leads")
    assert sorted(x for x in changed[1:] if x) == [
        "A\tdocs/handoff/stealth_leads/a.one.000.jsonl",
        "A\tdocs/handoff/stealth_leads/manifest.json",
        "D\tdocs/handoff/stealth_leads.json"]
    # someone else's change stays out of the hand-off commit and in the working tree (the
    # pull --rebase --autostash before the push hands it back unstaged)
    assert (repo / "other.txt").read_text() == "v2 staged by someone else"
    assert "other.txt" in _git(repo, "status", "--porcelain")
    assert _git(origin, "log", "-1", "--format=%s", "main").startswith("mac stealth hand-off")

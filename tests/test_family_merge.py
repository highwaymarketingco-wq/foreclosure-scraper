"""scripts/family_merge.py: scrape one family off the lock, merge it under the lock (audit O2, A2).

Nothing here loads the real board or runs a real scraper: scrapers are fakes, and the merge phase
is driven through a stand-in for scripts/merge_today_sources.py that writes to a scratch docs dir.
"""
from __future__ import annotations

import asyncio
import gzip
import importlib
import json
import os
import sys
import time
import types
from pathlib import Path

import pytest

from foreclosure_scraper import web_artifact as wa
from foreclosure_scraper.models import Listing, ListingType

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
fm = importlib.import_module("family_merge")


class FakeScraper:
    def __init__(self, slug, rows=0, outcome="ok", raises=None, sleeps=0.0):
        self.slug, self._rows, self.last_outcome, self._raises, self._sleeps = slug, rows, outcome, raises, sleeps

    async def safe_run(self):
        if self._sleeps:
            await asyncio.sleep(self._sleeps)
        if self._raises:
            raise self._raises
        return [Listing(source=self.slug if i % 2 else "", source_url=f"{self.slug}/{i}",
                        listing_type=ListingType.TAX_LIEN, state="NC", county="Gaston",
                        street_address=f"{i} Main St", raw={}) for i in range(self._rows)]


@pytest.fixture
def family(tmp_path, monkeypatch):
    import foreclosure_scraper.scrapers._registry as reg
    scrapers = {}
    monkeypatch.setattr(reg, "all_scrapers", lambda: list(scrapers.values()))
    monkeypatch.setattr(fm, "STAGE_DIR", tmp_path / "stage")
    monkeypatch.setitem(fm.FAMILIES, "nc_tax", {**fm.FAMILIES["nc_tax"], "slugs": []})
    rows_file = tmp_path / "rows.txt"
    monkeypatch.setenv("FAMILY_ROWS_FILE", str(rows_file))

    def add(*fakes):
        for f in fakes:
            scrapers[f.slug] = f
            fm.FAMILIES["nc_tax"]["slugs"].append(f.slug)
    return types.SimpleNamespace(add=add, rows_file=rows_file, tmp=tmp_path)


def test_every_family_slug_is_a_registered_scraper():
    """An unknown slug is a hard error, never a silent no-op (the merge_today_sources rule)."""
    for name, cfg in fm.FAMILIES.items():
        if cfg["slugs"]:
            assert len(fm._check_slugs(name)) == len(cfg["slugs"]), name


def test_the_families_cover_the_largest_unscheduled_sources():
    listed = set(fm.FAMILIES["qpaybill"]["slugs"]) | set(fm.FAMILIES["nc_tax"]["slugs"]) | set(fm.FAMILIES["sc_tax"]["slugs"])
    assert "counties_sc.qpaybill_delinquent_roll" in listed          # 33,528 rows
    assert "counties_nc.rutherford_tax" in listed and "counties_sc.greenville_delinquent_tax" in listed
    assert fm.FAMILIES["nc_ecourts"]["standalone"] == "nc_ecourts_judgments"
    assert fm.FAMILIES["qpaybill"]["post"] == "qpaybill_balances"


def test_scrape_stages_each_source_and_records_who_succeeded(family):
    family.add(FakeScraper("counties_nc.a", rows=5), FakeScraper("counties_nc.b", rows=0),
               FakeScraper("counties_nc.c", rows=3, outcome="TIMEOUT: soft cap"),
               FakeScraper("counties_nc.d", raises=RuntimeError("boom")))
    assert fm.phase_scrape("nc_tax") == 0
    stage, meta_path = fm._stage_paths("nc_tax")
    meta = json.loads(meta_path.read_text())
    src = meta["sources"]
    assert src["counties_nc.a"]["ok"] is True and src["counties_nc.a"]["rows"] == 5
    assert src["counties_nc.b"]["ok"] is False and src["counties_nc.b"]["rows"] == 0, "zero rows is not a success"
    assert src["counties_nc.c"]["ok"] is False, "rows with a TIMEOUT outcome are not a success"
    assert "RuntimeError" in src["counties_nc.d"]["outcome"], "one bad source must not lose the others"
    with gzip.open(stage, "rt") as fh:
        assert len([ln for ln in fh if ln.strip()]) == 8 == meta["rows"]
    assert family.rows_file.read_text() == "8"


def test_scrape_with_nothing_staged_exits_3_so_the_wrapper_fails_it(family):
    family.add(FakeScraper("counties_nc.a", rows=0))
    assert fm.phase_scrape("nc_tax") == 3


def test_a_per_scraper_timeout_keeps_the_sources_that_finished(family, monkeypatch):
    monkeypatch.setenv("FAMILY_SCRAPER_TIMEOUT", "0.3")
    family.add(FakeScraper("counties_nc.fast", rows=2), FakeScraper("counties_nc.slow", rows=9, sleeps=5))
    assert fm.phase_scrape("nc_tax") == 0
    meta = json.loads(fm._stage_paths("nc_tax")[1].read_text())
    assert meta["sources"]["counties_nc.fast"]["ok"] and meta["sources"]["counties_nc.slow"]["outcome"].startswith("timeout")
    assert meta["rows"] == 2


def _fake_mts(tmp_path, seen):
    docs = tmp_path / "board_docs"
    mts = types.ModuleType("merge_today_sources")
    mts.DOCS = docs
    mts.write_artifact = wa.write_artifact

    async def real_scrape_new():
        raise AssertionError("the merge phase must NOT scrape under the lock")
    mts._scrape_new = real_scrape_new

    def main():
        leads = asyncio.run(mts._scrape_new())
        seen["leads"] = leads
        seen["checkpoint_dir"] = os.environ.get("FORECLOSURE_CHECKPOINT_DIR")
        seen["merge_fast"] = os.environ.get("MERGE_FAST")
        mts.write_artifact(leads, {"by_source": {"x": len(leads)}, "notes": "partial merge"}, docs_dir=mts.DOCS)
        return 0
    mts.main = main
    return mts


def test_merge_replaces_the_scrape_with_the_staged_leads_and_stamps_per_source_success(family, monkeypatch):
    family.add(FakeScraper("counties_nc.a", rows=4), FakeScraper("counties_nc.dead", rows=0))
    fm.phase_scrape("nc_tax")
    seen: dict = {}
    mts = _fake_mts(family.tmp, seen)
    monkeypatch.setitem(sys.modules, "merge_today_sources", mts)
    monkeypatch.delenv("FORECLOSURE_CHECKPOINT_DIR", raising=False)
    monkeypatch.delenv("MERGE_FAST", raising=False)
    assert fm.phase_merge("nc_tax") == 0
    assert len(seen["leads"]) == 4
    assert seen["checkpoint_dir"] == "data/checkpoint_family_nc_tax", "a crash in one family must never be resumed by another"
    assert seen["merge_fast"] == "1"
    meta = json.loads((mts.DOCS / "run_meta.json").read_text())
    assert set(meta["source_last_success"]) == {"counties_nc.a"}, "only a source that returned rows is stamped fresh"
    assert "family merge [nc_tax]" in meta["notes"]
    assert family.rows_file.read_text() == "4"


def test_merge_refuses_a_stale_or_missing_stage(family, monkeypatch):
    monkeypatch.setitem(sys.modules, "merge_today_sources", _fake_mts(family.tmp, {}))
    with pytest.raises(SystemExit) as ei:
        fm.phase_merge("nc_tax")
    assert "nothing staged" in str(ei.value)
    family.add(FakeScraper("counties_nc.a", rows=2))
    fm.phase_scrape("nc_tax")
    stage, _ = fm._stage_paths("nc_tax")
    old = time.time() - 40 * 3600
    os.utime(stage, (old, old))
    with pytest.raises(SystemExit) as ei:
        fm.phase_merge("nc_tax")
    assert "refusing to merge stale data" in str(ei.value)


def test_post_phase_runs_the_qpaybill_balance_pass(monkeypatch):
    called = {}
    fake = types.ModuleType("qpaybill_tax_refresh")
    fake.main = lambda: called.setdefault("ran", 0)
    monkeypatch.setitem(sys.modules, "qpaybill_tax_refresh", fake)
    assert fm.phase_post("qpaybill") == 0 and called == {"ran": 0}
    assert fm.phase_post("nc_tax") == 0


def test_list_prints_every_family(capsys):
    assert fm.main(["--list"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"qpaybill", "nc_tax", "sc_tax", "nc_ecourts"}

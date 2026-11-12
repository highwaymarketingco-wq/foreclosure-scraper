#!/usr/bin/env python3
"""Per-family scheduled merge: scrape ONE family of sources, then merge it into the board.

WHY (audit 2026-09-21 O2, A2). 98.7% of the 170k board comes from sources no scheduler
refreshes: the only refresh is a 15 to 57 hour full run that has not landed since 8/29.
The pattern that works is scripts/merge_today_sources.py (scrape a chosen set of
sources, dedupe them into the persisted board, run the enrichment chain, write). This
wraps that pattern per FAMILY so each family gets its own short job, timeout, lock and
job event, and so the network-bound scrape does NOT hold the board lock.

    family_merge.py <family> --phase scrape   no lock. Runs the family's scrapers and
                                              stages their leads in data/family_stage/.
    family_merge.py <family> --phase merge    caller HOLDS the board lock. Folds the staged
                                              leads into the board via merge_today_sources.
    family_merge.py <family> --phase post     caller holds the lock. Optional follow-up
                                              (qpaybill: fill balances on county-tax rows).
    family_merge.py --list                    families and their slugs (JSON)

The wrappers scripts/run_family_<family>.sh drive the three phases.

WHAT THE MERGE DOES DIFFERENTLY FROM merge_today_sources.py
  * `_scrape_new` is replaced by the staged leads, so nothing is scraped under the lock.
  * A stage older than FAMILY_STAGE_MAX_AGE_H (36) is refused: never merge stale data.
  * Its own checkpoint directory per family and a 6 hour checkpoint age limit, so a crash
    in one family can never be "resumed" by another family's run onto a stale board.
  * The summary handed to write_artifact carries `source_refreshed`, the per-source
    last-success stamp (audit A2): only a source whose scrape returned rows and did not
    fail is stamped, so run_meta.source_last_success measures freshness per source
    instead of trusting row last_seen, which any merge bumps.

Safe on the 8 GB Mac: MERGE_FAST=1 by default (the proven landing mode; skips the per-lead
GIS chain that can wedge the event loop). Never run two at once: the wrappers serialise on
the board lock.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

STAGE_DIR = REPO / "data" / "family_stage"

# family -> what to scrape. `slugs` are registered scraper slugs (checked against the
# registry: an unknown slug is a hard error, never a silent no-op). `standalone` is the
# nc_ecourts_judgments lane, which is not a registered scraper.
FAMILIES = {
    "qpaybill": {
        "desc": "SC treasurer delinquent-tax roll on qPayBill portals (33,528 board rows)",
        "slugs": ["counties_sc.qpaybill_delinquent_roll"],
        "post": "qpaybill_balances",
    },
    "nc_tax": {
        "desc": "NC county delinquent-tax pulls (Rutherford, PTS Cloud, county PDFs and CSVs, Buncombe, Transylvania)",
        "slugs": [
            "counties_nc.rutherford_tax",
            "counties_nc.nc_ptscloud_delinquent_tax",
            "counties_nc.nc_county_pdf_delinquent_tax",
            "counties_nc.nc_county_csv_delinquent_tax",
            "counties_nc.buncombe_delinquent_tax",
            "counties_nc.transylvania_delinquent_tax",
        ],
    },
    "sc_tax": {
        "desc": "SC county delinquent-tax pulls (Berkeley, Greenville, Florence, Pickens, Spartanburg, Charleston, Dillon, Cherokee)",
        "slugs": [
            "counties_sc.berkeley_paystar_tax",
            "counties_sc.greenville_delinquent_tax",
            "counties_sc.florence_delinquent_tax",
            "counties_sc.pickens_delinquent_parcels",
            "counties_sc.spartanburg_delinquent_tax",
            "counties_sc.charleston_delinquent_tax",
            "counties_sc.dillon_delinquent_tax",
            "counties_sc.cherokee_delinquent_tax",
        ],
    },
    "nc_ecourts": {
        "desc": "NC eCourts open Judgment Search (lis pendens and liens; 3,273 board rows)",
        "slugs": [],
        "standalone": "nc_ecourts_judgments",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stage_paths(family: str):
    return STAGE_DIR / f"{family}.jsonl.gz", STAGE_DIR / f"{family}.meta.json"


def _write_rows_file(n: int) -> None:
    """The wrapper reads this for the job event's rows_changed."""
    f = os.environ.get("FAMILY_ROWS_FILE")
    if f:
        try:
            Path(f).write_text(str(int(n)))
        except OSError:
            pass


def _check_slugs(family: str) -> list:
    from foreclosure_scraper.scrapers._registry import all_scrapers
    cfg = FAMILIES[family]
    have = {s.slug: s for s in all_scrapers()}
    unknown = [s for s in cfg["slugs"] if s not in have]
    if unknown:
        raise SystemExit(f"family_merge: {family}: {len(unknown)} slug(s) match no registered scraper "
                         f"and would silently contribute nothing: {unknown}")
    return [have[s] for s in cfg["slugs"]]


# --------------------------------------------------------------------------- scrape phase

async def _scrape_family(family: str) -> dict:
    """Run each scraper of the family, staging its leads as it finishes so a wall-clock
    kill still leaves every finished source staged."""
    from foreclosure_scraper.models import Listing  # noqa: F401  (import check)
    cfg = FAMILIES[family]
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    stage, meta_path = _stage_paths(family)
    per_scraper = float(os.environ.get("FAMILY_SCRAPER_TIMEOUT", "5400"))
    meta = {"family": family, "started": _now_iso(), "sources": {}}
    leads_all: list = []

    def _flush():
        tmp = stage.with_name(stage.name + f".{os.getpid()}.tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            for li in leads_all:
                fh.write(li.model_dump_json() + "\n")
        os.replace(tmp, stage)
        meta["staged_at"] = _now_iso()
        meta["rows"] = len(leads_all)
        meta_path.write_text(json.dumps(meta, indent=1))

    if cfg.get("standalone") == "nc_ecourts_judgments":
        rows, info = await _scrape_nc_ecourts_judgments()
        leads_all.extend(rows)
        meta["sources"]["nc_ecourts_judgments"] = info
        _flush()
        return meta

    for s in _check_slugs(family):
        t0 = time.time()
        info = {"rows": 0, "ok": False, "outcome": "not_run", "seconds": 0}
        try:
            leads = list(await asyncio.wait_for(s.safe_run(), timeout=per_scraper))
            info["rows"] = len(leads)
            info["outcome"] = str(getattr(s, "last_outcome", "?"))
            # A scraper that came back with rows and did not report a failure outcome.
            bad = any(w in info["outcome"].lower() for w in ("error", "timeout", "blocked", "fail", "wall"))
            info["ok"] = len(leads) > 0 and not bad
            for li in leads:
                if not li.source:
                    li.source = s.slug
            leads_all.extend(leads)
        except asyncio.TimeoutError:
            info["outcome"] = f"timeout_{int(per_scraper)}s"
        except Exception as exc:  # noqa: BLE001 - one bad source must not lose the others
            info["outcome"] = f"error: {type(exc).__name__}: {str(exc)[:120]}"
        info["seconds"] = int(time.time() - t0)
        meta["sources"][s.slug] = info
        print(f"  {s.slug}: {info['rows']} ({info['outcome']}) {info['seconds']}s", flush=True)
        _flush()
    return meta


async def _scrape_nc_ecourts_judgments():
    """scripts/scrape_ncecourts.py (open Judgment Search JSON, no login, no WAF) writes
    /tmp/ncecourts_results.json; scripts/ingest_all.ingest_ncecourts turns it into Listings.
    Rows are stored DATELESS: the structured sale_date held the judgment date, which made
    _active_only drop every row (scripts/fix_nc_ecourts_judgments.py); the judgment date
    survives in raw.nc_ecourts.judgment_date."""
    import subprocess
    out = Path("/tmp/ncecourts_results.json")
    before = out.stat().st_mtime if out.exists() else 0
    t0 = time.time()
    proc = await asyncio.create_subprocess_exec(sys.executable, str(REPO / "scripts" / "scrape_ncecourts.py"),
                                                cwd=str(REPO))
    try:
        await asyncio.wait_for(proc.wait(), timeout=float(os.environ.get("FAMILY_SCRAPER_TIMEOUT", "5400")))
    except asyncio.TimeoutError:
        proc.kill()
        return [], {"rows": 0, "ok": False, "outcome": "timeout", "seconds": int(time.time() - t0)}
    info = {"rows": 0, "ok": False, "outcome": f"rc={proc.returncode}", "seconds": int(time.time() - t0)}
    if proc.returncode != 0 or not out.exists() or out.stat().st_mtime <= before:
        info["outcome"] += " (no fresh results file)"
        return [], info
    import ingest_all  # scripts/ingest_all.py (import has no side effects; main() is guarded)
    rows = ingest_all.ingest_ncecourts()
    for li in rows:
        li.sale_date = None
    info.update({"rows": len(rows), "ok": len(rows) > 0})
    return rows, info


def phase_scrape(family: str) -> int:
    meta = asyncio.run(_scrape_family(family))
    ok = [k for k, v in meta["sources"].items() if v.get("ok")]
    print(f"family_merge[{family}] scrape done: {meta.get('rows', 0)} rows staged, "
          f"{len(ok)}/{len(meta['sources'])} sources ok", flush=True)
    _write_rows_file(meta.get("rows", 0))
    return 0 if meta.get("rows", 0) > 0 else 3


# --------------------------------------------------------------------------- merge phase

def _load_stage(family: str):
    from foreclosure_scraper.models import Listing
    stage, meta_path = _stage_paths(family)
    if not stage.exists() or not meta_path.exists():
        raise SystemExit(f"family_merge: {family}: nothing staged (run --phase scrape first)")
    meta = json.loads(meta_path.read_text())
    age_h = (time.time() - stage.stat().st_mtime) / 3600.0
    max_h = float(os.environ.get("FAMILY_STAGE_MAX_AGE_H", "36"))
    if age_h > max_h:
        raise SystemExit(f"family_merge: {family}: staged data is {age_h:.1f} h old (limit {max_h:g} h); "
                         f"refusing to merge stale data")
    leads = []
    with gzip.open(stage, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                leads.append(Listing.model_validate_json(line))
    return leads, meta


def phase_merge(family: str) -> int:
    # Per-family checkpoint dir and a short age limit, BEFORE merge_today_sources is imported
    # (checkpoint.CHECKPOINT_DIR is read from the env once, at import).
    os.environ["FORECLOSURE_CHECKPOINT_DIR"] = f"data/checkpoint_family_{family}"
    os.environ.setdefault("FORECLOSURE_CHECKPOINT_MAX_AGE_H", "6")
    os.environ.setdefault("MERGE_FAST", "1")
    leads, meta = _load_stage(family)
    print(f"family_merge[{family}] merging {len(leads)} staged rows "
          f"(staged {meta.get('staged_at')})", flush=True)
    _write_rows_file(len(leads))

    import merge_today_sources as mts  # scripts/merge_today_sources.py; main() is guarded

    async def _staged_scrape_new():
        return list(leads)

    mts._scrape_new = _staged_scrape_new

    refreshed = {slug: _now_iso() for slug, v in meta.get("sources", {}).items() if v.get("ok")}
    real_write = mts.write_artifact

    def _write_with_stamps(listings, summary, docs_dir=mts.DOCS):
        summary = dict(summary or {})
        summary["source_refreshed"] = refreshed
        summary["notes"] = (f"family merge [{family}]: {len(leads)} staged rows, "
                            f"{len(refreshed)} source(s) refreshed")
        return real_write(listings, summary, docs_dir=docs_dir)

    mts.write_artifact = _write_with_stamps
    return mts.main()


# --------------------------------------------------------------------------- post phase

def phase_post(family: str) -> int:
    post = FAMILIES[family].get("post")
    if post == "qpaybill_balances":
        import qpaybill_tax_refresh  # scripts/qpaybill_tax_refresh.py
        return qpaybill_tax_refresh.main()
    print(f"family_merge[{family}]: no post step")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("family", nargs="?", choices=sorted(FAMILIES))
    ap.add_argument("--phase", choices=("scrape", "merge", "post"))
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    if args.list or not args.family:
        print(json.dumps({k: {"desc": v["desc"], "slugs": v["slugs"], "post": v.get("post"),
                              "standalone": v.get("standalone")} for k, v in FAMILIES.items()}, indent=1))
        return 0
    if not args.phase:
        ap.error("--phase is required")
    return {"scrape": phase_scrape, "merge": phase_merge, "post": phase_post}[args.phase](args.family)


if __name__ == "__main__":
    sys.exit(main())

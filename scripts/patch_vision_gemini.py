"""Fast re-Vision patch: apply Gemini Vision to the CURRENT docs/listings.json
without re-running the full pipeline, then recompute calc + grade + rewrite.

Use when the scraped/enriched data is fresh but Vision needs (re)running on a
different provider/config. Honors VISION_PROVIDER / VISION_MAX_LISTINGS /
VISION_INTER_CALL_DELAY from the env (run_local.sh-style). Gemini runs one
parallel stream per key.

  GEMINI_API_KEY_1=.. GEMINI_API_KEY_2=.. VISION_PROVIDER=gemini \
    VISION_MAX_LISTINGS=800 uv run python scripts/patch_vision_gemini.py

BOARD I/O CONTRACT (do not regress):
  read  -> web_artifact.load_board(), which merges the lazy-detail sidecar
           (docs/listings_detail.json) back into each lead's raw. "vision" is a
           LAZY_DETAIL_KEY, so a plain json.loads of the slim listings.json sees
           ZERO vision reports and this pass re-grades the same head of the list
           every single day instead of advancing coverage.
  write -> web_artifact.write_artifact(), which re-splits the sidecar and emits
           the .gz twins. Hand-writing listings.json silently wipes the sidecar.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_vision import enrich_with_vision
from foreclosure_scraper.valuation import calc as valuation_calc
from foreclosure_scraper.valuation import grading as valuation_grading
from foreclosure_scraper.web_artifact import load_board, write_artifact

DOCS = Path(__file__).resolve().parent.parent / "docs"


def _hydrate(d: dict) -> Listing | None:
    """Lenient record -> Listing. Drops unknown keys and coerces the two enum
    fields, so a record that strict Listing.model_validate rejects can still be
    recovered instead of being dropped from the published board."""
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    if isinstance(fields.get("listing_type"), str):
        try:
            fields["listing_type"] = ListingType(fields["listing_type"])
        except ValueError:
            fields.pop("listing_type", None)
    if isinstance(fields.get("property_kind"), str):
        try:
            fields["property_kind"] = PropertyKind(fields["property_kind"])
        except ValueError:
            fields.pop("property_kind", None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


def _merge_sidecar(docs: Path) -> list[dict]:
    """Raw board records with the index-aligned lazy-detail sidecar folded back
    into each record's raw — the same merge load_board() performs, minus the
    validation step. Used only by the no-shrink recovery path."""
    records = json.loads((docs / "listings.json").read_text())
    detail_path = docs / "listings_detail.json"
    details: list = []
    if detail_path.exists():
        try:
            details = json.loads(detail_path.read_text())
        except Exception:  # noqa: BLE001
            details = []
    for i, rec in enumerate(records):
        if i < len(details) and isinstance(details[i], dict) and details[i]:
            raw = rec.get("raw")
            if isinstance(raw, dict):
                raw.update(details[i])
    return records


def load_board_no_shrink(docs: Path | str = DOCS) -> tuple[list[Listing], int]:
    """load_board() plus a hard never-shrink guarantee.

    load_board() silently skips any record that fails Listing.model_validate.
    Publishing a board with fewer leads than it had is a far worse bug than the
    stale-coverage one this script exists to fix, so when the counts disagree we
    re-load every record through the lenient hydrator and keep the strays.

    Returns (listings, n_records_on_disk) so the caller can hard-guard the write.
    """
    docs = Path(docs)
    n_records = len(json.loads((docs / "listings.json").read_text()))
    board = load_board(docs)
    if len(board) == n_records:
        return board, n_records
    print(f"[{time.strftime('%H:%M:%S')}] load_board dropped "
          f"{n_records - len(board)} invalid record(s) — recovering them leniently "
          f"so the published board cannot shrink", flush=True)
    recovered: list[Listing] = []
    for rec in _merge_sidecar(docs):
        try:
            recovered.append(Listing.model_validate(rec))
            continue
        except Exception:  # noqa: BLE001
            pass
        li = _hydrate(rec)
        if li is not None:
            recovered.append(li)
    return recovered, n_records


def needs_vision(li: Listing) -> bool:
    """Daily-incremental target test: score listings that DON'T already have
    vision — PLUS ones only scored by the local Ollama floor (low quality), so a
    real provider upgrades them once fresh API quota is available. Each run thus
    advances coverage AND quality over the week as free quotas reset.

    Only correct when `li` came through load_board(): vision lives in the lazy
    sidecar, so a listing hydrated from the slim listings.json always looks
    un-scored.
    """
    vis = (li.raw or {}).get("vision")
    if not vis:
        return True
    return vis.get("_provider") == "ollama"


def _prior_meta(docs: Path) -> dict:
    """Carry the existing run_meta.json fields forward — write_artifact rebuilds
    run_meta from the summary it is handed, so an empty summary would blank the
    source_status / by_source panels the full run published."""
    try:
        meta = json.loads((docs / "run_meta.json").read_text())
    except Exception:  # noqa: BLE001
        return {}
    return {k: meta[k] for k in
            ("by_source", "by_state", "by_county_top", "source_status", "regressions", "errors")
            if k in meta}


async def main() -> int:
    # Read through load_board so the lazy-detail sidecar (vision/comps/cama) is
    # merged into raw BEFORE needs_vision() runs — otherwise every lead looks
    # un-scored and the pass re-grades the same head of the list forever.
    listings, n_records = load_board_no_shrink(DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)} listings "
          f"({n_records} records on disk, lazy-detail sidecar merged)", flush=True)

    cap = int(os.environ.get("VISION_MAX_LISTINGS", "800"))
    unscored = [li for li in listings if needs_vision(li)]
    already = len(listings) - len(unscored)
    print(f"[{time.strftime('%H:%M:%S')}] {already} already vision-scored; "
          f"{len(unscored)} un-scored. Running {os.environ.get('VISION_PROVIDER','?')} "
          f"vision (cap {cap}) on the un-scored, prioritized…", flush=True)
    t0 = time.time()
    # Hard wall-clock cap: a single hung worker (stuck network await) must NOT
    # stall the whole run forever. enrich_with_vision applies results to each
    # listing in place as it goes, so on timeout we still keep partial progress
    # and proceed to write/publish what was scored. Default 4h; +120s grace so
    # the pool's own internal VISION_MAX_SECONDS deadline fires first when set.
    hard_cap = float(os.environ.get("VISION_MAX_SECONDS", "14400")) + 120
    try:
        await asyncio.wait_for(
            enrich_with_vision(unscored, max_listings=cap), timeout=hard_cap)
    except asyncio.TimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] vision pass hit hard cap ({hard_cap:.0f}s) "
              f"— writing partial progress", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] vision pass done in {int(time.time()-t0)}s", flush=True)

    # Recompute calc + grade (condition_tier may have changed) onto every lead.
    scored = 0
    for li in listings:
        try:
            c = valuation_calc.compute(li)
            g = valuation_grading.grade(li, c)
            if not isinstance(li.raw, dict):
                li.raw = {}
            li.raw["calc"] = valuation_calc.to_dict(c)
            li.raw["grade"] = valuation_grading.to_dict(g)
        except Exception:
            pass
        if (li.raw or {}).get("vision"):
            scored += 1

    # Never publish a shrunken board. If anything above lost leads, bail BEFORE
    # the write — a stale board beats a truncated one.
    if len(listings) < n_records:
        print(f"[{time.strftime('%H:%M:%S')}] ABORT: would publish {len(listings)} of "
              f"{n_records} records — refusing to shrink the board", flush=True)
        return 2

    summary = _prior_meta(DOCS)
    summary["notes"] = (f"daily vision pass: {scored} of {len(listings)} listings "
                        f"have a vision report")
    write_artifact(listings, summary, docs_dir=DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] wrote {DOCS/'listings.json'} + sidecar — "
          f"{len(listings)} listings, {scored} total now have vision", flush=True)

    # Publish to the GitHub Pages dashboard (docs/ doesn't touch workflows,
    # so the normal token can push it).
    if os.environ.get("PATCH_PUBLISH", "1") == "1":
        import subprocess
        root = str(Path(__file__).parent.parent)
        try:
            # write_artifact emits four artifacts, and the dashboard fetches the
            # .gz twins — staging only listings.json would leave Pages serving a
            # stale gzip + a sidecar that no longer matches.
            subprocess.run(["git", "add", "docs/listings.json", "docs/listings.json.gz",
                            "docs/listings_detail.json", "docs/listings_detail.json.gz",
                            "docs/run_meta.json"], cwd=root, check=False)
            r = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=root)
            if r.returncode != 0:  # there are changes
                subprocess.run(["git", "commit", "-q", "-m",
                                f"daily vision: {scored} listings scored ({time.strftime('%Y-%m-%d')})"],
                               cwd=root, check=False)
                subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", "main"],
                               cwd=root, check=False)
                p = subprocess.run(["git", "push", "origin", "main"], cwd=root)
                print(f"[{time.strftime('%H:%M:%S')}] "
                      + ("dashboard published ✓" if p.returncode == 0 else "push failed ⚠"), flush=True)
        except Exception as exc:
            print(f"publish error: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

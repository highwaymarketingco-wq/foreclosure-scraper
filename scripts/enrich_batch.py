#!/usr/bin/env python3
"""Memory-safe batched enrichment for 8GB RAM.

Runs enrichers in small groups, each in its OWN process. Between batches,
the board is saved using a STREAMING writer that never holds all 53k listings
in memory at once — it writes one listing dict at a time to a temp file,
then gzips it. Peak memory during save ≈ board + 1 listing dict, not
board + 3 full copies.

Each batch: load board → run 2-3 enrichers → stream-save → exit → next batch
"""
import asyncio
import gc
import gzip
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ.setdefault("PATH", os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", ""))

from foreclosure_scraper.web_artifact import load_board, _to_dict, _slim_raw
from foreclosure_scraper.models import Listing

DOCS = Path(__file__).parent.parent / "docs"


# ─── Streaming save: write board to JSON without holding full copies ───
def stream_save_board(board: list[Listing], docs_dir: Path = DOCS):
    """Write listings.json + listings.json.gz without ever holding
    the full payload or full JSON string in memory.

    Writes one listing at a time to a temp file, then gzips the temp file
    in a streaming fashion. Peak memory: board + 1 listing dict.
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)
    listings_path = docs / "listings.json"
    gz_path = docs / "listings.json.gz"

    print(f"  [stream_save] Writing {len(board)} listings...")

    # Phase 1: Stream-write uncompressed JSON to temp file, one record at a time.
    #          We build the JSON array incrementally: [rec1, rec2, ... recN]
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json", dir=str(docs))
    total_bytes = 0
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write("[")
            for i, li in enumerate(board):
                if i > 0:
                    f.write(",")
                d = _to_dict(li)
                # Inline _slim_raw already done by _to_dict, but trim heavy keys
                raw = d.get("raw")
                if isinstance(raw, dict):
                    # Remove lazy detail keys (they go to detail sidecar)
                    for k in ("comps", "vision", "cama"):
                        raw.pop(k, None)
                chunk = json.dumps(d, ensure_ascii=False, default=str)
                f.write(chunk)
                total_bytes += len(chunk)
                if i % 10000 == 0:
                    print(f"    ...{i}/{len(board)} ({total_bytes//1024}KB)", flush=True)
                    gc.collect()
            f.write("]")
        print(f"  [stream_save] JSON written: {total_bytes//1024}KB")

        # Phase 2: Atomically replace listings.json
        os.replace(tmp_path, str(listings_path))

        # Phase 3: Stream-gzip the JSON file (read file → gzip → write .gz)
        #           This holds only the gzip buffer, not the full content.
        tmp_gz_fd, tmp_gz_path = tempfile.mkstemp(suffix=".gz", dir=str(docs))
        try:
            os.close(tmp_gz_fd)
            with open(listings_path, "rb") as src, \
                 gzip.GzipFile(filename=str(tmp_gz_path), mode="wb", compresslevel=9, mtime=0) as dst:
                while True:
                    block = src.read(65536)
                    if not block:
                        break
                    dst.write(block)
            os.replace(tmp_gz_path, str(gz_path))
        except Exception:
            if os.path.exists(tmp_gz_path):
                os.unlink(tmp_gz_path)
            raise

        print(f"  [stream_save] GZ written: {os.path.getsize(gz_path)//1024}KB")
        print(f"  [stream_save] Done — board saved atomically")

    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ─── Enricher batches (2-3 per batch to minimize memory growth) ──────
BATCHES = [
    # Batch 1: tax_owed + deed_chain (most important offline enrichers)
    [
        ("tax_owed", "foreclosure_scraper.enrichment_tax_owed", "enrich_tax_owed", 300, False),
        ("deed_chain", "foreclosure_scraper.enrichment_deed_chain", "enrich_deed_chain", 300, False),
    ],
    # Batch 2: tenure + fhfa_value
    [
        ("tenure", "foreclosure_scraper.enrichment_tenure", "enrich_tenure", 120, False),
        ("fhfa_value", "foreclosure_scraper.enrichment_fhfa_value", "enrich_fhfa_value", 300, True),
    ],
    # Batch 3: flood_zone (alone — network-heavy)
    [
        ("flood_zone", "foreclosure_scraper.enrichment_flood_zone", "enrich_flood_zones", 600, True),
    ],
    # Batch 4: vacant_landuse + bankruptcy_stay
    [
        ("vacant_landuse", "foreclosure_scraper.enrichment_vacant_landuse", "enrich_vacant_landuse", 120, False),
        ("bankruptcy_stay", "foreclosure_scraper.enrichment_bankruptcy_stay", "enrich_bankruptcy_stay", 120, False),
    ],
    # Batch 5: amount_owed + property_kind
    [
        ("amount_owed", "foreclosure_scraper.enrichment_amount_owed", "enrich_amount_owed", 300, False),
        ("property_kind", "foreclosure_scraper.enrichment_property_kind", "enrich_property_kind", 120, False),
    ],
    # Batch 6: derivation_flags + derived_signals
    [
        ("derivation_flags", "foreclosure_scraper.enrichment_derivation_flags", "enrich_derivation_flags", 120, False),
        ("derived_signals", "foreclosure_scraper.enrichment_derived_signals", "enrich_derived_signals", 120, False),
    ],
    # Batch 7: cama_condition + sc_cama
    [
        ("cama_condition", "foreclosure_scraper.enrichment_cama_condition", "enrich_cama_condition", 300, True),
        ("sc_cama", "foreclosure_scraper.enrichment_sc_cama", "enrich_sc_cama", 120, False),
    ],
    # Batch 8: process_timing + life_events
    [
        ("process_timing", "foreclosure_scraper.enrichment_process_timing", "enrich_process_timing", 120, False),
        ("life_events", "foreclosure_scraper.enrichment_life_events", "enrich_life_events", 120, False),
    ],
    # Batch 9: census_rent + equity
    [
        ("census_rent", "foreclosure_scraper.enrichment_census_rent", "enrich_census_rent", 300, False),
        ("equity", "foreclosure_scraper.enrichment_equity", "enrich_equity", 300, False),
    ],
    # Batch 10: title_risk + distress_score + strategy_fit
    [
        ("title_risk", "foreclosure_scraper.enrichment_title_risk", "enrich_title_risk", 120, False),
        ("distress_score", "foreclosure_scraper.distress_score", "score_board", 120, False),
        ("strategy_fit", "foreclosure_scraper.enrichment_strategy_fit", "enrich_strategy_fit", 120, False),
    ],
    # Batch 11: courts (network — alone)
    [
        ("courts", "foreclosure_scraper.enrichment_courts", "enrich_with_court_records", 600, True),
    ],
    # Batch 12: bankruptcy (network — alone)
    [
        ("bankruptcy", "foreclosure_scraper.enrichment_bankruptcy", "enrich_with_bankruptcy", 300, True),
    ],
    # Batch 13: final recompute pass
    [
        ("equity_recompute", "foreclosure_scraper.enrichment_equity", "enrich_equity", 300, False),
        ("amount_owed_recompute", "foreclosure_scraper.enrichment_amount_owed", "enrich_amount_owed", 300, False),
        ("title_risk_recompute", "foreclosure_scraper.enrichment_title_risk", "enrich_title_risk", 120, False),
        ("distress_recompute", "foreclosure_scraper.distress_score", "score_board", 120, False),
    ],
]


def _coverage(board: list[Listing]) -> dict:
    total = len(board)
    fields = {}
    for li in board:
        raw = li.raw if hasattr(li, "raw") and isinstance(li.raw, dict) else {}
        for k, v in raw.items():
            if v is not None and v != "" and v != [] and v != {}:
                fields[k] = fields.get(k, 0) + 1
    return {k: (v, round(100 * v / total, 1)) for k, v in sorted(fields.items(), key=lambda x: -x[1])}


async def run_batch(batch_num: int):
    if batch_num > len(BATCHES):
        print(f"\n✅ ALL {len(BATCHES)} BATCHES COMPLETE!")
        return

    batch = BATCHES[batch_num - 1]
    print(f"\n{'='*60}")
    print(f"BATCH {batch_num}/{len(BATCHES)}: {len(batch)} enrichers")
    print(f"{'='*60}")

    # Load board fresh — zero memory accumulation from prior batches
    print("  Loading board...", flush=True)
    t_load = time.time()
    board = load_board(DOCS)
    print(f"  Board: {len(board)} listings ({time.time()-t_load:.1f}s)")

    for name, module_path, func_name, timeout, is_async in batch:
        print(f"  [{name}]...", end=" ", flush=True)
        try:
            import importlib
            mod = importlib.import_module(module_path)
            func = getattr(mod, func_name)

            import inspect
            if inspect.iscoroutinefunction(func):
                s = await asyncio.wait_for(func(board), timeout=timeout)
            elif is_async:
                s = await asyncio.wait_for(asyncio.to_thread(func, board), timeout=timeout)
            else:
                s = func(board)

            s_str = str(s)
            if len(s_str) > 200:
                s_str = s_str[:200] + "..."
            print(f"OK: {s_str}")
        except asyncio.TimeoutError:
            print(f"TIMEOUT ({timeout}s)")
        except Exception as e:
            print(f"ERR: {e}")

        gc.collect()

    # Stream-save board — memory-safe, never holds full payload
    print("  Saving board (stream)...")
    try:
        stream_save_board(board)
    except Exception as e:
        print(f"  Save ERR: {e}")

    # Free memory before spawning next batch
    del board
    gc.collect()

    # Spawn next batch as a new process — fresh memory
    if batch_num < len(BATCHES):
        print(f"\n  → Spawning batch {batch_num + 1}...")
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            f"{Path(__file__).parent.parent / 'src'}:"
            f"{Path.home() / 'foreclosure-scraper/.venv/lib/python3.12/site-packages'}:"
            f"{env.get('PYTHONPATH', '')}"
        )
        log_path = f"/tmp/enrich_batch_{batch_num+1}.log"
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(batch_num + 1)],
            env=env,
            cwd=str(Path(__file__).parent.parent),
            stdout=open(log_path, "w"),
            stderr=subprocess.STDOUT,
        )
        print(f"  → Batch {batch_num + 1} spawned (see {log_path})")
    else:
        print("\n✅ ALL BATCHES COMPLETE — board fully enriched!")


if __name__ == "__main__":
    batch_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    asyncio.run(run_batch(batch_num))

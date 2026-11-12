#!/usr/bin/env python3
"""Run enrichment_doc_ocr.enrich_doc_ocr() board-wide, safely.

doc_ocr is free (Gemini-first, GitHub Models/Groq fallback -- confirmed no
ANTHROPIC_API_KEY set in this environment, so the paid Anthropic fallback in
that module can never fire), gated by FORECLOSURE_DOC_OCR (on by default),
and has always been callable board-wide -- it just never has been outside a
single main.py run's DOC_OCR_MAX=2500/DOC_OCR_BUDGET_S=2400s allowance.
Found 2026-09-16: board-wide it had reached exactly 1 row. Live-counted
5,796 candidate rows carry a document URL at all (most scrapers don't stash
one), and thanks to the aggregate-list path (a doc shared by >3 leads is
read ONCE and matched to every referencing lead), covering effectively all
of them needs only ~64 real OCR calls -- far under one run's budget, so no
chunking/checkpointing is needed here.

    python scripts/backfill_doc_ocr.py --dry-run
    python scripts/backfill_doc_ocr.py
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def _load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE .env loader -- no python-dotenv dependency.

    Found 2026-09-16: main.py's own `from dotenv import load_dotenv` is
    wrapped in `except ImportError: pass`, and python-dotenv is NOT actually
    installed in this venv (confirmed: `import dotenv` fails, no pip entry,
    not in pyproject). That means main.py's .env loading has ALWAYS been a
    silent no-op -- whatever actually feeds GEMINI_API_KEY_n etc. into real
    production runs does so upstream of Python (a shell wrapper / launchd
    plist that exports the file's contents directly), not via this code
    path. A standalone script invoked straight from a bare shell (as this
    one is) never gets that treatment, so it must load the file itself.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_env_file(REPO / ".env")

from foreclosure_scraper.enrichment_doc_ocr import enrich_doc_ocr  # noqa: E402
from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lock = contextlib.nullcontext() if args.dry_run else board_lock(REPO, owner="backfill_doc_ocr")
    with lock:
        rows = load_board(REPO / "docs")
        print(f"board rows: {len(rows):,}")

        if args.dry_run:
            from foreclosure_scraper.enrichment_doc_ocr import _doc_urls
            candidates = [li for li in rows if _doc_urls(li) and not (isinstance(li.raw, dict) and li.raw.get("doc_ocr"))]
            print(f"candidates: {len(candidates):,}")
            print("\nDRY RUN — enrich_doc_ocr() not called, nothing written.")
            return 0

        stats = asyncio.run(enrich_doc_ocr(rows))
        print(f"\nstats: {stats}")

        write_artifact(rows, {"backfill_doc_ocr": stats}, docs_dir=REPO / "docs")
        print(f"\nwrote board: {len(rows):,} rows")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

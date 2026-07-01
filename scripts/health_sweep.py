"""Full health matrix across every enabled free-public scraper.

Runs each registered, enabled scraper with a hard per-scraper timeout and
records: slug | count | seconds | STATUS. Never lets one failure stop the sweep.
Writes a TSV to the path given as argv[1] (default: logs/health_sweep.tsv).

Usage:
  uv run python scripts/health_sweep.py [out.tsv] [--slugs a,b,c]
"""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
from pathlib import Path

from foreclosure_scraper.scrapers._registry import all_scrapers

CRED_MARKERS = ("APIFY", "api_key", "API_KEY", "COURTLISTENER", "foreclosure_dot_com")


def is_free(scraper) -> bool:
    try:
        src = inspect.getsource(type(scraper))
    except Exception:
        src = ""
    if any(m in src for m in ("COURTLISTENER", "APIFY")):
        return False
    return True


async def run_one(scraper, timeout_s: float = 75.0):
    t0 = time.monotonic()
    try:
        listings = await asyncio.wait_for(scraper.safe_run(), timeout=timeout_s)
        dt = time.monotonic() - t0
        return len(listings), dt, "OK" if listings else "EMPTY"
    except asyncio.TimeoutError:
        return 0, timeout_s, f"TIMEOUT_{int(timeout_s)}s"
    except Exception as exc:  # noqa: BLE001
        dt = time.monotonic() - t0
        return 0, dt, f"ERROR:{type(exc).__name__}:{str(exc)[:160]}"


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else Path("logs/health_sweep.tsv")
    slug_filter = None
    for a in sys.argv[1:]:
        if a.startswith("--slugs="):
            slug_filter = set(a.split("=", 1)[1].split(","))

    scrapers = all_scrapers()
    # enabled + free only
    todo = []
    for s in scrapers:
        disabled = getattr(s, "disabled", False) or getattr(s, "enabled", True) is False
        if disabled:
            continue
        if not is_free(s):
            continue
        if slug_filter and s.slug not in slug_filter:
            continue
        todo.append(s)
    todo.sort(key=lambda x: x.slug)

    out.parent.mkdir(parents=True, exist_ok=True)
    fh = out.open("w")
    fh.write("slug\tcount\tseconds\tstatus\n")
    print(f"sweeping {len(todo)} free/enabled scrapers -> {out}", file=sys.stderr)
    for i, s in enumerate(todo, 1):
        n, dt, status = await run_one(s)
        line = f"{s.slug}\t{n}\t{dt:.1f}\t{status}"
        fh.write(line + "\n")
        fh.flush()
        print(f"[{i}/{len(todo)}] {line}", file=sys.stderr)
    fh.close()
    print("DONE", file=sys.stderr)


if __name__ == "__main__":
    os.environ.setdefault("LOG_LEVEL", "ERROR")
    asyncio.run(main())

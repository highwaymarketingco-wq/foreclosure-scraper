#!/usr/bin/env python3
"""Run the SC divorce backfill only while the FCCMS portal is fast enough.

The portal slows down for hours at a time (2026-09-18: 3s per search at noon,
10-11s from 15:15 on, with our own load stopped). Pushing a slow portal just
trips the enricher's failure guard after ~200 leads a round. This probes with
three real-surname searches every PROBE_EVERY seconds and starts
backfill_sc_divorce.py only when their mean latency is under HEALTHY_S. The
backfill still stops itself on a throttle abort or two low-yield rounds; this
loop then either finishes (done / low-yield) or waits and tries again.

The supervisor is light. The backfill it launches is the ONLY board process
while it runs -- do not start other board-loading jobs meanwhile.

    python scripts/sc_divorce_when_healthy.py             # up to 14h
    python scripts/sc_divorce_when_healthy.py --hours 3
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

PROBE_EVERY = 600
HEALTHY_S = 5.0
PROBE_NAMES = (("SMITH", "JOHN"), ("BROWN", "ROBERT"), ("JOHNSON", "MARY"))


def classify_exit(output: str) -> str:
    """'done' | 'low_yield' | 'throttled' | 'error' from a backfill run's output."""
    if "backfill complete" in output:
        return "done"
    if "low-yield" in output:
        return "low_yield"
    if "failing calls" in output or "handshake failed" in output:
        return "throttled"
    return "error"


def is_healthy(mean_latency: float | None) -> bool:
    return mean_latency is not None and mean_latency <= HEALTHY_S


async def probe_latency() -> float | None:
    from curl_cffi.requests import AsyncSession
    from foreclosure_scraper import enrichment_sc_divorce as m
    times: list[float] = []
    async with AsyncSession(verify=False) as s:
        tok = await m._handshake(s)
        if not tok:
            return None
        h = {"X-CSRF-TOKEN": tok, "RequestVerificationToken": tok, "Content-Type": "application/json",
             "Access-Control-Allow-Origin": "*", "Referer": m.BASE + "/", "Origin": m.BASE}
        for last, first in PROBE_NAMES:
            t = time.monotonic()
            try:
                r = await asyncio.wait_for(
                    s.post(m.SEARCH_URL, json=m._search_payload(last, first, 1046, 1062), headers=h,
                           impersonate="chrome", timeout=30), 35)
            except Exception:
                return None
            if r.status_code != 200:
                return None
            times.append(time.monotonic() - t)
    return sum(times) / len(times)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=14.0)
    args = ap.parse_args()
    deadline = time.monotonic() + args.hours * 3600
    stamp = lambda: time.strftime("%H:%M:%S")

    while time.monotonic() < deadline:
        lat = asyncio.run(probe_latency())
        print(f"[{stamp()}] probe mean latency: {'failed' if lat is None else f'{lat:.1f}s'} "
              f"({'healthy' if is_healthy(lat) else 'waiting'})", flush=True)
        if is_healthy(lat):
            print(f"[{stamp()}] launching backfill", flush=True)
            proc = subprocess.Popen([sys.executable, str(REPO / "scripts" / "backfill_sc_divorce.py")],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    cwd=REPO, env={**os.environ, "PYTHONUNBUFFERED": "1"})
            lines: list[str] = []
            for line in proc.stdout:           # stream, so progress is visible while it runs
                lines.append(line)
                if line.startswith(("round ", "  [checkpoint", "===", "FCCMS", "no targets", "pending",
                                    "board rows")) or "consecutive" in line:
                    print(line.rstrip(), flush=True)
            proc.wait()
            out = "".join(lines)
            verdict = classify_exit(out)
            print(f"[{stamp()}] backfill ended: {verdict}", flush=True)
            if verdict in ("done", "low_yield"):
                return 0
            if verdict == "error":
                print("unexpected backfill exit -- stopping so a human can look.", flush=True)
                return 1
        time.sleep(PROBE_EVERY)
    print(f"[{stamp()}] deadline reached; backfill is resumable.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

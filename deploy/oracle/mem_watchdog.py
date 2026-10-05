#!/usr/bin/env python3
"""Dual-signal memory watchdog for a long board job on the Oracle VM (Linux /proc only).

Samples the WHOLE process tree under --pid (``uv run`` puts python one level down) every
--interval seconds and appends one line per sample to --log:

    <epoch> rss_mb=.. swap_mb=.. pss_mb=.. swappss_mb=.. avail_mb=.. swapfree_mb=.. procs=..

  rss/swap   sum of /proc/<p>/status VmRSS / VmSwap over the tree
  pss        sum of /proc/<p>/smaps_rollup Pss (+ SwapPss): the "never trust RSS alone" second
             signal this project uses for every board-scale trial (see web_artifact's
             BOARD_*_MAX_SOURCE_MB comments)
  avail      /proc/meminfo MemAvailable / SwapFree: what the kernel's OOM killer looks at

It KILLS the tree (SIGKILL, children first) before the kernel would, when either
  * rss + swap of the tree exceeds --kill-total-mb, or
  * MemAvailable < --kill-avail-mb AND SwapFree < --kill-swapfree-mb (the machine is about to
    OOM, whatever the cause).
A kill here is the same outcome as the OOM killer (every board write is temp-file + rename, so
the published files are either the old set or the new one; the manifest catches a half-renamed
set) but it is OURS: logged with the numbers, and it never takes a different process instead.
Exits when the watched process is gone; the last lines are the peaks and whether it killed.
"""
from __future__ import annotations

import argparse
import os
import signal
import time
from pathlib import Path


def _kb(text: str, key: str) -> int:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return 0


def _children(pid: int) -> list[int]:
    out = []
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            try:
                out += [int(c) for c in Path(f"/proc/{pid}/task/{tid}/children").read_text().split()]
            except OSError:
                pass
    except OSError:
        pass
    return out


def _tree(pid: int) -> list[int]:
    seen, todo = [], [pid]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.append(p)
        todo += _children(p)
    return seen


def _sample(root: int) -> dict:
    s = {"rss": 0, "swap": 0, "pss": 0, "swappss": 0, "procs": 0}
    for p in _tree(root):
        try:
            st = Path(f"/proc/{p}/status").read_text()
        except OSError:
            continue
        s["procs"] += 1
        s["rss"] += _kb(st, "VmRSS")
        s["swap"] += _kb(st, "VmSwap")
        try:
            sr = Path(f"/proc/{p}/smaps_rollup").read_text()
            s["pss"] += _kb(sr, "Pss")
            s["swappss"] += _kb(sr, "SwapPss")
        except OSError:
            pass
    mi = Path("/proc/meminfo").read_text()
    s["avail"] = _kb(mi, "MemAvailable")
    s["swapfree"] = _kb(mi, "SwapFree")
    return {k: (v // 1024 if k != "procs" else v) for k, v in s.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--log", required=True)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--kill-total-mb", type=int, default=25 * 1024)
    ap.add_argument("--kill-avail-mb", type=int, default=700)
    ap.add_argument("--kill-swapfree-mb", type=int, default=400)
    a = ap.parse_args()
    peaks = {"rss": 0, "swap": 0, "pss": 0, "swappss": 0, "total": 0}
    low = {"avail": 1 << 40, "swapfree": 1 << 40}
    killed = ""
    with open(a.log, "a", buffering=1) as fh:
        fh.write(f"# watching pid {a.pid}: kill at tree rss+swap > {a.kill_total_mb} MB, or "
                 f"MemAvailable < {a.kill_avail_mb} MB with SwapFree < {a.kill_swapfree_mb} MB\n")
        while os.path.exists(f"/proc/{a.pid}") and not killed:
            try:
                st = Path(f"/proc/{a.pid}/stat").read_text()
                if st.rsplit(")", 1)[1].split()[0] == "Z":
                    break                         # exited, not yet reaped
            except OSError:
                break
            s = _sample(a.pid)
            total = s["rss"] + s["swap"]
            for k in ("rss", "swap", "pss", "swappss"):
                peaks[k] = max(peaks[k], s[k])
            peaks["total"] = max(peaks["total"], total)
            low["avail"] = min(low["avail"], s["avail"])
            low["swapfree"] = min(low["swapfree"], s["swapfree"])
            fh.write(f"{int(time.time())} rss_mb={s['rss']} swap_mb={s['swap']} pss_mb={s['pss']} "
                     f"swappss_mb={s['swappss']} avail_mb={s['avail']} swapfree_mb={s['swapfree']} "
                     f"procs={s['procs']}\n")
            if total > a.kill_total_mb:
                killed = f"tree rss+swap {total} MB > {a.kill_total_mb} MB"
            elif s["avail"] < a.kill_avail_mb and s["swapfree"] < a.kill_swapfree_mb:
                killed = (f"MemAvailable {s['avail']} MB < {a.kill_avail_mb} and SwapFree "
                          f"{s['swapfree']} MB < {a.kill_swapfree_mb}")
            if killed:
                for p in reversed(_tree(a.pid)):
                    try:
                        os.kill(p, signal.SIGKILL)
                    except OSError:
                        pass
                fh.write(f"KILLED {int(time.time())}: {killed}\n")
                break
            time.sleep(a.interval)
        fh.write(f"PEAK rss_mb={peaks['rss']} swap_mb={peaks['swap']} total_mb={peaks['total']} "
                 f"pss_mb={peaks['pss']} swappss_mb={peaks['swappss']} "
                 f"min_avail_mb={low['avail']} min_swapfree_mb={low['swapfree']} "
                 f"killed={'yes' if killed else 'no'}\n")
    return 9 if killed else 0


if __name__ == "__main__":
    raise SystemExit(main())

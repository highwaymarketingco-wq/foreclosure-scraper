#!/usr/bin/env python3
"""Standalone county-jail roster backfill (build queue J-02).

The bulk rosters are coded in enrichment_jail_bookings.ROSTERS, but the only
board-side caller is the full pipeline (main.py), which has not finished a run
since late July. Cleveland, Transylvania and Lincoln therefore carry zero
incarceration leads even though their rosters answer (Cleveland and Lincoln
CentralSquare P2C jqGrid, Transylvania Southern Software Citizen Connect).

This fetches each roster ONCE, indexes it by (last, first) and flags board leads
whose person-owner name matches exactly, through the SAME match rule the
pipeline uses (enrichment_jail_bookings.match_rosters). The signal is name-only
and low confidence, exactly as before: raw['jail_booking'] plus
raw['incarceration'] (distress_score weight 8), meaningful only stacked with
other distress. Scores are not recomputed here; run scripts/patch_distress_score.py
afterwards (or wait for the next scoring pass) so the new signal reaches the tiers.

Politeness (owner decision): one request at a time, at least --interval seconds
apart (default 1.0), a normal client, free public pages only. A host that answers
401/403/429 or a WAF challenge page is left alone for the rest of the run. No
login, no click-through, no CAPTCHA handling.

Privacy: jail rosters list real people. This script prints COUNTS only. It never
prints, logs or saves a roster name, DOB or charge.

    python scripts/backfill_jail_rosters.py                   # dry run: sizes + would-match counts
    python scripts/backfill_jail_rosters.py --counties Cleveland,Transylvania,Lincoln,Laurens,Oconee
    python scripts/backfill_jail_rosters.py --apply           # writes the board

The dry run streams docs/listings.json.gz (constant memory, ~7s) and writes
nothing. --apply needs the board in memory (about 2.8GB), so run it as the ONLY
board process; it holds board_lock for the whole load -> match -> write span.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_jail_bookings import (  # noqa: E402
    ROSTERS,
    _hydrate_tyler_hits,
    _load_roster,
    _name_parts,
    _norm_key,
    _owner_of,
    _plain_county,
    match_rosters,
)
from foreclosure_scraper.scrapers.national.jail_bookings import CITIZEN_CONNECT_BASE  # noqa: E402

BOARD_GZ = REPO / "docs" / "listings.json.gz"
MIN_INTERVAL = 1.0                       # seconds between requests, process-wide
BLOCK_STATUS = (401, 403, 429)           # login wall / forbidden / rate limit
# WAF challenge pages only. Deliberately not the bare word "captcha": ordinary
# app pages embed reCAPTCHA widgets on forms that never gate the roster JSON.
CHALLENGE = re.compile(r"just a moment|attention required|access denied|px-captcha|"
                       r"captcha-delivery|awswaf|verify you are human|unusual traffic", re.I)


# ---- polite HTTP: one at a time, spaced, stop a host that pushes back --------

class HostBlocked(Exception):
    pass


class Gate:
    """Spaces every request and remembers which hosts told us to stop."""

    def __init__(self, interval: float = MIN_INTERVAL, clock=time.monotonic,
                 sleep=asyncio.sleep):
        self.interval = interval
        self._clock, self._sleep = clock, sleep
        self._last: float | None = None
        self._lock = asyncio.Lock()
        self.blocked: dict[str, str] = {}      # host -> why
        self.requests = 0

    async def pace(self, host: str) -> None:
        if host in self.blocked:
            raise HostBlocked(f"{host}: {self.blocked[host]}")
        async with self._lock:
            if self._last is not None:
                wait = self.interval - (self._clock() - self._last)
                if wait > 0:
                    await self._sleep(wait)
            self._last = self._clock()
            self.requests += 1

    def judge(self, host: str, resp) -> None:
        code = getattr(resp, "status_code", 200)
        reason = f"HTTP {code}" if code in BLOCK_STATUS else None
        if reason is None:
            try:
                ctype = str(resp.headers.get("content-type") or "").lower()
                if "json" not in ctype and CHALLENGE.search((resp.text or "")[:200_000]):
                    reason = "challenge page"
            except Exception:  # noqa: BLE001 - a response we cannot inspect is not a block
                reason = None
        if reason:
            self.blocked[host] = reason


def _polite_class(real_cls, gate: Gate):
    class _Polite:
        def __init__(self, *a, **k):
            self._s = real_cls(*a, **k)

        async def __aenter__(self):
            await self._s.__aenter__()
            return self

        async def __aexit__(self, *exc):
            return await self._s.__aexit__(*exc)

        async def _req(self, method: str, url: str, *a, **k):
            host = urlsplit(url).netloc
            await gate.pace(host)
            resp = await getattr(self._s, method)(url, *a, **k)
            gate.judge(host, resp)
            return resp

        async def get(self, url, *a, **k):
            return await self._req("get", url, *a, **k)

        async def post(self, url, *a, **k):
            return await self._req("post", url, *a, **k)

        def __getattr__(self, name):           # cookies, headers, close ...
            return getattr(self._s, name)

    return _Polite


@contextlib.contextmanager
def polite_curl_cffi(gate: Gate):
    """Route every curl_cffi AsyncSession the roster adapters open through the gate.
    The adapters import AsyncSession inside each call, so patching the module
    attribute reaches all of them without editing them."""
    import curl_cffi.requests as ccr
    real = ccr.AsyncSession
    ccr.AsyncSession = _polite_class(real, gate)
    try:
        yield
    finally:
        ccr.AsyncSession = real


def roster_host(vendor: str, target: str) -> str:
    """The network host a roster entry talks to (the key Gate.blocked uses)."""
    if vendor == "zuercher":
        return f"{target}.zuercherportal.com"
    if vendor == "citizen_connect":
        return urlsplit(CITIZEN_CONNECT_BASE).netloc
    if vendor == "p2c_centralsquare":
        return urlsplit(target.partition("|")[0]).netloc
    return urlsplit(target).netloc             # p2c_jqgrid, tyler_inmate_inquiry


# ---- board scan (read-only, constant memory) ---------------------------------

def scan_board(rows, wanted: set) -> dict:
    """Per roster county: leads, person-owned leads not yet flagged, and a Counter
    of their normalised (last, first) keys. Uses the pipeline's own owner / county /
    name helpers on a light stand-in, so the counts follow the real match rule."""
    out = {k: {"leads": 0, "eligible": 0, "keys": Counter()} for k in wanted}
    for r in rows:
        v = SimpleNamespace(state=r.get("state"), county=r.get("county"),
                            raw=r.get("raw"), defendant=r.get("defendant"))
        s = out.get((v.state, _plain_county(v)))
        if s is None:
            continue
        s["leads"] += 1
        if isinstance(v.raw, dict) and v.raw.get("jail_booking"):
            continue
        parts = _name_parts(_owner_of(v) or "")
        if parts:
            s["eligible"] += 1
            s["keys"][_norm_key(*parts)] += 1
    return out


def would_match(scan_entry: dict, index: dict) -> int:
    return sum(n for k, n in scan_entry["keys"].items() if k in index)


# ---- rosters -----------------------------------------------------------------

def select_rosters(names: str | None) -> list[tuple]:
    if not names:
        return list(ROSTERS)
    want = {n.strip().lower() for n in names.split(",") if n.strip()}
    picked = [e for e in ROSTERS if e[1].lower() in want]
    unknown = want - {e[1].lower() for e in picked}
    if unknown:
        raise SystemExit(f"unknown roster county: {', '.join(sorted(unknown))}. "
                         f"Valid: {', '.join(sorted(e[1] for e in ROSTERS))}")
    return picked


async def fetch_rosters(entries: list[tuple], gate: Gate) -> dict:
    """Fetch each roster once, sequentially. -> {(state, county): {index, blocked}}.
    A roster whose host already pushed back is not asked again."""
    out: dict = {}
    for state, county, vendor, target in entries:
        host = roster_host(vendor, target)
        key = (state, county)
        if host in gate.blocked:
            out[key] = {"index": {}, "blocked": gate.blocked[host]}
            continue
        _k, index = await _load_roster(state, county, vendor, target)
        out[key] = {"index": index, "blocked": gate.blocked.get(host)}
    return out


def _note(size: int, blocked: str | None, eligible: int) -> str:
    if blocked:
        return f"BLOCKED ({blocked}); host left alone"
    if not eligible:
        return "no eligible leads, roster not fetched"
    if not size:
        return "EMPTY: unreachable, blocked or nobody in custody"
    return ""


def report(entries, scan, rosters) -> list[str]:
    head = f"{'county':<16}{'vendor':<22}{'leads':>8}{'person':>9}{'roster':>8}{'would match':>13}"
    lines = [head, "-" * len(head)]
    total = 0
    for state, county, vendor, _t in entries:
        s = scan[(state, county)]
        r = rosters.get((state, county))
        size = len(r["index"]) if r else 0
        wm = would_match(s, r["index"]) if r else 0
        total += wm
        lines.append(f"{state + ' ' + county:<16}{vendor:<22}{s['leads']:>8,}{s['eligible']:>9,}"
                     f"{(f'{size:,}' if r else '-'):>8}{wm:>13,}  "
                     f"{_note(size, r['blocked'] if r else None, s['eligible'])}".rstrip())
    lines.append(f"\nleads that would be flagged: {total:,}   (roster = distinct names in custody)")
    return lines


# ---- run ---------------------------------------------------------------------

async def _amain(args) -> int:
    entries = select_rosters(args.counties)
    wanted = {(s, c) for s, c, _v, _t in entries}
    try:
        scan = scan_board(iter_board_rows(args.board), wanted)
    except FileNotFoundError:
        print(f"board file not found: {args.board}", file=sys.stderr)
        return 2
    need = [e for e in entries if scan[(e[0], e[1])]["eligible"] > 0]
    gate = Gate(args.interval)
    with polite_curl_cffi(gate):
        rosters = await fetch_rosters(need, gate)
    print("\n".join(report(entries, scan, rosters)))
    print(f"requests sent: {gate.requests}   hosts that pushed back: {len(gate.blocked)}")

    if not args.apply:
        print("\nDRY RUN: nothing written. Re-run with --apply (as the only board process).")
        return 0

    usable = {k: v["index"] for k, v in rosters.items() if v["index"]}
    if not usable:
        print("\nno roster returned any rows; nothing to apply.")
        return 1
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner="backfill_jail_rosters"):
        rows = load_board(REPO / "docs")
        n = len(rows)
        matched = match_rosters(rows, usable)
        # Gaston's grid has no booking date or charges; pull them for matched rows only.
        with polite_curl_cffi(gate):
            hydrated = await _hydrate_tyler_hits(matched)
        assert len(rows) == n
        print(f"\nboard rows: {n:,}; flagged {len(matched):,} leads; hydrated {hydrated}")
        if not matched:
            print("nothing matched; board not rewritten.")
            return 0
        write_artifact(rows, {"notes": f"backfill_jail_rosters: {len(matched)} leads flagged "
                                       f"from {len(usable)} county rosters"},
                       docs_dir=REPO / "docs")
        print(f"wrote board: {n:,} rows")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (default: dry run)")
    ap.add_argument("--counties", help="comma-separated roster counties (default: all of ROSTERS)")
    ap.add_argument("--interval", type=float, default=MIN_INTERVAL,
                    help="minimum seconds between requests (default 1.0)")
    ap.add_argument("--board", type=Path, default=BOARD_GZ,
                    help="gzipped board to scan for the dry-run counts")
    return asyncio.run(_amain(ap.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())

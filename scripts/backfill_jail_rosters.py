#!/usr/bin/env python3
"""Standalone county-jail roster backfill (build queue J-02).

The bulk rosters are coded in enrichment_jail_bookings.ROSTERS, but the only
board-side caller is the full pipeline (main.py), which has not finished a run
since late July. Cleveland, Transylvania and Lincoln therefore carry zero
incarceration leads even though their rosters answer (Cleveland and Lincoln
CentralSquare P2C jqGrid, Transylvania Southern Software Citizen Connect).

This fetches each roster ONCE, indexes it by (last, first) and flags board leads
whose person-owner name matches exactly, through the SAME match rule the
pipeline uses (enrichment_jail_bookings.match_rosters). The signal is low
confidence: raw['jail_booking'] plus raw['incarceration'] (distress_score weight
8), meaningful only stacked with other distress. Scores are not recomputed here;
run scripts/patch_distress_score.py afterwards (or wait for the next scoring
pass) so the new signal reaches the tiers.

Since 2026-10-05 that shared rule also (a) refuses a match whose roster middle
name contradicts the owner's middle initial and (b) re-evaluates leads already
carrying the enricher's own stamp: a middle-name conflict clears it, presence
refreshes it, and absence from a roster the sidecar judges healthy marks the
booking released_or_transferred (custody_ended), unless the stay was 60 days or
more (a county roster cannot tell a release from a transfer to state prison:
the claim is kept) or the person is on the roster under a respelled first name
(jail_matching). The dry run reports those counts too. The roster fetch honours
the dry run: the sidecar diff and the roster-size log are only committed with
--apply (same fix as the pipeline's 2026-09-29 DRY-RUN SIDECAR BUG).

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
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.board_stream import iter_board_rows  # noqa: E402
from foreclosure_scraper.enrichment_jail_bookings import (  # noqa: E402
    ROSTERS,
    _hydrate_tyler_hits,
    _is_own_same_county_stamp,
    _load_roster,
    _long_stay_days,
    _name_parts,
    _norm_key,
    _owner_of,
    _owner_still_supports_match,
    _pick_hit,
    _plain_county,
    _roster_candidates,
    match_rosters,
)
from foreclosure_scraper.jail_matching import spelling_variants, variant_candidate  # noqa: E402
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
    """Per roster county: leads, person-owned leads not yet flagged, a Counter of
    their normalised (last, first) keys, the owner strings behind each key (for
    the middle-name gate), and the leads already carrying the enricher's own
    stamp (for the re-evaluation preview). Uses the pipeline's own owner / county
    / name helpers on a light stand-in, so the counts follow the real match rule."""
    out = {k: {"leads": 0, "eligible": 0, "keys": Counter(), "owners": {},
               "stamped": []} for k in wanted}
    for r in rows:
        v = SimpleNamespace(state=r.get("state"), county=r.get("county"),
                            raw=r.get("raw"), defendant=r.get("defendant"))
        s = out.get((v.state, _plain_county(v)))
        if s is None:
            continue
        s["leads"] += 1
        parts = _name_parts(_owner_of(v) or "")
        jbk = v.raw.get("jail_booking") if isinstance(v.raw, dict) else None
        if jbk:
            if parts and _is_own_same_county_stamp(v, jbk) and _owner_still_supports_match(v):
                s["stamped"].append((_norm_key(*parts), _owner_of(v),
                                     bool(jbk.get("left_roster_detected_at")), _stamp_dates(jbk)))
            continue
        if parts:
            key = _norm_key(*parts)
            s["eligible"] += 1
            s["keys"][key] += 1
            s["owners"].setdefault(key, Counter())[_owner_of(v)] += 1
    return out


def _stamp_dates(jbk: dict) -> dict:
    """The stamp's own booking facts the shared stay / spelling-drift rules read (no name)."""
    return {k: jbk.get(k) for k in ("arrest_date", "roster_dob", "roster_age",
                                    "last_confirmed_on_roster", "left_roster_detected_at")}


def would_match(scan_entry: dict, index: dict) -> int:
    """Leads the shared rule would flag: on the roster AND not a middle-name conflict."""
    owners = scan_entry.get("owners") or {}
    total = 0
    for k, n in scan_entry["keys"].items():
        if k not in index:
            continue
        if k not in owners:                          # older scan shape: no gate info
            total += n
            continue
        cands = _roster_candidates(index, k)
        total += sum(c for owner, c in owners[k].items() if _pick_hit(owner, cands)[1] != "conflict")
    return total


def reeval_preview(scan_entry: dict, index: dict, today=None) -> dict:
    """What re-evaluating already-flagged leads would do (counts only), by the same rules as
    enrichment_jail_bookings._reevaluate_stamp: a respelled first name on the roster is the same
    person, and an absence after a long stay is kept, not read as 'left the roster'."""
    out = {"rechecked": 0, "conflict_cleared": 0, "left_roster": 0, "long_stay_kept": 0,
           "name_variant": 0, "ambiguous_variant": 0}
    today = today or datetime.now(timezone.utc).date()
    healthy = bool(getattr(index, "healthy", False))
    for entry in scan_entry.get("stamped") or ():
        key, owner, already_ended = entry[:3]
        dates = entry[3] if len(entry) > 3 else {}
        out["rechecked"] += 1
        cands = _roster_candidates(index, key)
        if not cands and dates:
            found = spelling_variants(index, dates, key)
            if len(found) > 1:
                out["ambiguous_variant"] += 1
                continue
            if found:
                out["name_variant"] += 1
                cands = [variant_candidate(found[0], key)]
        if cands:
            out["conflict_cleared"] += _pick_hit(owner, cands)[1] == "conflict"
        elif healthy:
            if dates and _long_stay_days(dates, today) is not None:
                out["long_stay_kept"] += 1
            elif not already_ended:
                out["left_roster"] += 1
    return out


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


async def fetch_rosters(entries: list[tuple], gate: Gate, dry_run: bool = False) -> dict:
    """Fetch each roster once, sequentially. -> {(state, county): {index, blocked}}.
    A roster whose host already pushed back is not asked again. `dry_run` keeps
    the jail_roster_history sidecar uncommitted (see _load_roster)."""
    out: dict = {}
    for state, county, vendor, target in entries:
        host = roster_host(vendor, target)
        key = (state, county)
        if host in gate.blocked:
            out[key] = {"index": {}, "blocked": gate.blocked[host]}
            continue
        _k, index = await _load_roster(state, county, vendor, target, dry_run=dry_run)
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
    rejected = 0
    pre = {"rechecked": 0, "conflict_cleared": 0, "left_roster": 0, "long_stay_kept": 0,
           "name_variant": 0, "ambiguous_variant": 0}
    unhealthy = 0
    for state, county, vendor, _t in entries:
        s = scan[(state, county)]
        r = rosters.get((state, county))
        size = len(r["index"]) if r else 0
        wm = would_match(s, r["index"]) if r else 0
        total += wm
        if r and r["index"]:
            rejected += sum(n for k, n in s["keys"].items() if k in r["index"]) - wm
            for k, v in reeval_preview(s, r["index"]).items():
                pre[k] += v
            unhealthy += not getattr(r["index"], "healthy", False)
        lines.append(f"{state + ' ' + county:<16}{vendor:<22}{s['leads']:>8,}{s['eligible']:>9,}"
                     f"{(f'{size:,}' if r else '-'):>8}{wm:>13,}  "
                     f"{_note(size, r['blocked'] if r else None, s['eligible'] or len(s['stamped']))}".rstrip())
    lines.append(f"\nleads that would be flagged: {total:,}   (roster = distinct names in custody)")
    lines.append(f"name matches refused (middle-name conflict): {rejected:,}")
    lines.append(f"already-flagged leads re-checked: {pre['rechecked']:,}; would clear "
                 f"{pre['conflict_cleared']:,} (middle-name conflict), would mark "
                 f"{pre['left_roster']:,} left the roster (kept as a possible transfer to prison "
                 f"after a 60+ day stay: {pre['long_stay_kept']:,}; found under a respelled first "
                 f"name: {pre['name_variant']:,}; ambiguous: {pre['ambiguous_variant']:,}); fetched "
                 f"rosters not trusted for 'left the roster' (empty/small/no history): {unhealthy:,}")
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
    # A county is fetched for new matches OR to re-check leads already flagged.
    need = [e for e in entries
            if scan[(e[0], e[1])]["eligible"] > 0 or scan[(e[0], e[1])]["stamped"]]
    gate = Gate(args.interval)
    with polite_curl_cffi(gate):
        rosters = await fetch_rosters(need, gate, dry_run=not args.apply)
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
        gate_stats: dict = {}
        matched = match_rosters(rows, usable, stats=gate_stats)
        # Gaston's grid has no booking date or charges; pull them for matched rows only.
        with polite_curl_cffi(gate):
            hydrated = await _hydrate_tyler_hits(matched)
        assert len(rows) == n
        cleared = gate_stats.get("reeval_conflict_cleared", 0)
        ended = gate_stats.get("reeval_left_roster", 0)
        restored = gate_stats.get("reeval_long_stay_restored", 0)
        print(f"\nboard rows: {n:,}; flagged {len(matched):,} leads; hydrated {hydrated}; "
              f"refused {gate_stats.get('middle_conflict_rejected', 0):,} (middle-name conflict); "
              f"re-checked {sum(v for k, v in gate_stats.items() if k.startswith('reeval_')):,}: "
              f"cleared {cleared:,}, marked left the roster {ended:,}, "
              f"kept after a long stay {gate_stats.get('reeval_long_stay_kept', 0):,}, "
              f"restored after a long stay {restored:,}")
        # A refreshed last_confirmed_on_roster date alone is not worth a whole-board write.
        if not (matched or cleared or ended or restored):
            print("nothing matched or changed; board not rewritten.")
            return 0
        write_artifact(rows, {"notes": f"backfill_jail_rosters: {len(matched)} leads flagged, "
                                       f"{cleared} middle-name conflicts cleared, {ended} marked "
                                       f"left the roster, {restored} restored after a long stay, "
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

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
import copy
import json
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

def _patch_parts_in_place(docs: Path, patches: dict, dry_run: bool = False) -> dict:
    """Patch specific board rows IN PLACE, one part file at a time, preserving every part's
    existing row count exactly -- never re-chunks, so it can never self-overwrite a part it
    hasn't finished reading.

    web_artifact.patch_existing_rows() routes through board_parts.write_parts(), which
    re-splits the ENTIRE board's row stream into fresh part boundaries sized from
    run_meta.json's current rows_per_part hint. This board's parts are NOT uniformly sized
    (an earlier chunk-size change left early parts at ~18,000 rows and later ones at 12,500 --
    found live 2026-11-06, docs/run_meta.json board_parts.rows_per_part=12500 while
    docs/board.manifest.json shows parts 000-024ish at 18,000ish and 025-027 at 12,500). Any
    single hint_rows value write_parts() is given is therefore "wrong" for part of the board:
    writing new output using that one size produces boundaries that drift from the OLD ones as
    the stream progresses, and since write_parts() writes new parts into the SAME directory and
    NAMES it is still reading the old board FROM (no staging directory, no atomic whole-set
    swap), a drifted boundary means the writer overwrites an old part file before the reader
    has finished consuming it -- corrupting the read mid-stream. Reproduced twice, identically
    (same broken byte sizes both times), confirming it is deterministic, not a race with
    another process. Recovered both times from backups/listings_YYYYMMDD_HHMMSS_parts/ +
    board_manifest.py --rebuild.

    This sidesteps the whole hazard: each part is read, patched, and (if anything in it
    changed) written back to ITS OWN existing filename with ITS OWN existing row count --
    zero re-chunking, so old and new boundaries are always identical and nothing is ever read
    and written through the same path in the same pass. Parts with no match are left
    byte-for-byte untouched. Caller must hold the board lock and must call
    web_artifact.reseal_board(docs, resplit=False) afterward (resplit=False never calls
    write_parts(), so it cannot hit this same hazard) to bring the manifest's per-part
    size/sha256 in line with whatever actually changed.

    UNSAFE-IDENTITY GUARD (2026-11-06, found live on Guilford NC): Listing.dedupe_key() falls
    back to f"url:{source_url}" when a row has no parcel_id/street_address/case_number. That
    fallback is NOT a per-listing identity -- a generic portal-root source_url
    (https://bcpwa.ncptscloud.com/, seen live) is shared by thousands of unrelated rows across
    MANY counties. A single Guilford lead matched this way caused its raw['jail_booking'] patch
    to apply to 11,032 other rows across 6 other counties when this function matched by
    dedupe_key() across the whole board, exactly as designed -- the bug was the key itself being
    unsafe, not the matching logic. Any patch keyed by a bare `url:` fallback is therefore
    dropped here before it can touch a single row, and reported back separately so the caller
    can see what was skipped and why, rather than it silently vanishing or silently bleeding."""
    from foreclosure_scraper import board_parts as _bp
    from foreclosure_scraper.models import Listing as _Listing
    from foreclosure_scraper.web_artifact import _APPEND_SIG_FIELDS
    row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    unsafe_identity_skipped = [k for k in patches if k.startswith("url:")]
    if unsafe_identity_skipped:
        patches = {k: v for k, v in patches.items() if not k.startswith("url:")}
    remaining = set(patches.keys())
    touched: list[tuple[str, int]] = []
    applied = 0
    dup_keys: set = set()
    for fp in _bp.list_part_files(docs):
        blobs: list[bytes] = []
        changed = False
        for text in _bp.iter_gz_rows(fp, want_text=True):
            rec = json.loads(text)
            key = None
            if isinstance(rec, dict):
                light = _Listing.model_construct(**{k: rec.get(k) for k in _APPEND_SIG_FIELDS})
                try:
                    key = light.dedupe_key()
                except Exception:  # noqa: BLE001 - too malformed to key is simply unmatched
                    key = None
            if key is not None and key in patches:
                if key not in remaining:
                    dup_keys.add(key)  # same identity on >1 row -- apply to every match, log it
                remaining.discard(key)
                update = patches[key]
                raw_update = update.get("raw")
                if isinstance(raw_update, dict):
                    raw = rec.get("raw")
                    if not isinstance(raw, dict):
                        raw = {}
                        rec["raw"] = raw
                    raw.update(raw_update)
                for field, value in update.items():
                    if field != "raw":
                        rec[field] = value
                blobs.append(row_enc.encode(rec).encode("utf-8"))
                changed = True
                applied += 1
            else:
                blobs.append(text.encode("utf-8"))
        if changed:
            touched.append((fp.name, len(blobs)))
            if not dry_run:
                data = _bp.gzip_array(blobs)
                _bp.atomic_write_bytes(fp, data)
    return {"touched_parts": touched, "applied": applied,
            "not_found": sorted(remaining), "duplicate_key_matches": len(dup_keys),
            "unsafe_identity_skipped": unsafe_identity_skipped}


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
    from foreclosure_scraper.models import Listing
    from foreclosure_scraper.web_artifact import board_lock, reseal_board
    # Scoped, streamed load: only the counties actually being matched this run are ever
    # validated into Listing objects -- never the whole board. load_board()+write_artifact()
    # used to sit here; on this board's current size that took 10+ minutes just to load (empirically
    # timed 2026-11-05 -- 13+ min and still running, memory-bounded but far too slow for a
    # one-county fix), and both real --apply attempts that hit it never reached the write step
    # at all.
    with board_lock(REPO, owner="backfill_jail_rosters"):
        scoped: list[Listing] = []
        scanned = 0
        for rec in iter_board_rows(args.board):
            scanned += 1
            county = (rec.get("county") or "").replace(" County", "").strip().title()
            if (rec.get("state"), county) not in usable:
                continue
            try:
                scoped.append(Listing.model_validate(rec))
            except Exception:
                continue  # unparseable row -- not this script's job to fix, skip it
        before = {id(li): copy.deepcopy(li.raw) for li in scoped}
        gate_stats: dict = {}
        matched = match_rosters(scoped, usable, stats=gate_stats)
        # Gaston's grid has no booking date or charges; pull them for matched rows only.
        with polite_curl_cffi(gate):
            hydrated = await _hydrate_tyler_hits(matched)
        cleared = gate_stats.get("reeval_conflict_cleared", 0)
        ended = gate_stats.get("reeval_left_roster", 0)
        restored = gate_stats.get("reeval_long_stay_restored", 0)
        print(f"\nscanned {scanned:,} board rows, {len(scoped):,} in the targeted counties; "
              f"flagged {len(matched):,} leads; hydrated {hydrated}; "
              f"refused {gate_stats.get('middle_conflict_rejected', 0):,} (middle-name conflict); "
              f"re-checked {sum(v for k, v in gate_stats.items() if k.startswith('reeval_')):,}: "
              f"cleared {cleared:,}, marked left the roster {ended:,}, "
              f"kept after a long stay {gate_stats.get('reeval_long_stay_kept', 0):,}, "
              f"restored after a long stay {restored:,}")
        patches = {li.dedupe_key(): {"raw": li.raw}
                   for li in scoped if li.raw != before.get(id(li))}
        # A refreshed last_confirmed_on_roster date alone is not worth a board write.
        if not patches:
            print("nothing matched or changed; board not rewritten.")
            return 0
        result = _patch_parts_in_place(REPO / "docs", patches, dry_run=False)
        print(f"patched board: {result['applied']:,} rows updated across "
              f"{len(result['touched_parts']):,} part file(s) "
              f"({result['not_found']}: not found, "
              f"{result['duplicate_key_matches']:,} duplicate-key matches)")
        if result["unsafe_identity_skipped"]:
            print(f"  REFUSED {len(result['unsafe_identity_skipped'])} match(es) with no stronger "
                  f"identity than a shared source_url (would have bled across every other row "
                  f"sharing that URL) -- not applied: {result['unsafe_identity_skipped']}")
        for name, n in result["touched_parts"]:
            print(f"  rewrote {name} ({n:,} rows, same as before)")
        reseal_board(REPO / "docs", resplit=False)
        print("manifest resealed")
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

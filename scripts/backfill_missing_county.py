#!/usr/bin/env python3
"""Fill `county` on the leads that have none, from the row's OWN evidence, only when unambiguous.

Audit 2026-09-21 section 9: 4,503 rows have no county (NC tax_lien 3,745 = liensnc filings, SC
bankruptcy 397 and NC bankruptcy 340 = the `recap` source, REO 21 = vrm_va_reo). Without a county a
lead cannot be attributed, mailed or covered by a per-county pipeline.

EVIDENCE, in this order (a lower step never overrides a higher one, and a CONFLICT skips the row):
  1. parcel_id found in exactly one county's parcel cache of the lead's state. Long ids only (10+
     digits, all numeric): short internal ids repeat across counties.
  2. ZIP. Table built from the parcel caches themselves: every cached parcel whose owner mailing
     address begins with its own situs street is an owner-occupant, so the mailing ZIP is the
     parcel's ZIP and the cache's county is the truth. A ZIP that spans two counties shows up with
     both, and is skipped. The board's own (zip, county) pairs are only a cross-check: the board is
     noisy (stray McDowell/Buncombe rows on far-away ZIPs), so its plurality must AGREE with the cache
     table and is never the sole evidence unless it is overwhelming (10+ rows, 99%).
  3. City, the same way (state-qualified postal city from the same cache mailing addresses).
  Court district is NOT a county: bankruptcy rows with no ZIP, city or parcel are left alone.

Never overwrites a county already set, never adds or removes a row. The chosen county and the
evidence go to raw['county_backfill'] (needs a RAW_KEEP entry; the apply path refuses to run
without it, see docs/data_quality_fixes_2026-09-21.md).

    python scripts/backfill_missing_county.py            # dry run: resolved / ambiguous / none per source
    python scripts/backfill_missing_county.py --apply    # ONLY board process (about 3 GB)

Run it BEFORE scripts/quarantine_flip_leaks.py: a flip with no county cannot be judged against the
18-county footprint until it has one.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _dq_common import REPO, iter_rows, norm_county, print_counter  # noqa: E402

CACHE_DIR = REPO / "data" / "parcel_cache"
CACHE_MIN_ROWS = 5
CACHE_SHARE = 0.98
CACHE_STRONG_ROWS = 20          # cache-only evidence (board silent) needs at least this many rows
BOARD_MIN_ROWS = 5              # the board table speaks only with this many rows
BOARD_SHARE = 0.9               # ... and one county at this share (stray misattributions are ~5%)
BOARD_ONLY_MIN_ROWS = 10
BOARD_ONLY_SHARE = 0.99
LONG_ID_MIN = 10
COMPLETE_CACHES = {"NC": 98, "SC": 44}   # a state's caches are "complete" when this many counties are cached
SAMPLE_PER_CACHE = 40000

_WS = re.compile(r"\s+")
_CITY_ZIP = re.compile(r"^(?P<city>[A-Za-z][A-Za-z .'\-]*?)[ ,]+(?P<st>[A-Z]{2})"
                       r"(?:[ ,]+(?P<zip>\d{5})\d{0,4})?$")


def zip5(z) -> str:
    m = re.match(r"\s*(\d{5})", str(z or ""))
    return m.group(1) if m else ""


def city_key(c) -> str:
    return _WS.sub(" ", re.sub(r"[.,]", " ", str(c or "").lower())).strip()


def _norm(x) -> str:
    return _WS.sub(" ", re.sub(r"[.,#]", " ", str(x).upper())).strip()


def unique(counter, min_rows: int, share: float):
    """(county, total) when one county holds >= share of >= min_rows rows, else (None, total)."""
    if not counter:
        return None, 0
    tot = sum(counter.values())
    top, n = max(counter.items(), key=lambda kv: kv[1])
    return (top if tot >= min_rows and n / tot >= share else None), tot


def cache_files() -> list[tuple[str, str, Path]]:
    """[(state, county, path)] for every parcel cache whose state is knowable from its file name."""
    from foreclosure_scraper.validation import NC_COUNTIES, SC_COUNTIES
    nc = {c.lower().replace(" ", "_"): c for c in NC_COUNTIES}
    sc = {c.lower().replace(" ", "_"): c for c in SC_COUNTIES}
    out = []
    for p in sorted(glob.glob(str(CACHE_DIR / "*.sqlite"))):
        stem = os.path.basename(p)[:-7]
        if stem.endswith("_nc") and stem[:-3] in nc:
            out.append(("NC", nc[stem[:-3]], Path(p)))
        elif stem.endswith("_sc") and stem[:-3] in sc:
            out.append(("SC", sc[stem[:-3]], Path(p)))
        elif stem in nc and stem not in sc:
            out.append(("NC", nc[stem], Path(p)))
        elif stem in sc and stem not in nc:
            out.append(("SC", sc[stem], Path(p)))
    return out


class Evidence:
    """ZIP / city / parcel evidence tables. Build once, resolve many."""

    def __init__(self):
        self.cache_zip: dict[str, Counter] = defaultdict(Counter)
        self.cache_city: dict[str, Counter] = defaultdict(Counter)
        self.board_zip: dict[str, Counter] = defaultdict(Counter)
        self.board_city: dict[str, Counter] = defaultdict(Counter)
        self.caches: dict[str, list[tuple[str, sqlite3.Connection]]] = defaultdict(list)
        self.cache_rows_used = 0

    # -- builders ---------------------------------------------------------------------------
    def build_from_caches(self) -> None:
        """Scan each cache (strided sample, ~40k rows) for owner-occupied parcels."""
        for st, county, p in cache_files():
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            self.caches[st].append((county, con))
            try:
                mx = con.execute("SELECT max(rowid) FROM parcels").fetchone()[0] or 0
                k = max(1, mx // SAMPLE_PER_CACHE)
                for addr, mail in con.execute(
                        "SELECT address, owner_mailing FROM parcels WHERE rowid % ? = 0 "
                        "AND address IS NOT NULL AND owner_mailing IS NOT NULL", (k,)):
                    a, m = _norm(addr), _norm(mail)
                    if not a or not m.startswith(a + " "):
                        continue
                    mm = _CITY_ZIP.match(m[len(a):].strip())
                    if not mm or mm.group("st") != st:
                        continue
                    self.cache_rows_used += 1
                    if mm.group("zip"):
                        self.cache_zip[f"{st}|{mm.group('zip')}"][county] += 1
                    ck = city_key(mm.group("city"))
                    if len(ck) >= 3:
                        self.cache_city[f"{st}|{ck}"][county] += 1
            except sqlite3.OperationalError:
                continue          # stale-schema cache: skip it, never guess

    def add_board_row(self, state, county, zip_code, city) -> None:
        """A board row that HAS a county (cross-check tables only)."""
        c = norm_county(county)
        st = str(state or "").upper()
        if not c or c.lower() == "statewide" or st not in ("NC", "SC"):
            return
        z = zip5(zip_code)
        if z:
            self.board_zip[f"{st}|{z}"][c] += 1
        ck = city_key(city)
        if ck:
            self.board_city[f"{st}|{ck}"][c] += 1

    # -- resolver ---------------------------------------------------------------------------
    def _parcel(self, state, parcel_id):
        from foreclosure_scraper import parcel_cache as pc
        n = pc._norm_id(parcel_id)
        if len(n) < LONG_ID_MIN or not n.isdigit():
            return None, "id_not_long_numeric"
        variants = [k for k, tier in pc._lookup_candidates(parcel_id) if tier == "exact"]
        hits = set()
        for county, con in self.caches.get(state, []):
            for v in variants:
                try:
                    if con.execute("SELECT 1 FROM parcels WHERE id=? LIMIT 1", (v,)).fetchone():
                        hits.add(county)
                        break
                except sqlite3.OperationalError:
                    break
        if len(hits) == 1:
            return next(iter(hits)), "one_cache"
        return None, ("several_caches" if hits else "no_cache_hit")

    def _table(self, cache_tab, board_tab, key):
        """(county, note) from a cache table cross-checked against the board table.

        The cache table has blind spots: a county whose cached mailing address carries no ZIP (Henderson)
        or puts it before the city (Mecklenburg), or whose situs is a legal description (Transylvania),
        contributes no rows, so a ZIP it shares looks unique to the neighbour. The board table is the
        check on that: it must AGREE, and when the board is silent the cache alone needs real volume."""
        cu, ctot = unique(cache_tab.get(key), CACHE_MIN_ROWS, CACHE_SHARE)
        b = board_tab.get(key)
        bu, btot = unique(b, BOARD_MIN_ROWS, BOARD_SHARE)
        if cu:
            if btot >= BOARD_MIN_ROWS:
                return (cu, "cache+board") if bu == cu else (None, "board_disagrees")
            return (cu, "cache") if ctot >= CACHE_STRONG_ROWS else (None, "cache_too_thin")
        if ctot >= CACHE_MIN_ROWS:
            return None, "spans_counties"
        bo, _t = unique(b, BOARD_ONLY_MIN_ROWS, BOARD_ONLY_SHARE)
        if bo and ctot == 0:
            return bo, "board_only"
        return None, "no_evidence"

    def resolve(self, state, zip_code, city, parcel_id) -> dict:
        """{'status': resolved|ambiguous|none, 'county', 'evidence', 'note'}"""
        st = str(state or "").upper()
        if st not in ("NC", "SC"):
            return {"status": "none", "county": None, "evidence": None, "note": "no_state"}
        picks: dict[str, str] = {}
        notes: list[str] = []
        weak_parcel = None
        pid = str(parcel_id or "").strip()
        if pid:
            c, n = self._parcel(st, pid)
            notes.append(f"parcel:{n}")
            if c:
                # SC TMS numbers repeat across counties ("115-00-00-100.000" is a Cherokee parcel AND a
                # Colleton one) and most SC counties have no cache, so "found in exactly one cache" proves
                # nothing there. Decisive only where the state's caches cover (nearly) every county.
                if len(self.caches.get(st, [])) >= COMPLETE_CACHES[st]:
                    picks["parcel"] = c
                else:
                    weak_parcel = c
                    notes.append("parcel_weak_partial_cache_coverage")
        z = zip5(zip_code)
        zc_set: set[str] = set()
        if z:
            c, n = self._table(self.cache_zip, self.board_zip, f"{st}|{z}")
            notes.append(f"zip:{n}")
            if c:
                picks["zip"] = c
            zc_set = set(self.cache_zip.get(f"{st}|{z}", {}))
        ck = city_key(city)
        if ck:
            c, n = self._table(self.cache_city, self.board_city, f"{st}|{ck}")
            notes.append(f"city:{n}")
            if c:
                picks["city"] = c
        if weak_parcel and picks and weak_parcel not in set(picks.values()):
            return {"status": "ambiguous", "county": None, "evidence": None,
                    "note": f"parcel_cache_says_{weak_parcel};" + ";".join(notes)}
        vals = set(picks.values())
        if len(vals) > 1:
            return {"status": "ambiguous", "county": None, "evidence": "+".join(sorted(picks)),
                    "note": "conflict:" + ",".join(f"{k}={v}" for k, v in sorted(picks.items()))}
        if not vals:
            spans = any(n.endswith(("spans_counties", "board_disagrees")) for n in notes)
            return {"status": "ambiguous" if spans else "none", "county": None, "evidence": None,
                    "note": ";".join(notes) or "no_evidence"}
        county = next(iter(vals))
        # a unique city must sit inside a multi-county ZIP's own county set, or the pair is inconsistent
        if "zip" not in picks and zc_set and county not in zc_set:
            return {"status": "ambiguous", "county": None, "evidence": "+".join(sorted(picks)),
                    "note": f"city_county_not_in_zip_counties:{county}"}
        ev = "parcel_cache" if "parcel" in picks else "+".join(k for k in ("zip", "city") if k in picks)
        return {"status": "resolved", "county": county, "evidence": ev, "note": ";".join(notes)}


def _src(s) -> str:
    return str(s or "").split(".")[-1]


# --------------------------------------------------------------------------------------- dry run
#: Sources whose ZIP / city / parcel describe the PROPERTY (a tax roll's ZIP is the owner's mailing
#: ZIP, so it would mismeasure the resolver). Used only for the hold-out precision check.
HOLDOUT_SOURCES = {"liensnc", "vrm_va_reo", "fannie_homepath", "zillow_bulk"}


def _holdout_report(ev: "Evidence", hold: list) -> None:
    """Resolve rows that ALREADY have a county as if they did not (their own board contribution removed),
    and count how often the answer is the county they actually carry. The measured precision of the rule."""
    res_c: Counter = Counter()
    wrong_by_ev: Counter = Counter()
    ex = []
    for src, st, z, city, pid, county in hold:
        zk, ck = f"{st}|{zip5(z)}", f"{st}|{city_key(city)}"
        for tab, key in ((ev.board_zip, zk), (ev.board_city, ck)):
            if key in tab and county in tab[key]:
                tab[key][county] -= 1
        try:
            r = ev.resolve(st, z, city, pid)
        finally:
            for tab, key in ((ev.board_zip, zk), (ev.board_city, ck)):
                if key in tab and county in tab[key]:
                    tab[key][county] += 1
        if r["status"] != "resolved":
            res_c[r["status"]] += 1
            continue
        ok = r["county"] == county
        res_c["resolved_right" if ok else "resolved_WRONG"] += 1
        if not ok:
            wrong_by_ev[r["evidence"]] += 1
            if len(ex) < 6:
                ex.append((src, st, county, zip5(z), city, r["county"], r["evidence"]))
    tot = sum(res_c.values())
    rs = res_c["resolved_right"] + res_c["resolved_WRONG"]
    print(f"\nHOLD-OUT PRECISION (rows that already carry a county, resolved as if they did not; n={tot:,})")
    print_counter(res_c)
    if rs:
        print(f"  precision of resolved rows: {100 * res_c['resolved_right'] / rs:.1f}% ({res_c['resolved_right']:,} of {rs:,}); "
              f"recall {100 * rs / tot:.0f}%")
    if wrong_by_ev:
        print_counter(wrong_by_ev, "  wrong answers by evidence")
        print("  examples (source, state, true county, zip, city, answered, evidence):", ex)


def _dry_run(rows_file=None, board_agg=None) -> int:
    ev = Evidence()
    ev.build_from_caches()
    if board_agg:                    # dev replay: full-board (zip, county) counters saved from a live pass
        import json
        agg = json.load(open(board_agg))
        for k, v in agg["zip_county"].items():
            ev.board_zip[k].update(v)
        for k, v in agg["city_county"].items():
            ev.board_city[k].update(v)
    print(f"cache evidence: {len(ev.cache_zip):,} ZIPs, {len(ev.cache_city):,} cities from "
          f"{ev.cache_rows_used:,} owner-occupied parcels in {sum(len(v) for v in ev.caches.values())} caches")
    cands = []
    hold = []
    n = n_h = 0
    for r in iter_rows(rows_file):
        n += 1
        if norm_county(r.get("county")):
            if not board_agg:
                ev.add_board_row(r.get("state"), r.get("county"), r.get("zip_code"), r.get("city"))
            st = str(r.get("state") or "").upper()
            if (_src(r.get("source")) in HOLDOUT_SOURCES and st in ("NC", "SC")
                    and (zip5(r.get("zip_code")) or city_key(r.get("city")) or str(r.get("parcel_id") or "").strip())):
                n_h += 1
                if n_h % 4 == 0:
                    hold.append((_src(r.get("source")), st, r.get("zip_code"), r.get("city"),
                                 r.get("parcel_id"), norm_county(r.get("county"))))
        else:
            cands.append((_src(r.get("source")), str(r.get("state") or "").upper(),
                          r.get("zip_code"), r.get("city"), r.get("parcel_id")))
    print(f"board rows scanned: {n:,}; rows with no county: {len(cands):,}")
    by = defaultdict(Counter)
    evid = Counter()
    counties = Counter()
    notes = Counter()
    for src, st, z, city, pid in cands:
        res = ev.resolve(st, z, city, pid)
        by[(src, st)][res["status"]] += 1
        if res["status"] == "resolved":
            evid[res["evidence"]] += 1
            counties[(st, res["county"])] += 1
        else:
            notes[(res["status"], res["note"].split(";")[0][:60])] += 1
    print(f"\n{'source':28}{'state':6}{'rows':>7}{'resolved':>10}{'ambiguous':>10}{'none':>7}")
    tot = Counter()
    for (src, st), c in sorted(by.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"{src[:27]:28}{st:6}{sum(c.values()):>7,}{c['resolved']:>10,}{c['ambiguous']:>10,}{c['none']:>7,}")
        tot.update(c)
    print(f"{'TOTAL':34}{sum(tot.values()):>7,}{tot['resolved']:>10,}{tot['ambiguous']:>10,}{tot['none']:>7,}")
    print_counter(evid, "\nRESOLVED BY EVIDENCE")
    print_counter(Counter(dict(list(notes.most_common(8)))), "\nWHY NOT RESOLVED (top)")
    print("\nTOP RESOLVED COUNTIES:", ", ".join(f"{st} {c} {k:,}" for (st, c), k in counties.most_common(12)))
    _holdout_report(ev, hold)
    print("\nDRY RUN, nothing written. Re-run with --apply (as the only board process).")
    return 0


# ----------------------------------------------------------------------------------------- apply
REQUIRED_RAW_KEYS = ["county_backfill"]
BACKUP_NAME = "backfill_missing_county"


def build_evidence(rows: list) -> "Evidence":
    """Cache tables plus the board's own (ZIP, county) cross-check tables, from Listing objects."""
    ev = Evidence()
    ev.build_from_caches()
    for li in rows:
        if norm_county(li.county):
            ev.add_board_row(li.state, li.county, li.zip_code, li.city)
    return ev


def apply_rows(rows: list, *, dry_run: bool = False, evidence: "Evidence | None" = None) -> dict:
    """Fill `county` on Listing objects that have none, in place, only when unambiguous. Never overwrites a
    county, never changes len(rows), never writes a file (reads the parcel caches). dry_run=True mutates
    nothing. Pass `evidence` (build_evidence(rows)) to share the ~15 s cache scan with quarantine_flip_leaks."""
    from _dq_common import assert_raw_keep
    if not dry_run:
        assert_raw_keep(REQUIRED_RAW_KEYS)
    n = len(rows)
    ev = evidence or build_evidence(rows)
    c: Counter = Counter()
    for li in rows:
        if norm_county(li.county):
            continue
        res = ev.resolve(li.state, li.zip_code, li.city, li.parcel_id)
        c[res["status"]] += 1
        c[f"{res['status']}: {_src(li.source)}"] += 1
        if res["status"] != "resolved" or dry_run:
            continue
        li.county = res["county"]
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw["county_backfill"] = {"county": res["county"], "evidence": res["evidence"], "basis": res["note"]}
    assert len(rows) == n, "a county backfill must never change the row count"
    return {k: v for k, v in c.items() if v}


def _apply() -> int:
    from _dq_common import run_apply
    return run_apply("backfill_missing_county", apply_rows, REQUIRED_RAW_KEYS, BACKUP_NAME)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the board (ONLY board process)")
    ap.add_argument("--rows-file", help="dry run over a saved JSONL extract instead of the live board")
    ap.add_argument("--board-agg", help="with --rows-file: JSON of full-board zip/city county counters")
    args = ap.parse_args()
    if not args.apply:
        return _dry_run(args.rows_file, args.board_agg)
    if args.rows_file:
        raise SystemExit("--rows-file is dry-run only")
    return _apply()


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Run a NAMED LIST of registered scrapers, filter their rows exactly as the orchestrator
does, and (only with --apply) land the survivors on the board.

WHY THIS EXISTS. The full pipeline has not written the board since 2026-08-29, so a scraper
that has been fixed cannot "land" by waiting for the next full run. This is the scoped
equivalent: it runs only the slugs you name, applies the SAME gates ``main.run()`` applies
(imported from ``foreclosure_scraper.main``, never copied), reports what each gate dropped
and why, and lands the rest additively.

DRY-RUN BY DEFAULT. Nothing is written unless ``--apply`` is given. A dry run:
  * runs each scraper with a row cap (``--limit``, default 200). A scraper that defines
    ``apply_row_limit(n)`` is told to stop early (rutherford_wildfire_tax: 1,400 pages for a
    full sweep); the others are truncated after the fact,
  * partitions and filters like main.run(): sold-pool partition, ``_in_scope``,
    ``_active_only`` (dateless / DATELESS_OK_SOURCES, past-sale grace, horizon), the
    flip-candidate price gate, then ``dedupe``,
  * streams ``board_stream.iter_board_rows`` ONCE (constant memory, ~300 MB, no load_board)
    to say how many survivors are NEW versus already on the board,
  * prints per-slug counts, a sample row, and how many each filter dropped and why.

    python scripts/run_scoped_scrapers.py --slugs counties_nc.daily_courier,... --limit 200

APPLY. ``--apply`` takes the board lock, calls ``load_board`` (the ONLY way a board writer may
read it: it folds the lazy-detail sidecar back in), and ``apply_rows``:
  * ADDITIVE ONLY. A survivor that matches an existing row (dedupe_key or any strong
    same-property signature from ``dedupe._strong_sigs``) is reported and skipped; no existing
    row is modified or removed. The function asserts this by fingerprinting every existing
    row before and after.
  * new rows get only offline enrichment (tax-owed fold, valuation regrade, distress score).
    The network chain (geocode, parcel/GIS, name resolver) is NOT run here; the next
    ``scripts/merge_today_sources.py`` or full run does it.
  * ``write_artifact`` under ``board_lock`` (same conventions as merge_today_sources).
Use ``--save-json`` on the dry run and ``--load-json`` on the apply to land exactly what you
reviewed without re-scraping (a Rutherford sweep is ~30 minutes of polite requests).

    python scripts/run_scoped_scrapers.py --slugs a,b --save-json out.json
    python scripts/run_scoped_scrapers.py --load-json out.json --apply

``--env KEY=VAL`` sets an environment variable BEFORE the registry instantiates scrapers (a
feature flag such as FORECLOSURE_INCLUDE_GREENVILLE=1 is read in the constructor).
``--dateless-ok-extra slug,slug`` treats those slugs as if they were in DATELESS_OK_SOURCES for
this run only: it is how you preview (or land) a source whose ``main.py`` whitelist line has
not been added yet. It is printed loudly, and the next full run will still drop those rows
until main.py is changed.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DOCS = ROOT / "docs"
DEFAULT_LIMIT = 200


# --------------------------------------------------------------------------- #
# argument handling that must happen BEFORE the heavy imports
# --------------------------------------------------------------------------- #

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Run named scrapers with the orchestrator's filters; dry-run unless --apply.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--slugs", help="comma-separated registered slugs")
    g.add_argument("--slugs-file", help="file with one slug per line (# comments allowed)")
    g.add_argument("--load-json", help="apply/inspect rows saved by --save-json; no scraping")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max rows per scraper (default {DEFAULT_LIMIT})")
    ap.add_argument("--timeout", type=float, default=None,
                    help="cap each scraper's soft timeout (seconds)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VAL",
                    help="set an env var before scrapers are instantiated (repeatable)")
    ap.add_argument("--dateless-ok-extra", default="",
                    help="comma-separated slugs to treat as DATELESS_OK for this run only")
    ap.add_argument("--horizon-days", type=int, default=None,
                    help="override RuntimeConfig.sale_horizon_days")
    ap.add_argument("--board", default=str(DOCS / "listings.json.gz"),
                    help="board file streamed for the new-vs-existing count")
    ap.add_argument("--no-board", action="store_true", help="skip the new-vs-existing scan")
    ap.add_argument("--save-json", help="write the surviving rows here (dry run or apply)")
    ap.add_argument("--apply", action="store_true",
                    help="LAND the surviving rows on the board (takes the board lock)")
    ap.add_argument("--no-score", action="store_true", help="apply: skip the offline distress score")
    ap.add_argument("--docs", default=str(DOCS), help="board docs dir for --apply (tests only)")
    return ap.parse_args(argv)


def _apply_env(pairs: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            raise SystemExit(f"--env expects KEY=VAL, got {p!r}")
        k, v = p.split("=", 1)
        os.environ[k.strip()] = v
        out[k.strip()] = v
    return out


def _read_slugs(args: argparse.Namespace) -> list[str]:
    if args.slugs:
        raw = args.slugs.split(",")
    elif args.slugs_file:
        raw = [ln.split("#", 1)[0] for ln in Path(args.slugs_file).read_text().splitlines()]
    else:
        return []
    seen: list[str] = []
    for s in (x.strip() for x in raw):
        if s and s not in seen:
            seen.append(s)
    return seen


# --------------------------------------------------------------------------- #
# the orchestrator's gates, imported (never copied)
# --------------------------------------------------------------------------- #

def _gates():
    """Import lazily so ``--help`` and the argument tests stay light."""
    from foreclosure_scraper import main as M
    from foreclosure_scraper.dedupe import dedupe
    from foreclosure_scraper.enrichment_foreclosure_sold_comps import (
        is_sold_pool_candidate, state_upset_window_days)
    return M, dedupe, is_sold_pool_candidate, state_upset_window_days


def _scope_reason(M, li) -> str:
    if M._flip_outside_footprint(li):
        return f"flip outside the 18-county footprint ({li.county} {li.state})"
    if not (li.county or "").strip():
        return "no county on the row (and no NC/SC zip-prefix fallback)"
    return f"county {li.county} {li.state} is not in NC/SC scope"


def _active_reason(M, li, horizon: int, upset_days) -> str:
    st = (li.auction_status or "").lower()
    if st and st in M.TERMINAL_AUCTION_STATUSES:
        return f"terminal status '{li.auction_status}'"
    if li.sale_date is None:
        return "dateless and slug not in DATELESS_OK_SOURCES"
    sale = li.sale_date.replace(tzinfo=None) if li.sale_date.tzinfo else li.sale_date
    days = (datetime.utcnow() - sale).days
    if days > 0:
        return f"sale {days}d ago (grace {upset_days(li.state)}d)"
    return f"sale {-days}d out (horizon {horizon}d)"


def filter_like_orchestrator(listings, horizon_days: int, extra_dateless: Iterable[str] = ()):
    """Apply main.run()'s per-row gates in its order. Returns ``(kept, drops)`` where drops is
    ``{filter_name: Counter(reason -> n)}``. The keep/drop DECISION is main's own function;
    the reason text is explanation only."""
    M, dedupe, is_sold, upset_days = _gates()
    extra = set(extra_dateless)
    added = extra - M.DATELESS_OK_SOURCES
    M.DATELESS_OK_SOURCES.update(added)
    drops: dict[str, collections.Counter] = {
        "sold_pool": collections.Counter(), "scope": collections.Counter(),
        "active": collections.Counter(), "flip_price": collections.Counter(),
        "dedupe": collections.Counter()}
    try:
        stage1 = []
        for li in listings:
            if M._safe_pred(is_sold, li, False):
                drops["sold_pool"]["routed to the sold-comp pool, never the board"] += 1
            else:
                stage1.append(li)
        stage2 = []
        for li in stage1:
            if M._safe_pred(M._in_scope, li, False):
                stage2.append(li)
            else:
                drops["scope"][_scope_reason(M, li)] += 1
        stage3 = []
        for li in stage2:
            if M._safe_pred(lambda x: M._active_only(x, horizon_days), li, False):
                stage3.append(li)
            else:
                drops["active"][_active_reason(M, li, horizon_days, upset_days)] += 1
        stage4 = []
        for li in stage3:
            if M._safe_pred(M._flip_candidate, li, True):
                stage4.append(li)
            else:
                drops["flip_price"][f"priced {li.opening_bid}: over the flip-candidate cap"] += 1
        try:
            kept = dedupe(stage4)
        except Exception:  # noqa: BLE001  (orchestrator ships the un-deduped set on failure)
            kept = stage4
        n = len(stage4) - len(kept)
        if n > 0:
            drops["dedupe"]["merged into another row in this batch"] += n
    finally:
        M.DATELESS_OK_SOURCES.difference_update(added)
    return kept, drops


# --------------------------------------------------------------------------- #
# new-vs-existing: one streaming pass over the board
# --------------------------------------------------------------------------- #

_KEY_FIELDS = ("state", "county", "parcel_id", "street_address", "zip_code", "case_number",
               "source_url", "listing_type")


def _sigs_of(li) -> set:
    from foreclosure_scraper.dedupe import _strong_sigs
    out = set(_strong_sigs(li))
    try:
        out.add(("k", li.dedupe_key()))
    except Exception:  # noqa: BLE001
        pass
    return out


def board_overlap(candidates, rows: Iterable) -> dict[int, str]:
    """Which candidates are already on the board. ``rows`` is a stream of raw board dicts
    (``board_stream.iter_board_rows``) or of ``Listing`` objects (``apply_rows``); it is
    consumed ONCE. A dict row gets only a light ``model_construct`` of the identity fields, so
    the ~170k-row board never becomes 170k validated Listings. Returns
    ``{candidate_index: board_source_that_matched}``.

    Signature-only matching: ``dedupe_key()`` plus every strong same-property signature from
    ``dedupe._strong_sigs`` (parcel+state, case+address, address+zip, canonical street+county).
    """
    from foreclosure_scraper.models import Listing
    index: dict = collections.defaultdict(list)
    for i, li in enumerate(candidates):
        for sig in _sigs_of(li):
            index[sig].append(i)
    hit: dict[int, str] = {}
    for row in rows:
        if isinstance(row, dict):
            light = Listing.model_construct(**{k: row.get(k) for k in _KEY_FIELDS})
            src = str(row.get("source") or "?")
        else:
            light, src = row, str(getattr(row, "source", "") or "?")
        for sig in _sigs_of(light):
            for i in index.get(sig, ()):
                hit.setdefault(i, src)
        if len(hit) == len(candidates):
            break
    return hit


# --------------------------------------------------------------------------- #
# running scrapers
# --------------------------------------------------------------------------- #

async def run_scrapers(slugs: list[str], limit: int, timeout: float | None):
    """Run each named scraper in turn (never concurrently). Returns
    ``[(slug, outcome, reason, rows_after_limit, n_before_limit, seconds)]``."""
    from foreclosure_scraper.scrapers._registry import all_scrapers
    registry = {s.slug: s for s in all_scrapers()}
    unknown = [s for s in slugs if s not in registry]
    if unknown:
        raise SystemExit(f"run_scoped_scrapers: {len(unknown)} slug(s) match no registered "
                         f"scraper and would silently contribute nothing: {unknown}")
    results = []
    for slug in slugs:
        s = registry[slug]
        if timeout is not None:
            s.timeout_s = min(float(s.timeout_s), float(timeout))
        if hasattr(s, "apply_row_limit"):
            s.apply_row_limit(limit)
        t0 = datetime.utcnow()
        try:
            rows = list(await s.safe_run())
        except Exception as exc:  # noqa: BLE001
            results.append((slug, "ERROR", f"{type(exc).__name__}: {str(exc)[:120]}", [], 0, 0.0))
            continue
        for li in rows:
            if not li.source:
                li.source = slug
        n_before = len(rows)
        results.append((slug, getattr(s, "last_outcome", "?"), getattr(s, "last_reason", ""),
                        rows[:limit], n_before, (datetime.utcnow() - t0).total_seconds()))
    return results


# --------------------------------------------------------------------------- #
# landing rows
# --------------------------------------------------------------------------- #

def _fingerprint(li) -> str:
    return hashlib.blake2b(li.model_dump_json().encode(), digest_size=8).hexdigest()


def apply_rows(rows, new_listings, *, docs_dir: Path | str | None = None, write: bool = True,
               score: bool = True, note: str = "scoped scraper landing") -> dict:
    """Land ``new_listings`` on the board that ``rows`` was loaded from. ADDITIVE ONLY.

    ``rows``          the existing board as ``Listing`` objects, from ``web_artifact.load_board``
                      (which folds the lazy-detail sidecar back in, so the rewrite keeps it).
    ``new_listings``  surviving rows from ``filter_like_orchestrator``.

    A new listing that matches an existing row by ``dedupe_key`` or any strong signature is
    skipped and counted (``already_on_board``); existing rows are NEVER modified or removed, and
    that is asserted (per-row fingerprint before and after, plus length and identity). The
    caller must hold ``board_lock`` and must have loaded ``rows`` through ``load_board``.

    Returns ``{existing, candidates, added, already_on_board, added_by_source, skipped_by_source,
    written, score}``. With ``write=False`` it computes and asserts everything but does not call
    ``write_artifact``.
    """
    from foreclosure_scraper.dedupe import dedupe

    existing = list(rows)
    before = [_fingerprint(li) for li in existing]
    n_existing = len(existing)

    hit = board_overlap(new_listings, existing)
    fresh = [li for i, li in enumerate(new_listings) if i not in hit]
    skipped = collections.Counter(li.source for i, li in enumerate(new_listings) if i in hit)
    try:
        fresh = dedupe(fresh)
    except Exception:  # noqa: BLE001
        pass
    for li in fresh:
        if not isinstance(li.raw, dict):
            li.raw = {}
        li.raw.setdefault("landed_by", "scripts/run_scoped_scrapers.py")

    stats: dict = {"existing": n_existing, "candidates": len(new_listings), "added": len(fresh),
                   "already_on_board": len(hit), "written": False, "score": None,
                   "added_by_source": dict(collections.Counter(li.source for li in fresh)),
                   "skipped_by_source": dict(skipped)}

    if fresh:
        # OFFLINE enrichment of the NEW rows only. Existing rows are never passed to anything
        # that could rewrite them. Failures are reported, never swallowed silently.
        from foreclosure_scraper.enrichment_tax_owed import enrich_tax_owed
        from foreclosure_scraper.valuation import calc as vcalc, grading as vgrade
        try:
            stats["tax_owed"] = enrich_tax_owed(fresh)
        except Exception as exc:  # noqa: BLE001
            stats["tax_owed"] = f"ERROR {type(exc).__name__}: {str(exc)[:100]}"
        vfail = 0
        for li in fresh:
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001
                vfail += 1
        stats["valuation_failures"] = vfail
        if score:
            try:
                from foreclosure_scraper.distress_score import score_board
                # None of these rows shares a parcel/address with an existing row (they were
                # filtered against the board above), so scoring them alone equals scoring them
                # inside the board.
                stats["score"] = score_board(fresh)
            except Exception as exc:  # noqa: BLE001
                stats["score"] = f"SCORE_FAILED {type(exc).__name__}: {str(exc)[:120]}"

    merged = existing + fresh
    # ---- the guarantees -------------------------------------------------------------
    assert len(merged) == n_existing + len(fresh), "row count arithmetic broke"
    assert all(merged[i] is existing[i] for i in range(n_existing)), "existing rows were reordered"
    after = [_fingerprint(li) for li in merged[:n_existing]]
    changed = [i for i in range(n_existing) if before[i] != after[i]]
    assert not changed, (f"apply_rows modified {len(changed)} existing row(s); first index "
                         f"{changed[0]}. Refusing to write.")

    if write and fresh:
        from foreclosure_scraper.web_artifact import write_artifact
        docs = Path(docs_dir) if docs_dir else DOCS
        summary = {"by_source": dict(collections.Counter(li.source for li in merged if li.source)),
                   "notes": f"{note}: +{len(fresh)} rows, existing rows untouched"}
        write_artifact(merged, summary, docs_dir=docs)
        stats["written"] = True
    stats["total_after"] = len(merged)
    return stats


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def _sample(li) -> dict:
    d = li.model_dump(mode="json")
    keep = ("source", "listing_type", "county", "state", "parcel_id", "street_address", "owner_name",
            "defendant", "case_number", "sale_date", "opening_bid", "judgment_amount",
            "auction_status", "description")
    out = {k: d[k] for k in keep if d.get(k) not in (None, "", [])}
    if "description" in out:
        out["description"] = str(out["description"])[:110]
    return out


def _print_report(per_slug: list[dict], totals: dict) -> None:
    for r in per_slug:
        print(f"\n== {r['slug']}")
        print(f"   outcome {r['outcome']} in {r['seconds']:.0f}s"
              + (f" ({r['reason']})" if r["reason"] else ""))
        cut = f" (capped from {r['before_limit']})" if r["before_limit"] > r["rows"] else ""
        print(f"   scraped {r['rows']}{cut}   kept after filters {r['kept']}"
              f"   new {r['new']}   already on board {r['on_board']}"
              + ("" if r["overlap_checked"] else "   (board scan skipped)"))
        for filt, cnt in r["drops"].items():
            for reason, n in cnt.most_common(4):
                print(f"   dropped by {filt:<10} {n:>6}  {reason}")
        if r["sample"]:
            print("   sample:", json.dumps(r["sample"], default=str))
    print("\n== TOTAL   scraped {rows}  kept {kept}  new on board {new}  already on board {on_board}"
          .format(**totals))


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    env_set = _apply_env(args.env)
    slugs = _read_slugs(args)
    if not slugs and not args.load_json:
        raise SystemExit("give --slugs, --slugs-file or --load-json")

    from foreclosure_scraper.config import RuntimeConfig
    from foreclosure_scraper.models import Listing
    horizon = args.horizon_days if args.horizon_days is not None else RuntimeConfig.from_env().sale_horizon_days
    extra = [s.strip() for s in args.dateless_ok_extra.split(",") if s.strip()]
    if extra:
        print(f"NOTE: treating {extra} as DATELESS_OK for this run only. main.DATELESS_OK_SOURCES "
              "does not list them, so a normal full run will still drop these rows.")
    if env_set:
        print("env set for this run:", env_set)

    per_slug: list[dict] = []
    all_kept: list = []
    if args.load_json:
        loaded = [Listing.model_validate(d) for d in json.loads(Path(args.load_json).read_text())]
        print(f"loaded {len(loaded)} rows from {args.load_json}; no scraping, no filters re-run")
        all_kept = loaded
        per_slug = []
    else:
        results = asyncio.run(run_scrapers(slugs, args.limit, args.timeout))
        for slug, outcome, reason, rows, before_limit, secs in results:
            kept, drops = filter_like_orchestrator(rows, horizon, extra)
            per_slug.append({"slug": slug, "outcome": outcome, "reason": reason, "rows": len(rows),
                             "before_limit": before_limit, "seconds": secs, "kept_rows": kept,
                             "kept": len(kept), "drops": drops, "new": 0, "on_board": 0,
                             "overlap_checked": False,
                             "sample": _sample(kept[0]) if kept else None})
            all_kept.extend(kept)
        # cross-slug dedupe, the way one orchestrator run would see the union
        _, dedupe, _, _ = _gates()
        try:
            all_kept = dedupe(all_kept)
        except Exception:  # noqa: BLE001
            pass

    # ONE streaming pass over the board, for every surviving row of every slug
    flat = all_kept if args.load_json else [li for r in per_slug for li in r["kept_rows"]]
    overlap: dict[int, str] = {}
    scanned = False
    if flat and not args.no_board and Path(args.board).exists():
        from foreclosure_scraper.board_stream import iter_board_rows
        overlap = board_overlap(flat, iter_board_rows(args.board))
        scanned = True
    pos = 0
    for r in per_slug:
        r["overlap_checked"] = scanned
        n = len(r["kept_rows"])
        if scanned:
            r["on_board"] = sum(1 for i in range(pos, pos + n) if i in overlap)
            r["new"] = n - r["on_board"]
        pos += n
    totals = {"rows": sum(r["rows"] for r in per_slug), "kept": len(flat),
              "new": (len(flat) - len(overlap)) if scanned else 0,
              "on_board": len(overlap)}
    if per_slug:
        _print_report(per_slug, totals)
        if len(all_kept) != len(flat):
            print(f"(after cross-slug dedupe the batch is {len(all_kept)} rows)")
    else:
        print(f"{len(all_kept)} rows loaded; {len(overlap)} already on the board"
              + ("" if scanned else " (board scan skipped)"))
        if scanned:
            by_src: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
            for i, li in enumerate(flat):
                by_src[li.source or "?"][0 if i in overlap else 1] += 1
            for src, (old_n, new_n) in sorted(by_src.items()):
                print(f"   {src:<46} on board {old_n:>6}   NEW {new_n:>6}")

    if args.save_json:
        Path(args.save_json).write_text(json.dumps([li.model_dump(mode="json") for li in all_kept],
                                                   default=str))
        print(f"saved {len(all_kept)} rows to {args.save_json}")

    if not args.apply:
        print("\nDRY RUN: nothing was written. Re-run with --apply (or --load-json FILE --apply) "
              "to land the survivors.")
        return 0

    from foreclosure_scraper.web_artifact import BoardLockBusy, BoardMemoryPressure, board_lock, load_board
    docs = Path(args.docs)
    try:
        with board_lock(owner="run_scoped_scrapers", max_runtime=7200):
            rows = load_board(docs)
            print(f"existing board: {len(rows)} rows")
            stats = apply_rows(rows, all_kept, docs_dir=docs, score=not args.no_score)
    except (BoardLockBusy, BoardMemoryPressure) as exc:
        print(f"run_scoped_scrapers: not applied: {exc}", file=sys.stderr)
        return 75
    print("APPLIED:", json.dumps(stats, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

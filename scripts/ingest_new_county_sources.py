#!/usr/bin/env python3
"""Land the county sources built on 2026-09-21 on the board.

The full scrape pipeline has not run since 2026-08-29, so registering a scraper puts nothing on
the board. This script is the landing path, in the same shape as scripts/ingest_sc_delinquent_roll.py
and scripts/ingest_dillon_delinquent_tax.py: fetch, filter to scope, merge ADDITIVELY, write.

SOURCES (each a scraper under src/foreclosure_scraper/scrapers/; `--sources` takes these keys)
    catalis      counties_sc.sc_catalis_delinquent_roll   Chester, Hampton, Fairfield, Aiken
                 (Pickens is already on the board and is NOT re-read here)
    column       counties.column_legal_notices            NC tax foreclosures (Washington, Hertford
                 incl. Northampton, Bertie, Gates, Martin) + estates there + Florence/Marion/Marlboro estates
    its          counties_nc.nc_its_public_tax            Onslow, Graham unpaid property tax
    charleston   counties_sc.charleston_tax_sale_xlsx     Charleston tax-sale list (RP + MH .xlsx)
    horry        counties_sc.horry_delinquent_xlsx        Horry delinquent list (.xlsx)
    albemarle    counties_nc.albemarle_observer_tax_lists Tyrrell, Washington, Gates, Bertie lists

DRY RUN (the default; takes no lock, loads no board, writes nothing)
    Fetches a SAMPLE per source (`--limit`, default 25 rows; Catalis reads one surname per county),
    streams docs/listings.json.gz ONCE through board_stream.iter_board_rows to collect the parcel and
    address keys of just the counties in play, and prints per source: rows, field coverage, how many
    would be NEW versus already on the board, how many the scope gate would drop, and one sample row
    (owner names masked unless --show-pii). About 300 MB and 8 seconds for the board pass.

        uv run python scripts/ingest_new_county_sources.py
        uv run python scripts/ingest_new_county_sources.py --sources its,horry --limit 100

APPLY (`--apply`) -- ONE BOARD PROCESS AT A TIME. load_board is ~2.8 GB on the 8 GB Mac.
    1. Fetch every selected source IN FULL, before the lock is taken (Catalis alone is hours at its 8 s
       pace, so run it separately: `--sources catalis`). `--harvest PATH` writes the fetched rows to a
       JSON file first, so a failed board write never costs the fetch, and reads it back on the next
       run instead of fetching again. The file holds owner names: keep it under logs/ (git-ignored).
    2. Drop rows outside scope: main._in_scope (flips only in the 18 footprint counties, distressed
       anywhere in NC and SC) and, for rows that carry a sale date, main._active_only. A dateless
       standing roll is NOT run through _active_only, because that gate deletes any dateless source
       missing from main.DATELESS_OK_SOURCES (see docs/new_county_sources_2026-09-21.md).
    3. `with board_lock(...)`: load_board, apply_rows, write_artifact.

apply_rows(rows, new_listings) -> dict   (importable)
    Additive only. New rows are deduped among themselves, matched against the board on the repo's own
    dedupe_key plus dedupe._strong_sigs, and APPENDED when they match nothing. A row that matches an
    existing one leaves that row untouched (`--merge-matches` folds it in with Listing.merge instead).
    It never removes or reorders a row, and asserts before returning that every existing row's identity
    fields are byte-for-byte what they were and that len(rows) == before + added.

    python scripts/ingest_new_county_sources.py                       # dry run
    python scripts/ingest_new_county_sources.py --apply --sources its,charleston,horry,albemarle,column
    python scripts/ingest_new_county_sources.py --apply --sources catalis --harvest logs/new_county_catalis.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from foreclosure_scraper.models import Listing, ListingType, _normalize_addr, _normalize_parcel  # noqa: E402

DOCS = REPO / "docs"
BOARD_GZ = DOCS / "listings.json.gz"
SALE_HORIZON_DAYS = 120                     # config.RuntimeConfig.sale_horizon_days

NEW_CATALIS_COUNTIES = ("Chester", "Hampton", "Fairfield", "Aiken")
COLUMN_NEW_NC = ("Washington", "Hertford", "Northampton", "Bertie", "Gates", "Martin")
COLUMN_NEW_SC = ("Florence", "Marion", "Marlboro")
COLUMN_TYPES = (ListingType.TAX_SALE, ListingType.TAX_LIEN, ListingType.PROBATE_NOTICE)
#: One common surname per county for a dry run's single request.
CATALIS_SAMPLE_PREFIX = {"Chester": "BROWN", "Hampton": "BROWN", "Fairfield": "ALSTON", "Aiken": "BROWN"}


# --------------------------------------------------------------------------- source specs

@dataclass
class Spec:
    key: str
    slug: str
    make: Callable[[], object]
    sample: Callable[[object, int], None]
    keep: Callable[[Listing], bool] = lambda li: True


def _catalis_make():
    from foreclosure_scraper.scrapers.counties_sc.sc_catalis_delinquent_roll import SCCatalisDelinquentRoll
    return SCCatalisDelinquentRoll()


def _catalis_sample(s, limit):
    s.sample_prefixes = {c: CATALIS_SAMPLE_PREFIX[c] for c in _catalis_counties()}


def _catalis_counties() -> tuple[str, ...]:
    raw = os.environ.get("CATALIS_ROLL_COUNTIES", "")
    got = tuple(c.strip().title() for c in raw.split(",") if c.strip())
    return got or NEW_CATALIS_COUNTIES


def _column_make():
    from foreclosure_scraper.scrapers.newspapers.column_legal_notices import ColumnLegalNotices
    s = ColumnLegalNotices()
    s.only_new_counties = True
    return s


def _column_keep(li: Listing) -> bool:
    county = (li.county or "").strip().title()
    if li.listing_type not in COLUMN_TYPES:
        return False                          # a mortgage foreclosure there would be a flip
    if (li.state or "").upper() == "NC":
        return county in COLUMN_NEW_NC
    return county in COLUMN_NEW_SC


def _limit_attr(s, limit):
    s.limit = limit


def _make(modpath: str, cls: str):
    def make():
        import importlib
        return getattr(importlib.import_module(modpath), cls)()
    return make


SPECS: dict[str, Spec] = {
    "catalis": Spec("catalis", "counties_sc.sc_catalis_delinquent_roll", _catalis_make, _catalis_sample,
                    keep=lambda li: (li.county or "") in _catalis_counties()),
    "column": Spec("column", "counties.column_legal_notices", _column_make, lambda s, n: None, keep=_column_keep),
    "its": Spec("its", "counties_nc.nc_its_public_tax",
                _make("foreclosure_scraper.scrapers.counties_nc.nc_its_public_tax", "NcItsPublicTax"), _limit_attr),
    "charleston": Spec("charleston", "counties_sc.charleston_tax_sale_xlsx",
                       _make("foreclosure_scraper.scrapers.counties_sc.charleston_tax_sale_xlsx",
                             "CharlestonTaxSaleXlsx"), _limit_attr),
    "horry": Spec("horry", "counties_sc.horry_delinquent_xlsx",
                  _make("foreclosure_scraper.scrapers.counties_sc.horry_delinquent_xlsx",
                        "HorryDelinquentXlsx"), _limit_attr),
    "albemarle": Spec("albemarle", "counties_nc.albemarle_observer_tax_lists",
                      _make("foreclosure_scraper.scrapers.counties_nc.albemarle_observer_tax_lists",
                            "AlbemarleObserverTaxLists"), _limit_attr),
}


async def fetch_source(spec: Spec, sample_limit: int | None) -> tuple[list[Listing], dict]:
    """Run one scraper. A failure keeps whatever the scraper had collected so far."""
    s = spec.make()
    if sample_limit:
        spec.sample(s, sample_limit)
    t0 = time.monotonic()
    err = None
    try:
        rows = list(await s.fetch())
    except Exception as exc:  # noqa: BLE001
        rows = list(getattr(s, "partial", []) or [])
        err = f"{type(exc).__name__}: {exc}"[:200]
    kept = [li for li in rows if spec.keep(li)]
    for li in kept:
        if not li.source:
            li.source = spec.slug
    return kept, {"fetched": len(rows), "kept": len(kept), "seconds": round(time.monotonic() - t0, 1),
                  "error": err}


# --------------------------------------------------------------------------- keys

def row_keys(state, county, parcel_id, street_address, zip_code) -> set[str]:
    """The parcel and address keys Listing.dedupe_key() would build, from plain fields.

    A board row is a dict, not a Listing, and constructing 170,000 of them is the 2.8 GB
    load this dry run exists to avoid. Both address forms are emitted (with zip, and with
    state:county), because the board writes whichever the row's own fields allowed.
    """
    keys: set[str] = set()
    st = state or ""
    cty = (county or "").strip().lower()
    if parcel_id and str(parcel_id).strip():
        p = _normalize_parcel(str(parcel_id))
        if p:
            keys.add(f"parcel:{st}:{cty}:{p}")
    if street_address and str(street_address).strip():
        a = _normalize_addr(str(street_address))
        if a:
            z = (zip_code or "").strip()[:5] if isinstance(zip_code, str) else ""
            if z:
                keys.add(f"addr:{a}|{z}")
            if cty:
                keys.add(f"addr:{a}|{st}:{cty}")
    return keys


def listing_keys(li: Listing) -> set[str]:
    return row_keys(li.state, li.county, li.parcel_id, li.street_address, li.zip_code)


def scan_board(path: Path, wanted: set[tuple[str, str]]) -> tuple[set[str], int, Counter]:
    """ONE pass over the published board. Keeps keys only for (state, county) pairs in `wanted`."""
    from foreclosure_scraper.board_stream import iter_board_rows
    keys: set[str] = set()
    total = 0
    per_county: Counter = Counter()
    for r in iter_board_rows(path):
        total += 1
        st = (r.get("state") or "").upper()
        cty = (r.get("county") or "").strip().lower()
        if (st, cty) not in wanted:
            continue
        per_county[(st, cty)] += 1
        keys |= row_keys(r.get("state"), r.get("county"), r.get("parcel_id"),
                         r.get("street_address"), r.get("zip_code"))
    return keys, total, per_county


# --------------------------------------------------------------------------- scope

def scope_fns():
    """main._in_scope and main._active_only, or a config-only stand-in if main cannot import."""
    try:
        from foreclosure_scraper.main import _active_only, _in_scope
        return _in_scope, _active_only
    except Exception:  # noqa: BLE001
        from foreclosure_scraper.config import in_scope, in_scope_distressed
        flips = {ListingType.FORECLOSURE_SALE, ListingType.AUCTION, ListingType.SHERIFF_SALE,
                 ListingType.HOA_SALE, ListingType.REO}

        def _in(li):
            return in_scope(li.county, li.state) if li.listing_type in flips else \
                in_scope_distressed(li.county, li.state)

        def _act(li, horizon, *, now=None):
            return True
        return _in, _act


def in_scope_and_live(rows: list[Listing]) -> tuple[list[Listing], Counter]:
    """Scope gate for the new rows. A dateless standing roll is live by nature and skips
    _active_only (which would delete it for want of a DATELESS_OK_SOURCES entry)."""
    _in, _active = scope_fns()
    kept: list[Listing] = []
    dropped: Counter = Counter()
    for li in rows:
        if not _in(li):
            dropped["out of scope (flip outside the 18-county footprint, or not NC/SC)"] += 1
            continue
        if li.sale_date is not None and not _active(li, SALE_HORIZON_DAYS):
            dropped["dated sale outside the active window"] += 1
            continue
        kept.append(li)
    return kept, dropped


# --------------------------------------------------------------------------- the merge

def _fp(li: Listing) -> tuple:
    """Identity fields of a row. If any of these change on an existing row, the ingest touched it."""
    return (li.source, li.source_url, li.listing_type.value if li.listing_type else None,
            li.parcel_id, li.street_address, li.owner_name, li.county, li.state, li.zip_code,
            li.sale_date, li.case_number, li.tax_value, li.market_value, len(li.raw or {}))


def _match_sigs(li: Listing) -> set:
    """Signatures used to decide "already on the board".

    dedupe_key() (parcel > address > case > url, county-qualified) plus the address and case
    signatures from dedupe._strong_sigs. The state-wide PARCEL signature ("p", digits, state) is
    left out on purpose: it is not county-qualified, so a short parcel such as Onslow's "801-154"
    can equal a parcel in another NC county, and a false match here would silently DROP a new
    lead. The county-qualified parcel is already the primary key.
    """
    from foreclosure_scraper.dedupe import _strong_sigs
    return {li.dedupe_key()} | {s for s in _strong_sigs(li) if s[0] != "p"}


def _dedupe_batch(new: list[Listing]) -> list[Listing]:
    """Collapse exact-key duplicates inside the new batch, keeping the first-seen order.

    This is dedupe()'s pass 1 (same dedupe_key, and the different-house-number guard) and none
    of its fuzzy address or signature passes, which can fuse rows across counties.
    """
    from foreclosure_scraper.dedupe import _provably_different_property
    out: list[Listing] = []
    by_key: dict[str, int] = {}
    for li in new:
        k = li.dedupe_key()
        if k in by_key and not _provably_different_property(out[by_key[k]], li):
            out[by_key[k]] = out[by_key[k]].merge(li)
        elif k in by_key:
            out.append(li)                   # same key, different house: keep both
        else:
            by_key[k] = len(out)
            out.append(li)
    return out


def apply_rows(rows: list[Listing], new_listings: list[Listing], *, merge_matches: bool = False) -> dict:
    """Append `new_listings` to the board list `rows` IN PLACE and return the stats.

    Additive: nothing is removed or reordered, and an existing row is left untouched unless
    `merge_matches` asks for its missing fields to be filled from a matching new row. Raises
    AssertionError if the existing rows changed or the arithmetic does not hold.
    """
    before = len(rows)
    fp_before = [_fp(li) for li in rows]

    by_sig: dict = {}
    for li in rows:
        for sig in _match_sigs(li):
            by_sig.setdefault(sig, li)

    fresh = _dedupe_batch(list(new_listings))                # within the new batch only
    stats = {"before": before, "new_in": len(new_listings), "after_internal_dedupe": len(fresh),
             "dup_within_new": len(new_listings) - len(fresh), "added": 0,
             "matched_untouched": 0, "matched_merged": 0, "added_by_source": Counter()}
    add: list[Listing] = []
    for li in fresh:
        sigs = _match_sigs(li)
        twin = next((by_sig[s] for s in sigs if s in by_sig), None)
        if twin is not None:
            if merge_matches:
                merged = twin.merge(li)
                if merged is not twin:
                    twin.__dict__.update(merged.__dict__)
                stats["matched_merged"] += 1
            else:
                stats["matched_untouched"] += 1
            continue
        add.append(li)
        stats["added_by_source"][li.source] += 1
        for s in sigs:
            by_sig.setdefault(s, li)

    rows.extend(add)
    stats["added"] = len(add)
    stats["after"] = len(rows)
    assert len(rows) == before + len(add), "row count math is wrong"
    if merge_matches:
        # A merge may FILL a blank, never overwrite: every identity field that had a value keeps it.
        for i, was in enumerate(fp_before):
            now = _fp(rows[i])
            assert all(a is None or a == b for a, b in zip(was[:-1], now[:-1])), \
                f"existing row {i} lost or changed an identity field"
    else:
        assert fp_before == [_fp(li) for li in rows[:before]], "an existing row changed; refusing to write"
    stats["existing_rows_unchanged"] = True
    stats["added_by_source"] = dict(stats["added_by_source"])
    return stats


# --------------------------------------------------------------------------- harvest file

def save_harvest(path: Path, rows: list[Listing]) -> None:
    from foreclosure_scraper.web_artifact import _to_dict
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps([_to_dict(li) for li in rows], default=str))
    os.replace(tmp, path)


def load_harvest(path: Path) -> list[Listing]:
    out = []
    for r in json.loads(path.read_text()):
        try:
            out.append(Listing(**r))
        except Exception:  # noqa: BLE001
            continue
    return out


# --------------------------------------------------------------------------- reporting

def _mask(name: str | None) -> str | None:
    if not name:
        return name
    return name[0] + "*" * min(6, max(1, len(name) - 1))


def describe(rows: list[Listing], board_keys: set[str] | None, show_pii: bool) -> dict:
    n = len(rows)
    new = sum(1 for li in rows if board_keys is not None and not (listing_keys(li) & board_keys))
    cov = {
        "parcel": sum(1 for li in rows if li.parcel_id), "street": sum(1 for li in rows if li.street_address),
        "owner": sum(1 for li in rows if li.owner_name),
        "amount": sum(1 for li in rows if (li.raw or {}).get("tax_owed")),
        "sale_date": sum(1 for li in rows if li.sale_date),
    }
    owed = sum(((li.raw or {}).get("tax_owed") or {}).get("balance") or 0 for li in rows)
    sample = None
    if rows:
        li = rows[len(rows) // 2] if n > 2 else rows[0]
        sample = {"county": li.county, "state": li.state, "type": li.listing_type.value,
                  "parcel": li.parcel_id, "street": li.street_address, "zip": li.zip_code,
                  "owner": li.owner_name if show_pii else _mask(li.owner_name),
                  "sale_date": str(li.sale_date.date()) if li.sale_date else None,
                  "balance": ((li.raw or {}).get("tax_owed") or {}).get("balance"),
                  "description": (li.description or "")[:110]}
    return {"rows": n, "would_be_new": new if board_keys is not None else None,
            "already_on_board": (n - new) if board_keys is not None else None,
            "coverage": cov, "total_tax_owed": round(owed, 2),
            "by_county": dict(Counter(f"{li.state} {li.county}" for li in rows).most_common(8)),
            "by_type": dict(Counter(li.listing_type.value for li in rows)), "sample": sample}


def _print_report(key: str, meta: dict, d: dict, scope_dropped: Counter) -> None:
    print(f"\n=== {key}: fetched {meta['fetched']}, kept {meta['kept']} in {meta['seconds']}s"
          + (f"   ERROR {meta['error']}" if meta.get("error") else ""))
    if not d["rows"]:
        return
    print(f"    types {d['by_type']}   counties {d['by_county']}")
    print(f"    coverage {d['coverage']}   tax owed in sample ${d['total_tax_owed']:,.2f}")
    if d["would_be_new"] is not None:
        print(f"    new vs board: {d['would_be_new']} new, {d['already_on_board']} already on the board")
    for why, c in scope_dropped.items():
        print(f"    scope gate would drop {c}: {why}")
    print(f"    sample row: {d['sample']}")


# --------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="fetch in full, take the board lock, write the board")
    ap.add_argument("--sources", default=None,
                    help="comma list of: " + ", ".join(SPECS) + ". Default: all for a dry run; for --apply "
                         "all EXCEPT catalis, which is hours at its 8 s pace and must be asked for by name")
    ap.add_argument("--limit", type=int, default=25, help="dry run: rows per source (default 25)")
    ap.add_argument("--catalis-counties", default=",".join(NEW_CATALIS_COUNTIES))
    ap.add_argument("--catalis-mobile-homes", action="store_true",
                    help="also read Aiken/Fairfield 'Mobile Home' bills (CATALIS_ROLL_MOBILE_HOMES=1)")
    ap.add_argument("--merge-matches", action="store_true", help="fill blanks on rows that already exist")
    ap.add_argument("--harvest", help="apply: write fetched rows here first; reuse the file if it exists")
    ap.add_argument("--board", default=str(BOARD_GZ), help="published board for the dry-run key scan")
    ap.add_argument("--no-scan", action="store_true", help="dry run: skip the board key scan")
    ap.add_argument("--show-pii", action="store_true", help="dry run: do not mask owner names in samples")
    args = ap.parse_args(argv)

    if args.sources is None:
        args.sources = ",".join(k for k in SPECS if not (args.apply and k == "catalis"))
        if args.apply:
            print("--sources not given: applying all except catalis (ask for it by name: --sources catalis)")
    keys = [k.strip() for k in args.sources.split(",") if k.strip()]
    bad = [k for k in keys if k not in SPECS]
    if bad:
        print(f"unknown source(s): {bad}; choose from {list(SPECS)}")
        return 2
    os.environ["CATALIS_ROLL_COUNTIES"] = args.catalis_counties
    if args.catalis_mobile_homes:
        os.environ["CATALIS_ROLL_MOBILE_HOMES"] = "1"

    # ---- fetch (before any lock) ----
    harvest = Path(args.harvest) if args.harvest else None
    gathered: dict[str, list[Listing]] = {}
    metas: dict[str, dict] = {}
    if args.apply and harvest and harvest.exists():
        loaded = load_harvest(harvest)
        print(f"reusing harvest {harvest}: {len(loaded):,} rows")
        by_slug: dict[str, list[Listing]] = {}
        for li in loaded:
            by_slug.setdefault(li.source, []).append(li)
        for k in keys:
            if SPECS[k].slug in by_slug:
                gathered[k] = by_slug[SPECS[k].slug]
                metas[k] = {"fetched": len(gathered[k]), "kept": len(gathered[k]), "seconds": 0.0, "error": None}
    for k in keys:
        if k in gathered:
            continue
        print(f"fetching {k} ({'FULL' if args.apply else f'sample, limit {args.limit}'}) ...", flush=True)
        gathered[k], metas[k] = asyncio.run(fetch_source(SPECS[k], None if args.apply else args.limit))

    all_rows = [li for k in keys for li in gathered[k]]
    if args.apply and harvest and all_rows:
        save_harvest(harvest, all_rows)
        print(f"harvest written: {harvest} ({len(all_rows):,} rows)")

    # ---- dry run ----
    if not args.apply:
        board_keys = None
        if not args.no_scan and Path(args.board).exists():
            wanted = {((li.state or "").upper(), (li.county or "").strip().lower()) for li in all_rows}
            t0 = time.monotonic()
            board_keys, total, per_county = scan_board(Path(args.board), wanted)
            print(f"\nboard scan: {total:,} rows streamed once in {time.monotonic() - t0:.1f}s; "
                  f"existing rows in the counties in play: {sum(per_county.values()):,}")
        else:
            print("\nboard scan skipped")
        for k in keys:
            rows = gathered[k]
            kept, dropped = in_scope_and_live(rows)
            _print_report(k, metas[k], describe(rows, board_keys, args.show_pii), dropped)
        print("\nDRY RUN: nothing written, no lock taken, no board loaded.")
        return 0

    # ---- apply ----
    if not all_rows:
        print("nothing fetched; aborting")
        return 1
    scoped, dropped = in_scope_and_live(all_rows)
    print(f"\nfetched {len(all_rows):,}; {len(scoped):,} pass the scope gate")
    for why, c in dropped.items():
        print(f"  dropped {c:,}: {why}")
    if not scoped:
        return 1
    from foreclosure_scraper.web_artifact import board_lock, load_board, write_artifact
    with board_lock(REPO, owner="ingest_new_county_sources"):
        rows = load_board(DOCS)
        print(f"board rows before: {len(rows):,}")
        stats = apply_rows(rows, scoped, merge_matches=args.merge_matches)
        for k in ("new_in", "dup_within_new", "matched_untouched", "matched_merged", "added"):
            print(f"  {k:<20}{stats[k]:>9,}")
        for src, n in sorted(stats["added_by_source"].items()):
            print(f"    +{n:>7,}  {src}")
        assert stats["after"] >= stats["before"], "an ingest must never shrink the board"
        write_artifact(rows, {
            "total": stats["after"], "off_footprint_removed": 0,
            "notes": (f"new county sources ingest 2026-09-21: {stats['new_in']:,} in, "
                      f"{stats['added']:,} net-new, {stats['matched_untouched'] + stats['matched_merged']:,} "
                      f"already on the board. Existing rows untouched."),
        }, docs_dir=DOCS)
        print(f"wrote board: {stats['before']:,} -> {stats['after']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

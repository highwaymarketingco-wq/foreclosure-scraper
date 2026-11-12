#!/usr/bin/env python
"""Live proof for the top-80 verification group: run each named verifier on a few real board rows
and print verdict COUNTS (never a name, address or notice text).

    uv run python scripts/top80_verify_proof.py --board docs/listings.json.gz --per 6
    uv run python scripts/top80_verify_proof.py --board <checkpoint dir> --only tax_lien_pwa --per 4
    uv run python scripts/top80_verify_proof.py --notices            # nc_heir_notices, one live fetch

One board pass (streamed; never loaded whole), then one row at a time through the sweep's own
Fetcher (2 s between requests to a host). Read-only: the ledgers are not written.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

DEFAULT = ("nc_ecourts_case", "heir_roll", "tax_lien_perquimans", "tax_lien_itsnet", "tax_lien_pwa")


def pick(board: Path, verifiers: dict, per: int, seed: int) -> dict:
    """{verifier name: [rows]} with at most `per` rows, spread over distinct counties."""
    import gap_matrix as gm
    rnd = random.Random(seed)
    pools: dict = collections.defaultdict(list)
    for row in gm.board_rows(board):
        for name, v in verifiers.items():
            try:
                if not v.applies(row):
                    continue
            except Exception:  # noqa: BLE001
                continue
            pool = pools[name]
            if len(pool) < 400:
                pool.append(row)
            elif rnd.randrange(2000) < 400:
                pool[rnd.randrange(400)] = row
    out = {}
    for name, rows in pools.items():
        rnd.shuffle(rows)
        seen: set = set()
        chosen = []
        for r in rows:
            if r.get("county") in seen and len(seen) < per:
                continue
            seen.add(r.get("county"))
            chosen.append(r)
            if len(chosen) >= per:
                break
        out[name] = chosen
    return out


async def run(chosen: dict, verifiers: dict) -> None:
    from foreclosure_scraper.verification.fetch import Fetcher
    f = Fetcher()
    for name, rows in chosen.items():
        tally: collections.Counter = collections.Counter()
        for row in rows:
            try:
                res = await asyncio.wait_for(verifiers[name].verify(row, f), timeout=180)
                tally[(res.verdict, res.evidence.get("reason") or "")] += 1
            except Exception as exc:  # noqa: BLE001
                tally[("error", type(exc).__name__)] += 1
        print(f"{name}: {len(rows)} rows in {len({r.get('county') for r in rows})} counties -> "
              + ", ".join(f"{v}{'/' + why if why else ''} {n}" for (v, why), n in sorted(tally.items())))
    print("requests:", f.stats())


async def notices() -> None:
    from foreclosure_scraper.scrapers.public_notices.nc_heir_notices import NcHeirNotices
    rows = list(await NcHeirNotices().fetch())
    kinds = collections.Counter(r.raw["heir_naming_publication"]["kind"] for r in rows)
    print(f"nc_heir_notices: {len(rows)} leads in {len({r.county for r in rows})} counties; "
          f"kinds {dict(kinds)}; with parcel {sum(1 for r in rows if r.parcel_id)}; "
          f"quiet-title {sum(1 for r in rows if r.raw['heir_naming_publication']['is_quiet_title'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=str(REPO / "docs" / "listings.json.gz"))
    ap.add_argument("--per", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="", help="comma list of verifier names")
    ap.add_argument("--notices", action="store_true")
    args = ap.parse_args()
    if args.notices:
        asyncio.run(notices())
        return
    from foreclosure_scraper.verification.registry import discover
    names = [n for n in (args.only.split(",") if args.only else DEFAULT) if n]
    verifiers = {v.name: v for v in discover() if v.name in names}
    chosen = pick(Path(args.board), verifiers, args.per, args.seed)
    asyncio.run(run(chosen, verifiers))


if __name__ == "__main__":
    main()

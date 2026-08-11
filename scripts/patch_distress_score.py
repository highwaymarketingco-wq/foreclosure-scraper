"""Apply the stacked-distress score (HOT/WARM/COLD tiers) to docs/listings.json
and republish. Pure computation over existing signals — no scraping."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.distress_score import score_board
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, _to_dict, board_lock, read_board_json,
)

REPO = Path(__file__).resolve().parent.parent


def _hydrate(d: dict) -> Listing | None:
    fields = {k: v for k, v in d.items() if k in Listing.model_fields}
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)
    try:
        li = Listing.model_validate(fields)
    except Exception:
        return None
    li.raw = d.get("raw") or {}
    return li


def main() -> int:
    # THE LOCK. This script rewrites docs/listings.json in place, so it is a
    # board writer like any other and must not run beside one — the loser's
    # work is silently reverted, with no error anywhere. See
    # web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="patch_distress_score.py"):
            return _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping.", flush=True)
        return 0


def _run() -> int:
    path = Path("docs/listings.json")
    # read_board_json, not json.loads: on a fresh clone (or any checkout where
    # the >100MB uncompressed twin has not been rebuilt) only the committed
    # listings.json.gz exists, and reading the plain path raises there.
    data = read_board_json(path)
    listings, by_id = [], {}
    for d in data:
        li = _hydrate(d)
        if li:
            listings.append(li)
            by_id[id(li)] = d
    hist = score_board(listings)
    print(f"[{time.strftime('%H:%M:%S')}] tiers: {hist}", flush=True)

    for li in listings:
        by_id[id(li)]["raw"] = _to_dict(li)["raw"]

    path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    hot = sum(1 for x in data if (x.get("raw") or {}).get("distress_stack", {}).get("tier") == "HOT")
    warm = sum(1 for x in data if (x.get("raw") or {}).get("distress_stack", {}).get("tier") == "WARM")
    print(f"[{time.strftime('%H:%M:%S')}] wrote — {hot} HOT, {warm} WARM", flush=True)
    import gzip as _gz  # regen the .gz the dashboard fetches (listings.json is gitignored)
    _p = Path("docs/listings.json")
    (_p.parent / "listings.json.gz").write_bytes(_gz.compress(_p.read_bytes(), compresslevel=9, mtime=0))

    # THIS SCRIPT DOES NOT PUBLISH. Unconditionally, by design, always.
    #
    # It is a board writer that BYPASSES write_artifact(): it mutates
    # docs/listings.json in place and regenerates only listings.json.gz, so it
    # cannot regenerate docs/listings_slim.json.gz or docs/detail_shards/ — the
    # index-aligned mobile payloads write_artifact() emits from the same call.
    # Pushing the board without them ships a fresh board beside a slim file and
    # a shard set describing the PREVIOUS one: phones render stale tiers, and
    # because a shard is joined to the board BY ARRAY INDEX, any change to the
    # record count or order hands one lead's comps, vision and CAMA to a
    # different lead's address. Desktop looks perfect throughout.
    #
    # WHAT USED TO BE HERE was `if (docs/listings_slim.json.gz).exists() or
    # (docs/detail_shards).exists(): return 0`, followed by a git add/commit/push
    # block gated on STACK_PUBLISH. The comment described that as a conditional
    # guard. It has not been conditional since both payloads started shipping on
    # every publish — both always exist, the branch always fires, and the publish
    # block below it was dead code that nothing had reached in months. A guard
    # whose comment claims it sometimes lets you through is worse than no
    # comment: it sends the next reader looking for the run where it did.
    #
    # NOTHING IS LOST BY NOT PUBLISHING. The mutation is persisted to
    # docs/listings.json, and the next write_artifact() caller (the daily vision
    # pass, the noon lrcpwa pass, run_local.sh, recompute_valuation.py) loads it
    # through load_board() and re-emits board + detail + slim + shards together
    # from one payload. The score ships on the next publish, joined correctly.
    print(f"[{time.strftime('%H:%M:%S')}] docs/listings.json updated in place "
          f"({hot} HOT, {warm} WARM). NOT PUBLISHING — this script cannot "
          "regenerate docs/listings_slim.json.gz or docs/detail_shards/, and "
          "shipping the board without them mis-joins every phone.\n"
          "  It will go live on the next write_artifact() publish (the daily "
          "vision pass, the noon lrcpwa pass, or run_local.sh).\n"
          "  To publish now:  uv run python scripts/recompute_valuation.py",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Backfill owner + mailing + absentee/out-of-state onto the existing board.

The #0 contactability fix. Runs enrich_owner_mailing over the board (county
ArcGIS REST, free, no token), fills raw['owner_mailing'] + parcel_id (plus GIS
specs/value/CAMA backfill where the record exposes them), and lands only the
rows that actually changed. Incremental: skips listings already filled.

BOARD I/O REWRITE (2026-10-01, docs/HANDOFF.md item 21/24 -- same migration
family as _dq_common.run_apply()'s and lrcpwa_refresh.py's 2026-10-01
rewrites). This used to call read_board_json() to parse the WHOLE board into
one `data` list, hydrate every row into a Listing, mutate, then rewrite
docs/listings.json directly with path.write_text(json.dumps(data)) followed by
reseal_board(resplit=True) -- two full copies of the whole board (the parsed
object graph AND the serialized output string) alive at once, every run,
entirely bypassing write_artifact()/patch_existing_rows(). This is the
"manual trap" docs/HANDOFF.md item 21 flagged: not on any schedule, but one
`uv run python scripts/patch_owner_mailing.py` away from an OOM on today's
2.4+ GB board.

CLASSIFICATION (traced through enrich_owner_mailing() in full, not assumed):
its own `targets` filter reads only each row's OWN fields -- state, county,
street_address, parcel_id, listing_type, raw['owner_mailing'] -- no cross-row
comparison, no board-wide aggregation. Each target is then resolved
independently against county GIS. This is a bounded, per-row pass, the same
shape as sos_agent_refresh.py's/lrcpwa_refresh.py's enrichers, NOT a
whole-board operation like distress_score.score_board() (see
patch_distress_score.py and docs/HANDOFF.md item 24 for that one, which is
NOT migrated for exactly this distinction).

THE LAZY-DETAIL SUBTLETY (checked carefully, not assumed -- the same check
that mattered for lrcpwa_refresh.py's calc/grade recompute). The only raw key
enrich_owner_mailing() writes that is also a LAZY_DETAIL_KEY is 'cama' (county
CAMA distress), and it is an unconditional REPLACE (`li.raw["cama"] = dist`)
built fresh from the GIS response, never read first -- verified by grepping
every `li.raw` access in enrichment_owner_mailing.py (only 'owner_mailing' is
ever READ). So building the working set from board_stream.iter_board_rows()
(the slim stream, no lazy-detail sidecar merge) rather than
web_artifact._iter_board_records() cannot impoverish anything this script
computes: there is nothing here that reads an existing vision/comps/cama/
rent_comps/foreclosure_sold_comps value to decide what to write.

HOW. One board_stream.iter_board_rows() pass, hydrated through this script's
own _hydrate() (kept exactly as it was: it tolerates a stale/invalid
listing_type or property_kind string by dropping just that ONE field rather
than the whole row, which a plain Listing.model_validate() would not -- a
real behavioral difference from _dq_common._light_rows(), which is why that
helper is not reused here even though its shape is very close), building a
full list[Listing] in memory. This is still a FULL materialization (every row
held at once, same as load_board() and _dq_common.run_apply()'s
_light_rows()) -- enrich_owner_mailing()'s targets need no repeated/random
cross-row access, so a true constant-memory per-row dispatch (like
lrcpwa_refresh.py's) was possible in principle, but was not worth the
duplication risk here for a single enricher; the real win is dropping the
sidecar-merge cost (load_board()'s documented dominant factor) and replacing
the write. A pre-mutation snapshot of every row (dedupe_key(), computed
BEFORE enrich_owner_mailing() can fill parcel_id, plus a JSON-mode dump of
every scalar field and a deep copy of raw) is taken before enrichment runs,
diffed against each row's post-mutation state, and only rows that actually
changed land via web_artifact.patch_existing_rows() -- which MERGES `raw`
rather than replacing it, so an existing row's vision/comps/grade/skip_trace
(none of which this script ever loads) survive untouched.

DISCLOSED BEHAVIOR CHANGE (an improvement, not a regression -- called out
explicitly, same as lrcpwa_refresh.py's disclosed changes, rather than left
for someone to discover later). The OLD code only ever copied TWO things from
the mutated Listing back onto the row it wrote: raw (via
`_to_dict(li)["raw"]`, a full raw REPLACE) and parcel_id. But
enrich_owner_mailing() also fills tax_value/market_value/assessed_value/
living_sqft/year_built/bedrooms/bathrooms directly on the Listing when the
GIS record exposes them (see its own "Backfill building specs" / "feeds the
proxy-ARV" comments) -- those scalar fills were computed every run and then
silently discarded, never reaching docs/listings.json. Confirmed by reading
enrichment_owner_mailing.py in full, not assumed. The new diff (every scalar
field, before vs. after) persists these like any other field now.

THIS SCRIPT STILL DOES NOT FULLY PUBLISH. patch_existing_rows(), like the
load_board()/write_artifact() pair it replaces here, does not regenerate
docs/listings_slim.json.gz or docs/detail_shards/ (see its own docstring) --
same disclosed gap as lrcpwa_refresh.py/sos_agent_refresh.py/
patch_vision_gemini.py already live with. Unlike the OLD code's hand-rolled
reseal_board(resplit=True), it DOES correctly pop the lazy-detail sidecar
(vision/comps/cama/...) back out of listings.json's raw into
listings_detail.json(.gz) and re-cut listings_part_NNN.json.gz itself, so
there is no longer a window where a freshly-written 'cama' sits inline in
listings.json waiting for the next write_artifact() to split it back out.
The next real write_artifact() caller (the daily vision pass, the noon
lrcpwa pass, run_local.sh, recompute_valuation.py) still owns refreshing
slim/shards.

NOT LIVE-TESTED against the real board (same memory-safety reasoning as
every other 2026-09-30/10-01 migration this week: ~80 MB free / ~78% swap at
migration time did not permit even a read-only live probe to be worth the
risk, and a write was never on the table regardless). See docs/HANDOFF.md
item 24 for the recommended supervised follow-up. Synthetic-fixture tests
only: tests/test_patch_owner_mailing_patch_integration.py.
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from _dq_common import require_raw_keep  # noqa: E402

from foreclosure_scraper.board_stream import iter_board_rows
from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.enrichment_owner_mailing import enrich_owner_mailing
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, board_lock, patch_existing_rows, _raise_if_board_too_large_to_patch,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: raw keys this script (or enrich_owner_mailing() on its behalf) writes -- checked against
#: web_artifact.RAW_KEEP before touching anything, same defensive preflight
#: _dq_common.run_apply() uses (all three are already registered; this just keeps it that way).
REQUIRED_RAW_KEYS = ("owner_mailing", "cama", "distressed")


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


def _diff_raw(before: dict | None, after: dict | None) -> dict:
    """{raw sub-key: new value} for every key this pass added or changed. A plain add/change
    diff is safe here -- enrich_owner_mailing() never pops or deletes a raw key, only ever sets
    one (verified by reading it in full; see this module's docstring)."""
    before = before or {}
    after = after or {}
    return {k: v for k, v in after.items() if before.get(k) != v}


def _diff_row(li: Listing, before_scalars: dict, before_raw: dict | None) -> dict | None:
    """Build patch_existing_rows()'s per-row update dict from a pre-mutation snapshot, or None
    if nothing changed."""
    update: dict = {}
    after_scalars = li.model_dump(mode="json", exclude={"raw"})
    for k, v in after_scalars.items():
        if before_scalars.get(k) != v:
            update[k] = v
    raw_update = _diff_raw(before_raw, li.raw if isinstance(li.raw, dict) else None)
    if raw_update:
        update["raw"] = raw_update
    return update or None


async def main() -> int:
    # THE LOCK. This script writes the board, so it is a board writer like any other and must
    # not run beside one -- the loser's work is silently reverted, with no error anywhere. See
    # web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="patch_owner_mailing.py"):
            return await _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping.", flush=True)
        return 0


async def _run() -> int:
    require_raw_keep(REQUIRED_RAW_KEYS)
    # Fail before the expensive full-list build, not after -- the same ceiling
    # patch_existing_rows() itself re-checks before writing.
    _raise_if_board_too_large_to_patch(DOCS)

    listings: list[Listing] = []
    pre: list[tuple[str | None, dict, dict | None]] = []
    dropped = 0
    for rec in iter_board_rows(DOCS / "listings.json.gz"):
        li = _hydrate(rec)
        if li is None:
            dropped += 1
            continue
        listings.append(li)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001 - a row too malformed to key is simply unpatchable
            key = None
        pre.append((key, li.model_dump(mode="json", exclude={"raw"}),
                    copy.deepcopy(li.raw) if isinstance(li.raw, dict) else None))
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)}"
          + (f" (dropped {dropped})" if dropped else ""), flush=True)

    t0 = time.time()
    counts = await enrich_owner_mailing(
        listings, max_concurrency=int(os.environ.get("OM_CONCURRENCY", "6")))
    print(f"[{time.strftime('%H:%M:%S')}] owner/mailing: {counts} in {int(time.time() - t0)}s",
          flush=True)

    patches: dict[str, dict] = {}
    for li, (key, before_scalars, before_raw) in zip(listings, pre):
        if key is None:
            continue
        update = _diff_row(li, before_scalars, before_raw)
        if update:
            patches[key] = update

    mailable = sum(1 for li in listings
                   if isinstance(li.raw, dict) and (li.raw.get("owner_mailing") or {}).get("mailing"))

    if not patches:
        print(f"[{time.strftime('%H:%M:%S')}] nothing to patch — mailable now {mailable}",
              flush=True)
        return 0

    stats = patch_existing_rows(patches, {"notes": "owner/mailing backfill"}, docs_dir=DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] wrote board | patched {stats['applied']:,} of "
          f"{len(patches):,} changed row(s) (existing board: {stats['existing']:,}) — "
          f"mailable now {mailable}", flush=True)

    # THIS SCRIPT STILL DOES NOT FULLY PUBLISH. See this module's docstring: patch_existing_rows()
    # does not regenerate docs/listings_slim.json.gz or docs/detail_shards/, same disclosed gap
    # every other 2026-09-30/10-01 streaming migration carries. NOTHING IS LOST: the next
    # write_artifact() caller (the daily vision pass, the noon lrcpwa pass, run_local.sh,
    # recompute_valuation.py) re-emits board + detail + slim + shards together from one payload.
    print(f"[{time.strftime('%H:%M:%S')}] NOT fully published — patch_existing_rows() does not "
          "regenerate docs/listings_slim.json.gz or docs/detail_shards/.\n"
          "  It will go live on the next write_artifact() publish (the daily vision pass, the "
          "noon lrcpwa pass, or run_local.sh).\n"
          "  To publish now:  uv run python scripts/recompute_valuation.py",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""Daily incremental court-detail pass over the board.

Drills into per-case court records to capture judgment / balance / sale
documents / sale_status (incl. the confirmed-sold flag that filters
already-sold properties off the board). Browser-based (Tyler + SC Public
Index sit behind anti-bot), so LOCAL-only and capped per run; incremental
(skips already-enriched cases) so coverage builds across days like vision.

  NC_ECOURTS_INCREMENTAL=1 NC_ECOURTS_AUTH_CAP=150 \
  SC_COURT_INCREMENTAL=1 SC_COURT_CAP=80 \
    uv run python scripts/patch_court_detail.py

BOARD I/O REWRITE (2026-10-01, docs/HANDOFF.md item 21/24 -- same migration
family as _dq_common.run_apply()'s and lrcpwa_refresh.py's 2026-10-01
rewrites). This used to call read_board_json() to parse the WHOLE board into
one `data` list, hydrate every row into a Listing, run both enrichers over
the full list, then rewrite docs/listings.json directly with
path.write_text(json.dumps(data)) followed by reseal_board(resplit=True) --
two full copies of the whole board alive at once, every run, entirely
bypassing write_artifact()/patch_existing_rows(). This is one of the two
undocumented siblings of patch_distress_score.py docs/HANDOFF.md item 21
found: not on any schedule today (its wrapper, run_daily_court.sh, was
disabled via com.highway.foreclosure.dailycourt.plist on 2026-09-20), but one
`bash scripts/run_daily_court.sh` or plist re-enable away from being live
again against a board that has since grown past even the streaming-patch
ceiling.

CLASSIFICATION (traced through both enrichers in full, not assumed).
enrich_with_nc_case_status_authenticated() and enrich_case_detail_addresses()
each build their OWN bounded `targets` list from the full `listings`
population (NC_ECOURTS_AUTH_CAP / SC_COURT_CAP), reading only identity/state
fields (state, case_number, county, street_address, source, and
raw['court_sale_status']/raw['nc_case_status'] for the incremental skip) --
no cross-row comparison, no board-wide aggregation. This is a bounded,
per-row (browser-driven, hence capped) pass, NOT a whole-board operation like
distress_score.score_board() (see patch_distress_score.py and
docs/HANDOFF.md item 24, which is NOT migrated for exactly that distinction).

THE LAZY-DETAIL SUBTLETY (checked carefully -- the exact hazard
lrcpwa_refresh.py's own migration documents, and the reason this script does
NOT use board_stream.iter_board_rows() the way patch_owner_mailing.py's
sibling migration does). Neither enricher touches a lazy-detail key (verified
by grep: enrichment_nc_case_status_tyler.py / enrichment_case_detail.py never
read or write vision/comps/cama/rent_comps/foreclosure_sold_comps). BUT this
script's own post-pass recomputes calc/grade for every row that just gained a
court_sale_status or nc_case_status, via valuation.calc.compute(), and
calc.compute() DOES read raw['vision']/raw['cama']/raw['comps'] (confirmed by
grep, same as lrcpwa_refresh.py's docstring already established). A plain
board_stream.iter_board_rows() slim read would silently impoverish every
recomputed calc/grade on this script's touched rows -- exactly the hazard
being guarded against here. So this reads via
web_artifact._iter_board_records() (sidecar merged), not the slim stream.

DISCLOSED BEHAVIOR CHANGE (an improvement, not a regression -- called out
explicitly rather than left for someone to discover later). Because
read_board_json() (the OLD reader) only ever parsed docs/listings.json and
never merged listings_detail.json, this script's calc/grade recompute was
ALREADY running without vision/comps/cama on any board that had been through
a normal write_artifact() publish since the last time a lazy-detail key was
set (the common case) -- a real, silent, pre-existing impoverishment, not
introduced by this migration. Reading via _iter_board_records() fixes it as a
side effect of adopting the correct primitive; flagged here rather than left
for someone to notice a sudden swing in recomputed grades.

A second, separate disclosed fix: the OLD code only ever copied
judgment_amount and street_address from the mutated Listing back onto the
row it wrote. But enrich_with_nc_case_status_authenticated() also sets
li.sale_date directly (see its own "det[\"judgment_amount\"]" /
"_docket_dt" assignments) -- verified by reading
enrichment_nc_case_status_tyler.py in full. That scalar fill was computed
every run and silently discarded, never reaching docs/listings.json. The new
diff (every scalar field, before vs. after) persists it now.

HOW, CONCRETELY. One _iter_board_records() pass hydrates every row through
this script's own _hydrate() (kept exactly as it was: tolerates a stale/
invalid listing_type or property_kind string by dropping just that ONE field
rather than the whole row) into a full list[Listing] -- still a FULL
materialization, WITH the sidecar merge, i.e. the SAME memory profile
load_board() has (unlike patch_owner_mailing.py's sibling migration, which
could drop the sidecar-merge cost; this script genuinely cannot, because its
calc/grade recompute needs it). The two real, UNCHANGED enrichers then run
over that list exactly as before (same asyncio.wait_for/timeout budget, same
NC_ECOURTS_INCREMENTAL/SC_COURT_INCREMENTAL env defaults), followed by the
same per-row calc/grade recompute the original ran. A pre-mutation snapshot
of every row (dedupe_key(), computed BEFORE either enricher can fill
street_address -- an identity field -- plus a JSON-mode dump of every scalar
field and a deep copy of raw) is taken before anything runs, diffed against
each row's post-mutation state, and only rows that actually changed land via
web_artifact.patch_existing_rows() -- which MERGES `raw` rather than
replacing it, so an existing row's comps/skip_trace/etc. survive untouched.
Not a true constant-memory redesign (unlike lrcpwa_refresh.py's bespoke
single-pass target collection): re-deriving both enrichers' own internal
targeting/capping logic externally, just to avoid holding the full list, was
judged not worth the duplication risk for this migration -- the same
tradeoff _dq_common.run_apply()'s _light_rows() documents making for its own
nine callers.

THIS SCRIPT STILL DOES NOT FULLY PUBLISH. patch_existing_rows() does not
regenerate docs/listings_slim.json.gz or docs/detail_shards/ (see its own
docstring) -- same disclosed gap every other 2026-09-30/10-01 streaming
migration carries. Unlike the OLD code's hand-rolled reseal_board(resplit=
True), it DOES correctly keep the lazy-detail sidecar split between
listings.json and listings_detail.json(.gz) and re-cut
listings_part_NNN.json.gz itself. The next real write_artifact() caller
still owns refreshing slim/shards.

NOT LIVE-TESTED against the real board (same memory-safety reasoning as
every other 2026-09-30/10-01 migration this week: ~80 MB free / ~78% swap at
migration time did not permit even a read-only live probe to be worth the
risk, and a write was never on the table regardless). Given this script
genuinely cannot drop the sidecar-merge cost, a supervised live dry run (RSS
watchdog, BOARD_PATCH_ALLOW_LARGE=1 if needed) matters MORE here than for
patch_owner_mailing.py -- see docs/HANDOFF.md item 24. Synthetic-fixture
tests only: tests/test_patch_court_detail_patch_integration.py.
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

from foreclosure_scraper.models import Listing, ListingType, PropertyKind
from foreclosure_scraper.valuation import calc as vcalc
from foreclosure_scraper.valuation import grading as vgrade
from foreclosure_scraper.web_artifact import (
    BoardLockBusy, _iter_board_records, board_lock, patch_existing_rows,
    _raise_if_board_too_large_to_patch,
)

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"

#: raw keys this script (or the court enrichers on its behalf) write -- checked against
#: web_artifact.RAW_KEEP before touching anything, same defensive preflight
#: _dq_common.run_apply() uses (all are already registered; this just keeps it that way).
REQUIRED_RAW_KEYS = ("court_sale_status", "nc_case_status", "calc", "grade")


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
    diff is safe here -- neither court enricher nor the calc/grade recompute ever pops or
    deletes a raw key, only ever sets one (verified by reading all four modules in full)."""
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
    # not run beside one -- the loser's work is silently reverted, with no error anywhere. It
    # also runs for up to COURT_MAX_SECONDS=3600 by default, which is more than long enough to
    # straddle the noon and 2pm scheduled passes. See web_artifact.board_lock.
    try:
        with board_lock(REPO, owner="patch_court_detail.py"):
            return await _run()
    except BoardLockBusy as exc:
        print(f"{exc} — skipping.", flush=True)
        return 0


async def _run() -> int:
    require_raw_keep(REQUIRED_RAW_KEYS)
    # Fail before the expensive full-list build, not after -- the same ceiling
    # patch_existing_rows() itself re-checks before writing.
    _raise_if_board_too_large_to_patch(DOCS)

    os.environ.setdefault("NC_ECOURTS_INCREMENTAL", "1")
    os.environ.setdefault("SC_COURT_INCREMENTAL", "1")
    budget = float(os.environ.get("COURT_MAX_SECONDS", "3600"))

    listings: list[Listing] = []
    pre: list[tuple[str | None, dict, dict | None]] = []
    dropped = 0
    for rec in _iter_board_records(DOCS):
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
    print(f"[{time.strftime('%H:%M:%S')}] loaded {len(listings)} listings"
          + (f" (dropped {dropped})" if dropped else ""), flush=True)

    from foreclosure_scraper.enrichment_nc_case_status_tyler import (
        enrich_with_nc_case_status_authenticated)
    from foreclosure_scraper.enrichment_case_detail import enrich_case_detail_addresses

    t0 = time.time()
    try:
        await asyncio.wait_for(asyncio.gather(
            enrich_with_nc_case_status_authenticated(listings),
            enrich_case_detail_addresses(listings),
        ), timeout=budget)
    except asyncio.TimeoutError:
        print(f"[{time.strftime('%H:%M:%S')}] court pass hit cap ({budget:.0f}s) — writing partial",
              flush=True)
    except Exception as exc:
        print(f"[{time.strftime('%H:%M:%S')}] court pass error: {str(exc)[:160]}", flush=True)
    print(f"[{time.strftime('%H:%M:%S')}] court pass done in {int(time.time() - t0)}s", flush=True)

    tagged = 0
    for li in listings:
        if (li.raw or {}).get("court_sale_status") or (li.raw or {}).get("nc_case_status"):
            try:
                c = vcalc.compute(li)
                g = vgrade.grade(li, c)
                li.raw["calc"] = vcalc.to_dict(c)
                li.raw["grade"] = vgrade.to_dict(g)
            except Exception:  # noqa: BLE001 - matches the original script's own bare except here
                pass
            tagged += 1

    patches: dict[str, dict] = {}
    for li, (key, before_scalars, before_raw) in zip(listings, pre):
        if key is None:
            continue
        update = _diff_row(li, before_scalars, before_raw)
        if update:
            patches[key] = update

    if not patches:
        print(f"[{time.strftime('%H:%M:%S')}] nothing to patch — {tagged} listings carry court "
              "detail", flush=True)
        return 0

    stats = patch_existing_rows(patches, {"notes": "daily court-detail pass"}, docs_dir=DOCS)
    print(f"[{time.strftime('%H:%M:%S')}] wrote board | patched {stats['applied']:,} of "
          f"{len(patches):,} changed row(s) (existing board: {stats['existing']:,}) — "
          f"{tagged} listings carry court detail", flush=True)

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

"""Streaming-safe primitives for the two genuinely whole-board operations this codebase has:
`dedupe.dedupe()` (cross-bucket fuzzy address matching across the ENTIRE board) and
`distress_score.score_board()` (board-wide parcel grouping + HOT/WARM/COLD tiering).

BACKGROUND (task_board_dedupe_stream, 2026-10-01). Four scripts call one or both of these
functions on a FULLY-MATERIALIZED `list[Listing]` built by `web_artifact.load_board()`:
`scripts/daily_api_refresh.py`, `scripts/ingest_publicindex_files.py`,
`scripts/ingest_fresh_court_leads.py`, `scripts/patch_distress_score.py`. `docs/HANDOFF.md` items
15 and 24 already looked at this and concluded score_board() "needs ... the full `list[Listing]`
at once" and that forcing it onto the streaming primitives "would mean either re-materializing
the whole board anyway (no actual memory win) or silently changing the scoring algorithm's
cross-row grouping" -- true of a NAIVE port, but there is a third option neither of those two
considered: feed the REAL, UNMODIFIED `dedupe()`/`score_board()` a POPULATION OF LIGHTWEIGHT
LISTINGS instead of fully-hydrated ones.

WHY THIS IS SAFE, NOT A REIMPLEMENTATION. Both functions were read in full (not assumed) to
confirm exactly which fields they touch:
  * `dedupe()` (src/foreclosure_scraper/dedupe.py) never reads `Listing.raw` AT ALL. Its three
    passes (bucket by `dedupe_key()`, cross-bucket fuzzy match with zip/locale BLOCKING -- already
    sub-quadratic, not naive O(n^2) -- and signature union-find via `_strong_sigs()`) read only
    eight scalar fields: source, source_url, listing_type, street_address, city, state, zip_code,
    county, parcel_id, case_number (the same `_APPEND_SIG_FIELDS` tuple `append_new_rows()`/
    `patch_existing_rows()` already use for their own "light Listing" tricks). `raw` only matters
    inside `Listing.merge()` (called BY `dedupe()` to fold a bucket), which deep-merges it via
    `_deep_merge_dict()` -- harmless on an empty or near-empty `raw`.
  * `distress_score.score_board()`/`_score_group()`/`_collect()` (src/foreclosure_scraper/
    distress_score.py) were read in full and every `r.get(...)`/`raw.get(...)` call site was
    grepped to build `SCORE_RAW_KEYS` below -- an exhaustive, explicit whitelist of the raw
    sub-keys scoring actually touches. Everything else a fully-enriched row carries (vision,
    comps, cama, rent_comps, foreclosure_sold_comps -- the lazy-detail sidecar, already excluded
    by `board_stream.iter_board_rows()` -- plus description, assessor_card, gis_attrs, skip_trace,
    strategy_fit, buyer_match, multifamily_class, data_quality, outreach, images, and more) is
    never read by scoring and is dropped from the projection.

Because both functions are called HERE UNCHANGED -- not reimplemented -- on a population built
from this narrow field set, their output is correct by construction: whatever `dedupe()`/
`score_board()` would compute from the full board, they compute identically from the projection,
PROVIDED the projection really is exhaustive. `tests/test_board_dedupe_stream.py` proves this
empirically (same synthetic fixture, scored/deduped both the old whole-board way and the new
streaming way, asserted byte-identical) rather than resting on the grep alone.

THE TWO PRIMITIVES

  find_dedupe_merge_groups(docs_dir)
      PASS 1 (cheap, streaming): board_stream.iter_board_rows() once, building ONE lightweight
      Listing per row (the 8 scalar identity fields + raw={"_prov": {row_identity_hash: True}} --
      see _light_listing_for_dedupe()'s docstring for why a DICT, not a list, is what survives
      dedupe()'s own Listing.merge() calls un-clobbered: _deep_merge_dict() UNIONS dict values on
      a leaf collision, so the real dedupe() run below leaves each output stub's raw["_prov"]
      holding the exact UNION of every original row's identity hash that got folded into it --
      free provenance tracking, using dedupe()'s own existing merge semantics, no modification to
      dedupe.py/models.py needed).
      PASS 2 (cheap, pure computation): dedupe.dedupe() -- the REAL function -- runs on the
      lightweight population. Any output stub whose raw["_prov"] has 2+ keys names a group that
      needs to merge; one key means "no change, leave alone".
      PASS 3 (targeted, bounded): a second streaming pass retains only rows whose
      row_identity_hash() is in a pending group (a tiny fraction of the board), to pick which
      member survives as merge_groups' index 0 (completeness heuristic, same one
      scripts/run_duplicate_merge_20260930.py already uses in production). Returns merge_groups
      ready for `web_artifact.merge_duplicate_rows()` -- this function does NOT write; the caller
      applies via that existing, already-shipped, already-tested primitive (commit 6719e6bd),
      which does its own independent validation (refuses on any ambiguous/missing hash) before
      writing anything.

  stream_score_board(docs_dir, previous_path=None, today=None)
      PASS 1 (cheap, streaming): board_stream.iter_board_rows() once, building ONE lightweight
      Listing per row (the scalar fields `_collect()` reads + raw projected to SCORE_RAW_KEYS
      only), while separately recording each row's CURRENT raw['distress_stack'] and a count of
      how many board rows share its dedupe_key() (needed for the collision guard below).
      PASS 2 (cheap, pure computation): distress_score.score_board() -- the REAL function -- runs
      on the lightweight population, computing every row's new distress_stack exactly as a
      full-board run would (grouping is by parcel key, built from scalar fields only; see
      SCORE_RAW_KEYS' own comment for why the projection is still sufficient for the SIGNAL
      computation too, not just the grouping).
      PASS 3 (targeted, bounded): diff each row's new distress_stack against the one captured in
      PASS 1; only rows whose stack actually CHANGED become a patch entry, keyed by dedupe_key()
      (the same identity patch_existing_rows() itself re-derives internally, and the same pattern
      scripts/backfill_unlocatable_equity_retraction.py already uses in production for this exact
      field). A dedupe_key() shared by more than one board row is DROPPED from the patch set
      entirely (never guess which of several differently-scored rows a shared key was meant for
      -- same defensive collision check backfill_unlocatable_equity_retraction.py already applies)
      rather than applying one row's score to another. Returns the patches dict for the caller to
      apply via `web_artifact.patch_existing_rows()`.

DISCLOSED, DELIBERATE DIFFERENCE FROM THE IN-MEMORY ALGORITHM'S EXACT SHAPE. score_board() POPS
raw['distress_stack'] entirely when every listing on a parcel is sold_confirmed (no active
group). patch_existing_rows() can only SET fields on a raw dict (`raw.update(...)`), never DELETE
one, so stream_score_board() represents "no longer active" as an EMPTY dict ({}) instead of an
absent key. Every reader of raw['distress_stack'] in this codebase was grepped (2026-10-01): all
of them do `(raw.get("distress_stack") or {}).get(...)` or an equivalent "falsy input -> {}"
guard, for which {} and a missing key are indistinguishable. This is the one place this module's
output is not byte-identical to score_board()'s own in-memory mutation; everywhere else it is.

WHAT THIS DOES NOT SOLVE. `daily_api_refresh.py`/`ingest_publicindex_files.py`/
`ingest_fresh_court_leads.py` call dedupe()/score_board() on a list ALREADY held fully in memory
for OTHER reasons (equity/CAMA/GIS/title-risk/owner-mailing enrichment, which operate on full
Listing objects with full raw and are not in this module's scope) -- swapping just their dedupe()/
score_board() calls for these streaming primitives would not, by itself, reduce THOSE scripts'
peak memory, since load_board() already happened before either call runs. This module's complete,
unqualified win is for a script whose ONLY job is a whole-board dedupe/score pass with no other
full-row enrichment in between -- `scripts/patch_distress_score.py` is exactly that shape, and is
migrated onto `stream_score_board()` as the proof of concept. See docs/HANDOFF.md's entry for the
fuller writeup of why the other three are a smaller, differently-shaped win (the dedupe FINDER is
still useful there as a periodic, standalone cleanup pass -- the same role
scripts/run_duplicate_merge_20260930.py already plays -- rather than as an inline replacement."""
from __future__ import annotations

import collections
from pathlib import Path
from typing import Optional

from .board_stream import iter_board_rows
from .dedupe import dedupe
from .distress_score import score_board
from .models import Listing, ListingType, PropertyKind
from .web_artifact import row_identity_hash

#: The 8 scalar identity fields dedupe()'s bucket/fuzzy/signature passes read (dedupe_key(),
#: _strong_sigs(), _provably_different_property() -- verified by reading dedupe.py in full).
#: Identical to web_artifact._APPEND_SIG_FIELDS; kept as its own tuple here since that one is
#: private to web_artifact.py and this module has no reason to depend on its internals.
_DEDUPE_SCALAR_FIELDS = ("source", "source_url", "listing_type", "street_address", "city",
                        "state", "zip_code", "county", "parcel_id", "case_number")

#: The Listing scalar fields distress_score._collect()/_score_group()/_parcel_key() read,
#: verified by reading distress_score.py in full. Notably narrower than a full row: no
#: plaintiff/defendant/trustee/sale_time/sale_location/judgment_amount/legal_description/
#: zoning/acreage/*_sqft/bedrooms/bathrooms/year_built/assessed_value/market_value/tax_value/
#: land_use/description -- none of those are ever read by scoring.
_SCORE_SCALAR_FIELDS = ("source", "source_url", "listing_type", "property_kind",
                        "street_address", "city", "state", "zip_code", "county", "parcel_id",
                        "case_number", "sale_date", "opening_bid", "owner_name",
                        "redemption_deadline")

#: raw sub-keys distress_score.py actually reads -- grepped exhaustively against every
#: `r.get("...")`/`raw.get("...")` call site in distress_score.py (2026-10-01), not assumed from
#: the module's prose docstring. Copied WHOLESALE (not sub-projected further) into the
#: lightweight Listing's raw dict; everything else on a fully-enriched row (the lazy-detail
#: sidecar, already excluded by board_stream.iter_board_rows() -- plus description, assessor_card,
#: gis_attrs, skip_trace, strategy_fit, buyer_match, multifamily_class, data_quality, outreach,
#: images, resolved-name detail beyond `confidence`, and more) is dropped. If distress_score.py
#: ever starts reading a NEW raw sub-key, this whitelist goes stale silently unless
#: tests/test_board_dedupe_stream.py's equivalence tests are re-run with a fixture that actually
#: exercises the new key -- see that test file's own module docstring for the mitigation.
SCORE_RAW_KEYS = frozenset({
    "amount_owed", "bankruptcy", "bankruptcy_stay", "calc", "code_enforcement", "condemned",
    "condition_cama", "court_sale_status", "distressed", "divorce", "equity", "estate",
    "helene", "homeharvest", "incarceration", "jail_booking", "market_velocity",
    "owner_mailing", "pickens_delinquent", "probate", "redemption_deadline",
    "relationship_signal", "resolved_from_name", "scope", "sold_confirmed", "storm_damage",
    "str_permit_lapsed", "tax_owed", "tax_relief", "title_risk", "upset_bid", "vacancy",
    "vacant",
})


def _coerce_enums(fields: dict) -> None:
    for ef, enum in (("listing_type", ListingType), ("property_kind", PropertyKind)):
        if isinstance(fields.get(ef), str):
            try:
                fields[ef] = enum(fields[ef])
            except ValueError:
                fields.pop(ef, None)


def _light_listing_for_dedupe(rec: dict, prov_hash: str) -> Optional[Listing]:
    """A lightweight Listing carrying only dedupe()'s own 8 identity fields, plus a `_prov`
    dict-valued raw key recording this row's row_identity_hash().

    WHY A DICT, NOT A LIST, SURVIVES dedupe()'s MERGES. models._deep_merge_dict() -- the function
    Listing.merge() uses for `raw` -- recurses into a leaf ONLY when BOTH sides are dicts (unions
    their keys); for any other type (including a list) the incoming side's value simply REPLACES
    the existing one. A list-valued `_prov` would lose every hash but the last one merged in; a
    dict-valued one accumulates the full set for free, through dedupe()'s three passes, using
    dedupe()'s own existing merge semantics unmodified."""
    # Only keys actually PRESENT in `rec` -- same convention the codebase's own _hydrate()
    # helpers use (e.g. scripts/daily_api_refresh.py), so an absent `listing_type`/`property_kind`
    # falls back to the model's own enum default instead of failing validation on an explicit
    # None for a non-Optional field.
    fields = {k: rec[k] for k in _DEDUPE_SCALAR_FIELDS if k in rec}
    _coerce_enums(fields)
    fields["raw"] = {"_prov": {prov_hash: True}}
    try:
        return Listing.model_validate(fields)
    except Exception:  # noqa: BLE001 - a row too malformed to key is simply skipped
        return None


def _light_listing_for_scoring(rec: dict) -> Optional[Listing]:
    """A lightweight Listing carrying only the scalar fields and SCORE_RAW_KEYS raw sub-keys
    distress_score.py reads -- sufficient for score_board() to compute the identical
    distress_stack a full-board run would, without ever materializing the heavy keys a
    fully-enriched row also carries (vision/comps/cama/description/assessor_card/gis_attrs/...)."""
    fields = {k: rec[k] for k in _SCORE_SCALAR_FIELDS if k in rec}  # see _light_listing_for_dedupe
    _coerce_enums(fields)
    raw = rec.get("raw")
    fields["raw"] = ({k: raw[k] for k in SCORE_RAW_KEYS if k in raw}
                     if isinstance(raw, dict) else {})
    try:
        return Listing.model_validate(fields)
    except Exception:  # noqa: BLE001 - a row too malformed to score is simply skipped
        return None


def _completeness(rec: dict) -> tuple:
    """Same tie-break scripts/run_duplicate_merge_20260930.py already uses in production to pick
    which member of a duplicate group is the survivor: more populated raw keys + more of the
    core identity/value fields wins."""
    raw = rec.get("raw") or {}
    score = len(raw) if isinstance(raw, dict) else 0
    for f in ("case_number", "opening_bid", "sale_date", "owner_name", "owner_phone"):
        if rec.get(f):
            score += 1
    return (score, str(rec.get("source") or ""))


def find_dedupe_merge_groups(docs_dir: Path | str = "docs",
                             *, board_path: Path | str | None = None) -> tuple[list, dict]:
    """Find genuine duplicate-row groups by running the REAL dedupe() over a lightweight,
    streamed population -- see this module's own docstring for the full design and why it is
    correct, not a reimplementation.

    Returns (merge_groups, stats). merge_groups is already in the shape
    `web_artifact.merge_duplicate_rows()` expects (each group a list of row_identity_hash()
    values, survivor first) -- this function does NOT write; the caller applies it. `stats` is
    {scanned, skipped, candidate_groups, merge_groups, missing_in_pass2}.

    Does not hold the board lock itself (it writes nothing) -- the caller should still hold it
    across both this call and the merge_duplicate_rows() call that follows, so the board cannot
    change in between."""
    docs = Path(docs_dir)
    path = Path(board_path) if board_path is not None else (docs / "listings.json.gz")

    stubs: list[Listing] = []
    scanned = 0
    skipped = 0
    for rec in iter_board_rows(path):
        scanned += 1
        h = row_identity_hash(rec)
        li = _light_listing_for_dedupe(rec, h)
        if li is None:
            skipped += 1
            continue
        stubs.append(li)

    merged = dedupe(stubs)
    del stubs

    raw_groups: list[list[str]] = []
    for out in merged:
        prov = out.raw.get("_prov") if isinstance(out.raw, dict) else None
        if isinstance(prov, dict) and len(prov) >= 2:
            raw_groups.append(sorted(prov.keys()))
    del merged

    if not raw_groups:
        return [], {"scanned": scanned, "skipped": skipped, "candidate_groups": 0,
                    "merge_groups": 0, "missing_in_pass2": 0}

    needed = {h for g in raw_groups for h in g}

    # PASS 2 (of this finder; dedupe() above was the pure-computation pass): a second streaming
    # pass, retaining only the small candidate set, to pick the survivor by completeness.
    found: dict[str, dict] = {}
    n2 = 0
    for rec in iter_board_rows(path):
        n2 += 1
        h = row_identity_hash(rec)
        if h in needed:
            found[h] = rec
    if n2 != scanned:
        raise RuntimeError(
            f"board row count changed between dedupe-finder passes ({scanned} vs {n2}) -- "
            f"another writer touched it, aborting without producing merge_groups"
        )

    merge_groups: list[list[str]] = []
    missing = 0
    for g in raw_groups:
        recs = [found.get(h) for h in g]
        if any(r is None for r in recs):
            # A hash from PASS 1's dedupe() run vanished from the board between the two
            # passes (shouldn't happen given the row-count check above, but never guess which
            # member to drop) -- skip the whole group rather than merge a partial set.
            missing += 1
            continue
        order = sorted(range(len(g)), key=lambda i: _completeness(recs[i]), reverse=True)
        merge_groups.append([g[i] for i in order])

    stats = {"scanned": scanned, "skipped": skipped, "candidate_groups": len(raw_groups),
             "merge_groups": len(merge_groups), "missing_in_pass2": missing}
    return merge_groups, stats


def stream_score_board(docs_dir: Path | str = "docs", *, previous_path=None,
                       today=None, board_path: Path | str | None = None) -> dict:
    """Compute distress_stack for the whole board by running the REAL score_board() over a
    lightweight, streamed population -- see this module's own docstring for the full design.

    Returns {scanned, skipped, scored, changed, stack_removed, tiers, patches}. `patches` is
    already in the shape `web_artifact.patch_existing_rows()` expects (dedupe_key() -> {"raw":
    {"distress_stack": ...}}) -- this function does NOT write; the caller applies it (and should
    hold the board lock across both calls).

    Raises distress_score.ScoreBoardError exactly when score_board() itself would -- propagated
    unchanged, with NO patches computed or returned, mirroring the full-board callers' own
    convention (daily_api_refresh.py, main.py) of never publishing a partially-scored board."""
    docs = Path(docs_dir)
    path = Path(board_path) if board_path is not None else (docs / "listings.json.gz")

    light_listings: list[Listing] = []
    old_stacks: list[Optional[dict]] = []
    groups_by_key: dict[str, list[int]] = collections.defaultdict(list)
    scanned = 0
    skipped = 0
    for rec in iter_board_rows(path):
        scanned += 1
        li = _light_listing_for_scoring(rec)
        if li is None:
            skipped += 1
            continue
        idx = len(light_listings)
        light_listings.append(li)
        raw = rec.get("raw")
        old_stacks.append(raw.get("distress_stack") if isinstance(raw, dict) else None)
        try:
            key = li.dedupe_key()
        except Exception:  # noqa: BLE001
            key = None
        if key is not None:
            groups_by_key[key].append(idx)

    hist = score_board(light_listings, previous_path=previous_path, today=today)

    # Diff per DEDUPE_KEY GROUP, not per row: patch_existing_rows() applies ONE patch value to
    # every row matching a key, so a key shared by 2+ rows (the address/case branches of
    # dedupe_key() are looser than the parcel branch distress_score groups by, so two rows CAN
    # share a key while scoring as separate singleton parcel groups) is only safe to patch when
    # every row under it agrees on the new value -- same defensive check
    # scripts/backfill_unlocatable_equity_retraction.py already applies for this exact field.
    patches: dict[str, dict] = {}
    changed = 0
    stack_removed = 0
    dropped_collisions = 0
    for key, idxs in groups_by_key.items():
        new_values = [light_listings[i].raw.get("distress_stack")
                     if isinstance(light_listings[i].raw, dict) else None for i in idxs]
        first = new_values[0]
        if any(v != first for v in new_values[1:]):
            dropped_collisions += 1
            continue
        # Canonicalize None (score_board() popped the key -- no active group) and {} (this
        # module's own disclosed stand-in for that, since patch_existing_rows() cannot delete a
        # key) to the SAME value for both the "did anything change" check and the patch itself --
        # otherwise a row published as {} by a prior run of this function would look "changed"
        # forever on every later run that recomputes None, patching {} back in a no-op loop.
        new_norm = first or {}
        if all((old_stacks[i] or {}) == new_norm for i in idxs):
            continue  # every row under this key already publishes this value -- no-op
        patches[key] = {"raw": {"distress_stack": new_norm}}
        if first is None:
            stack_removed += 1
        changed += 1

    return {"scanned": scanned, "skipped": skipped, "scored": len(light_listings),
            "changed": changed, "stack_removed": stack_removed,
            "dropped_key_collisions": dropped_collisions, "tiers": hist, "patches": patches}

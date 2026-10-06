"""Cumulative-board persistence for the full pipeline run.

main.run() rebuilds the board from a FRESH scrape (~22k active leads) each run.
write_artifact then REPLACES the published board with only that fresh set, which
has two costs:

  1. COUNT DROP — every persisted lead that wasn't re-scraped this run vanishes.
     That includes the manual ``sc_public_index_export`` lane (~4k leads that can
     NOT be re-scraped) and any source that produced fewer rows this run. The
     fresh set falls below the count-drop guard's 75% floor, the guard fires, and
     run_local.sh skips the publish — the 14h run updates nothing.
  2. RE-ENRICH WASTE — a lead that persists across runs is re-scraped as a fresh
     Listing with NO vision, so the vision pass re-grades it from scratch, burning
     free-tier quota on work already done.

``merge_prior_board`` folds the prior published board into the fresh scrape so the
run is ADDITIVE (same behavior as the scripts/merge_today_sources.py path, but
fresh-wins):

  - matched leads (in BOTH fresh + prior): the FRESH scrape's fields win (new
    sale_date / auction_status / opening_bid), and the prior enrichment
    (vision / images / gis / comps / grade) is carried onto the fresh Listing so
    the idempotent enrichers SKIP them (no re-grade, no re-image).
  - fresh-only leads: pass through untouched, enriched normally downstream.
  - prior-only leads (persisted but NOT re-scraped this run): kept but AGED via
    the SAME ``raw["pulled_sale"]`` consecutive-miss counter the pulled-sales
    enricher already uses. Dropped when terminal (``sold_confirmed`` / court
    sale confirmed / sale past the upset-bid window) OR after N consecutive
    misses (``FULLRUN_PERSIST_MAX_MISSES``, default = pulled-sales retention).

STREAMING, not load_board() + dedupe() (2026-10-04, replacing the ORIGINAL
implementation that called ``load_board(docs_dir)`` then ``dedupe(fresh + prior)``).

THE PROBLEM THAT FORCED THIS. The original implementation paid BOARD_LOAD_MAX_
SOURCE_MB's own worst case (load_board() materializing the WHOLE prior board as
Listing objects) and then ran dedupe() over a DOUBLED ``fresh + prior`` combined
list on top of that -- dedupe()'s bucket dict, zip/locale blocking indexes,
``final`` list and union-find ``parent`` array are all sized to the COMBINED row
count, every one a full-length structure alive simultaneously with the two
full-length row lists (``prior``, ``combined``) that fed it. On the real board
(2,668 MB combined source, ~221K rows) that chain's first link -- load_board() --
now refuses outright via BoardLoadTooLarge before the run gets far enough to find
out whether a bigger host would have survived the rest of it. See
web_artifact.BOARD_PRIOR_MERGE_MAX_SOURCE_MB's comment for the full writeup and
the real measured numbers this rewrite is based on.

HOW THE REWRITE WORKS. The prior board is streamed via ``_iter_board_records()``
(the same incremental-JSON, lazy-detail-merged generator append_new_rows()/
patch_existing_rows() already use) exactly once, matched against a SMALL index
built from ``fresh_deduped`` only (bounded by the fresh scrape's own size, NOT the
board's) using the exact same _append_row_sigs()/_append_dict_sigs() signature
trick append_new_rows() already uses and has its own measured ceiling for (dedupe_
key() equality plus dedupe.py's strong same-property signatures -- see that
function's docstring in web_artifact.py). A prior row is validated into a real
Listing ONLY when it is either part of that small matched set (to fold onto the
matching fresh Listing via Listing.merge()) or survives the aging check into the
kept-prior-only set -- never for a row that gets aged out and dropped, and never
twice for the same row. No ``combined`` list, no doubled ``prior`` list, no
dedupe()'s full-board auxiliary structures exist at any point.

DISCLOSED SCOPE-NARROWING: matching is dedupe_key()/strong-signature equality
only -- the SAME "additive dedupe" fidelity append_new_rows() already accepts,
not dedupe()'s pass-2 fuzzy address scoring (rapidfuzz token_set_ratio >= 92 with
no shared key/signature). A fresh/prior pair that would only have matched via
that fuzzy pass now surfaces as two rows this run (the fresh copy re-enriched
from scratch, the prior copy aging down the same miss counter every other
prior-only lead uses) instead of one carried-enrichment merge -- a quota-cost
regression, not a data-loss or safety one, and self-healing since the unmatched
prior copy still ages out on schedule. Prior-vs-prior matching (two already-
published rows that are duplicates of EACH OTHER, not of anything in the fresh
scrape) is also not attempted here: the published board is itself the output of
a previous run's dedupe() pass, so it should already be internally deduplicated,
and this function's own job has never been to re-discover THAT -- see
merge_duplicate_rows() (web_artifact.py) for the dedicated, separately-measured
tool that targets exactly that (rare, residual) case.

PLACEHOLDER TWINS (2026-10-05). A prior row the house-number guard refuses is no longer aged
straight away when the only disagreement is a "no number" sentinel: Spartanburg/Rutherford write
an unnumbered lot as "0 PATCH DR", Buncombe as "99999 GREEN TREE LN", and the published copy of the
same row later got its real situs from the parcel cache ("499 PATCH DR"). The guard read 0 vs 499
as two houses and the 10/5 run kept ~380 such parcels twice (the pre-rewrite load_board()+dedupe()
path splits the same pairs; replayed on the real rows). Such a prior row now folds into its fresh
row when placeholder_twins.twin_pair_ok() holds (same valid parcel key, a shared source, at most
one real house number, no unit, no resolver-derived parcel), exactly one fresh row carries that
parcel key, and the fresh row plus all its twins agree on one real house number (else they age as
before). The fold is Listing.merge() fresh-first, keeping the prior's numbered situs over the
sentinel. FULLRUN_PERSIST_PLACEHOLDER_TWINS=0 turns it off.

DIFFERENT VALID PARCELS (2026-10-06). A strict match is also refused when the prior row and the
fresh candidate carry two different VALID parcels (_different_valid_parcels(); dedupe()'s own
identity rule), so a shared address signature can no longer fold one parcel's prior row into
another parcel's fresh row. stats['refused_different_parcel'] counts prior rows that were left
unmatched only by this rule.

WHAT THIS DOES NOT FIX: the return value is still a full ``list[Listing]`` of the
merged board, because main.run() runs it through ~2,400 more lines of enrichment/
filtering before its own write_artifact() call -- peak memory for THAT part is
still proportional to the final kept-row count, the same way load_board()'s
always was. This rewrite removes the EXTRA multiplicative cost stacked on top of
that one, it does not make holding the final merged board's worth of Listing
objects free. BOARD_PRIOR_MERGE_MAX_SOURCE_MB (web_artifact.py) is this
function's own, separately measured ceiling for that remaining cost;
BOARD_PRIOR_MERGE_ALLOW_LARGE=1 overrides it for one supervised run.

Reuses the existing ``dedupe()``'s signature machinery (not a parallel
reimplementation of it -- see _append_row_sigs()/_append_dict_sigs() in
web_artifact.py, which this module imports directly) and the existing
``pulled_sale`` aging field — no parallel mechanism is invented.
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog

from .enrichment_pulled_sales import PULLED_RETENTION_WEEKS
from .models import Listing
from .row_keys import share_keys
from .web_artifact import (
    BoardLoadDropError,
    _append_dict_sigs,
    _append_row_sigs,
    _board_file_present,
    _iter_board_records,
    _raise_if_board_too_large_to_prior_merge,
    load_board,  # noqa: F401 -- unused here since the 2026-10-04 streaming rewrite
    # (this module no longer calls it), but re-exported: scripts/enrich_bankruptcy.py
    # does `from foreclosure_scraper.board_persist import load_board` and must keep
    # working. Removing this import silently breaks that script's import line.
)
from .dedupe import _house_no_of, different_valid_parcels as _different_valid_parcels_id
from .dedupe import identity as _identity
from .models import _normalize_parcel
from .placeholder_twins import MAX_GROUP_ROWS, fold, real_house_no, sources_of, twin_pair_ok
from .validation import _PARCEL_BAD_PATTERNS

log = structlog.get_logger()


# A prior-only lead whose foreclosure sale is this many days past is treated as
# terminal (the auction happened, the NC 10-day upset-bid window has closed) and
# dropped so the board doesn't accumulate dead post-sale rows.
TERMINAL_SALE_GRACE_DAYS = int(
    os.environ.get("FULLRUN_PERSIST_TERMINAL_GRACE_DAYS", "365")
)

# A malformed prior row this function cannot even validate into a Listing (when it
# survives aging, or is part of a matched pair) is DROPPED, same as load_board()'s own
# drop-rate discipline -- counted, logged, and only tolerated up to this fraction of the
# rows actually streamed before merge_prior_board refuses outright (never silently
# publishes a board that quietly lost more than this). Deliberately the SAME default as
# BOARD_LOAD_MAX_DROP_RATE (0.1%): this is the identical failure mode (a row load_board()
# itself would also have dropped), just detected at a different point in a different
# streaming pass.
PRIOR_MERGE_MAX_DROP_RATE = float(
    os.environ.get("BOARD_LOAD_MAX_DROP_RATE", "0.001")
)


def _naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo so prior-board (often tz-aware ISO) dates compare against a
    naive utcnow() without raising."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


def _parse_iso_dt(v) -> Optional[datetime]:
    """Parse an ISO-8601 datetime STRING straight off a streamed board row dict,
    without validating the whole row into a Listing just to read one field. Mirrors
    ``_naive()``'s tz-stripping so a dict-sourced comparison behaves identically to
    the Listing-sourced one _is_terminal() used to do. Anything that isn't a clean
    ISO string (None, a non-string, a value this can't parse) returns None -- same
    "a row too malformed to key is simply unmatched" tolerance
    _append_dict_sigs()/patch_existing_rows() already apply elsewhere in this
    codebase, rather than raising mid-stream over one bad date field."""
    if not isinstance(v, str) or not v:
        return None
    s = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return _naive(dt)


def _is_terminal(li: Listing, now: datetime) -> bool:
    """A prior-only lead that is no longer actionable and should be dropped
    outright (not aged): a confirmed sale, or a sale date past the upset-bid
    window."""
    raw = li.raw if isinstance(li.raw, dict) else {}
    if raw.get("sold_confirmed"):
        return True
    if raw.get("court_sale_status") == "confirmed":
        return True
    dl = _naive(li.upset_bid_deadline)
    if dl is not None and dl < now:
        return True
    sd = _naive(li.sale_date)
    if sd is not None and sd < now - timedelta(days=TERMINAL_SALE_GRACE_DAYS):
        return True
    return False


def _is_terminal_dict(rec: dict, now: datetime) -> bool:
    """Same check as ``_is_terminal()``, read directly off a streamed board row
    dict -- used for the prior-only majority this function never validates into a
    Listing unless it survives this check. Kept as a SEPARATE function (not a
    dict-wrapping shim around _is_terminal()) because Listing.model_construct()
    would not parse these ISO date strings into real datetimes (model_construct
    skips validation by design), so a shim would silently compare strings to a
    datetime and always come out False -- see _parse_iso_dt()'s docstring."""
    raw = rec.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("sold_confirmed"):
        return True
    if raw.get("court_sale_status") == "confirmed":
        return True
    dl = _parse_iso_dt(rec.get("upset_bid_deadline"))
    if dl is not None and dl < now:
        return True
    sd = _parse_iso_dt(rec.get("sale_date"))
    if sd is not None and sd < now - timedelta(days=TERMINAL_SALE_GRACE_DAYS):
        return True
    return False


def _addr_key(v) -> str:
    return "".join(ch for ch in str(v or "").upper() if ch.isalnum())


def keep_mailing_off_address(fresh: Listing, prior: Listing, merged: Listing) -> bool:
    """Undo Listing.merge()'s backfill of the PROPERTY address from a prior row when what it
    backfilled is the owner's MAILING address. True when anything was undone.

    merge() fills every field the fresh row left empty from the prior copy. Sources that used
    to publish the owner's mailing address as the property (counties_nc.transylvania_
    delinquent_tax, counties_nc.buncombe_elderly, the Buncombe unpaid-bill layers before
    2026-09-29; docs/HANDOFF.md item 69) now leave street/city/ZIP empty when the parcel's
    situs is unknown and keep the mailing block in raw['owner_mailing']. Without this, the
    first full run after the fix re-inherited the very mailing address from the prior board,
    because this merge runs before any enricher could resolve the situs.

    Only a field the FRESH row left empty is touched, only when the backfilled value is part
    of the fresh row's own owner-mailing text, and never when the prior street came from the
    county's own situs by parcel id (raw['situs_address_source'] 'parcel_cache:*')."""
    om = fresh.raw.get("owner_mailing") if isinstance(fresh.raw, dict) else None
    mailing = om.get("mailing") if isinstance(om, dict) else (om if isinstance(om, str) else None)
    key = _addr_key(mailing)
    if not key:
        return False
    praw = prior.raw if isinstance(prior.raw, dict) else {}
    if str(praw.get("situs_address_source") or "").startswith("parcel_cache:"):
        return False
    undone = False
    for f in ("street_address", "city", "zip_code"):
        if getattr(fresh, f, None) in (None, "") and getattr(merged, f, None):
            v = _addr_key(getattr(merged, f))
            if len(v) >= 4 and v in key:
                setattr(merged, f, None)
                undone = True
    if undone and isinstance(merged.raw, dict):
        merged.raw["mailing_address_not_inherited"] = True
    return undone


def _provably_different_dict(rec: dict, li: Listing) -> bool:
    """dedupe.py's house-number guard (_provably_different_property), applied
    between a streamed prior-row DICT and a candidate fresh Listing, without
    constructing a Listing for the prior side just to read one field. Same
    narrow rule: a DIFFERENT house number on BOTH sides is a different house,
    essentially always -- see dedupe._provably_different_property's own
    docstring for the real merge bugs this caught (parcel ids shared across two
    different street numbers)."""
    ha = _house_no_of(rec.get("street_address"))
    hb = _house_no_of(li.street_address)
    return bool(ha and hb and ha != hb)


def _different_valid_parcels(rec: dict, li: Listing) -> bool:
    """dedupe()'s parcel rule (dedupe.identity_conflict, 2026-10-06) between a streamed prior row
    and a fresh candidate: two different VALID parcels (placeholder_twins.parcel_key, not attached
    by a resolver) are two properties, whatever address signature they share. Without it a prior
    row could fold into a DIFFERENT parcel's fresh row through an address signature ('115 SOUTHPORT
    RD' is two parcels, so is '0 SOUTHPORT RD' on a board that kept the sentinel), carrying its
    enrichment onto the wrong lead, and, when its own parcel was not re-scraped, vanishing instead
    of aging. Only this rule is applied here: the house-number guard above stays as it was (the
    placeholder-twin fallback below depends on it), and an unnumbered prior row may still match
    its own re-scraped record."""
    a = _identity(rec)
    if not a.pk:
        return False
    return _different_valid_parcels_id(a, _identity(li))


#: Where a source keeps, in its own raw block, the id it wrote as parcel_id: (block, key). Read
#: only for a published row that predates raw['parcel_id_nulled'] (validation.py, 2026-10-06).
#: Each entry is the scraper's own assignment, checked in its code: parcel_id=ident with
#: county_id=ident (nc_county_pdf_delinquent_tax), parcel_id=parcel with "parcel": parcel
#: (rutherford_tax, nc_ptscloud_delinquent_tax), parcel_id=PARCELID or PIN with "PARCELID"
#: (lincoln_vacant; a PIN is 10 digits and never nulled).
_SOURCE_PARCEL_FIELDS = {
    "counties_nc.nc_county_pdf_delinquent_tax": ("nc_county_pdf_delinquent_tax", "county_id"),
    "counties_nc.rutherford_tax": ("rutherford_tax", "parcel"),
    "counties_nc.nc_ptscloud_delinquent_tax": ("nc_ptscloud_delinquent_tax", "parcel"),
    "counties_nc.lincoln_vacant": ("lincoln_vacant", "PARCELID"),
}


def _restored_parcel_key(rec: dict) -> str | None:
    """The dedupe_key() a published prior row had BEFORE validation nulled its short parcel id,
    i.e. the key this run's re-scrape of it carries (fresh rows are not validated until after
    the merge). None when the row has a parcel id or none was nulled.

    Why (2026-10-06). validation._validate_parcel_id() nulls a parcel id under 7 characters, so
    Catawba's tax-account rows publish with parcel None and dedupe_key 'url:<the county PDF>'
    while the next scrape keys them 'parcel:NC:catawba:65771'. No signature matched, every one
    was aged, and dedupe2 then fused the live row into its own aged copy (3,737 of the 6,414
    wrongly "presumed withdrawn" rows of the 10/5 run). With dedupe()'s identity rule (240b8de9)
    dedupe2 no longer fuses two unnumbered rows on a synthesized address, so the same miss would
    leave the live row AND an aged copy on the board, one more copy every run."""
    if rec.get("parcel_id"):
        return None
    raw = rec.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    pid = None
    nulled = raw.get("parcel_id_nulled")
    if isinstance(nulled, dict) and nulled.get("reason") == "too_short":
        pid = nulled.get("value")
    if not pid:
        spec = _SOURCE_PARCEL_FIELDS.get(rec.get("source") or "")
        blk = raw.get(spec[0]) if spec else None
        if isinstance(blk, dict):
            pid = blk.get(spec[1])
    pid = str(pid or "").strip()
    norm = _normalize_parcel(pid)
    # Too weak to identify one row: '0', '00', '123' and the like key many rows of a county.
    if len(norm) < 4 or len(set(norm)) == 1 or any(p.match(pid) for p in _PARCEL_BAD_PATTERNS):
        return None
    try:
        sigs = _append_dict_sigs({**rec, "parcel_id": pid})
    except Exception:  # noqa: BLE001 - an unkeyable row simply gets no restored key
        return None
    key = next((s[1] for s in sigs if s[0] == "k"), None)
    return key if isinstance(key, str) and key.startswith("parcel:") else None


def _shares_source(rec: dict, li: Listing) -> bool:
    raw = rec.get("raw")
    return bool(sources_of(rec.get("source"), raw) & sources_of(li.source, li.raw))


def _placeholder_twin_index(rec: dict, rec_sigs, fresh_sig_index: dict,
                            fresh_deduped: list[Listing]) -> int | None:
    """The fresh row a prior row is a placeholder twin of (placeholder_twins.py), or None.

    Only reached when the strict match failed, i.e. when the house-number guard refused every
    candidate. Reached through the parcel branch of dedupe_key() only, and only when exactly ONE
    fresh row carries that key: a parcel the fresh scrape itself lists more than once (units of
    one building, a master-tract PIN) never gets the relaxed rule."""
    k = next((s for s in rec_sigs if s[0] == "k" and str(s[1]).startswith("parcel:")), None)
    if k is None:
        return None
    cands = fresh_sig_index.get(k)
    if not cands or len(cands) != 1:
        return None
    i = cands[0]
    return i if twin_pair_ok(rec, fresh_deduped[i]) else None


def merge_prior_board(
    fresh_deduped: list[Listing],
    docs_dir: Path | str | None = None,
    now: Optional[datetime] = None,
    max_misses: Optional[int] = None,
) -> tuple[list[Listing], dict]:
    """Merge the prior published board into this run's fresh (deduped) scrape.

    Returns ``(merged_listings, stats)``. On an empty/missing prior board (the
    first-ever run) the fresh set is returned unchanged. Re-raises on a prior-row
    drop rate over PRIOR_MERGE_MAX_DROP_RATE (BoardLoadDropError) or a board over
    BOARD_PRIOR_MERGE_MAX_SOURCE_MB (BoardLoadTooLarge) -- the caller must treat
    merge_prior_board as a critical phase either way: falling back to fresh-only
    silently drops the vast majority of the board.
    """
    if now is None:
        now = datetime.utcnow()
    if max_misses is None:
        max_misses = int(
            os.environ.get("FULLRUN_PERSIST_MAX_MISSES", str(PULLED_RETENTION_WEEKS))
        )
    if docs_dir is None:
        docs_dir = Path(__file__).resolve().parent.parent.parent / "docs"
    docs = Path(docs_dir)

    stats: dict = {
        "fresh_count": len(fresh_deduped),
        "prior_count": 0,
        "merged_count": 0,
        "matched": 0,
        "fresh_only": 0,
        "prior_only_kept": 0,
        "aged_out_terminal": 0,
        "aged_out_misses": 0,
        "carried_vision": 0,
        "prior_drop_errors": 0,
        "matched_placeholder_twin": 0,
        "placeholder_twin_ambiguous": 0,
        "refused_different_parcel": 0,
        "matched_restored_parcel": 0,
        "reappeared_untagged": 0,
    }
    # Placeholder twins (placeholder_twins.py): on by default; FULLRUN_PERSIST_PLACEHOLDER_TWINS=0
    # restores the strict-only matching of the 2026-10-04 rewrite.
    twins_on = os.environ.get("FULLRUN_PERSIST_PLACEHOLDER_TWINS", "1") != "0"

    listings_path = docs / "listings.json"
    if not _board_file_present(listings_path):
        # No published board yet (first-ever run) — nothing to persist.
        stats["merged_count"] = len(fresh_deduped)
        stats["fresh_only"] = len(fresh_deduped)
        return list(fresh_deduped), stats

    _raise_if_board_too_large_to_prior_merge(docs)

    # --- SMALL index built from the fresh scrape ONLY (bounded by len(fresh_deduped),
    # never by the board's size) -- the same signature trick append_new_rows() uses to
    # dedupe its own small candidate set against a streamed board, reused here in the
    # other direction (streamed prior rows checked against a small fresh index). ---
    fresh_sig_index: dict[tuple, list[int]] = {}
    for i, li in enumerate(fresh_deduped):
        for sig in _append_row_sigs(li):
            fresh_sig_index.setdefault(sig, []).append(i)
    fresh_matched = [False] * len(fresh_deduped)
    # This run's own carryover replays (carryover.py), before any prior copy is folded in: the
    # only fresh rows whose raw['carryover'] marker is their own.
    fresh_carryover = {i for i, li in enumerate(fresh_deduped)
                       if isinstance(li.raw, dict) and li.raw.get("carryover")}

    kept: list[Listing] = []
    prior_total = 0
    streamed_for_drop_rate = 0
    drop_errors: list[str] = []
    # fresh index -> prior row dicts that are placeholder twins of it. Decided after the stream
    # (all of a fresh row's twins must be seen before we know they agree on one house number).
    # Bounded by the prior rows the house-number guard refused on a single-row parcel key.
    deferred: dict[int, list[dict]] = {}
    # One str per distinct raw key across all prior rows (row_keys.py): the stream decodes one row
    # at a time, so without this every kept row holds its own copy of every key.
    key_cache: dict = {}

    def _age(rec: dict) -> None:
        """Prior-only (persisted but not re-scraped this run) => AGE, entirely off the raw
        dict -- no Listing constructed for a row that might still get dropped by this check."""
        nonlocal streamed_for_drop_rate
        if _is_terminal_dict(rec, now):
            stats["aged_out_terminal"] += 1
            return
        raw = rec.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        prev_pulled = raw.get("pulled_sale") or {}
        consecutive = prev_pulled.get("consecutive_misses", 0) + 1
        if consecutive > max_misses:
            stats["aged_out_misses"] += 1
            return
        raw["pulled_sale"] = {
            "first_missed_at": prev_pulled.get(
                "first_missed_at", now.isoformat() + "Z"
            ),
            "consecutive_misses": consecutive,
            "presumed_withdrawn": True,
            "last_seen_source": rec.get("source"),
            "last_seen_sale_date": rec.get("sale_date"),
        }
        rec["raw"] = raw
        if not rec.get("auction_status"):
            rec["auction_status"] = "presumed_withdrawn"
        streamed_for_drop_rate += 1
        try:
            kept.append(Listing.model_validate(share_keys(rec, key_cache)))
        except Exception as exc:  # noqa: BLE001 - same drop tolerance as the matched branch
            drop_errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
            stats["prior_drop_errors"] += 1
            return
        stats["prior_only_kept"] += 1

    for rec in _iter_board_records(docs):
        prior_total += 1
        match_idx: int | None = None
        rec_sigs = ()
        refused_parcel = False
        if isinstance(rec, dict) and fresh_sig_index:
            try:
                rec_sigs = _append_dict_sigs(rec)
            except Exception:  # noqa: BLE001
                # _append_dict_sigs() builds an UNVALIDATED Listing.model_construct() of this
                # row's identity fields -- unlike load_board()'s old path, nothing has coerced
                # or rejected a malformed field (e.g. a non-string zip_code) before this point.
                # A row too malformed to key is simply unmatched (the same tolerance
                # patch_existing_rows() already applies around its own light dedupe_key() call),
                # not a reason to crash the whole streaming pass over everything after it.
                rec_sigs = ()
            for sig in rec_sigs:
                cands = fresh_sig_index.get(sig)
                if not cands:
                    continue
                for i in cands:
                    if _provably_different_dict(rec, fresh_deduped[i]):
                        continue
                    if _different_valid_parcels(rec, fresh_deduped[i]):
                        refused_parcel = True
                        continue
                    match_idx = i
                    break
                if match_idx is not None:
                    break
            # No signature matched: a prior row validation stripped of its short parcel id still
            # matches its own re-scrape under the key it had before (_restored_parcel_key), from
            # the same source only.
            if match_idx is None:
                rk = _restored_parcel_key(rec)
                same = [i for i in fresh_sig_index.get(("k", rk), ())
                        if _shares_source(rec, fresh_deduped[i])] if rk else []
                # exactly one same-source fresh row under that key, or no match at all
                if (len(same) == 1 and not _provably_different_dict(rec, fresh_deduped[same[0]])
                        and not _different_valid_parcels(rec, fresh_deduped[same[0]])):
                    match_idx = same[0]
                    stats["matched_restored_parcel"] += 1

        if refused_parcel and match_idx is None:
            stats["refused_different_parcel"] += 1
        if match_idx is not None:
            streamed_for_drop_rate += 1
            try:
                prior_li = Listing.model_validate(share_keys(rec, key_cache))
            except Exception as exc:  # noqa: BLE001 - a malformed matched row is dropped, not fatal
                drop_errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                stats["prior_drop_errors"] += 1
                continue
            # Fresh FIRST so Listing.merge() keeps the base's (fresh) non-null fields
            # and only backfills from prior where fresh is missing a value — fresh
            # scrape wins, prior enrichment is carried. Folds ALL prior rows that
            # match this same fresh row (a dedupe_key() matching more than one
            # existing row is rare but possible — same tolerance patch_existing_rows()
            # applies), not just the first.
            merged = fresh_deduped[match_idx].merge(prior_li)
            if keep_mailing_off_address(fresh_deduped[match_idx], prior_li, merged):
                stats["mailing_address_not_inherited"] = stats.get("mailing_address_not_inherited", 0) + 1
            fresh_deduped[match_idx] = merged
            fresh_matched[match_idx] = True
            continue

        if not isinstance(rec, dict):
            continue
        # Strict match refused (by the house-number guard, the only way a shared parcel key
        # fails): a placeholder twin of a single fresh row is deferred, not aged. 2026-10-05:
        # the 10/5 run kept ~380 such parcels twice, '0 PATCH DR' fresh beside '499 PATCH DR'
        # prior; see placeholder_twins.py.
        if twins_on and rec_sigs:
            ti = _placeholder_twin_index(rec, rec_sigs, fresh_sig_index, fresh_deduped)
            if ti is not None:
                deferred.setdefault(ti, []).append(rec)
                continue
        _age(rec)

    # Placeholder twins, decided per fresh row now that all of its twins are known: folded only
    # when the fresh row and every twin agree on at most ONE real house number and the group is
    # small. Otherwise each twin goes down the ordinary prior-only aging path, exactly as before.
    twin_samples: list[tuple] = []
    for i, recs in deferred.items():
        hns = {real_house_no(fresh_deduped[i].street_address)}
        hns.update(real_house_no(r.get("street_address")) for r in recs)
        hns.discard("")
        if len(hns) > 1 or 1 + len(recs) > MAX_GROUP_ROWS:
            stats["placeholder_twin_ambiguous"] += len(recs)
            for rec in recs:
                _age(rec)
            continue
        for rec in recs:
            streamed_for_drop_rate += 1
            try:
                prior_li = Listing.model_validate(share_keys(rec, key_cache))
            except Exception as exc:  # noqa: BLE001 - same drop tolerance as the matched branch
                drop_errors.append(f"{type(exc).__name__}: {str(exc)[:160]}")
                stats["prior_drop_errors"] += 1
                continue
            if len(twin_samples) < 5:
                twin_samples.append((fresh_deduped[i].source, fresh_deduped[i].parcel_id,
                                     fresh_deduped[i].street_address, prior_li.street_address))
            # fold(): Listing.merge() with fresh first (fresh wins, prior backfills), keeping the
            # prior's numbered situs over the fresh row's no-number sentinel.
            fresh_deduped[i] = fold(fresh_deduped[i], prior_li)
            fresh_matched[i] = True
            stats["matched_placeholder_twin"] += 1
    deferred.clear()
    if stats["matched_placeholder_twin"] or stats["placeholder_twin_ambiguous"]:
        log.info("board_persist.placeholder_twins",
                 folded=stats["matched_placeholder_twin"],
                 ambiguous_aged=stats["placeholder_twin_ambiguous"], sample=twin_samples)

    if drop_errors:
        rate = stats["prior_drop_errors"] / streamed_for_drop_rate if streamed_for_drop_rate else 0.0
        log.error("board_persist.prior_rows_dropped", dropped=stats["prior_drop_errors"],
                  validated=streamed_for_drop_rate, rate=round(rate, 6), first=drop_errors[:5])
        if rate > PRIOR_MERGE_MAX_DROP_RATE:
            raise BoardLoadDropError(
                f"merge_prior_board dropped {stats['prior_drop_errors']:,} of "
                f"{streamed_for_drop_rate:,} rows it tried to validate ({rate:.3%}), over the "
                f"{PRIOR_MERGE_MAX_DROP_RATE:.3%} limit. Publishing this merge would silently "
                f"lose them. BOARD_LOAD_MAX_DROP_RATE raises the limit."
            )

    # Finalize pass over the (small) fresh set ONCE each, after all of a row's prior
    # matches (if any) are folded in — mirrors the ORIGINAL implementation's
    # post-dedupe loop, which only ever ran this logic after dedupe() had finished
    # merging, never per-intermediate-merge.
    for i, li in enumerate(fresh_deduped):
        if fresh_matched[i]:
            stats["matched"] += 1
            raw = li.raw if isinstance(li.raw, dict) else {}
            if raw.get("vision"):
                stats["carried_vision"] += 1
            # A reappeared lead is active again. Listing.merge() backfilled the prior copy's
            # withdrawn tag onto it: the pulled_sale miss counter, the 'presumed_withdrawn'
            # status (no scraper writes that value, so on a matched row it is always the
            # prior's) and board_quality's raw['stale_case'] (set only for those two reasons;
            # this run's board_quality re-derives it). Until 2026-10-06 stale_case was kept:
            # 7,741 rows the 10/5 run re-scraped still carried it, and the dashboard reads it as
            # "presumed withdrawn" and lead_signals caps intent at 69 on it.
            stats["reappeared_untagged"] += bool(raw.get("pulled_sale") or raw.get("stale_case")
                                                 or li.auction_status == "presumed_withdrawn")
            raw.pop("pulled_sale", None)
            raw.pop("stale_case", None)
            if li.auction_status == "presumed_withdrawn":
                li.auction_status = None
            # raw['carryover'] marks a replay of last run's row for a source that returned zero
            # (carryover.py). A re-scraped row inherits it from its prior copy and is then hinted
            # as a stale link forever (3,647 live rows on 10/5 carried one from 8/14 or 9/22).
            if raw.get("carryover") and i not in fresh_carryover:
                raw.pop("carryover", None)
            li.raw = raw
        else:
            stats["fresh_only"] += 1
        kept.append(li)

    stats["prior_count"] = prior_total
    stats["merged_count"] = len(kept)
    log.info("board_persist.done", **stats)
    return kept, stats

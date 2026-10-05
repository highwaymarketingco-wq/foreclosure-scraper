# The list-materializing write_artifact() exactly as it stood before the 2026-10-05 streaming
# rewrite (origin/main 37f28ced, src/foreclosure_scraper/web_artifact.py), kept VERBATIM as the
# reference tests/test_write_artifact_streaming.py compares the streaming writer against, byte
# for byte. It is exec'd inside a copy of web_artifact's own namespace, so it calls the same
# helpers (_to_dict, _emit_slim, _emit_detail_shards, _load_prior_details_by_key, ...) the
# module still ships. Not imported by production code. Do not "fix" or modernize it: its only
# job is to be the old behaviour.
def write_artifact(
    listings: list[Listing],
    summary: dict,
    docs_dir: Path | str = "docs",
) -> tuple[Path, Path]:
    """Write the whole payload set, then the manifest that seals it.

    Refuses (BoardLockNotHeld) unless the caller holds the board lock, and
    (BoardChangedSinceLoad) if listings.json is not the file this process loaded
    — see require_board_lock / _check_not_changed_since_load and audit O3.
    """
    docs = Path(docs_dir)
    docs.mkdir(parents=True, exist_ok=True)

    listings_path = docs / "listings.json"
    meta_path = docs / "run_meta.json"

    # FIRST, before any expensive work and before a single byte is touched.
    require_board_lock(docs)
    _check_not_changed_since_load(listings_path)

    payload = [_to_dict(li) for li in listings]

    # Split the heavy, detail-panel-only raw keys (comps/vision arrays — the
    # most deeply nested payload) into an index-aligned sidecar the dashboard
    # fetches lazily on the first card open. Index alignment (not a per-lead id)
    # is the join: both files are built from `payload` in the same order, so
    # detail[i] belongs to listing[i]. Popping happens LAST (after _to_dict /
    # _slim_raw / annotate_stale_links) so nothing re-adds these keys. Additive:
    # if listings_detail.json is missing/mismatched, those panels render empty.
    # Prior sidecar, keyed by identity — lets a full re-scrape (which only
    # re-visions a capped subset) KEEP vision/comps/cama for the leads it
    # didn't touch this run, instead of overwriting details[i] with {}.
    # Fresh detail from THIS run always wins; prior only backfills missing keys.
    prior = _load_prior_details_by_key(docs)
    # Guard BOTH sides: a key can be unique in the prior board yet ambiguous in
    # what we are about to write (e.g. a re-scrape that pulled 3,293 leads from
    # one ArcGIS URL). Carrying detail across it would fan one report out to all
    # of them, so only keys unique on BOTH sides are allowed to match.
    payload_unique = _unique_key_map(payload) if prior else {}
    details = []
    for rec in payload:
        raw = rec.get("raw")
        d = {}
        if isinstance(raw, dict):
            for k in LAZY_DETAIL_KEYS:
                if k in raw:
                    d[k] = raw.pop(k)
        if prior:
            pri = None
            for key in _identity_keys(rec):
                if payload_unique.get(key) and key in prior:
                    pri = prior[key]
                    break
            if pri:
                for k in LAZY_DETAIL_KEYS:
                    if k not in d and k in pri:
                        d[k] = pri[k]
        details.append(d)
    import gzip
    # One bytes object per row, in board order. json.dumps over the whole list is exactly
    # "[" + ", ".join(rows) + "]" (same encoder, same default separators), so the plain
    # listings.json below is byte-identical to what the single dumps used to produce, but the
    # 1.1 GB document is never one string and never held twice (audit O1: the parts cut the
    # same rows, and need per-row bytes to land on a row boundary).
    _row_enc = json.JSONEncoder(ensure_ascii=False, default=str)
    listing_blobs = [_row_enc.encode(rec).encode("utf-8") for rec in payload]
    detail_path = docs / "listings_detail.json"
    detail_bytes = json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")
    # Atomic writes (temp + os.replace) so a kill mid-write can never leave a
    # truncated 100MB+ file — the prior good file survives. git history is the
    # rollback backup for a completed-but-bad write (the count-drop guard flags
    # those before publish).
    # BACKUP-BEFORE-OVERWRITE + COUNT GUARD (extracted to _count_guard_and_backup, shared with
    # append_new_rows -- see that function's docstring for the two real incidents it guards
    # against).
    _accepted_intentional = _count_guard_and_backup(docs, listings_path, len(payload), summary)
    # The manifest (written LAST) needs each big file's size and sha256. Take them
    # from the bytes already in memory rather than re-reading 1.1 GB from disk.
    _manifest_pre: dict = {
        "listings.json": {**_write_plain_array(listings_path, listing_blobs), "records": len(payload)},
        "listings_detail.json": {"bytes": len(detail_bytes),
                                 "sha256": hashlib.sha256(detail_bytes).hexdigest(),
                                 "records": len(details)},
    }
    _atomic_write_bytes(detail_path, detail_bytes)
    # The PUBLISHED form of the board: contiguous, independently gzipped parts, each under
    # board_parts.PART_MAX_BYTES (audit O1). The single docs/listings.json.gz is no longer
    # written: it was 84 MiB against GitHub's 100 MiB limit. A stale copy left by an older
    # version is not touched here and is ignored by every reader once the manifest lists parts.
    # mtime=0 keeps the gzip deterministic so identical rows produce identical bytes (no git
    # churn), and the row-per-part count is kept from write to write so a change confined to
    # some rows rewrites only the parts that hold them.
    _prior_parts = _bp.manifest_parts_block(_bp.read_manifest(docs)) or {}
    _parts = _bp.write_parts(docs, listing_blobs, hint_rows=_prior_parts.get("rows_per_part"))
    _parts_block = _bp.make_block(_parts["entries"], rows_per_part=_parts["rows_per_part"],
                                  cap=_parts["cap"])
    del listing_blobs
    # Also emit a gzipped copy of the sidecar the dashboard fetches (16x smaller). The .json
    # files remain the local source-of-truth + a fallback. mtime=0 as above.
    detail_gz = gzip.compress(detail_bytes, compresslevel=9, mtime=0)
    _manifest_pre["listings_detail.json.gz"] = {"bytes": len(detail_gz),
                                                "sha256": hashlib.sha256(detail_gz).hexdigest(),
                                                "records": len(details)}
    _atomic_write_bytes(docs / "listings_detail.json.gz", detail_gz)
    # Identity of the sidecar THIS call wrote — see the detail_count/
    # detail_digest note where run_meta is assembled. Deterministic (sha256 of
    # deterministic gzip bytes), so a republish of identical data does not churn.
    detail_digest = hashlib.sha256(detail_gz).hexdigest()[:16]
    del detail_gz

    # SLIM-V1, the mobile payload. Derived from the SAME `payload` list, and
    # deliberately emitted only after the two authoritative files are already on
    # disk: nothing below this line can change listings.json's bytes, and a bug
    # in the derivative cannot cost a run its board. See the SLIM-V1 block above.
    del detail_bytes    # free the sidecar bytes before projecting (8 GB box)
    _report_slim_drops(listings)   # loud about what slim leaves behind — see the docstring
    slim_count = _emit_slim(docs, payload)

    # DETAIL SHARDS, the mobile detail payload. Same contract as the slim file
    # and deliberately last: every authoritative byte is already on disk, this
    # reads `payload` and `details` without mutating either, and a failure here
    # costs a derivative, never a board. Gated on the slim emit having succeeded
    # — the two are one mobile payload, advertised in one metadata block. See
    # the DETAIL SHARDS block above.
    shard_meta = _emit_detail_shards(docs, payload, details,
                                     slim_ok=slim_count is not None)

    _now = datetime.utcnow()
    _now_iso = _now.isoformat() + "Z"
    meta = {
        "run_time": _now_iso,
        "total": len(listings),
        "by_source": summary.get("by_source", {}),
        # by_state is DERIVED from the board being written, never taken from the
        # caller and never carried forward. It is a pure function of `listings`,
        # so there is no reason for it ever to disagree with the board — and it
        # did: the live file said NC 18,712 / SC 17,348, summing 36,060 against a
        # 38,500 board, while the real split was NC 20,654 / SC 17,846. 2,440
        # leads (6.3%) unaccounted for, on the only per-source health report
        # there is. A scrape-time count is not a description of what shipped.
        "by_state": _count_by(listings, "state"),
        # Same argument, for sources: this is what is ON the board right now,
        # which is the question run_meta exists to answer ("which sources are
        # actually contributing"). It is NOT `by_source`: that one is the
        # scrape-time per-scraper yield the full run computes (pre-dedup,
        # pre-scope-filter), it is carried forward by partial writers, and on
        # the live board it listed 85 sources summing 38,650 while omitting
        # reo.vrm_va_reo entirely. Both are useful; only one of them describes
        # the published board, and it is this one.
        "by_source_on_board": _count_by(listings, "source"),
        "by_county_top": summary.get("by_county_top", []),
        "source_status": summary.get("source_status", {}),
        "regressions": summary.get("regressions", []),
        "errors": summary.get("errors", []),
        "notes": summary.get("notes", ""),
        # THE DESKTOP DETAIL JOIN, declared. dashboard.js ensureDetails() merges
        # listings_detail.json into LISTINGS whenever details.length ===
        # LISTINGS.length — length equality with a payload that may itself be a
        # cached copy from another publish. The board has been exactly 38,500 for
        # four consecutive publishes, so that test proves nothing, and a
        # cross-publish sidecar Object.assigns one property's comps, vision and
        # CAMA onto a different property's address with no error.
        #
        # run_meta.json is fetched with `?t=${Date.now()}` (dashboard.js:681), so
        # it is the one payload that is ALWAYS current. These two keys are
        # therefore a fresh statement to check a possibly-cached sidecar against:
        #   detail_count  — len(listings_detail.json) as written by THIS call
        #   detail_digest — sha256 of listings_detail.json.gz's bytes, first 16
        #                   hex chars; changes whenever the sidecar's content
        #                   changes even if its length does not
        # Top level, NOT inside meta["board"]: tests/test_board_slim.py pins the
        # board block's key set to {schema, count, detail_shards}, and the block
        # is deliberately absent whenever the slim payload was not written, while
        # the desktop sidecar is written unconditionally.
        "detail_count": len(details),
        "detail_digest": detail_digest,
        # THE BOARD, AS PARTS (audit O1). The dashboard reads this list (same ?t=<run_time>
        # cache key as every payload file), fetches the parts in parallel and concatenates them
        # in order; each entry carries its row range, size and sha256. Top level for the same
        # reason as detail_count: the "board" block's key set is pinned by tests and describes
        # the slim payload only. Always describes the parts THIS call wrote.
        "board_parts": _parts_block,
    }
    # Board block: how the dashboard learns the slim payload exists and how many
    # records it must contain. run_meta.json is already in every publish list, so
    # this adds zero new entries to the five hardcoded ones. Absent whenever the
    # slim emit was skipped or failed — and it is NOT carried forward from the
    # prior meta by the health-preservation block below, which is the point: a
    # board block always describes the slim file written by THIS call.
    #
    # detail_shards is a SIBLING key, added without touching schema/count: the
    # client's boardExpectedCount() (dashboard.js:469) gates on board.schema ===
    # "slim-v1" and returns null for anything else, so renaming or re-shaping
    # the outer block would silently disable the record-count gate that stops a
    # short payload rendering as a whole board. It carries `size` so the client
    # derives shard index i // size instead of hardcoding 1000, and `records` so
    # a client that fetched a shard set from a different write can tell.
    if slim_count is not None:
        meta["board"] = {"schema": "slim-v1", "count": slim_count}
        if shard_meta is not None:
            meta["board"]["detail_shards"] = shard_meta

    # PRESERVE per-source health across partial writers (extracted to
    # _apply_health_freshness, shared with append_new_rows -- see its docstring).
    prior_meta: dict = {}
    if meta_path.exists():
        try:
            prior_meta = json.loads(meta_path.read_text())
        except Exception:  # noqa: BLE001 - a corrupt prior file must not block the write
            prior_meta = {}
        if not isinstance(prior_meta, dict):
            prior_meta = {}
    _apply_health_freshness(meta, prior_meta, summary, _now_iso, _now)
    _atomic_write_bytes(meta_path, json.dumps(meta, ensure_ascii=False, default=str, indent=2).encode("utf-8"))

    # --- update high-water mark ---
    # After a successful write, persist the new count as the high-water mark.
    # This is what the count guard above compares against next run. Only moves
    # UP (a smaller board never lowers the high-water mark — that's the point).
    try:
        _hw_path = docs / "board_highwater.json"
        _prev_hw = 0
        if _hw_path.exists():
            _prev_hw = json.loads(_hw_path.read_text()).get("count", 0)
        # Normally the mark only moves UP -- a smaller board must never lower the
        # bar the next run has to clear. The ONE exception is a shrink we just
        # accepted as an intentional buy-box correction: after removing rows that
        # were never in the footprint, the old mark describes a DIFFERENT
        # population, and leaving it in place deadlocks every future run (see the
        # 2026-09-08 note on the guard above). So rebase down by at most the
        # allowance we actually granted, never further.
        if len(listings) > _prev_hw:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": len(listings),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }, indent=2).encode("utf-8"))
            log.info("web_artifact.highwater_updated",
                     old=_prev_hw, new=len(listings))
        elif _accepted_intentional > 0 and len(listings) >= _prev_hw - _accepted_intentional:
            _atomic_write_bytes(_hw_path, json.dumps({
                "count": len(listings),
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "rebased_from": _prev_hw,
                "reason": f"{_accepted_intentional:,} off-footprint rows removed",
            }, indent=2).encode("utf-8"))
            log.warning("web_artifact.highwater_rebased",
                        old=_prev_hw, new=len(listings),
                        off_footprint_removed=_accepted_intentional)
    except Exception:  # noqa: BLE001
        pass

    # THE MANIFEST, last. Everything above is on disk; this seals the set. A kill
    # before this line leaves a stale manifest that DISAGREES with the new files,
    # which is exactly the signal the next reader needs (BoardIntegrityError).
    try:
        write_manifest(docs, _manifest_pre, meta, slim_count=slim_count, shard_meta=shard_meta,
                       parts_block=_parts_block)
    except Exception:  # noqa: BLE001
        # A manifest we could not write must not pass for a current one.
        try:
            (docs / MANIFEST_NAME).unlink(missing_ok=True)
        except OSError:
            pass
        log.error("web_artifact.manifest_failed", exc_info=True)
    # The board on disk is now the one THIS process wrote: refresh the load stamp so
    # a second write in the same process is not mistaken for someone else's.
    # Only when this process had loaded before: a full re-scrape that never loaded has no
    # stamp, and inventing one would just add a check nobody asked for.
    if str(listings_path.resolve()) in _LOAD_STAMPS:
        _remember_load(docs, listings_path)

    log.info("web_artifact.written", listings=len(listings), bytes=listings_path.stat().st_size)
    return listings_path, meta_path

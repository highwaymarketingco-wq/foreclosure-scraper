"""jail_roster_history.py — the sidecar that turns each jail-roster fetch into
a standing re-query (Dirty Deeds Tier B #36).

What these pin:
  * a name never seen before under (state, county) is reported is_new=True with
    first_seen_at == now
  * seeing that same name again reports is_new=False and PRESERVES the original
    first_seen_at ("start the clock at detection" — the clock must not reset)
  * times_seen increments on every re-fetch
  * an EMPTY fetch writes nothing and returns {} — never read as "everybody on
    the roster was released" (that would be indistinguishable from a fetch that
    silently failed; see the module's own docstring on this)
  * a name that drops off a REAL (non-empty) re-fetch is demoted
    currently_listed=0 without touching anyone still present
  * two different counties never collide on the same name
  * stats() rolls up per (state, county) coverage
"""
from __future__ import annotations

from datetime import datetime, timezone

from foreclosure_scraper import jail_roster_history as jrh


def _rec(last, first, arrest="2026-09-01", charge="TRESPASSING", dob=None):
    return {"last": last, "first": first, "arrest_date": arrest, "charge": charge, "dob": dob}


def test_first_sighting_is_new_with_first_seen_now(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    meta = jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                               [_rec("SMITH", "JOHN")], now=now)
    m = meta[("SMITH", "JOHN")]
    assert m["is_new"] is True
    assert m["first_seen_at"] == now.replace(microsecond=0).isoformat()
    assert m["times_seen"] == 1


def test_second_sighting_keeps_the_original_first_seen_and_bumps_times_seen(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    t1 = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
    jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                        [_rec("SMITH", "JOHN")], now=t1)
    meta = jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                               [_rec("SMITH", "JOHN")], now=t2)
    m = meta[("SMITH", "JOHN")]
    assert m["is_new"] is False
    # the clock does NOT reset on a re-sighting -- this is the "start the clock
    # at detection" mechanic the synthesis asks for
    assert m["first_seen_at"] == t1.replace(microsecond=0).isoformat()
    assert m["last_seen_at"] == t2.replace(microsecond=0).isoformat()
    assert m["times_seen"] == 2


def test_empty_fetch_writes_nothing_and_does_not_mark_anyone_departed(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    t1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                        [_rec("SMITH", "JOHN")], now=t1)
    # A later fetch returns [] -- could be a genuinely empty roster, could be a
    # silent failure (the fetcher cannot tell the two apart). Either way this
    # must not wipe out what was already recorded.
    meta = jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare", [], now=t1)
    assert meta == {}
    row = con.execute("SELECT currently_listed FROM bookings WHERE booking_key=?",
                      (jrh.booking_key("NC", "Buncombe", "SMITH", "JOHN"),)).fetchone()
    assert row["currently_listed"] == 1  # untouched, not demoted


def test_a_real_refetch_demotes_whoever_is_absent_but_not_whoever_remains(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    t1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 8, tzinfo=timezone.utc)
    jrh.diff_and_record(con, "SC", "Cherokee", "zuercher",
                        [_rec("ADAMS", "BRUCE"), _rec("BANKS", "ERNEST")], now=t1)
    # ADAMS released; BANKS still in custody; DOE is a brand-new booking.
    jrh.diff_and_record(con, "SC", "Cherokee", "zuercher", [_rec("BANKS", "ERNEST"),
                                                            _rec("DOE", "JANE")], now=t2)
    rows = {r["last_name"] + "," + r["first_name"]: r["currently_listed"]
           for r in con.execute("SELECT last_name, first_name, currently_listed"
                                " FROM bookings WHERE county='Cherokee'")}
    assert rows["ADAMS,BRUCE"] == 0    # demoted: absent from a real refetch
    assert rows["BANKS,ERNEST"] == 1   # still there
    assert rows["DOE,JANE"] == 1       # new


def test_two_counties_with_the_same_name_do_not_collide(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    meta_a = jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                                 [_rec("SMITH", "JOHN")], now=now)
    meta_b = jrh.diff_and_record(con, "NC", "Cleveland", "p2c_jqgrid",
                                 [_rec("SMITH", "JOHN")], now=now)
    # Both are "new" — Cleveland is a different roster and has never seen this
    # name before, even though Buncombe just did.
    assert meta_a[("SMITH", "JOHN")]["is_new"] is True
    assert meta_b[("SMITH", "JOHN")]["is_new"] is True
    assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 2


def test_booking_key_normalizes_case_and_punctuation():
    # Callers pass an already county-suffix-stripped county (see
    # enrichment_jail_bookings._plain_county); this module only case/punctuation
    # normalizes, matching _norm_key's own contract in that module.
    a = jrh.booking_key("nc", "buncombe", "o'neal", "  mary-jane ")
    b = jrh.booking_key("NC", "BUNCOMBE", "ONEAL", "MARYJANE")
    assert a == b


def test_stats_rolls_up_per_state_county(tmp_path):
    con = jrh.connect(tmp_path / "h.db")
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                        [_rec("SMITH", "JOHN"), _rec("DOE", "JANE")], now=now)
    rows = {(r["state"], r["county"]): r for r in jrh.stats(con)}
    r = rows[("NC", "Buncombe")]
    assert r["total"] == 2
    assert r["in_custody"] == 2


def test_a_missing_sidecar_file_is_created_lazily_not_an_error(tmp_path):
    p = tmp_path / "nested" / "new.db"
    assert not p.exists()
    con = jrh.connect(p)
    assert p.exists()
    assert con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0


# ---- commit=False ("dry run") -- 2026-09-29 fix -------------------------
#
# scripts/run_pending_signal_enrichers.py --dry-run found 590 genuine
# jail_booking_new cross-county matches; the REAL apply pass ~35 minutes
# later found 0 new matches for the same counties, because the dry run's own
# roster fetch had already been diffed-and-recorded as "seen." These pin the
# fix: `commit=False` still computes and reports an accurate diff (so a dry
# run's own printed report is correct) but never persists it, so a later
# real call against the same fetch still reports is_new=True.

def test_commit_false_computes_an_accurate_report_but_does_not_persist(tmp_path):
    db_path = tmp_path / "h.db"
    con = jrh.connect(db_path)
    t1 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    meta = jrh.diff_and_record(con, "NC", "Buncombe", "p2c_centralsquare",
                               [_rec("SMITH", "JOHN")], now=t1, commit=False)
    # the report is exactly as accurate as a real (commit=True) call would be
    m = meta[("SMITH", "JOHN")]
    assert m["is_new"] is True
    assert m["first_seen_at"] == t1.replace(microsecond=0).isoformat()
    assert m["times_seen"] == 1
    con.close()  # never committed -- sqlite discards the pending transaction

    # a fresh connection to the SAME file sees no trace of the dry run
    con2 = jrh.connect(db_path)
    assert con2.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] == 0
    con2.close()


def test_a_real_diff_after_a_commit_false_dry_run_still_reports_new(tmp_path):
    """The exact 2026-09-29 regression, reproduced at the sidecar layer: a
    dry-run-style call (commit=False) must not cause a later REAL call
    (commit=True, the default) against the same fetch to see is_new=False."""
    db_path = tmp_path / "h.db"
    t1 = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)

    con = jrh.connect(db_path)
    dry_meta = jrh.diff_and_record(con, "SC", "Cherokee", "zuercher",
                                   [_rec("ADAMS", "BRUCE")], now=t1, commit=False)
    assert dry_meta[("ADAMS", "BRUCE")]["is_new"] is True
    con.close()

    # ~35 minutes later, matching the real incident's timing
    t2 = datetime(2026, 9, 29, 9, 35, tzinfo=timezone.utc)
    con2 = jrh.connect(db_path)
    real_meta = jrh.diff_and_record(con2, "SC", "Cherokee", "zuercher",
                                    [_rec("ADAMS", "BRUCE")], now=t2)
    assert real_meta[("ADAMS", "BRUCE")]["is_new"] is True  # NOT swallowed by the dry run
    con2.close()

    # and this real call genuinely DID persist -- a third fetch now correctly
    # sees the name as no longer new, proving commit=True still works as before
    con3 = jrh.connect(db_path)
    meta3 = jrh.diff_and_record(con3, "SC", "Cherokee", "zuercher",
                                [_rec("ADAMS", "BRUCE")], now=t2)
    assert meta3[("ADAMS", "BRUCE")]["is_new"] is False
    con3.close()

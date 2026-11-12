"""enrichment_foreclosure_docket_history.py — wiring for Dirty Deeds Tier B #37.

Uses realistic Listing.raw shapes copied from the actual scraper output (see
sc_public_index_lis_pendens.py's raw={"sc_public_index": {...}}, sc_public_
index.py's (counties_sc bulk) raw={"court": {...}}, national/sc_public_index.
py's raw={"sc_public_index": {...}}, and nc_ecourts_lis_pendens.py's
raw={"nc_ecourts": {...}}) rather than guessed field names, so a rename in any
of those four scrapers' raw schema breaks this test instead of silently
going unflagged.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from foreclosure_scraper.enrichment_foreclosure_docket_history import (
    enrich_foreclosure_docket_history,
    SOURCES,
)
from foreclosure_scraper import foreclosure_docket_history as fdh
from foreclosure_scraper.models import Listing, ListingType, PropertyKind


def _sc_pi_lis_pendens(case_number: str, status: str, defendant: str,
                       plaintiff: str = "ACME MORTGAGE") -> Listing:
    """Matches counties_sc.sc_public_index_lis_pendens._parse_results's shape."""
    return Listing(
        source="counties_sc.sc_public_index_lis_pendens",
        source_url="https://publicindex.sccourts.org/Spartanburg/PublicIndex/x",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county="Spartanburg",
        case_number=case_number, plaintiff=plaintiff, defendant=defendant,
        auction_status=status.lower(),
        raw={"sc_public_index": {"filed_date": "2026-06-01T00:00:00",
                                 "status": status, "subtype": "Foreclosure",
                                 "case_raw": case_number, "co_defendants": None}},
    )


def _national_sc_pi(case_number: str, status: str, county: str = "Spartanburg") -> Listing:
    """Matches national.sc_public_index.SCPublicIndexScraper._to_listings's shape."""
    return Listing(
        source="national.sc_public_index",
        source_url="https://publicindex.sccourts.org/",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="SC", county=county,
        case_number=case_number,
        defendant="MARY WHITE",
        raw={"sc_public_index": {"name": "MARY WHITE", "role": "Defendant",
                                 "case_number": case_number, "date_filed": "01/15/2026",
                                 "status": status, "court": "SC Common Pleas",
                                 "source": "publicindex.sccourts.org"}},
    )


def _nc_ecourts_hit_listing(case_number: str, status: str, defendant: str) -> Listing:
    """Matches counties_nc.nc_ecourts_lis_pendens._hit_to_listing's shape."""
    return Listing(
        source="counties_nc.nc_ecourts_lis_pendens",
        source_url="https://portal-nc.tylertech.cloud/app/NCJudgmentSearch/#/x",
        listing_type=ListingType.LIS_PENDENS,
        property_kind=PropertyKind.UNKNOWN,
        state="NC", county="Henderson",
        case_number=case_number, defendant=defendant, plaintiff="BIG BANK",
        raw={"nc_ecourts": {"cause": "CV - Lis Pendens", "civilJudgmentStatus": status,
                            "caseCategoryKey": "CV", "orderedDate": "2026-06-01T00:00:00",
                            "ordered_date_iso": "2026-06-01T00:00:00", "location": "Henderson District Court"}},
    )


def _run(listings):
    return asyncio.run(enrich_foreclosure_docket_history(listings))


def test_sources_constant_matches_the_four_investigated_scrapers():
    assert SOURCES == {
        "counties_nc.nc_ecourts_lis_pendens",
        "counties_sc.sc_public_index_lis_pendens",
        "counties_sc.sc_public_index",
        "national.sc_public_index",
    }


def test_unrelated_source_is_left_untouched():
    li = Listing(source="newspapers.daily_courier", source_url="https://x",
                state="NC", county="Henderson")
    counts = _run([li])
    assert counts == {"observed": 0, "flagged": 0}
    assert "repeat_foreclosure_filing" not in li.raw


def test_two_dismissed_sc_public_index_lis_pendens_cases_flag_a_third(tmp_path, monkeypatch):
    # Isolate the sidecar DB per test so runs don't bleed into each other.
    monkeypatch.setattr(fdh, "DB_PATH", tmp_path / "h.db")
    a = _sc_pi_lis_pendens("2026-CP-42-00001", "Dismissed", "JOHN SMITH")
    b = _sc_pi_lis_pendens("2026-CP-42-00002", "Dismissed", "JOHN SMITH")
    c = _sc_pi_lis_pendens("2026-CP-42-00003", "Pending", "JOHN SMITH")
    counts = _run([a, b, c])
    assert counts["observed"] == 3
    # a and b are each other's only dismissed sibling once the OTHER one is
    # excluded -- 1 prior dismissal each, below the 2+ threshold -- but c
    # (still pending) sees BOTH a and b as prior dismissed history.
    assert "repeat_foreclosure_filing" not in a.raw
    assert "repeat_foreclosure_filing" not in b.raw
    assert "repeat_foreclosure_filing" in c.raw
    flag = c.raw["repeat_foreclosure_filing"]
    assert flag["count"] == 2
    assert flag["basis"] == "status_text"


def test_judgment_status_from_national_sc_public_index_never_counts_as_dismissed(tmp_path, monkeypatch):
    monkeypatch.setattr(fdh, "DB_PATH", tmp_path / "h.db")
    won = _national_sc_pi("2026CP4200001", "Judgment")  # lender WON, not a failure
    settled = _national_sc_pi("2026CP4200002", "Settled")
    active = _national_sc_pi("2026CP4200003", "Pending")
    _run([won, settled, active])
    assert "repeat_foreclosure_filing" not in active.raw, (
        "Judgment/Settled must never be read as a failed filing"
    )


def test_nc_ecourts_active_listing_gets_flagged_from_history_the_scraper_already_recorded(tmp_path, monkeypatch):
    """Simulates the NC asymmetry: nc_ecourts_lis_pendens.py's own
    _record_docket_history hook already wrote two Dismissed observations for
    this owner directly to the sidecar (those hits never became Listings),
    and now a THIRD, still-Active hit DID become a Listing. The enrichment
    pass must be able to flag it purely from sidecar history, without ever
    having seen a Listing for the two dismissed cases."""
    monkeypatch.setattr(fdh, "DB_PATH", tmp_path / "h.db")
    con = fdh.connect()
    fdh.observe_case(con, state="NC", county="Henderson", case_number="24CVD001111-320",
                     owner_name="BOB JONES", plaintiff="BIG BANK", status="Dismissed")
    fdh.observe_case(con, state="NC", county="Henderson", case_number="24CVD002222-320",
                     owner_name="BOB JONES", plaintiff="BIG BANK", status="Terminated")
    con.close()

    active = _nc_ecourts_hit_listing("24CVD003333-320", "Active", "BOB JONES")
    counts = _run([active])
    assert counts["flagged"] == 1
    assert active.raw["repeat_foreclosure_filing"]["count"] == 2


def test_different_owners_in_the_same_county_do_not_cross_contaminate(tmp_path, monkeypatch):
    monkeypatch.setattr(fdh, "DB_PATH", tmp_path / "h.db")
    a1 = _sc_pi_lis_pendens("2026-CP-42-00010", "Dismissed", "AAA OWNER")
    a2 = _sc_pi_lis_pendens("2026-CP-42-00011", "Dismissed", "AAA OWNER")
    b1 = _sc_pi_lis_pendens("2026-CP-42-00012", "Pending", "BBB OWNER")
    _run([a1, a2, b1])
    assert "repeat_foreclosure_filing" not in b1.raw


def test_raw_key_is_registered_in_raw_keep():
    from foreclosure_scraper.web_artifact import RAW_KEEP
    assert "repeat_foreclosure_filing" in RAW_KEEP


# ---- dry-run/real-run double persistence -- 2026-09-29 investigation ------
#
# Sibling to enrichment_jail_bookings.py's 2026-09-29 fix (commit 1ec77297,
# "Fix jail-roster sidecar losing 590 signals to dry-run/real-run
# sequencing"). enrich_foreclosure_docket_history() has NO dry_run parameter:
# its con.commit() after the record loop runs unconditionally, so a --dry-run
# invocation of scripts/run_pending_signal_enrichers.py DOES persist real
# case observations to data/foreclosure_docket_history.db (confirmed live
# 2026-09-29: this exact dry-run-then-real-run sequence happened for THIS
# enricher too, ~37 minutes apart -- same job, same script, all 8 STEPS
# including this one run unconditionally regardless of --dry-run).
#
# UNLIKE jail bookings' is_new_booking (a diff against last-known roster
# state that gets silently swallowed once a dry run marks a name "seen"),
# repeat_foreclosure_filing depends on repeat_filing_flag's cumulative count
# of ever_dismissed cases for an owner -- a stateless aggregate, not a diff.
# That is why no dry_run parameter was added here: this test pins that
# calling the enrichment function a second time (standing in for the real
# run, after an earlier "dry run" call already recorded the same targets)
# still produces the identical, correct flag -- no signal is lost the way
# jail_booking_new's was.

def test_calling_the_enrichment_twice_does_not_lose_the_repeat_flag(tmp_path, monkeypatch):
    """Dry-run-then-real-run, reproduced at the enrichment-function layer: two
    dismissed cases plus a third active one, enriched in ONE call ('dry
    run'), then fresh Listing objects for the exact same three real-world
    cases enriched AGAIN in a second call ('real run') -- the second call's
    flag on the active listing must match the first's, not be silently
    dropped because the dry run already recorded the two dismissals."""
    monkeypatch.setattr(fdh, "DB_PATH", tmp_path / "h.db")
    a = _sc_pi_lis_pendens("2026-CP-42-00001", "Dismissed", "JOHN SMITH")
    b = _sc_pi_lis_pendens("2026-CP-42-00002", "Dismissed", "JOHN SMITH")
    c = _sc_pi_lis_pendens("2026-CP-42-00003", "Pending", "JOHN SMITH")
    dry_counts = _run([a, b, c])
    assert dry_counts == {"observed": 3, "flagged": 1}
    assert c.raw["repeat_foreclosure_filing"]["count"] == 2

    # Fresh Listing objects for the SAME real-world cases -- standing in for
    # the real run's own re-scrape of the same board rows minutes later.
    a2 = _sc_pi_lis_pendens("2026-CP-42-00001", "Dismissed", "JOHN SMITH")
    b2 = _sc_pi_lis_pendens("2026-CP-42-00002", "Dismissed", "JOHN SMITH")
    c2 = _sc_pi_lis_pendens("2026-CP-42-00003", "Pending", "JOHN SMITH")
    real_counts = _run([a2, b2, c2])
    assert real_counts == {"observed": 3, "flagged": 1}
    assert c2.raw["repeat_foreclosure_filing"]["count"] == 2, (
        "a case recorded by an earlier call must still count toward a later "
        "call's repeat-filing flag -- this signal is NOT lost the way "
        "jail_booking_new's is_new gate was (2026-09-29 investigation)"
    )

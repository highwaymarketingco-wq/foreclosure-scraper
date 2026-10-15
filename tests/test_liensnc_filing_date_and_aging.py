"""LiensNC filings: the filing date is not a sale date, and a filing never ages out as 'pulled'."""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.board_persist import AGE_EXEMPT_SOURCES, merge_prior_board
from foreclosure_scraper.main import _active_only

from tests.test_board_persist import NOW, _li, _write_board


def _filing(src: str, days_ago: int):
    return _li(source=src, sale_date=datetime(2026, 10, 7) - timedelta(days=days_ago))


def test_a_liensnc_filing_from_months_ago_is_still_active():
    now = datetime(2026, 10, 7)
    assert _active_only(_filing("counties_generic.liensnc", 120), 120, now=now)
    assert _active_only(_filing("liensnc", 300), 120, now=now)


def test_a_filing_older_than_a_year_is_not_active():
    assert not _active_only(_filing("liensnc", 400), 120, now=datetime(2026, 10, 7))


def test_other_sources_keep_the_short_upset_window():
    assert not _active_only(_filing("counties_nc.some_foreclosure_list", 120), 120, now=datetime(2026, 10, 7))


def test_a_prior_only_liensnc_row_is_kept_without_aging(tmp_path):
    prior = [_li(street_address="10 Elm St", zip_code="28801", source="counties_generic.liensnc",
                 auction_status="presumed_withdrawn",
                 raw={"pulled_sale": {"consecutive_misses": 4, "presumed_withdrawn": True}})]
    _write_board(tmp_path, prior)
    fresh = [_li(street_address="99 Somewhere", zip_code="28803")]
    out, stats = merge_prior_board(fresh, docs_dir=tmp_path, now=NOW, max_misses=4)
    kept = [li for li in out if li.street_address == "10 Elm St"]
    assert kept, "the filing must survive any number of missed runs"
    assert "pulled_sale" not in (kept[0].raw or {})
    assert kept[0].auction_status is None
    assert stats["prior_only_kept_age_exempt"] == 1 and stats["aged_out_misses"] == 0


def test_an_ordinary_prior_only_row_still_ages_out(tmp_path):
    prior = [_li(street_address="8 Maple St", zip_code="28801",
                 raw={"pulled_sale": {"consecutive_misses": 4, "first_missed_at": "2026-06-01Z"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Somewhere", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    assert "8 Maple St" not in {li.street_address for li in out} and stats["aged_out_misses"] == 1


def test_the_exempt_set_is_liensnc_plus_the_rod_nod_family():
    # 2026-10-14 (date-coverage audit pass2, item #5): deliberately widened from exactly
    # {"liensnc"} to also cover the ROD/NOD pre-foreclosure recording-sweep family -- a
    # recording with no case-status field of any kind, same "a filing is history, not
    # something that gets un-filed" reasoning liensnc already has on record. This guard now
    # pins the FULL intentional membership so a future addition is reviewed, not silent.
    # 2026-10-15 (date-coverage audit pass3): widened again with 7 more sources found by the
    # same audit method applied to the files pass1/pass2 hadn't yet covered -- see
    # tests/test_open_case_hold_pass2.py's _PASS3_AGE_EXEMPT_FAMILY for the per-source detail.
    assert AGE_EXEMPT_SOURCES == frozenset({
        "liensnc",
        "nc_rod_substitute_trustee",
        "wnc_rod_foreclosure_starts",
        "nc_rod_captcha",
        "nc_rod_logan",
        "sc_rod_acclaim",
        "sc_rod_cott",
        "sc_rod_walled",
        "cherokee_rod",
        "nod_discovery",
        "cash_buyer_deeds",
        "anderson_acpass_deeds",
        "nc_rowan_cott",
        "horry_probate",
        "nc_heir_notices",
        "publicnoticesc_estates",
        "nc_unclaimed",
        "nc_cchs_deeds",      # currently dormant, same as cherokee_rod -- see board_persist.py
    })

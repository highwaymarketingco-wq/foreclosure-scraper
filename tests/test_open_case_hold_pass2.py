"""Date-coverage audit pass2 (2026-10-14) — extending the Charleston open_case_hold() pattern to
three more window-searched sources: CourtListener (item #2), NC eCourts lis pendens / judgment
liens (item #1), and the SC Upstate Public Index siblings (items #3/#4). Each of these only
re-discovers a case through a short filed/ordered-date window; without a hold, a case still
genuinely open just ages out of the board once its scraper stops re-finding it (the SAME
mechanism tests/test_open_case_hold.py already pins for Charleston). Made-up cases, names and
addresses.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from foreclosure_scraper.board_persist import (
    AGE_EXEMPT_SOURCES,
    courtlistener_open_hold,
    merge_prior_board,
    nc_ecourts_open_hold,
    sc_upstate_open_hold,
)

from tests.test_board_persist import _li, _write_board

NOW = datetime(2026, 10, 14)


# ---------------------------------------------------------------------------
# CourtListener (item #2)
# ---------------------------------------------------------------------------

def _cl_rec(source="national.courtlistener_bankruptcy", raw_key="courtlistener", **block):
    b = {"court": "ncwb", "docket_number": "26-01234", "date_terminated": None}
    b.update(block)
    return {"source": source, "raw": {raw_key: b}}


def test_courtlistener_bankruptcy_open_case_is_held():
    assert courtlistener_open_hold(_cl_rec())


def test_courtlistener_civil_and_adversary_use_their_own_raw_key():
    assert courtlistener_open_hold(_cl_rec("national.courtlistener_civil", "courtlistener_civil"))
    assert courtlistener_open_hold(_cl_rec("national.courtlistener_adversary", "courtlistener_adversary"))


def test_courtlistener_terminated_case_is_not_held():
    assert not courtlistener_open_hold(_cl_rec(date_terminated="2026-09-01"))


def test_courtlistener_unrelated_source_is_not_held():
    assert not courtlistener_open_hold(_cl_rec(source="national.sc_public_index"))


def test_courtlistener_missing_block_for_right_source_defaults_open():
    """A row whose raw block is missing the key entirely (never actually produced by any of
    the three scrapers, but defensive): treated the same permissive way open_case_hold() treats
    a row with no case date at all -- unknown is not evidence of closed."""
    rec = {"source": "national.courtlistener_civil", "raw": {"courtlistener": {"date_terminated": None}}}
    assert courtlistener_open_hold(rec)


def test_courtlistener_merge_holds_open_case_and_ages_terminated_one(tmp_path):
    # Pre-seeded at 4 consecutive misses (same model as tests/test_open_case_hold.py's
    # Charleston _case() helper): one more merge_prior_board() call is the 5th miss, over
    # max_misses=4, so the NOT-held row ages out in this single call rather than needing 5.
    prior = [
        _li(source="national.courtlistener_bankruptcy", street_address="10 Sample St",
            zip_code="28801", raw={"courtlistener": {"date_terminated": None}}),
        _li(source="national.courtlistener_bankruptcy", street_address="12 Sample St",
            zip_code="28801", raw={"courtlistener": {"date_terminated": "2026-01-01"},
                                   "pulled_sale": {"consecutive_misses": 4}}),
    ]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by and "12 Sample St" not in by  # 5th miss, not held: aged out
    assert stats["prior_only_kept_courtlistener_open"] == 1


# ---------------------------------------------------------------------------
# NC eCourts (item #1)
# ---------------------------------------------------------------------------

def _nce_rec(source="counties_nc.nc_ecourts_lis_pendens", ordered_date="2026-08-01T00:00:00",
            status="", first_seen="2026-08-01"):
    return {
        "source": source, "state": "NC", "county": "Buncombe", "first_seen": first_seen,
        "raw": {"nc_ecourts": {"orderedDate": ordered_date, "civilJudgmentStatus": status}},
    }


def test_nc_ecourts_open_judgment_is_held():
    assert nc_ecourts_open_hold(_nce_rec(), NOW)


def test_nc_ecourts_judgment_lien_sub_slug_is_held():
    assert nc_ecourts_open_hold(_nce_rec(source="counties_nc.nc_ecourts_lis_pendens.judgment_lien"), NOW)


def test_nc_ecourts_dismissed_status_is_not_held():
    assert not nc_ecourts_open_hold(_nce_rec(status="Dismissed"), NOW)


def test_nc_ecourts_satisfied_status_is_not_held():
    assert not nc_ecourts_open_hold(_nce_rec(status="Satisfied"), NOW)


def test_nc_ecourts_idle_over_a_year_is_not_held():
    assert not nc_ecourts_open_hold(_nce_rec(ordered_date="2025-01-01T00:00:00"), NOW)


def test_nc_ecourts_other_source_is_not_held():
    # 2026-10-15 (date-coverage audit pass3): this used to use "counties_nc.nc_ecourts_divorce" as
    # its example of an unrelated, non-member source -- which pinned the exact gap pass3 found and
    # fixed (divorce judgments carry the identical raw['nc_ecourts'] shape as lis_pendens but were
    # never added to NC_ECOURTS_OPEN_SOURCES). Switched to a genuinely unrelated source; the fixed
    # divorce behavior is pinned separately below.
    assert not nc_ecourts_open_hold(_nce_rec(source="counties_sc.sc_public_index"), NOW)


def test_nc_ecourts_divorce_open_judgment_is_held():
    """Pass3 fix: counties_nc.nc_ecourts_divorce is the same shape as its lis-pendens sibling
    (same vendor/API, same raw['nc_ecourts'] block, JUDGMENT_LOOKBACK_DAYS=120 instead of the
    sibling's 90) and was simply never added to NC_ECOURTS_OPEN_SOURCES when it was built."""
    assert nc_ecourts_open_hold(_nce_rec(source="counties_nc.nc_ecourts_divorce"), NOW)


def test_nc_ecourts_divorce_dismissed_status_is_not_held():
    assert not nc_ecourts_open_hold(
        _nce_rec(source="counties_nc.nc_ecourts_divorce", status="Dismissed"), NOW)


def test_nc_ecourts_divorce_merge_holds_open_and_ages_dismissed(tmp_path):
    prior = [
        _li(source="counties_nc.nc_ecourts_divorce", street_address="20 Sample St",
            zip_code="28801", state="NC", county="Buncombe", first_seen=datetime(2026, 8, 1),
            raw={"nc_ecourts": {"orderedDate": "2026-08-01T00:00:00", "civilJudgmentStatus": ""}}),
        _li(source="counties_nc.nc_ecourts_divorce", street_address="22 Sample St",
            zip_code="28801", state="NC", county="Buncombe", first_seen=datetime(2026, 8, 1),
            raw={"nc_ecourts": {"orderedDate": "2026-08-01T00:00:00",
                                "civilJudgmentStatus": "Dismissed"},
                 "pulled_sale": {"consecutive_misses": 4}}),
    ]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "20 Sample St" in by and "22 Sample St" not in by
    assert stats["prior_only_kept_nc_ecourts_open"] == 1


def test_nc_ecourts_merge_holds_open_and_ages_dismissed(tmp_path):
    prior = [
        _li(source="counties_nc.nc_ecourts_lis_pendens", street_address="10 Sample St",
            zip_code="28801", state="NC", county="Buncombe", first_seen=datetime(2026, 8, 1),
            raw={"nc_ecourts": {"orderedDate": "2026-08-01T00:00:00", "civilJudgmentStatus": ""}}),
        _li(source="counties_nc.nc_ecourts_lis_pendens", street_address="12 Sample St",
            zip_code="28801", state="NC", county="Buncombe", first_seen=datetime(2026, 8, 1),
            raw={"nc_ecourts": {"orderedDate": "2026-08-01T00:00:00",
                                "civilJudgmentStatus": "Dismissed"},
                 "pulled_sale": {"consecutive_misses": 4}}),
    ]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by and "12 Sample St" not in by
    assert stats["prior_only_kept_nc_ecourts_open"] == 1


# ---------------------------------------------------------------------------
# SC Upstate Public Index (items #3/#4)
# ---------------------------------------------------------------------------

def _scu_lp_rec(status="Active", date_filed="08/01/2026", county="Spartanburg"):
    return {
        "source": "counties_sc.sc_public_index_lis_pendens", "state": "SC", "county": county,
        "raw": {"sc_public_index": {"date_filed": date_filed, "status": status}},
    }


def _scu_bulk_rec(status="Active", filed_date="08/01/2026", disposition_date="", county="Anderson"):
    return {
        "source": "counties_sc.sc_public_index", "state": "SC", "county": county,
        "raw": {"court": {"filed_date": filed_date, "status": status,
                          "disposition_date": disposition_date}},
    }


def test_sc_public_index_lis_pendens_open_case_is_held():
    assert sc_upstate_open_hold(_scu_lp_rec(), NOW)


def test_sc_public_index_bulk_open_case_is_held():
    assert sc_upstate_open_hold(_scu_bulk_rec(), NOW)


def test_sc_public_index_lis_pendens_dismissed_is_not_held():
    assert not sc_upstate_open_hold(_scu_lp_rec(status="Dismissed"), NOW)


def test_sc_public_index_bulk_disposed_is_not_held():
    assert not sc_upstate_open_hold(_scu_bulk_rec(disposition_date="09/01/2026"), NOW)


def test_sc_public_index_bulk_withdrawn_status_is_not_held():
    assert not sc_upstate_open_hold(_scu_bulk_rec(status="Withdrawn"), NOW)


def test_sc_public_index_wrong_county_is_not_held():
    # Charleston is the OPEN_CASE_SOURCES (national.sc_public_index) county, not this family's.
    assert not sc_upstate_open_hold(_scu_lp_rec(county="Charleston"), NOW)
    assert not sc_upstate_open_hold(_scu_bulk_rec(county="Charleston"), NOW)


def test_sc_public_index_idle_over_a_year_is_not_held():
    assert not sc_upstate_open_hold(_scu_lp_rec(date_filed="08/01/2024"), NOW)
    assert not sc_upstate_open_hold(_scu_bulk_rec(filed_date="08/01/2024"), NOW)


def test_sc_public_index_merge_holds_open_and_ages_dismissed(tmp_path):
    prior = [
        _li(source="counties_sc.sc_public_index_lis_pendens", street_address="10 Sample St",
            zip_code="29301", state="SC", county="Spartanburg",
            raw={"sc_public_index": {"date_filed": "08/01/2026", "status": "Active"}}),
        _li(source="counties_sc.sc_public_index_lis_pendens", street_address="12 Sample St",
            zip_code="29301", state="SC", county="Spartanburg",
            raw={"sc_public_index": {"date_filed": "08/01/2026", "status": "Dismissed"},
                 "pulled_sale": {"consecutive_misses": 4}}),
        _li(source="counties_sc.sc_public_index", street_address="14 Sample St",
            zip_code="29621", state="SC", county="Anderson",
            raw={"court": {"filed_date": "08/01/2026", "status": "Active",
                           "disposition_date": ""}}),
    ]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by and "14 Sample St" in by
    assert "12 Sample St" not in by
    assert stats["prior_only_kept_sc_upstate_open"] == 2


# ---------------------------------------------------------------------------
# ROD/NOD recording-sweep family (item #5) -- AGE_EXEMPT_SOURCES, not status tracking
# ---------------------------------------------------------------------------

_ROD_FAMILY = (
    "nc_rod_substitute_trustee", "wnc_rod_foreclosure_starts", "nc_rod_captcha",
    "nc_rod_logan", "sc_rod_acclaim", "sc_rod_cott", "sc_rod_walled", "cherokee_rod",
    "nod_discovery",
)


def test_all_nine_rod_nod_sources_are_age_exempt():
    missing = {s for s in _ROD_FAMILY if s not in AGE_EXEMPT_SOURCES}
    assert not missing, f"ROD/NOD sources dropped from AGE_EXEMPT_SOURCES: {missing}"


def test_rod_pre_sale_row_survives_past_four_misses(tmp_path):
    """A pre-foreclosure ROD recording (no case-status field exists to check) must survive past
    the generic PULLED_RETENTION_WEEKS miss limit, same model as liensnc."""
    prior = [_li(source="counties_nc.nc_rod_substitute_trustee", street_address="10 Sample St",
                 zip_code="28801", sale_date=None,
                 raw={"nc_rod": {"vendor": "aumentum", "kind": "pre_sale"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_rod_completed_sale_still_ages_out_via_terminal_check(tmp_path):
    """A completed-sale ROD row (real sale_date, now AGE_EXEMPT via the same slug) must still be
    dropped once it is more than TERMINAL_SALE_GRACE_DAYS past its sale_date --
    _is_terminal_dict() is unconditional and runs BEFORE the AGE_EXEMPT_SOURCES check."""
    old_sale = NOW - timedelta(days=400)
    prior = [_li(source="counties_nc.nc_rod_substitute_trustee", street_address="10 Sample St",
                 zip_code="28801", sale_date=old_sale,
                 raw={"nc_rod": {"vendor": "aumentum", "kind": "post_sale"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" not in by
    assert stats["aged_out_terminal"] == 1


# ---------------------------------------------------------------------------
# Pass3 (2026-10-15) additions to AGE_EXEMPT_SOURCES -- same liensnc/ROD-NOD model: each of these
# 7 sources is a recorded/filed permanent fact (or, for horry_probate/publicnoticesc_estates, an
# estate with no status field reachable) discovered only through a rolling day-window, with no
# case-status field to branch on.
# ---------------------------------------------------------------------------

_PASS3_AGE_EXEMPT_FAMILY = (
    "cash_buyer_deeds", "anderson_acpass_deeds", "nc_rowan_cott", "horry_probate",
    "nc_heir_notices", "publicnoticesc_estates", "nc_unclaimed", "nc_cchs_deeds",
)


def test_all_seven_pass3_sources_are_age_exempt():
    missing = {s for s in _PASS3_AGE_EXEMPT_FAMILY if s not in AGE_EXEMPT_SOURCES}
    assert not missing, f"pass3 sources dropped from AGE_EXEMPT_SOURCES: {missing}"


def test_cash_buyer_deed_row_survives_past_four_misses(tmp_path):
    """A recorded cash-buyer deed (the grantee really did buy in cash; that doesn't become untrue
    once the 30-day sweep window moves past it) must survive past the generic miss limit."""
    prior = [_li(source="national.cash_buyer_deeds", street_address="10 Sample St",
                 zip_code="28801", sale_date=NOW - timedelta(days=200),
                 raw={"cash_buyer_deeds": {"county": "Buncombe", "is_cash_buyer": True}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_cash_buyer_deed_still_ages_out_via_terminal_check_past_a_year(tmp_path):
    """Unlike nod_discovery's old fabricated-date bug, cash_buyer_deeds.sale_date is the REAL
    recorded_date, so the unconditional terminal-sale-date rule must still fire past
    TERMINAL_SALE_GRACE_DAYS regardless of the new AGE_EXEMPT_SOURCES entry."""
    prior = [_li(source="national.cash_buyer_deeds", street_address="10 Sample St",
                 zip_code="28801", sale_date=NOW - timedelta(days=400),
                 raw={"cash_buyer_deeds": {"county": "Buncombe", "is_cash_buyer": True}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" not in by
    assert stats["aged_out_terminal"] == 1


def test_horry_probate_filing_survives_past_four_misses(tmp_path):
    """An open SC probate estate has no status field this scraper can read -- same liensnc model,
    exempt by slug component alone."""
    prior = [_li(source="counties_sc.horry_probate", street_address="10 Sample St",
                 zip_code="28801", sale_date=None, county="Horry", state="SC",
                 raw={"probate": {"case_number": "2026-ES-26-00123"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_nc_heir_notices_row_survives_past_four_misses(tmp_path):
    prior = [_li(source="public_notices.nc_heir_notices", street_address="10 Sample St",
                 zip_code="28801", sale_date=None,
                 raw={"heir_notice": {"case_number": "26-SP-123"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_publicnoticesc_estates_row_survives_past_four_misses(tmp_path):
    prior = [_li(source="public_notices.publicnoticesc_estates", street_address="10 Sample St",
                 zip_code="28801", sale_date=None, county="Charleston", state="SC",
                 raw={"estate_notice": {"case_number": "2026ES1000123"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_anderson_acpass_deeds_row_survives_past_four_misses(tmp_path):
    prior = [_li(source="counties_sc.anderson_acpass_deeds", street_address="10 Sample St",
                 zip_code="28801", sale_date=None, county="Anderson", state="SC",
                 raw={"acpass": {"instrument_type": "POA"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_nc_rowan_cott_row_survives_past_four_misses(tmp_path):
    """Pass3's other "two stacked bugs" file (with nc_unclaimed below): Listing() never sets
    sale_date, and the slug was missing from both main.DATELESS_OK_SOURCES (fixed separately,
    pinned in test_dateless_sources.py-style tests) and AGE_EXEMPT_SOURCES (pinned here)."""
    prior = [_li(source="counties_nc.nc_rowan_cott", street_address="10 Sample St",
                 zip_code="28801", sale_date=None, county="Rowan", state="NC",
                 raw={"rowan_detail": {"index_type": "DEED"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1


def test_nc_unclaimed_row_survives_past_four_misses(tmp_path):
    """nc_unclaimed's own search ledger never re-searches a surname once searched, so a found
    claim can never be re-matched by a fresh scrape -- AGE_EXEMPT is the only available fix, same
    as liensnc (no status field exists either; the DB only ever returns currently-unclaimed rows
    by construction)."""
    prior = [_li(source="national.nc_unclaimed", street_address="10 Sample St",
                 zip_code="28801", sale_date=None,
                 raw={"nc_unclaimed": {"owner_name": "SMITH JOHN"}})]
    _write_board(tmp_path, prior)
    out, stats = merge_prior_board([_li(street_address="99 Elsewhere Rd", zip_code="28803")],
                                   docs_dir=tmp_path, now=NOW, max_misses=4)
    by = {li.street_address: li for li in out}
    assert "10 Sample St" in by
    assert stats["prior_only_kept_age_exempt"] == 1

"""Scoring and signal-logic fixes from the 2026-09-21 audits (docs/audit_signal_logic_2026-09-21.md).

One or more tests per finding, each built from a SYNTHETIC Listing. Every docstring records what the
scenario did BEFORE the fix, measured by running the same Listing through the previous scorer
(commit d8a5d60), so the test is the reproduction and its passing is the proof.

Nothing here touches the board. `score_board` is always given a previous_path that does not exist, and
its prior-run price index is only ever read when a listing has MLS fields anyway.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from foreclosure_scraper import distress_score as dsm
from foreclosure_scraper.distress_score import (
    ScoreBoardError, _derive_tier, _equity_band, _parcel_key, _signals_for, _tier,
    retract_equity_rank, score_board,
)
from foreclosure_scraper.enrichment_board_quality import enrich_board_quality
from foreclosure_scraper.enrichment_equity import enrich_equity, equity_is_evidenced
from foreclosure_scraper.mailing_shape import mailing_of
from foreclosure_scraper.models import Listing, ListingType as LT

NOPE = Path("/nonexistent/listings.json")        # score_board must never read the real board
TODAY = date(2026, 9, 21)
MAIL = {"mailing": "1 Main St, Elsewhere TX", "absentee": True, "out_of_state": False}
EQ = {"pct": 0.5, "value": 100000, "payoff_source": "recorded_deed_of_trust", "confidence": "high"}
EQ_EST = {"pct": 0.4, "value": 60000, "payoff_source": "assessed_value_estimate", "confidence": "low"}
CLEAN_TITLE = {"kind": "senior_lien_foreclosure", "surviving_senior_debt": False}
JUNIOR_TITLE = {"kind": "junior_lien_foreclosure", "surviving_senior_debt_risk": True}


def _dt(days: int) -> datetime:
    """A datetime `days` from TODAY (negative = in the past)."""
    return datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0) + timedelta(days=days)


def L(lt=LT.FORECLOSURE_SALE, *, source="counties_nc.test", state="NC", county="Gaston",
      parcel=None, sale=None, raw=None, **kw) -> Listing:
    return Listing(source=source, source_url="u", listing_type=lt, state=state, county=county,
                   parcel_id=parcel, sale_date=sale, raw=raw if raw is not None else {}, **kw)


def ds_of(*listings: Listing, today: date = TODAY) -> dict:
    """Score the listings together and return the first one's distress_stack."""
    score_board(list(listings), previous_path=NOPE, today=today)
    return listings[0].raw["distress_stack"]


def _hot_base(**extra) -> dict:
    """raw for a lead that clears every HOT gate: evidenced equity, a mailable owner, a clean title."""
    raw = {"owner_mailing": dict(MAIL), "equity": dict(EQ), "title_risk": dict(CLEAN_TITLE)}
    raw.update(extra)
    return raw


# ===========================================================================
# F1 (the scorer half was fixed in 4bc5792; the lead-signals chip still read the old predicate)
# ===========================================================================
def test_f1_the_lead_signals_chip_uses_the_same_countable_debt_predicate_as_the_scorer_and_equity():
    """BEFORE: enrichment_lead_signals added a `recorded_debt` chip for ANY amount_owed.value > 0,
    including the assessed-value placeholder the scorer and the equity engine already refuse."""
    from foreclosure_scraper.enrichment_lead_signals import _facet_signals
    est = L(LT.TAX_LIEN, raw={"amount_owed": {"value": 250000, "source": "assessed_value", "is_actual_debt": False}})
    assert "recorded_debt" not in _facet_signals(est, TODAY)
    real = L(LT.TAX_LIEN, raw={"amount_owed": {"value": 187425, "source": "judgment", "is_actual_debt": True}})
    assert "recorded_debt" in _facet_signals(real, TODAY)
    assert "recorded_debt" in [n for n, _c, _w in _signals_for(real, today=TODAY)]


# ===========================================================================
# F2. Ended events keep scoring and stay HOT
# ===========================================================================
def test_f2_a_sale_that_ended_contributes_nothing_and_caps_the_tier_at_cold():
    """BEFORE: foreclosure sale 200 days ago + probate + absentee + equity = HOT stack 2, score 58."""
    li = L(sale=_dt(-200), parcel="P100200", raw=_hot_base(probate={"case_number": "22E1"}))
    ds = ds_of(li)
    assert ds["tier"] == "COLD"
    assert "foreclosure_sale" not in ds["signals"]
    assert "passed 200 days ago" in ds["stale_reason"]


@pytest.mark.parametrize("state,days_ago,live", [
    ("NC", 14, True), ("NC", 15, False),           # NC keeps the upset-bid window: 14 days
    ("SC", 7, True), ("SC", 8, False),             # SC has no upset bid: 7 days
])
def test_f2_the_grace_period_is_14_days_in_nc_and_7_in_sc(state, days_ago, live):
    li = L(state=state, county="Anderson" if state == "SC" else "Gaston", sale=_dt(-days_ago), parcel="P100201")
    names = [n for n, _c, _w in _signals_for(li, today=TODAY)]
    assert ("foreclosure_sale" in names) is live


def test_f2_an_open_upset_bid_window_keeps_a_just_sold_lead_alive():
    ub = {"in_window": True, "deadline_iso": _dt(6).isoformat(), "days_remaining": 6}
    li = L(sale=_dt(-20), parcel="P100202", raw={"upset_bid": ub})
    names = [n for n, _c, _w in _signals_for(li, today=TODAY)]
    assert "foreclosure_sale" in names and "upset_bid" in names


def test_f2_a_closed_upset_window_scores_nothing():
    """BEFORE: enrich_upset_bid closes a window by writing {in_window: False, ...}, a non-empty dict,
    and the scorer tested truthiness, so a window closed 60 days ago still scored FINANCIAL 22."""
    closed = {"in_window": False, "days_remaining": 0, "stale_reason": "outside 10-day window now"}
    li = L(LT.TAX_LIEN, parcel="P100203", raw={"upset_bid": closed})
    assert "upset_bid" not in [n for n, _c, _w in _signals_for(li, today=TODAY)]


def test_f2_an_upset_window_whose_deadline_has_passed_is_closed_even_if_the_flag_is_stale():
    """`in_window` is frozen when the enricher ran (F15); the deadline is re-read against today."""
    ub = {"in_window": True, "deadline_iso": _dt(-2).isoformat()}
    assert "upset_bid" not in [n for n, _c, _w in _signals_for(L(LT.TAX_LIEN, raw={"upset_bid": ub}), today=TODAY)]


def test_f2_an_sc_tax_sale_stays_alive_through_its_redemption_period_and_dies_after():
    sc = dict(state="SC", county="Anderson", source="counties_sc.test")
    inside = L(LT.TAX_SALE, sale=_dt(-100), parcel="P100204",
               raw={"redemption_deadline": (TODAY + timedelta(days=200)).isoformat()}, **sc)
    assert ("tax_sale", "FINANCIAL", 20) in _signals_for(inside, today=TODAY)   # alive, weighted as a lien
    after = L(LT.TAX_SALE, sale=_dt(-500), parcel="P100205",
              raw={"redemption_deadline": (TODAY - timedelta(days=100)).isoformat()}, **sc)
    assert not _signals_for(after, today=TODAY)
    # no stored deadline: the statute's 12 months from the sale applies
    assert _signals_for(L(LT.TAX_SALE, sale=_dt(-300), parcel="P100206", **sc), today=TODAY)
    assert not _signals_for(L(LT.TAX_SALE, sale=_dt(-400), parcel="P100207", **sc), today=TODAY)


def test_f2_a_stale_sale_does_not_cap_a_parcel_that_still_has_a_live_event():
    stale = L(sale=_dt(-200), parcel="P100208")
    live = L(LT.LIS_PENDENS, parcel="P100208", raw=_hot_base())
    ds = ds_of(stale, live)
    assert "stale_reason" not in ds and ds["tier"] != "COLD"


def test_f2_board_quality_downranks_on_the_pulled_sales_marker_not_only_the_status_string():
    """BEFORE: only auction_status == 'presumed_withdrawn' demoted a HOT lead; a vanished lead whose
    last status was 'active' kept HOT (pulled_sale.presumed_withdrawn=True, stale_case never set)."""
    li = L(parcel="P100209", auction_status="active",
           raw={"pulled_sale": {"presumed_withdrawn": True}, "distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([li], today=TODAY)
    assert li.raw["distress_stack"]["tier"] == "WARM"
    assert li.raw["stale_case"] is True and li.raw["distress_stack"]["downranked_reason"]


def test_f2_board_quality_downranks_a_past_sale_outside_the_upset_window_only():
    old = L(sale=_dt(-40), parcel="P100210", auction_status="cancelled",
            raw={"distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([old], today=TODAY)
    assert old.raw["distress_stack"]["tier"] == "WARM"
    assert old.raw["distress_stack"]["downranked_reason"] == "sale_date_passed"
    assert "stale_case" not in old.raw        # that flag still means "the source stopped listing it"
    recent = L(sale=_dt(-3), parcel="P100211", raw={"distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([recent], today=TODAY)
    assert recent.raw["distress_stack"]["tier"] == "HOT"           # inside the window: a live lead
    windowed = L(sale=_dt(-12), parcel="P100212",
                 raw={"upset_bid": {"in_window": True, "deadline_iso": _dt(2).isoformat()},
                      "distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([windowed], today=TODAY)
    assert windowed.raw["distress_stack"]["tier"] == "HOT"         # past the grace but the window is open


def test_f2_board_quality_leaves_an_sc_tax_sale_in_its_redemption_period_alone():
    """The scorer keeps such a lead alive (F2); the board-quality pass must not undo that."""
    li = L(LT.TAX_SALE, state="SC", county="Anderson", sale=_dt(-100), parcel="P100215",
           raw={"redemption_deadline": (TODAY + timedelta(days=200)).isoformat(),
                "distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([li], today=TODAY)
    assert li.raw["distress_stack"]["tier"] == "HOT"
    gone = L(LT.TAX_SALE, state="SC", county="Anderson", sale=_dt(-500), parcel="P100216",
             raw={"redemption_deadline": (TODAY - timedelta(days=100)).isoformat(),
                  "distress_stack": {"tier": "HOT", "stack": 2}})
    enrich_board_quality([gone], today=TODAY)
    assert gone.raw["distress_stack"]["tier"] == "WARM"


def test_f2_the_upset_bid_enricher_records_when_it_computed_the_window():
    from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
    li = L(sale=datetime(2026, 9, 18, 10, 0), parcel="P100213")
    enrich_upset_bid([li], now=datetime(2026, 9, 21, 12, 0))
    assert li.raw["upset_bid"]["in_window"] is True and li.raw["upset_bid"]["as_of"] == "2026-09-21"
    late = L(sale=datetime(2026, 8, 1, 10, 0), parcel="P100214", raw={"upset_bid": {"in_window": True}})
    enrich_upset_bid([late], now=datetime(2026, 9, 21, 12, 0))
    assert late.raw["upset_bid"]["in_window"] is False and late.raw["upset_bid"]["as_of"] == "2026-09-21"


# ===========================================================================
# Filing-date sources: sale_date is a lien FILING date, not an auction (lead's requirement)
# ===========================================================================
_FILING = dict(source="counties_generic.liensnc", state="NC", county="Gaston")


def _liensnc(days_ago: int, **raw) -> Listing:
    """A LiensNC-style row: listing_type tax_lien, sale_date = the filing date."""
    return L(LT.TAX_LIEN, sale=_dt(-days_ago), parcel="P550001", raw=raw, **_FILING)


def test_filing_date_sources_is_one_shared_frozenset():
    assert dsm.FILING_DATE_SOURCES == frozenset({"liensnc", "nc_sos_ucc"})
    assert isinstance(dsm.FILING_DATE_SOURCES, frozenset)
    assert dsm.SALE_EVENT_TYPES == frozenset({"foreclosure_sale", "auction", "sheriff_sale", "tax_sale",
                                              "hoa_sale", "lis_pendens"})


@pytest.mark.parametrize("source", ["counties_generic.liensnc", "liensnc", "national.nc_sos_ucc", "nc_sos_ucc"])
def test_a_filing_date_is_not_an_event_date_for_the_scorer(source):
    """A liensnc-style row (tax_lien, sale_date 31 days ago) must get no stale_reason, no COLD cap and
    no days_to_event from the date. The lifecycle would have read a 31-day-old 'sale' as ended."""
    raw = {"owner_mailing": dict(MAIL), "equity": dict(EQ), "tax_owed": {"balance": 5200.0},
           "probate": {"case_number": "22E1"}}
    filed = L(LT.TAX_LIEN, source=source, state="NC", county="Gaston", parcel="P550002", sale=_dt(-31), raw=dict(raw))
    undated = L(LT.TAX_LIEN, source=source, state="NC", county="Gaston", parcel="P550003", sale=None, raw=dict(raw))
    a, b = ds_of(filed), ds_of(undated)
    assert "stale_reason" not in a and "days_to_event" not in a and "lane" not in a
    assert a["tier"] == b["tier"] != "COLD"
    assert a["signals"] == b["signals"]
    assert dsm.sale_date_is_event(filed) is False


def test_a_filing_date_row_never_reads_as_a_sale_even_when_the_filing_is_recent_or_the_type_is_a_sale_type():
    recent = _liensnc(5)
    assert dsm._sale_date_of(recent, recent.raw) is None
    # even if such a source ever carried a sale-type listing type, the source rule wins
    odd = L(LT.FORECLOSURE_SALE, sale=_dt(-31), parcel="P550004", raw=_hot_base(), **_FILING)
    assert dsm._sale_date_of(odd, odd.raw) is None and dsm.sale_date_is_event(odd) is False


def test_sale_date_is_only_an_event_date_for_sale_type_leads():
    for lt in (LT.FORECLOSURE_SALE, LT.AUCTION, LT.SHERIFF_SALE, LT.TAX_SALE, LT.HOA_SALE, LT.LIS_PENDENS):
        assert dsm.sale_date_is_event(L(lt, sale=_dt(5))) is True, lt
    for lt in (LT.TAX_LIEN, LT.PROBATE_NOTICE, LT.DISTRESSED, LT.REO, LT.ELDERLY_DISABLED, LT.BANKRUPTCY):
        assert dsm.sale_date_is_event(L(lt, sale=_dt(5))) is False, lt
    court = L(LT.TAX_LIEN, sale=_dt(5), raw={"court_sale_status": "sale_noticed"})
    assert dsm.sale_date_is_event(court) is True                      # a docket-noticed sale is a sale
    assert dsm.sale_date_is_event(L(LT.TAX_LIEN, sale=_dt(5), raw={"court_sale_status": "judgment"})) is False


def test_board_quality_stamps_no_sale_date_passed_on_a_filing_date_row_and_removes_an_old_stamp():
    li = L(LT.TAX_LIEN, sale=_dt(-31), parcel="P550005", auction_status="active",
           raw={"sale_date_passed": True, "sale_date_passed_days": 31,
                "calc": {"arv_expected": 250000.0, "max_bid_70": 170000.0, "deal_status": "GREAT",
                         "deal_message": "bid it", "notes": []}}, **_FILING)
    stats = enrich_board_quality([li], today=TODAY)
    assert "sale_date_passed" not in li.raw and "sale_date_passed_days" not in li.raw
    assert li.raw["calc"]["deal_status"] == "GREAT" and li.auction_status == "active"    # verdict and status untouched
    assert stats["sale_date_passed_cleared"] == 1 and "sale_date_passed" not in stats
    # ... while a foreclosure with the same date still gets the stamp
    fc = L(LT.FORECLOSURE_SALE, sale=_dt(-31), parcel="P550006", raw={})
    enrich_board_quality([fc], today=TODAY)
    assert fc.raw["sale_date_passed"] is True


def test_the_upset_bid_enricher_opens_no_window_from_a_filing_date_and_clears_an_old_one():
    from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
    now = datetime(2026, 9, 21, 12, 0)
    filed = L(LT.TAX_LIEN, sale=datetime(2026, 9, 16, 10, 0), parcel="P550007", **_FILING)      # filed 5 days ago
    stats = enrich_upset_bid([filed], now=now)
    assert "upset_bid" not in filed.raw and stats["not_a_sale_date"] == 1 and stats["tagged_in_window"] == 0
    prior = L(LT.TAX_LIEN, sale=datetime(2026, 9, 16, 10, 0), parcel="P550008",
              raw={"upset_bid": {"in_window": True, "source_signal": "counties_generic.liensnc",
                                 "deadline_iso": "2026-09-30T10:00:00"}}, **_FILING)
    prior.upset_bid_deadline = datetime(2026, 9, 30, 10, 0)
    enrich_upset_bid([prior], now=now)
    assert "upset_bid" not in prior.raw and prior.upset_bid_deadline is None
    ucc = L(LT.TAX_LIEN, sale=datetime(2026, 9, 18, 10, 0), parcel="P550009", source="national.nc_sos_ucc",
            state="NC", county="Wake")
    assert enrich_upset_bid([ucc], now=now)["tagged_in_window"] == 0
    # a real foreclosure sale 3 days ago still opens its window
    fc = L(LT.FORECLOSURE_SALE, sale=datetime(2026, 9, 18, 10, 0), parcel="P550010")
    assert enrich_upset_bid([fc], now=now)["tagged_in_window"] == 1


def test_a_recent_filing_cannot_open_a_foreclosure_lane_through_the_upset_bid_path():
    """The chain: enrich_upset_bid -> score_board. A LiensNC row filed 5 days ago used to be tagged in_window
    (NC, sale_date 0-14 days back), which the scorer read as an open upset-bid window and a lane event."""
    from foreclosure_scraper.enrichment_upset_bid import enrich_upset_bid
    filed = L(LT.TAX_LIEN, sale=datetime(2026, 9, 16, 10, 0), parcel="P550011",
              raw={"title_risk": dict(CLEAN_TITLE), "owner_mailing": dict(MAIL), "equity": dict(EQ)}, **_FILING)
    enrich_upset_bid([filed], now=datetime(2026, 9, 21, 12, 0))
    ds = ds_of(filed)
    assert "lane" not in ds and "upset_bid" not in ds["signals"] and ds["tier"] == "COLD"


# ===========================================================================
# Footprint rule: a flip outside the 18 counties is capped COLD (data_quality_fixes handoff)
# ===========================================================================
_OUT = {"scope": "flip_outside_footprint"}
_COAST = dict(state="SC", county="Charleston", source="counties_sc.charleston_mie")


def test_a_stamped_flip_outside_the_footprint_is_capped_cold_with_the_reason():
    """The same row unstamped is a foreclosure with a sale in 6 days and a clean title: HOT in the lane."""
    raw = {"title_risk": dict(CLEAN_TITLE), "owner_mailing": dict(MAIL), "equity": dict(EQ)}
    live = L(sale=_dt(6), parcel="P660001", raw=dict(raw), **_COAST)
    assert ds_of(live)["tier"] == "HOT"
    stamped = L(sale=_dt(6), parcel="P660002", raw={**raw, **_OUT}, **_COAST)
    ds = ds_of(stamped)
    assert ds["tier"] == "COLD" and ds["scope_capped"] == "flip_outside_footprint"
    assert ds["signals"] == [] and ds["stack"] == 0 and "lane" not in ds
    assert dsm.LAST_STATS["scope_capped"] == 1


@pytest.mark.parametrize("lt", [LT.FORECLOSURE_SALE, LT.AUCTION, LT.SHERIFF_SALE, LT.HOA_SALE, LT.REO])
def test_every_flip_type_is_capped_when_stamped(lt):
    li = L(lt, parcel="P660003", raw={**_hot_base(), **_OUT}, **_COAST)
    ds = ds_of(li)
    assert ds["tier"] == "COLD" and ds["scope_capped"] and dsm.flip_outside_footprint(li)


def test_a_distressed_type_lead_is_unaffected_by_the_stamp():
    """Distressed leads are in scope anywhere in NC and SC: a real tax delinquency in a coastal county still scores."""
    for lt in (LT.TAX_LIEN, LT.TAX_SALE, LT.LIS_PENDENS, LT.PROBATE_NOTICE, LT.DISTRESSED):
        li = L(lt, parcel="P660004", raw={**_hot_base(code_enforcement={"has_open": True}), **_OUT}, **_COAST)
        assert not dsm.flip_outside_footprint(li)
        assert "scope_capped" not in ds_of(li), lt
    tax = L(LT.TAX_LIEN, parcel="P660005", raw={**_hot_base(code_enforcement={"has_open": True}), **_OUT}, **_COAST)
    assert ds_of(tax)["tier"] == "HOT"


def test_a_capped_flip_adds_nothing_to_a_distressed_lead_on_the_same_parcel():
    """A Charleston tax lien plus an out-of-footprint sale on one parcel: the lien is scored on its own."""
    lien = L(LT.TAX_LIEN, parcel="P660006", raw=_hot_base(code_enforcement={"has_open": True}), **_COAST)
    sale = L(LT.FORECLOSURE_SALE, sale=_dt(4), parcel="P660006", raw={**_OUT, "title_risk": dict(CLEAN_TITLE)}, **_COAST)
    score_board([lien, sale], previous_path=NOPE, today=TODAY)
    a, b = lien.raw["distress_stack"], sale.raw["distress_stack"]
    assert b["tier"] == "COLD" and b["scope_capped"] == "flip_outside_footprint"
    assert "foreclosure_sale" not in a["signals"] and "lane" not in a and "scope_capped" not in a
    assert sorted(a["categories"]) == ["FINANCIAL", "PROPERTY"] and a["tier"] == "HOT"


def test_a_flip_only_parcel_counts_as_one_cold_group_and_a_mixed_parcel_counts_once():
    a = L(LT.AUCTION, parcel="P660007", raw=dict(_OUT), **_COAST)
    b = L(LT.REO, parcel="P660007", raw=dict(_OUT), **_COAST)
    assert score_board([a, b], previous_path=NOPE, today=TODAY) == {"HOT": 0, "WARM": 0, "COLD": 1}
    mixed = score_board([L(LT.TAX_LIEN, parcel="P660008", **_COAST), L(LT.AUCTION, parcel="P660008", raw=dict(_OUT), **_COAST)],
                        previous_path=NOPE, today=TODAY)
    assert sum(mixed.values()) == 1


def test_a_stamp_with_any_other_value_does_nothing_and_a_capped_stack_survives_retraction():
    other = L(sale=_dt(6), parcel="P660009", raw={**_hot_base(), "scope": "in_footprint"}, **_COAST)
    assert "scope_capped" not in ds_of(other)
    capped = L(LT.AUCTION, parcel="P660010", raw={**_hot_base(), **_OUT}, **_COAST)
    ds_of(capped)
    assert retract_equity_rank(capped) is False and capped.raw["distress_stack"]["tier"] == "COLD"
    assert _derive_tier({"scope_capped": "flip_outside_footprint", "stack": 3, "score": 80,
                         "contactable": True, "lane": "foreclosure", "title_status": "clean"}, True, True) == "COLD"


def test_the_capped_lead_reads_cold_on_the_chip_and_intent():
    from foreclosure_scraper.enrichment_lead_signals import _band, _intent_score
    li = L(LT.AUCTION, parcel="P660011", raw={**_hot_base(), **_OUT, "grade": {"overall_score": 100}}, **_COAST)
    ds_of(li)
    assert _band(_intent_score(li)) == "cold"


def test_flip_types_match_the_orchestrators_flip_scope():
    """distress_score cannot import main (heavy, and a cycle), so it mirrors main._FLIP_LISTING_TYPES."""
    from foreclosure_scraper.main import _FLIP_LISTING_TYPES
    assert dsm.FLIP_TYPES == frozenset(t.value for t in _FLIP_LISTING_TYPES)


# ===========================================================================
# F3. A stayed foreclosure ranks higher, not lower
# ===========================================================================
_STAY = {"status": "stayed", "chapter": "13", "resume_risk": "moderate",
         "date_filed": (TODAY - timedelta(days=60)).isoformat()}
_BK = {"chapter": "13", "date_filed": (TODAY - timedelta(days=60)).isoformat()}


def test_f3_a_stayed_foreclosure_gets_no_bankruptcy_category_and_is_capped_at_warm():
    """BEFORE: foreclosure sale in 5 days + absentee + equity + a Chapter 13 match = HOT stack 2 score 56."""
    li = L(sale=_dt(5), parcel="P300001", raw=_hot_base(bankruptcy=dict(_BK), bankruptcy_stay=dict(_STAY)))
    ds = ds_of(li)
    assert "bankruptcy" not in ds["signals"] and "LEGAL" not in ds["categories"]
    assert ds["tier"] == "WARM"
    assert ds["stay"]["status"] == "stayed" and ds["stay"]["chapter"] == "13"


def test_f3_the_cap_holds_in_the_distressed_lane_too():
    li = L(sale=_dt(90), parcel="P300002",
           raw=_hot_base(probate={"case_number": "22E1"}, bankruptcy=dict(_BK), bankruptcy_stay=dict(_STAY)))
    unstayed = L(sale=_dt(90), parcel="P300003",
                 raw=_hot_base(probate={"case_number": "22E1"}))
    assert ds_of(unstayed)["tier"] == "HOT"                     # control: same lead without the stay
    assert ds_of(li)["tier"] == "WARM"


def test_f3_a_lapsed_bankruptcy_stops_counting_and_stops_staying():
    old = {"chapter": "7", "date_filed": (TODAY - timedelta(days=400)).isoformat()}
    li = L(LT.TAX_LIEN, parcel="P300004", raw={"bankruptcy": old, "bankruptcy_stay": {**_STAY, **old}})
    ds = ds_of(li)
    assert "bankruptcy" not in ds["signals"] and "stay" not in ds
    ch13 = {"chapter": "13", "date_filed": (TODAY - timedelta(days=400)).isoformat()}
    assert "bankruptcy" in [n for n, _c, _w in _signals_for(L(LT.TAX_LIEN, raw={"bankruptcy": ch13}), today=TODAY)]


def test_f3_the_stay_enricher_marks_a_lapsed_case_and_ignores_non_foreclosure_types():
    from foreclosure_scraper.enrichment_bankruptcy_stay import enrich_bankruptcy_stay
    lapsed = L(sale=_dt(5), raw={"bankruptcy": {"chapter": "7", "date_filed": "2025-01-01"}})
    stats = enrich_bankruptcy_stay([lapsed], today=TODAY)
    assert lapsed.raw["bankruptcy_stay"]["status"] == "lapsed" and stats["lapsed"] == 1 and stats["stayed"] == 0
    # 'distressed' is the catch-all type for code violations and registries, not a foreclosure
    code = L(LT.DISTRESSED, raw={"bankruptcy": {"chapter": "13", "date_filed": _BK["date_filed"]}})
    assert enrich_bankruptcy_stay([code], today=TODAY)["stayed"] == 0 and "bankruptcy_stay" not in code.raw


# ===========================================================================
# F4. The equity gate is arithmetic, not evidence
# ===========================================================================
def test_f4_estimated_equity_can_help_a_lead_reach_warm_but_not_hot():
    """BEFORE: payoff assumed at 60% of assessed value gives exactly 40% equity, band 'high', and the HOT
    gate was met by construction. tax_lien + probate + absentee + mailing = HOT stack 2."""
    est = L(LT.TAX_LIEN, parcel="P400001",
            raw={"owner_mailing": dict(MAIL), "equity": dict(EQ_EST), "probate": {"case_number": "22E1"}})
    ds = ds_of(est)
    assert ds["equity_band"] == "high" and ds["equity_evidenced"] is False
    assert ds["tier"] == "WARM"
    real = L(LT.TAX_LIEN, parcel="P400002",
             raw={"owner_mailing": dict(MAIL), "equity": dict(EQ), "probate": {"case_number": "22E1"}})
    assert ds_of(real)["tier"] == "HOT" and ds_of(real)["equity_evidenced"] is True


@pytest.mark.parametrize("payoff_source,confidence,expected", [
    ("recorded_deed_of_trust", "high", True),
    ("amount_owed:judgment", "high", True),
    ("amount_owed:opening_bid", "medium", True),
    ("foreclosure_proxy:opening_bid", "low", True),           # an opening bid IS evidence even at low confidence
    ("foreclosure_proxy:judgment_amount", "low", True),
    ("last_sale_amortized", "low", False),
    ("assessed_value_estimate", "low", False),
    ("amount_owed:tax_owed", "medium", False),                # a tax bill is not the mortgage
    ("something_new", "medium", True),                        # the rule's second arm: confidence >= medium
    ("something_new", "low", False),
])
def test_f4_which_payoffs_are_evidence(payoff_source, confidence, expected):
    assert equity_is_evidenced({"pct": 0.5, "payoff_source": payoff_source, "confidence": confidence}) is expected
    assert equity_is_evidenced({"payoff_source": "recorded_deed_of_trust"}) is False       # no figure, no evidence
    assert equity_is_evidenced(None) is False


def test_f4_the_equity_engine_keeps_publishing_the_numbers_and_stamps_whether_they_are_evidenced():
    assumed = L(LT.TAX_LIEN, assessed_value=200000.0, raw={})
    proxy = L(LT.FORECLOSURE_SALE, assessed_value=200000.0, judgment_amount=90000.0, raw={})
    enrich_equity([assumed, proxy])
    a, p = assumed.raw["equity"], proxy.raw["equity"]
    assert a["payoff_source"] == "assessed_value_estimate" and a["pct"] == 0.4 and a["value"] > 0
    assert a["evidenced"] is False
    assert p["payoff_source"].startswith("foreclosure_proxy") and p["evidenced"] is True
    assert _equity_band(assumed) == "high"                    # the band is still computed, as before


def test_f4_a_missing_provenance_is_not_evidence_and_the_roi_fallback_never_is():
    bare = L(LT.TAX_LIEN, parcel="P400003", raw={"owner_mailing": dict(MAIL), "equity": {"pct": 0.8},
                                                 "probate": {"case_number": "22E1"}})
    assert ds_of(bare)["tier"] == "WARM"
    roi = L(LT.TAX_LIEN, parcel="P400004", raw={"owner_mailing": dict(MAIL),
                                                "calc": {"arv_expected": 300000.0, "roi_pct": 90.0},
                                                "probate": {"case_number": "22E1"}})
    ds = ds_of(roi)
    assert ds["equity_band"] == "high" and ds["equity_evidenced"] is False and ds["tier"] == "WARM"


# ===========================================================================
# F5. One event can make stack 2
# ===========================================================================
def test_f5_a_sheriff_sale_and_a_foreclosure_sale_are_one_financial_category():
    """BEFORE: sheriff_sale was SALES and foreclosure_sale FINANCIAL, so the same enforcement on one
    parcel read FINANCIAL + SALES = HOT stack 2, score 63."""
    a = L(LT.SHERIFF_SALE, parcel="P500001", raw=_hot_base())
    b = L(LT.FORECLOSURE_SALE, parcel="P500001")
    ds = ds_of(a, b)
    assert ds["categories"] == ["FINANCIAL"] and ds["stack"] == 1


def test_f5_reo_and_auction_after_a_foreclosure_are_the_same_event_but_stand_alone_otherwise():
    fc = L(LT.FORECLOSURE_SALE, parcel="P500002", raw=_hot_base())
    reo = L(LT.REO, parcel="P500002")
    assert ds_of(fc, reo)["categories"] == ["FINANCIAL"]
    auc = L(LT.AUCTION, parcel="P500003")
    assert ds_of(fc.model_copy(deep=True), auc)["categories"] == ["FINANCIAL"]
    assert ds_of(L(LT.REO, parcel="P500004"))["categories"] == ["SALES"]      # no enforcement record beside it
    assert ds_of(L(LT.AUCTION, parcel="P500005"))["categories"] == ["SALES"]
    # a lien is not an enforcement event, so an REO beside a tax lien is a real second kind of distress
    assert ds_of(L(LT.TAX_LIEN, parcel="P500006"), L(LT.REO, parcel="P500006"))["categories"] == ["FINANCIAL", "SALES"]


def test_f5_a_price_cut_needs_mls_fields():
    """BEFORE: a tax lien whose opening_bid fell 9,000 -> 4,000 (the owner paying it down) earned a
    SALES price_cut 16 and reached stack 2."""
    lien = L(LT.TAX_LIEN, parcel="P500007", opening_bid=4000.0)
    assert "price_cut" not in [n for n, _c, _w in _signals_for(lien, prior_price=9000.0, today=TODAY)]
    mls = L(LT.DISTRESSED, source="counties_nc.homeharvest_distressed", parcel="P500008", opening_bid=230000.0,
            raw={"homeharvest": {"mls_status": "active", "days_on_mls": 10}})
    assert "price_cut" in [n for n, _c, _w in _signals_for(mls, prior_price=250000.0, today=TODAY)]


def test_f5_the_prior_price_index_is_only_read_when_a_listing_has_mls_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(dsm, "_prior_price_index", lambda p: calls.append(p) or {})
    score_board([L(LT.TAX_LIEN, parcel="P500009")], previous_path=NOPE, today=TODAY)
    assert calls == []
    mls = L(LT.DISTRESSED, parcel="P500010", raw={"homeharvest": {"mls_status": "expired"}})
    score_board([mls], previous_path=NOPE, today=TODAY)
    assert len(calls) == 1


def test_f5_the_pickens_delinquency_boolean_is_not_a_property_signal():
    """BEFORE: Pickens set raw['distressed']=True for 3+ delinquency cycles; the scorer read it as
    PROPERTY 8, so tax_lien + that = HOT stack 2 on one delinquency record."""
    pk = dict(source="counties_sc.pickens_delinquent_parcels", state="SC", county="Pickens")
    chronic = L(LT.TAX_LIEN, parcel="P500011", raw={"distressed": True,
                "pickens_delinquent": {"chronic": True, "cycle_count": 4}}, **pk)
    sigs = _signals_for(chronic, today=TODAY)
    assert "distressed_condition" not in [n for n, _c, _w in sigs]
    assert ("tax_lien_chronic", "FINANCIAL", 24) in sigs
    # the assessor's condition code is real evidence and still counts on that source
    real = L(LT.TAX_LIEN, parcel="P500012", raw={"distressed": True, "condition_cama": {"distressed": True}}, **pk)
    assert ("distressed_condition", "PROPERTY", 8) in _signals_for(real, today=TODAY)


def test_f5_a_stack_of_two_needs_at_least_one_category_of_weight_15():
    li = L(LT.ELDERLY_DISABLED, parcel="P500013",
           raw={"tax_relief": {"kind": "elderly"}, "distressed": True, "owner_mailing": dict(MAIL), "equity": dict(EQ)})
    ds = ds_of(li)
    assert sorted(ds["categories"]) == ["LIFE_EVENT", "PROPERTY"]        # both are present ...
    assert ds["stack"] == 1 and ds["stack_capped"]                        # ... two 8-point attributes are not a stack
    assert ds["tier"] != "HOT"


# ===========================================================================
# F6. Name-only matches count as full evidence
# ===========================================================================
_JAIL = {"state": "NC", "source": "DAC", "confidence": "name_only_low"}


def test_f6_a_name_only_match_adds_score_but_cannot_complete_a_stack():
    """BEFORE: foreclosure sale + a jail-roster name collision = HOT stack 2, score 46."""
    li = L(sale=_dt(60), parcel="P600001", raw=_hot_base(incarceration=dict(_JAIL)))
    ds = ds_of(li)
    assert ds["stack"] == 1 and ds["uncounted_categories"] == ["LEGAL"]
    assert ds["score"] >= 30 + 8                                          # the 8 still counts toward the score
    assert ds["tier"] != "HOT"
    assert ds["evidence"]["incarceration"] == "name_only"
    assert "foreclosure_sale" not in ds["evidence"]                       # record is the default and is not listed


def test_f6_name_based_categories_do_count_once_two_record_categories_exist():
    li = L(LT.TAX_LIEN, parcel="P600002", raw=_hot_base(code_enforcement={"has_open": True},
                                                        incarceration=dict(_JAIL)))
    ds = ds_of(li)
    assert ds["stack"] == 3 and "uncounted_categories" not in ds


def test_f6_bankruptcy_and_court_divorce_are_name_only_and_a_resolved_parcel_is_name_joined():
    dv = {"case_count": 1, "cases": [{"role": "Plaintiff", "filed_date": (TODAY - timedelta(days=100)).isoformat()}]}
    li = L(LT.TAX_LIEN, parcel="P600003", raw={"bankruptcy": dict(_BK), "divorce": dv})
    ds = ds_of(li)
    assert ds["evidence"] == {"bankruptcy": "name_only", "divorce": "name_only"}
    assert ds["stack"] == 1
    resolved = L(LT.TAX_LIEN, parcel="P600004", raw={"resolved_from_name": {"confidence": "unique_match"}})
    assert ds_of(resolved)["evidence"] == {"tax_lien": "name_joined"}
    unresolved = L(LT.TAX_LIEN, parcel="P600005", raw={"resolved_from_name": {"confidence": "no_match"}})
    assert "evidence" not in ds_of(unresolved)


def test_f6_hot_needs_a_record_linked_signal():
    inf = L(LT.DISTRESSED, source="counties_nc.distressed", parcel="P600006",       # keyword-derived: inferred
            raw=_hot_base(relationship_signal={"kind": "divorce", "keyword": "divorce decree"}))
    ds = ds_of(inf)
    assert ds["stack"] == 2 and ds["record_linked"] is False               # two inferred categories DO stack ...
    assert ds["tier"] == "WARM"                                            # ... but never reach HOT on that alone


def test_f6_a_probate_notice_is_a_record_unless_its_parcel_came_from_a_name_search():
    rec = L(LT.PROBATE_NOTICE, parcel="P600007")
    assert "evidence" not in ds_of(rec)
    by_name = L(LT.PROBATE_NOTICE, parcel="P600008", raw={"resolved_from_name": {"confidence": "unique_match"}})
    assert ds_of(by_name)["evidence"] == {"probate_notice": "name_joined"}


def test_f6_nc_divorce_dates_in_the_us_format_are_read():
    """BEFORE: date.fromisoformat inside `except ValueError: continue` scored every NC hit (MM/DD/YYYY) 0."""
    us = (TODAY - timedelta(days=90)).strftime("%m/%d/%Y")
    dv = {"case_count": 1, "cases": [{"role": "Defendant", "filed_date": us}]}
    assert dsm._divorce_signal({"divorce": dv}, TODAY) == ("divorce", "LIFE_EVENT", 12)


def test_f6_incarceration_stops_counting_when_the_booking_says_released():
    jb = {"release_status": "released", "scheduled_release": None}
    li = L(LT.TAX_LIEN, parcel="P600009", raw={"incarceration": dict(_JAIL), "jail_booking": jb})
    assert "incarceration" not in [n for n, _c, _w in _signals_for(li, today=TODAY)]
    held = L(LT.TAX_LIEN, parcel="P600010", raw={"incarceration": dict(_JAIL),
                                                 "jail_booking": {"release_status": "in_custody"}})
    assert "incarceration" in [n for n, _c, _w in _signals_for(held, today=TODAY)]


# ===========================================================================
# F7. The HOT rule is built for the wrong lane
# ===========================================================================
def test_f7_a_foreclosure_with_a_sale_in_three_days_is_hot_without_mail_or_equity():
    """BEFORE: sale in 3 days, owner-occupied, no equity figure = COLD, score 30."""
    li = L(sale=_dt(3), parcel="P700001",
           raw={"owner_mailing": {"mailing": "1 A St", "absentee": False}, "title_risk": dict(CLEAN_TITLE)})
    ds = ds_of(li)
    assert ds["lane"] == "foreclosure" and ds["days_to_event"] == 3
    assert ds["tier"] == "HOT" and ds["equity_band"] is None and ds["contactable"] is True


def test_f7_the_lane_needs_no_owner_mailing_at_all_and_no_equity():
    li = L(LT.SHERIFF_SALE, sale=_dt(10), parcel="P700002", raw={"title_risk": dict(CLEAN_TITLE)})
    assert ds_of(li)["tier"] == "HOT"


@pytest.mark.parametrize("title,expected", [
    (dict(CLEAN_TITLE), "HOT"),
    ({"kind": "unknown", "party": "Acme Holdings LLC"}, "WARM"),
    (None, "WARM"),                                          # no party text at all: unknown, not clean (F18)
    (dict(JUNIOR_TITLE), "COLD"),                            # a junior lien leaves the senior debt with the buyer
])
def test_f7_the_lane_tier_follows_title_risk(title, expected):
    raw = {"title_risk": title} if title else {}
    assert ds_of(L(sale=_dt(5), parcel="P700003", raw=raw))["tier"] == expected


def test_f7_a_stay_keeps_a_lane_lead_at_warm():
    li = L(sale=_dt(5), parcel="P700004", raw={"title_risk": dict(CLEAN_TITLE), "bankruptcy_stay": dict(_STAY)})
    assert ds_of(li)["tier"] == "WARM"


@pytest.mark.parametrize("days,lane", [(0, True), (30, True), (31, False), (-1, False)])
def test_f7_the_lane_window_is_zero_to_thirty_days(days, lane):
    li = L(sale=_dt(days), parcel="P700005", raw={"title_risk": dict(CLEAN_TITLE)})
    assert (ds_of(li).get("lane") == "foreclosure") is lane


def test_f7_an_open_upset_window_is_a_lane_event_with_days_from_the_deadline():
    ub = {"in_window": True, "deadline_iso": _dt(4).isoformat(), "days_remaining": 4}
    li = L(LT.TAX_LIEN, parcel="P700006", raw={"upset_bid": ub, "title_risk": dict(CLEAN_TITLE)})
    ds = ds_of(li)
    assert ds["lane"] == "foreclosure" and ds["days_to_event"] == 4 and ds["tier"] == "HOT"


def test_f7_a_court_sale_notice_with_a_near_date_is_a_lane_event_and_a_sold_one_is_not():
    noticed = L(LT.LIS_PENDENS, sale=_dt(8), parcel="P700007",
                raw={"court_sale_status": "sale_noticed", "title_risk": dict(CLEAN_TITLE)})
    assert ds_of(noticed)["lane"] == "foreclosure"
    sold = L(LT.LIS_PENDENS, sale=_dt(8), parcel="P700008",
             raw={"court_sale_status": "sold_unconfirmed", "title_risk": dict(CLEAN_TITLE)})
    assert "lane" not in ds_of(sold)


def test_f7_tax_liens_and_lis_pendens_stay_in_the_distressed_lane():
    ds = ds_of(L(LT.LIS_PENDENS, sale=_dt(5), parcel="P700009", raw=_hot_base()))
    assert "lane" not in ds and "days_to_event" in ds                     # dated, informational only
    assert ds["tier"] == "WARM"                                           # stack 1: one FINANCIAL category


def test_f7_a_far_sale_date_is_reported_but_uses_the_seller_rules():
    ds = ds_of(L(sale=_dt(45), parcel="P700010", raw=_hot_base(probate={"case_number": "1"})))
    assert ds["days_to_event"] == 45 and "lane" not in ds and ds["tier"] == "HOT"


def test_f7_fullmer_marks_lane_leads_and_carries_days_to_event():
    from foreclosure_scraper.fullmer_rank import score
    li = L(sale=_dt(5), parcel="P700011", raw={"title_risk": dict(CLEAN_TITLE)})
    ds_of(li)
    r = score(li)
    assert r["lane"] == "foreclosure" and r["days_to_event"] == 5 and "foreclosure_lane_not_judged" in r["flags"]
    plain = L(LT.TAX_LIEN, parcel="P700012")
    ds_of(plain)
    assert score(plain)["lane"] == "distressed" and score(plain)["days_to_event"] is None


# ===========================================================================
# F9. The parcel key fuses unrelated properties
# ===========================================================================
def test_f9_the_same_parcel_number_in_two_counties_is_two_properties():
    """BEFORE: Anderson and Pickens sharing parcel "123-45-6" fused a tax lien with a probate notice into one HOT stack."""
    a = L(LT.TAX_LIEN, state="SC", county="Anderson", parcel="123-45-6", raw=_hot_base())
    b = L(LT.PROBATE_NOTICE, state="SC", county="Pickens", parcel="123-45-6")
    assert _parcel_key(a) != _parcel_key(b)
    score_board([a, b], previous_path=NOPE, today=TODAY)
    assert a.raw["distress_stack"]["stack"] == 1 and b.raw["distress_stack"]["stack"] == 1


def test_f9_the_same_parcel_in_one_county_still_fuses_whatever_its_punctuation():
    a = L(LT.TAX_LIEN, county="Gaston County", parcel="123-45-678")
    b = L(LT.PROBATE_NOTICE, county="gaston", parcel="12345678")
    assert _parcel_key(a) == _parcel_key(b)
    assert ds_of(a, b)["stack"] == 2


@pytest.mark.parametrize("pid", ["N/A", "0", "TBD", "UNKNOWN", "NONE", "123", "0000", "----", ""])
def test_f9_placeholder_parcel_ids_never_group(pid):
    """BEFORE: 'N/A', '0', 'TBD' each mapped to ONE key per state and fused every row carrying them."""
    a = L(LT.TAX_LIEN, parcel=pid or None)
    b = L(LT.PROBATE_NOTICE, parcel=pid or None)
    assert _parcel_key(a) != _parcel_key(b)


def test_f9_each_listing_gets_its_own_copy_of_the_stack():
    """BEFORE: one shared dict was assigned to every listing on a parcel, so enrich_board_quality's
    in-place downrank on one sibling re-tiered all of them."""
    a = L(LT.TAX_LIEN, parcel="P900001", raw=_hot_base(probate={"case_number": "1"}))
    b = L(LT.PROBATE_NOTICE, parcel="P900001")
    score_board([a, b], previous_path=NOPE, today=TODAY)
    assert a.raw["distress_stack"] is not b.raw["distress_stack"]
    assert a.raw["distress_stack"]["categories"] is not b.raw["distress_stack"]["categories"]
    a.raw["distress_stack"]["tier"] = "COLD"
    assert b.raw["distress_stack"]["tier"] == "HOT"
    a.raw["distress_stack"]["tier"] = "HOT"
    a.auction_status = "presumed_withdrawn"
    enrich_board_quality([a, b], today=TODAY)
    assert a.raw["distress_stack"]["tier"] == "WARM" and b.raw["distress_stack"]["tier"] == "HOT"


# ===========================================================================
# F10. Weights depend on the scraper's choice of listing type
# ===========================================================================
_SC = dict(state="SC", county="Spartanburg", source="counties_sc.qpaybill_delinquent_roll")


def test_f10_a_standing_delinquent_roll_typed_tax_sale_weighs_like_a_tax_lien():
    """BEFORE: an SC roll row (no sale date) scored 30 and reached WARM on its own; the same NC fact typed tax_lien scored 20."""
    roll = L(LT.TAX_SALE, parcel="P100001", **_SC)
    assert [(n, w) for n, _c, w in _signals_for(roll, today=TODAY)] == [("tax_sale", 20)]
    nc = L(LT.TAX_LIEN, parcel="P100002")
    assert [w for _n, _c, w in _signals_for(nc, today=TODAY)] == [20]
    scheduled = L(LT.TAX_SALE, sale=_dt(40), parcel="P100003", **_SC)
    assert [(n, w) for n, _c, w in _signals_for(scheduled, today=TODAY)] == [("tax_sale", 30)]
    assert ds_of(L(LT.TAX_SALE, parcel="P100004", **_SC))["tier"] == "COLD"


@pytest.mark.parametrize("slug", ["sc_flc", "spartanburg_flc", "terry_howe_flc", "oconee_flc_assignment",
                                  "oconee_forfeited_land", "kershaw_flc"])
def test_f10_county_owned_flc_inventory_is_not_owner_motivation_unless_a_sale_is_scheduled(slug):
    li = L(LT.TAX_SALE, parcel="P100005", state="SC", county="Oconee", source=f"counties_sc.{slug}")
    assert _signals_for(li, today=TODAY) == []
    scheduled = L(LT.TAX_SALE, sale=_dt(20), parcel="P100006", state="SC", county="Oconee", source=f"counties_sc.{slug}")
    assert [w for _n, _c, w in _signals_for(scheduled, today=TODAY)] == [30]


def test_f10_greenville_adverts_score_as_a_foreclosure_record_by_source_and_by_type():
    """BEFORE: typed DISTRESSED, PROPERTY 10. Rows on the board keep that type until re-scraped."""
    src = "counties_sc.greenville_mie_adverts"
    legacy = L(LT.DISTRESSED, source=src, state="SC", county="Greenville", parcel="P100007")
    assert _signals_for(legacy, today=TODAY) == [("lis_pendens", "FINANCIAL", 28)]
    retyped = L(LT.LIS_PENDENS, source=src, state="SC", county="Greenville", parcel="P100008")
    assert _signals_for(retyped, today=TODAY) == [("lis_pendens", "FINANCIAL", 28)]
    # 97.6% of these adverts are past-dated; the structured sale_date is None on purpose, so the
    # advert's own date in raw is what ends the event
    ended = L(LT.LIS_PENDENS, source=src, state="SC", county="Greenville", parcel="P100009",
              raw={"greenville_mie": {"sale_date": "08/07/2023"}})
    assert _signals_for(ended, today=TODAY) == []
    assert ds_of(ended)["tier"] == "COLD" and "passed" in ds_of(ended)["stale_reason"]


def test_f10_mcdowell_probate_is_retyped_at_the_source():
    import inspect
    from foreclosure_scraper.scrapers.counties_nc import mcdowell_probate
    assert "ListingType.ESTATE_LEAD" in inspect.getsource(mcdowell_probate)
    assert "ListingType.DISTRESSED" not in inspect.getsource(mcdowell_probate).split("class ")[1]


# ===========================================================================
# F11. Listing types and signals that never reached the score
# ===========================================================================
@pytest.mark.parametrize("lt,expected", [
    (LT.DIVORCE_NOTICE, ("divorce_notice", "LIFE_EVENT", 15)),
    (LT.ESTATE_LEAD, ("estate_lead", "LIFE_EVENT", 20)),
    (LT.HOA_SALE, ("hoa_sale", "FINANCIAL", 25)),
    (LT.ELDERLY_DISABLED, ("elderly_disabled", "LIFE_EVENT", 8)),
    (LT.TAX_SALE_OVERAGE, ("tax_sale_overage", "FINANCIAL", 15)),
])
def test_f11_listing_types_that_never_scored_now_do(lt, expected):
    """BEFORE: all six returned no signal at all."""
    assert _signals_for(L(lt, parcel="P110001"), today=TODAY) == [expected]


def test_f11_a_bankruptcy_filing_scores_only_once_it_is_tied_to_a_property():
    assert _signals_for(L(LT.BANKRUPTCY), today=TODAY) == []
    assert _signals_for(L(LT.BANKRUPTCY, parcel="P110002"), today=TODAY) == [("bankruptcy", "LEGAL", 18)]
    assert _signals_for(L(LT.BANKRUPTCY, street_address="12 Oak St"), today=TODAY) == [("bankruptcy", "LEGAL", 18)]


def test_f11_an_hoa_sale_is_part_of_the_enforcement_chain_and_ends_with_its_date():
    assert _signals_for(L(LT.HOA_SALE, sale=_dt(-30), parcel="P110003"), today=TODAY) == []
    ds = ds_of(L(LT.HOA_SALE, parcel="P110004", raw=_hot_base()), L(LT.REO, parcel="P110004"))
    assert ds["categories"] == ["FINANCIAL"]


@pytest.mark.parametrize("level,extra,weight", [
    ("destroyed", {}, 20), ("Natural Disaster - Destroyed", {}, 20),
    ("major damage", {}, 16), ("red", {"substantial_damage": True}, 19),
    ("yellow", {}, 12), ("yellow", {"substantial_damage": True}, 16),
    ("minor damage", {}, None), ("green", {}, None), ("affected", {}, None), (None, {}, None),
])
def test_f11_storm_damage_is_graded_and_only_real_structural_damage_scores(level, extra, weight):
    raw = {"storm_damage": {"damage_level": level, **extra}}
    sigs = _signals_for(L(LT.TAX_LIEN, parcel="P110005", raw=raw), today=TODAY)
    got = [w for n, _c, w in sigs if n == "storm_damage"]
    assert got == ([weight] if weight else [])


def test_f11_storm_damage_and_a_helene_placard_are_one_property_category():
    hel = L(LT.DISTRESSED, source="counties_nc.asheville_helene", parcel="P110006",
            raw={"helene": {"worst_placard": "unsafe"}, "storm_damage": {"damage_level": "red"}})
    assert ds_of(hel)["categories"] == ["PROPERTY"]


def test_f11_a_code_officer_confirmed_vacant_or_boarded_structure_scores_property():
    for vac in ({"vacant": True}, {"boarded_up": True}, {"vacant": True, "boarded_up": True}):
        assert ("vacant_structure", "PROPERTY", 12) in _signals_for(L(LT.TAX_LIEN, raw={"vacancy": vac}), today=TODAY)
    for none in ({"vacant": None, "boarded_up": False}, {}):
        assert "vacant_structure" not in [n for n, _c, _w in _signals_for(L(LT.TAX_LIEN, raw={"vacancy": none}), today=TODAY)]
    # an undeveloped lot is land, not a distressed house
    assert "vacant_structure" not in [n for n, _c, _w in _signals_for(L(LT.TAX_LIEN, raw={"vacant_lot": {"land_use": "VACANT"}}), today=TODAY)]


# ===========================================================================
# F12. Closed and resolved records score as open
# ===========================================================================
@pytest.mark.parametrize("ce,counts", [
    ({"has_open": False, "open_violations": 0, "total_violations": 3}, False),   # BEFORE: scored PROPERTY 14
    ({"has_open": True, "open_violations": 2}, True),
    ({"open_violations": 0}, False),                                             # county shape without has_open
    ({"open_violations": 1}, True),
    ({"violations": [{"status": "Closed"}, {"status": "resolved"}]}, False),
    ({"violations": [{"status": "Closed"}, {"status": "Open"}]}, True),
    ([{"status": "Closed"}], False),                                             # the Charlotte list shape
    ([{"status": "NOV Mailed"}], True),
    (True, True),                                                                # a bare marker is kept (old behaviour)
    ({"stale_after": "2026-01-01", "has_open": True}, False),                    # aged out
])
def test_f12_code_enforcement_scores_only_while_a_case_is_open(ce, counts):
    li = L(LT.TAX_LIEN, parcel="P120001", raw={"code_enforcement": ce})
    assert ("code_enforcement" in [n for n, _c, _w in _signals_for(li, today=TODAY)]) is counts


def test_f12_a_condemned_flag_counts_alone_but_not_beside_a_block_that_says_closed():
    assert "code_enforcement" in [n for n, _c, _w in _signals_for(L(LT.TAX_LIEN, raw={"condemned": True}), today=TODAY)]
    closed = L(LT.TAX_LIEN, raw={"condemned": True, "code_enforcement": {"has_open": False}})
    assert "code_enforcement" not in [n for n, _c, _w in _signals_for(closed, today=TODAY)]


def test_f12_the_stamp_helpers_round_trip():
    from foreclosure_scraper.signal_freshness import is_stale, stamp
    blk = stamp({"x": 1}, today=date(2026, 9, 1), ttl_days=30)
    assert blk["stamped_at"] == "2026-09-01" and blk["stale_after"] == "2026-10-01"
    assert not is_stale(blk, date(2026, 10, 1)) and is_stale(blk, date(2026, 10, 2))
    assert not is_stale({"x": 1}, date(2030, 1, 1)) and not is_stale("junk")


class _Resp:
    def __init__(self, feats):
        self.status_code, self._feats = 200, feats

    def json(self):
        return {"features": self._feats}


class _Client:
    def __init__(self, resp=None, boom=False):
        self.resp, self.boom = resp, boom

    async def get(self, *_a, **_k):
        if self.boom:
            raise RuntimeError("outage")
        return self.resp


def test_f12_the_code_enforcement_enricher_tells_no_case_from_an_outage_and_stamps_its_writes():
    from foreclosure_scraper import enrichment_code_enforcement as ce
    li = L(LT.TAX_LIEN, city="Charlotte", street_address="123 Oak Street", raw={})
    cfg = ce.CITY_ENDPOINTS["Charlotte"]
    assert asyncio.run(ce._fetch_violations_for_listing(_Client(_Resp([])), li, cfg)) == []       # answered: none
    assert asyncio.run(ce._fetch_violations_for_listing(_Client(boom=True), li, cfg)) is None      # could not ask
    counts: dict = {}
    li.raw["code_enforcement"] = {"source": ce._SOURCE_TAG, "has_open": True}
    ce._clear_stale_block(li, counts)
    assert "code_enforcement" not in li.raw and counts["cleared"] == 1
    other = L(LT.TAX_LIEN, raw={"code_enforcement": {"source": "henderson_ordinance_violations_tracking", "has_open": True}})
    ce._clear_stale_block(other, {})
    assert "code_enforcement" in other.raw                      # another writer's block is never cleared


# ===========================================================================
# F13. "N signals" chip and signal_stack count synonyms
# ===========================================================================
def _chip(li: Listing) -> dict:
    from foreclosure_scraper.enrichment_lead_signals import _signal_stack
    ds_of(li)
    return _signal_stack(li, TODAY)


def test_f13_one_tax_delinquency_reads_as_one_signal_category():
    """BEFORE: tax_lien + tax_delinquent + recorded_debt = 'N=3 signals' for one delinquency."""
    li = L(LT.TAX_LIEN, parcel="P130001", raw={"tax_owed": {"balance": 4200.0}})
    chip = _chip(li)
    assert chip["count"] == 1 and "tax_delinquent" not in chip["signals"]
    assert set(chip["signals"]) == {"tax_lien", "recorded_debt"}


def test_f13_one_helene_placard_reads_as_one_signal():
    """BEFORE: helene_unsafe + storm_damage = 2."""
    li = L(LT.DISTRESSED, source="counties_nc.asheville_helene", parcel="P130002",
           raw={"helene": {"worst_placard": "unsafe"}})
    chip = _chip(li)
    assert chip["count"] == 1 and "storm_damage" not in chip["signals"]


def test_f13_the_chip_does_not_advertise_a_stack_the_badge_refused():
    """A jail-roster name match beside a foreclosure is listed but is not a second category (F6);
    a bankruptcy on a stayed foreclosure is not one either (F3)."""
    named = L(sale=_dt(60), parcel="P130004", raw=_hot_base(incarceration=dict(_JAIL)))
    chip = _chip(named)
    assert chip["count"] == 1 and "incarceration" in chip["signals"]
    stayed = L(sale=_dt(60), parcel="P130005", raw=_hot_base(bankruptcy=dict(_BK), bankruptcy_stay=dict(_STAY)))
    chip = _chip(stayed)
    assert chip["count"] == 1 and "bankruptcy_stay" in chip["signals"]


def test_f13_ownership_context_is_listed_but_not_counted_as_a_distress_category():
    li = L(LT.TAX_LIEN, parcel="P130003", raw={"owner_mailing": {"mailing": "x", "absentee": True, "out_of_state": True}})
    chip = _chip(li)
    assert chip["count"] == 1 and {"absentee_owner", "out_of_state_owner"} <= set(chip["signals"])


def test_f13_trust_and_a_bare_estate_in_an_owner_name_are_not_probate():
    from foreclosure_scraper.enrichment_lead_signals import _facet_signals
    for owner in ("ACME REAL ESTATE HOLDINGS LLC", "SMITH FAMILY TRUST", "JONES JOHN ET AL"):
        li = L(LT.TAX_LIEN, owner_name=owner, raw={"life_events": ["estate_probate", "trust", "multiple_heirs"]})
        assert "probate" not in _facet_signals(li, TODAY), owner
    for owner in ("HEIRS OF JOHN SMITH", "SMITH JOHN EST OF", "ESTATE OF JANE DOE"):
        li = L(LT.TAX_LIEN, owner_name=owner, raw={"life_events": ["estate_probate"]})
        assert "probate" in _facet_signals(li, TODAY), owner


def test_f13_a_closed_upset_window_a_lapsed_bankruptcy_and_a_release_add_no_chip():
    from foreclosure_scraper.enrichment_lead_signals import _facet_signals
    li = L(LT.TAX_LIEN, raw={"upset_bid": {"in_window": False}, "bankruptcy": {"chapter": "7", "date_filed": "2020-01-01"},
                             "incarceration": {"x": 1}, "jail_booking": {"release_status": "released"},
                             "code_enforcement": {"has_open": False}})
    assert not ({"upset_bid", "bankruptcy", "incarceration", "code_enforcement"} & _facet_signals(li, TODAY))


def test_f13_the_absentee_chip_reads_owner_mailing_and_not_a_stray_raw_key():
    from foreclosure_scraper.enrichment_lead_signals import _facet_signals
    stray = L(LT.TAX_LIEN, raw={"absentee": True})            # mailing_dict(raw) returned raw itself here
    assert "absentee_owner" not in _facet_signals(stray, TODAY)


def test_f13_intent_is_capped_for_a_stale_or_stayed_lead():
    from foreclosure_scraper.enrichment_lead_signals import _band, _intent_score
    big = {"stack": 3, "score": 90}
    grade = {"overall_score": 100}
    hot = L(raw={"distress_stack": dict(big), "grade": grade})
    assert _band(_intent_score(hot)) == "hot"
    stale = L(raw={"distress_stack": {**big, "stale_reason": "sale passed"}, "grade": grade})
    assert _band(_intent_score(stale)) == "cold"
    stayed = L(raw={"distress_stack": {**big, "stay": {"status": "stayed"}}, "grade": grade})
    assert _band(_intent_score(stayed)) == "warm"
    withdrawn = L(raw={"distress_stack": dict(big), "grade": grade, "stale_case": True})
    assert _band(_intent_score(withdrawn)) == "warm"


def test_f13_strategy_fit_needs_a_real_distress_tier_and_a_real_death_for_probate():
    from foreclosure_scraper.enrichment_strategy_fit import enrich_strategy_fit
    from foreclosure_scraper.models import PropertyKind

    def _land(**raw):
        return L(LT.TAX_LIEN, property_kind=PropertyKind.LAND, owner_name=raw.pop("owner", None), raw=raw)
    # BEFORE: any signal on the stack (even a placeholder) made vacant land "distressed"
    est = _land(distress_stack={"tier": "COLD", "signals": ["recorded_debt"]})
    enrich_strategy_fit([est])
    assert "strategy_fit" not in est.raw
    warm = _land(distress_stack={"tier": "WARM", "signals": ["tax_lien"]})
    enrich_strategy_fit([warm])
    assert warm.raw["strategy_fit"]["reasons"]["LAND_WHOLESALE"] == "vacant land + distress signal"
    # an LLC with ESTATE in its name is not a probate lead; an owner naming a death is
    llc = _land(owner="ACME REAL ESTATE HOLDINGS LLC", life_events=["estate_probate"], tenure={"long_tenure": False},
                distress_stack={"tier": "WARM"})
    enrich_strategy_fit([llc])
    assert llc.raw["strategy_fit"]["reasons"]["LAND_WHOLESALE"] == "vacant land + distress signal"
    heirs = _land(owner="HEIRS OF JOHN SMITH", life_events=["estate_probate"], distress_stack={"tier": "COLD"})
    enrich_strategy_fit([heirs])
    assert heirs.raw["strategy_fit"]["reasons"]["LAND_WHOLESALE"] == "vacant land + probate/estate"


# ===========================================================================
# F14. Bare-string owner_mailing makes leads un-HOT-able
# ===========================================================================
def test_f14_a_bare_string_mailing_address_makes_the_lead_contactable_and_hot_able():
    """BEFORE: only dict mailing blocks counted, so 5,098 Spartanburg leads had contactable False and could never be HOT."""
    raw = {"owner_mailing": "123 MAIN ST, SPARTANBURG SC 29301", "equity": dict(EQ),
           "code_enforcement": {"has_open": True}}
    li = L(LT.TAX_LIEN, state="SC", county="Spartanburg", parcel="P140001", raw=raw)
    ds = ds_of(li)
    assert ds["contactable"] is True and ds["tier"] == "HOT"


def test_f14_mailing_of_reads_only_the_owner_mailing_key():
    assert mailing_of({"owner_mailing": "1 A St"}) == {"mailing": "1 A St"}
    assert mailing_of({"owner_mailing": {"absentee": True}}) == {"absentee": True}
    assert mailing_of({"absentee": True, "mailing": "x"}) == {}          # a stray key is not a mailing block
    assert mailing_of(L(raw={"owner_mailing": "  "})) == {} and mailing_of(None) == {}


def test_f14_fullmer_reads_a_bare_string_mailing_without_crashing():
    from foreclosure_scraper.fullmer_rank import score
    assert score(L(LT.TAX_LIEN, raw={"owner_mailing": "1 A St"}))["rank"] >= 0


# ===========================================================================
# F16. WARM on absentee plus any 8-point attribute
# ===========================================================================
_ABS = {"mailing": "x", "absentee": True, "out_of_state": True}


def test_f16_absentee_plus_an_8_point_attribute_is_no_longer_warm():
    """BEFORE: out-of-state owner + an elderly exemption and nothing else = WARM (8 + 8 + 4 = 20)."""
    li = L(LT.ELDERLY_DISABLED, parcel="P160001", raw={"owner_mailing": dict(_ABS), "tax_relief": {"kind": "elderly"}})
    ds = ds_of(li)
    assert ds["score"] == 20 and ds["non_attribute"] is False and ds["tier"] == "COLD"


def test_f16_absentee_plus_a_real_event_is_still_warm():
    li = L(LT.TAX_LIEN, parcel="P160002", raw={"owner_mailing": dict(_ABS), "code_enforcement": {"has_open": True}})
    ds = ds_of(li)
    assert ds["tier"] == "WARM" and "non_attribute" not in ds          # 14 + 8 + 4 = 26, an event
    assert ds_of(L(LT.TAX_LIEN, parcel="P160003", raw={"owner_mailing": dict(_ABS)}))["tier"] == "WARM"


def test_f16_tier_keeps_its_original_six_argument_signature_and_meaning():
    assert _tier(1, 20, False, False, True, False) == "WARM"           # the old rule, no gate arguments given
    assert _tier(1, 20, False, False, True, False, non_attribute=False) == "COLD"
    assert _tier(2, 40, True, True, False, False) == "HOT"
    assert _tier(2, 40, True, True, False, False, eq_evidenced=False) == "WARM"
    assert _tier(2, 40, True, True, False, False, record_linked=False) == "WARM"
    assert _tier(2, 40, True, True, False, True) == "WARM" and _tier(0, 5, False, False, False, False) == "COLD"


# ===========================================================================
# F17. Silent failures
# ===========================================================================
def test_f17_score_board_raises_after_scoring_the_rest_and_leaves_no_prior_tier_behind(monkeypatch):
    """BEFORE: a failure was logged by the caller and the run carried on with the PREVIOUS run's tiers on the rows."""
    good = L(LT.TAX_LIEN, parcel="P170001", raw=_hot_base(code_enforcement={"has_open": True}))
    bad = L(LT.TAX_LIEN, parcel="P170002", raw={"distress_stack": {"tier": "HOT", "stack": 3}})
    real = dsm._collect

    def flaky(li, pp, today):
        if li is bad:
            raise RuntimeError("boom")
        return real(li, pp, today)

    monkeypatch.setattr(dsm, "_collect", flaky)
    with pytest.raises(ScoreBoardError) as exc:
        score_board([good, bad], previous_path=NOPE, today=TODAY)
    assert exc.value.failed == 1 and exc.value.hist["HOT"] == 1
    assert good.raw["distress_stack"]["tier"] == "HOT"                  # everything that could be scored, was
    assert bad.raw["distress_stack"]["tier"] == "COLD" and bad.raw["distress_stack"]["score_error"] == "RuntimeError"
    assert dsm.LAST_STATS["errors"] == 1


def test_f17_a_corrupt_prior_snapshot_is_reported_not_silently_ignored(tmp_path):
    bad = tmp_path / "listings.json"
    bad.write_text('[{"source": "s", "opening_bid": 5000, "state": "NC"}, {"source": "trunc')
    assert dsm._prior_price_index(bad) == {}
    assert "price_index_error" in dsm.LAST_STATS
    ok = tmp_path / "ok" / "listings.json"
    ok.parent.mkdir()
    ok.write_text('[{"source": "s", "source_url": "u", "opening_bid": 5000, "state": "NC", "county": "Gaston", '
                  '"parcel_id": "P1234", "listing_type": "tax_lien"}]')
    idx = dsm._prior_price_index(ok)
    assert list(idx.values()) == [5000.0]


def test_f17_the_prior_snapshot_reader_streams_rows_across_chunk_boundaries(tmp_path, monkeypatch):
    import gzip
    import json
    rows = [{"source": f"s{i}", "opening_bid": 1000 + i, "pad": "x" * 500} for i in range(40)]
    plain, gz = tmp_path / "board.json", tmp_path / "board.json.gz"
    plain.write_text(json.dumps(rows))
    gz.write_bytes(gzip.compress(json.dumps(rows).encode()))
    monkeypatch.setattr(dsm, "_CHUNK", 700)            # rows are ~550 bytes, so every row straddles a chunk edge
    for path in (plain, gz):
        assert [r["opening_bid"] for r in dsm._stream_json_rows(path)] == [1000 + i for i in range(40)]


def test_f17_lead_signals_clears_a_stale_intent_and_counts_the_failure(monkeypatch):
    from foreclosure_scraper import enrichment_lead_signals as mod
    li = L(LT.TAX_LIEN, raw={"intent_score": 99, "intent_band": "hot", "signal_stack": {"count": 4, "signals": ["a"]}})
    monkeypatch.setattr(mod, "_signal_stack", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    stats = mod.enrich_lead_signals([li])
    assert stats["failed"] == 1
    assert li.raw["intent_score"] == 0 and li.raw["intent_band"] == "cold" and li.raw["signal_stack"]["error"] is True


# ===========================================================================
# F18. Title-risk unknown is treated as clean
# ===========================================================================
def test_f18_unknown_or_missing_title_risk_is_not_hot_eligible_on_a_foreclosure_type():
    """BEFORE: only surviving_senior_debt_risk was read, so unknown and missing passed the HOT gate."""
    base = dict(sale=_dt(90), parcel="P180001")
    common = {"owner_mailing": dict(MAIL), "equity": dict(EQ), "probate": {"case_number": "1"}}
    assert ds_of(L(**base, raw={**common, "title_risk": dict(CLEAN_TITLE)}))["tier"] == "HOT"
    unknown = ds_of(L(**{**base, "parcel": "P180002"}, raw={**common, "title_risk": {"kind": "unknown", "party": "X LLC"}}))
    assert unknown["tier"] == "WARM" and unknown["title_status"] == "unknown"
    missing = ds_of(L(**{**base, "parcel": "P180003"}, raw=dict(common)))
    assert missing["tier"] == "WARM" and missing["title_status"] == "missing"


def test_f18_a_junior_lien_risk_caps_a_bidder_lead_at_cold():
    """BEFORE: a proven junior-lien trap only lost 20 points and stayed WARM."""
    li = L(sale=_dt(90), parcel="P180004", raw={"owner_mailing": dict(MAIL), "equity": dict(EQ),
                                                "probate": {"case_number": "1"}, "title_risk": dict(JUNIOR_TITLE)})
    ds = ds_of(li)
    assert ds["tier"] == "COLD" and ds["surviving_senior_debt_risk"] is True and ds["title_status"] == "junior_risk"


def test_f18_leads_that_are_not_a_bidders_are_unaffected():
    tax = L(LT.TAX_LIEN, parcel="P180005", raw={"owner_mailing": dict(MAIL), "equity": dict(EQ),
                                                "code_enforcement": {"has_open": True}})
    ds = ds_of(tax)
    assert ds["tier"] == "HOT" and "bidder" not in ds and "title_status" not in ds


# ===========================================================================
# F19. Legacy equity flags
# ===========================================================================
def test_f19_the_legacy_zestimate_arithmetic_no_longer_produces_equity_flags():
    """BEFORE: a Zestimate minus the last sale price stamped `high_equity` (a green chip) outside the ARV trust gate."""
    from foreclosure_scraper.flags import _flag_one
    li = L(LT.TAX_LIEN, tax_value=100000.0, judgment_amount=10000.0,
           raw={"flags": ["high_equity", "vacant"], "zillow": {"zestimate": 500000},
                "gis": {"mailing": "1 Elsewhere Rd", "last_sale": {"amount": 20000}}})
    flags = _flag_one(li)
    assert not ({"high_equity", "low_equity", "negative_equity"} & set(flags))
    assert "vacant" in flags


def test_f19_equity_flags_come_from_the_gated_equity_block_and_high_needs_evidence():
    from foreclosure_scraper.flags import _flag_one
    high = L(LT.TAX_LIEN, raw={"equity": {"pct": 0.6, "evidenced": True}})
    assert "high_equity" in _flag_one(high)
    assumed = L(LT.TAX_LIEN, raw={"equity": {"pct": 0.6, "evidenced": False}})
    assert "high_equity" not in _flag_one(assumed)
    assert "negative_equity" in _flag_one(L(LT.TAX_LIEN, raw={"equity": {"pct": -0.1, "is_underwater": True}}))
    assert "low_equity" in _flag_one(L(LT.TAX_LIEN, raw={"equity": {"pct": 0.1}}))
    withheld = L(LT.TAX_LIEN, raw={"equity": {"withheld": True}, "flags": ["high_equity"]})
    assert not ({"high_equity", "low_equity", "negative_equity"} & set(_flag_one(withheld)))


# ===========================================================================
# A8. liensnc is context-only
# ===========================================================================
@pytest.mark.parametrize("source", ["counties_generic.liensnc", "liensnc", "national.liensnc"])
def test_a8_liensnc_adds_no_listing_type_signal_and_cannot_reach_warm_alone(source):
    """BEFORE: tax_lien 20 + absentee 8 = 28 = WARM with no other evidence (52% of all WARM leads)."""
    li = L(LT.TAX_LIEN, source=source, parcel="P080001", raw={"owner_mailing": dict(MAIL), "equity": dict(EQ)})
    assert _signals_for(li, today=TODAY) == []
    ds = ds_of(li)
    assert ds["tier"] == "COLD" and ds["signals"] == [] and ds["stack"] == 0


def test_a8_a_liensnc_row_with_another_real_signal_still_scores_it():
    raw = {"owner_mailing": dict(MAIL), "equity": dict(EQ), "tax_owed": {"balance": 5200.0},
           "code_enforcement": {"has_open": True}}
    li = L(LT.TAX_LIEN, source="counties_generic.liensnc", parcel="P080002", raw=raw)
    sigs = {n for n, _c, _w in _signals_for(li, today=TODAY)}
    assert sigs == {"recorded_debt", "code_enforcement"}
    # neither category reaches weight 15 (12 and 14), so the stack rule (F5) caps this at one
    # category; it is still a WARM lead on its score, which the liensnc filing alone never was
    ds = ds_of(li)
    assert ds["tier"] == "WARM" and ds["stack"] == 1 and ds["stack_capped"]
    other = L(LT.TAX_LIEN, source="counties_generic.somewhere_else", parcel="P080003")
    assert [n for n, _c, _w in _signals_for(other, today=TODAY)] == ["tax_lien"]


# ===========================================================================
# Compatibility
# ===========================================================================
def test_the_distress_stack_keeps_its_shape_and_adds_fields_only_when_they_matter():
    """The dashboard reads signal names and tier; a plain lead must carry exactly the old keys (payload size is tight)."""
    li = L(LT.TAX_LIEN, parcel="P990001")
    ds = ds_of(li)
    assert set(ds) == {"tier", "stack", "categories", "signals", "score", "equity_band", "absentee",
                       "out_of_state", "contactable", "surviving_senior_debt_risk"}
    assert ds["tier"] == "COLD" and ds["signals"] == ["tax_lien"] and ds["categories"] == ["FINANCIAL"]


def test_retract_equity_rank_rederives_through_the_one_tier_function():
    li = L(LT.TAX_LIEN, parcel="P990002", raw=_hot_base(code_enforcement={"has_open": True}))
    ds_of(li)
    assert li.raw["distress_stack"]["tier"] == "HOT"
    assert retract_equity_rank(li) is True
    ds = li.raw["distress_stack"]
    assert ds["tier"] == "WARM" and ds["equity_band"] is None and ds["equity_evidenced"] is False
    # a lane lead needs no equity, so pulling it changes nothing
    lane = L(sale=_dt(4), parcel="P990003", raw={"equity": dict(EQ), "title_risk": dict(CLEAN_TITLE)})
    ds_of(lane)
    retract_equity_rank(lane)
    assert lane.raw["distress_stack"]["tier"] == "HOT"


def test_retract_works_on_a_stack_written_before_the_new_fields_existed():
    li = L(LT.TAX_LIEN, raw={"distress_stack": {"tier": "HOT", "stack": 2, "score": 48, "equity_band": "high",
                                                "contactable": True, "absentee": False,
                                                "surviving_senior_debt_risk": False}})
    assert retract_equity_rank(li) and li.raw["distress_stack"]["tier"] == "WARM"


def test_derive_tier_is_pure_and_defaults_are_the_old_behaviour():
    assert _derive_tier({"stack": 2, "score": 40, "contactable": True}, True, None) == "HOT"
    assert _derive_tier({"stack": 2, "score": 40, "contactable": True, "stale_reason": "x"}, True, True) == "COLD"


def test_a_sold_property_is_excluded_and_a_group_can_mix_sold_and_active_listings():
    sold = L(LT.TAX_LIEN, parcel="P990004", raw={"sold_confirmed": True, "distress_stack": {"tier": "HOT"}})
    score_board([sold], previous_path=NOPE, today=TODAY)
    assert "distress_stack" not in sold.raw


def test_score_board_accepts_a_datetime_for_today_and_defaults_to_the_real_date():
    li = L(sale=datetime.now() - timedelta(days=200), parcel="P990005")
    score_board([li], previous_path=NOPE)
    assert li.raw["distress_stack"]["tier"] == "COLD"
    li2 = L(sale=_dt(-200), parcel="P990006")
    score_board([li2], previous_path=NOPE, today=datetime(2026, 9, 21, 12, 0))
    assert "stale_reason" in li2.raw["distress_stack"]
